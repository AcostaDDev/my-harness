"""Opt-in composition of the managed mode inside the local service (H2 exit, part 1).

Without explicit configuration there are no projects, ports or supervisor: the managed API
only reads. Projects are registered on the server; the HTTP client
names them by identifier and never supplies paths, commands or selections.
The supervisor has a writer thread and a chat thread over snapshots in the Uvicorn process,
both with `LocalSupervisor.run_once`; the queue, the exclusion and the recovery stay in
SQLite. Shutting down the service does not release a half-done job: its lease expires and it stays
RECOVERY_REQUIRED until an explicit confirmation. A confirmed live configuration set (D238) is staged
completely and installed at an idle boundary; the worker loops read the factories on every claim.
"""

from collections.abc import Callable, Mapping
import copy
from dataclasses import dataclass, replace
import importlib
import logging
import os
from pathlib import Path
import re
from threading import Event, Lock, Thread

from my_harness.core.engine.context import ProjectContext
from my_harness.services.managed import LocalSupervisor
from my_harness.storage.managed import SQLiteManagedRepository
from my_harness.storage.prompts import PromptRepository
from my_harness.storage.managed_views import SQLiteManagedViews
from my_harness.i18n import tr

logger = logging.getLogger(__name__)

CONFIG_ENV = "HARNESS_MANAGED_CONFIG"
PROJECT_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
REQUIRED_VERSIONS = frozenset({"engine", "agent_adapter", "commands", "evidence"})


@dataclass(frozen=True)
class ManagedProject:
    """Manageable checkout with context and freezable versions fixed by whoever starts the service."""

    id: str
    context: ProjectContext
    versions: Mapping[str, str | None]
    permission_authority: Mapping | None = None
    # H3.4: kind of the phase closure tag; lightweight by default, annotated with a deterministic intent.
    tag_kind: str = "lightweight"
    # H4.2: opt-in capability to create exclusively in this empty target.
    bootstrap_enabled: bool = False


def agents_view(project: ManagedProject) -> dict:
    """D052: provider, model and effort of each agent; provider None outside a CLI composition (cli-5+)."""
    policy, versions = project.context.policy, project.versions
    return {'planning_mode': policy.planning_mode,
            'reviewer': {'provider': versions.get('reviewer_provider'), 'model': policy.reviewer_model,
                         'effort': policy.reviewer_effort},
            'planner': {'model': policy.planner_model, 'effort': policy.planner_effort},
            'executor': {'provider': versions.get('executor_provider'), 'selection_mode': policy.executor_mode,
                         'models': list(policy.executor_models), 'efforts': list(policy.executor_efforts),
                         'effort_vocabulary': list(policy.executor_effort_vocabulary)}}


@dataclass(frozen=True)
class ManagedConfig:
    """`ports_factory(context, versions)` and `commit_factory(context, versions)` as in `LocalSupervisor`.

    The H2.3 CLI and H2.4 Git adapters only take part if injected here.
    `supervisor=True` starts the executor thread with the service; by default jobs
    stay in the persisted queue without running.
    """

    projects: tuple[ManagedProject, ...] = ()
    ports_factory: Callable | None = None
    commit_factory: Callable | None = None
    supervisor: bool = False
    lease_seconds: float = 30.0
    poll_seconds: float = 0.5
    migrations_dir: Path | None = None
    # D076: operator authority that composes projects registered from the UI (`local-config-3`).
    registrar: object | None = None


def load_config(spec: str | None = None) -> ManagedConfig:
    """`module:attribute` in HARNESS_MANAGED_CONFIG: a ManagedConfig or a function that returns one."""
    spec = spec if spec is not None else os.environ.get(CONFIG_ENV)
    if not spec:
        return ManagedConfig()
    module, separator, attribute = spec.partition(":")
    if not separator or not module or not attribute:
        raise ValueError(tr('runtime.config_reference', variable=CONFIG_ENV))
    value = getattr(importlib.import_module(module), attribute)
    config = value() if callable(value) and not isinstance(value, ManagedConfig) else value
    if not isinstance(config, ManagedConfig):
        raise TypeError(tr('runtime.config_type', spec=spec))
    return config


def _validate(config: ManagedConfig, database: Path, migrations_dir: Path) -> None:
    validate_projects(config)
    for project in config.projects:
        for path, key in ((database, 'runtime.database_inside'), (migrations_dir, 'runtime.migrations_inside')):
            if path.is_relative_to(project.context.root) or project.context.root.is_relative_to(path):
                raise ValueError(tr(key, project=project.id))


def validate_projects(config: ManagedConfig) -> None:
    """Checks without database or service; the local TOML configuration also uses them."""
    ids, roots = set(), set()
    for project in config.projects:
        if not isinstance(project.id, str) or not PROJECT_ID.fullmatch(project.id):
            raise ValueError(tr('runtime.invalid_id', id=repr(project.id)))
        if project.id in ids:
            raise ValueError(tr('runtime.duplicate', id=project.id))
        if project.context.root in roots:
            raise ValueError(tr('runtime.shared_root', root=project.context.root))
        ids.add(project.id)
        roots.add(project.context.root)
        if type(project.bootstrap_enabled) is not bool:
            raise ValueError(tr('runtime.bootstrap_enabled_explicit_boolean'))
        if project.bootstrap_enabled and config.commit_factory is None:
            raise ValueError(tr('runtime.bootstrap_requires_explicit_git'))
        if project.tag_kind not in ("lightweight", "annotated"):
            raise ValueError(tr('runtime.tag_kind', id=project.id, kind=repr(project.tag_kind)))
        if not isinstance(project.versions, Mapping) or not REQUIRED_VERSIONS <= project.versions.keys():
            raise ValueError(tr('runtime.versions', id=project.id))
        if project.permission_authority is not None:
            from my_harness.core.engine.permissions import KINDS, LAYERS
            authority = project.permission_authority
            if set(authority) != set(LAYERS) or any(
                not isinstance(values, Mapping) or not set(values) <= set(KINDS)
                or any(not isinstance(targets, (list, tuple)) or not all(isinstance(t, str) and t.strip() for t in targets)
                       for targets in values.values()) for values in authority.values()):
                raise ValueError(tr('runtime.explicit_global_project_contract'))
    if config.supervisor and config.ports_factory is None:
        raise ValueError(tr('runtime.ports_factory'))


class SupervisorWorker:
    """One job per lane (writer/chat); errors are quarantined, without retry."""

    def __init__(self, supervisor: LocalSupervisor, poll_seconds: float):
        self.supervisor = supervisor
        self.poll_seconds = poll_seconds
        self.idle: Callable | None = None  # D238: boundary hook of the writer lane
        self.wake, self.stopping = Event(), Event()
        self.thread: Thread | None = None
        self.chat_thread: Thread | None = None
        self.last_error: str | None = None
        self._lock = Lock()

    def start(self) -> None:
        self.thread = Thread(target=self._loop, name="managed-supervisor", daemon=True)
        self.thread.start()
        self.chat_thread = Thread(target=self._loop, args=('chat',), name="managed-chat", daemon=True)
        self.chat_thread.start()

    def notify(self) -> None:
        self.wake.set()

    def _loop(self, lane='writer') -> None:
        supervisor = LocalSupervisor(self.supervisor.repository, self.supervisor.ports_factory,
            lease_seconds=self.supervisor.lease_seconds, commit_factory=self.supervisor.commit_factory, lane=lane)
        while not self.stopping.is_set():
            try:
                prepared = self.preparation.run_once() if lane != 'chat' and getattr(self, 'preparation', None) else None
                claimed = prepared or supervisor.run_once()
            except Exception as exc:  # job in RECOVERY_REQUIRED or local failure; never retried on its own
                with self._lock:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Managed job stopped; explicit reconciliation required.")
                claimed = None
            if claimed is None and lane == 'writer' and self.idle is not None:
                try:
                    self.idle()
                except Exception:  # the pending set stays visible; nothing is retried on its behalf
                    logger.exception("Pending configuration could not be applied.")
            if claimed is None:
                self.wake.wait(self.poll_seconds)
                self.wake.clear()

    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive() and self.chat_thread and self.chat_thread.is_alive())

    def stop(self, timeout: float) -> None:
        """Without interrupting the running job: if it does not finish in time, its lease decides the recovery."""
        self.stopping.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join(timeout)
        if self.chat_thread is not None:
            self.chat_thread.join(timeout)

    def error(self) -> str | None:
        with self._lock:
            return self.last_error


class ManagedRuntime:
    """Composed in the lifespan: exporting OpenAPI neither connects SQLite nor imports configuration."""

    def __init__(self, engine, config: ManagedConfig | None = None):
        self.engine = engine
        self._explicit = config
        self.setup = None
        self.config: ManagedConfig | None = None
        self.repository = self.views = self.worker = self.registry = self.preferences = None
        self.database: Path | None = None
        self.migrations_dir: Path | None = None
        self.projects: dict[str, ManagedProject] = {}
        self._projects_lock = Lock()
        self._apply_lock = Lock()
        # Projects whose active configuration could not be installed (documentary capabilities only).
        self.degraded: dict[str, str] = {}
        self._domain_operations = None

    def start(self) -> None:
        from my_harness.storage.backup import is_read_only_archive
        # Not even importing user configuration: a factory may have effects when loaded.
        if is_read_only_archive(self.engine):
            config = ManagedConfig()
        elif self.setup is not None:
            config = self.setup.start(self._explicit)
        else:
            config = self._explicit if self._explicit is not None else load_config()
        database = Path(self.engine.url.database).resolve()
        try:
            migrations_dir = Path(config.migrations_dir or database.parent / 'migrations').resolve()
            _validate(config, database, migrations_dir)
            if config.registrar is not None and hasattr(config.registrar, 'resolve_config'):
                config = config.registrar.resolve_config(config)
        except (ValueError, OSError):
            if self.setup is None:
                raise
            # Invalid legacy composition or CLI preflight also leaves the protected editor available.
            self.setup.startup_error = 'configuration_invalid'
            self.setup.legacy = False
            config = ManagedConfig()
            migrations_dir = database.parent / 'migrations'
        self.migrations_dir = migrations_dir
        self.config = config
        self.repository = SQLiteManagedRepository(self.engine)
        from my_harness.storage.preferences import PreferencesRepository
        self.preferences = PreferencesRepository(SQLiteManagedRepository(self.engine))
        from my_harness.services.managed import guarded_writer
        config = replace(config, commit_factory=guarded_writer(config.commit_factory, self.repository.guard))
        self.config = config
        self.views = SQLiteManagedViews(self.engine)
        self.prompts = PromptRepository(self.engine)
        from my_harness.storage.permissions import PermissionRepository
        self.permissions = PermissionRepository(self.repository)
        from my_harness.storage.phases import PhaseRepository
        self.phases = PhaseRepository(self.repository)
        from my_harness.storage.chat import ChatRepository
        self.chat = ChatRepository(self.repository)
        self.projects = {project.id: self._toml_work_language(project) for project in config.projects}
        self.database = database
        from my_harness.services.project_registry import ProjectRegistry
        self.registry = ProjectRegistry(self)
        from my_harness.services.project_configuration import ProjectConfiguration
        self.project_configuration = ProjectConfiguration(self)
        self.registry.load()
        from my_harness.services.work_language import WorkLanguageMigration
        self.work_language = WorkLanguageMigration(self)
        from my_harness.services.project_creation import ProjectCreation
        self.creation = ProjectCreation(self)
        setup_ready = self.setup is None or self.setup.state()['mode'] == 'READY'
        if setup_ready:
            self.creation.reconcile()
        from my_harness.services.project_preparation import ProjectPreparation
        self.preparation = ProjectPreparation(self)
        if setup_ready and not is_read_only_archive(self.engine):
            self.preparation.repository.recover_expired()
        if self.setup is not None and not self.setup.legacy:
            self.setup.repository.project_verifier = self.project_configuration.verify
        for project in list(self.projects.values()):
            bound = self.preparation.bind(project)
            if self.setup is not None and not self.setup.legacy:
                try:
                    self.install(self.project_configuration.install_active(bound))
                except (ValueError, OSError) as exc:
                    # Keep documentary capabilities; admission must revalidate the active reference.
                    self.degraded[project.id] = getattr(exc, 'code', 'project_configuration_invalid')
                    self.install(bound)
        if self.setup is not None:
            self.repository.write_guard = self.setup.require_ready
            if not self.setup.legacy and not is_read_only_archive(self.engine):
                self.setup.repository.restart_fields = self._restart_fields
                self.setup.repository.live_verifier = self._stage
        if config.supervisor:
            self._start_worker(config)
        if self.setup is not None:
            self.try_apply_pending()

    def _start_worker(self, config: ManagedConfig) -> None:
        # The factories are read on every claim, so a live switch reaches both lanes (D238).
        ports = (lambda context, versions: self.config.ports_factory(context, versions))
        commit = ((lambda context, versions: self.config.commit_factory(context, versions))
                  if config.commit_factory is not None else None)
        supervisor = LocalSupervisor(self.repository, ports, lease_seconds=config.lease_seconds, commit_factory=commit)
        self.worker = SupervisorWorker(supervisor, config.poll_seconds)
        self.worker.preparation = self.preparation
        if self.setup is not None:
            self.worker.idle = self.apply_pending
        self.worker.start()

    # --- live configuration (D238) ---------------------------------------------------------

    def _restart_fields(self, session, data) -> list[str]:
        """Global fields this process cannot switch; an empty list means a live set."""
        from my_harness.services.configuration import parse
        from my_harness.services.configuration_import import imported
        setup = self.setup
        if setup is None or setup.legacy or imported(session) and not setup.loaded:
            return ['configuration_import']
        if self.worker is None:
            return []  # a stopped supervisor starts with the new values at the switch
        loaded = (parse(setup.repository.document('global', setup.loaded['revision']), 'global')['service']
                  if setup.loaded else {})
        defaults = {'lease_seconds': 30.0, 'poll_seconds': 0.5}
        return [f'service.{key}' for key in ('supervisor', 'lease_seconds', 'poll_seconds')
                if data['service'].get(key, defaults.get(key)) != loaded.get(key, defaults.get(key))]

    def _stage(self, references):
        """Complete candidate runtime: global composer, exact client preflight and every registered project.

        Built outside write transactions and never installed here. Refusals name the project/role, the
        code and its correction; a project that already fails with the active authority does not block.
        """
        from my_harness.core.engine.journal import JournalError
        from my_harness.services import local_config as legacy
        from my_harness.services.configuration import parse, runtime
        from my_harness.services.managed import guarded_writer
        from my_harness.services.project_configuration import ProjectConfiguration
        from my_harness.services.project_preparation import ProjectPreparation
        from my_harness.services.project_registry import ProjectRegistry, RegistryError
        from my_harness.storage.configuration import ConfigurationConflict
        setup = self.setup
        refs = {ref['scope']: ref for ref in references}
        reference = refs.get('global') or setup.repository.read('global')['active']
        if reference is None:
            raise ConfigurationConflict('active_global_configuration_required')
        def refusal(exc, **where):
            code = getattr(exc, 'code', None) or getattr(exc.__context__, 'code', None) or 'configuration_invalid'
            return {'project': None, 'role': None, **where, 'code': code, 'diagnostic': str(exc)[:500]}
        candidate = runtime(parse(setup.repository.document('global', reference['revision']), 'global'))
        try:
            config = legacy._build(candidate, setup.directory / 'global.toml', allow_empty_compositions=True,
                                   editor=True)[0]
            _validate(config, self.database, self.migrations_dir)
            config = config.registrar.resolve_config(config)
        except (ValueError, OSError) as exc:
            raise ConfigurationConflict('live_configuration_refused', [refusal(exc)]) from None
        details = []
        # Both roles are probed even without registered projects: a wrong path never becomes active.
        for role, declaration in config.registrar.agents.items():
            try:
                config.registrar._resolve_agents({role: declaration})
            except (ValueError, OSError) as exc:
                details.append(refusal(exc, role=role, setting=f'agents.{role}'))
        config = replace(config, commit_factory=guarded_writer(config.commit_factory, self.repository.guard))
        staging = copy.copy(self)
        staging.config, staging.projects, staging._projects_lock, staging.degraded = config, {}, Lock(), {}
        staging.registry = ProjectRegistry(staging)
        staging.registry.unavailable = {}
        staging.project_configuration = ProjectConfiguration(staging)
        staging.preparation = ProjectPreparation(staging)
        failing = set(self.registry.unavailable) | set(self.degraded)
        global_reference = refs.get('global')
        for item in staging.registry.repository.rows():
            if item['status'] != 'ACTIVE':
                continue
            scope = 'project:' + item['id']
            try:
                staging.registry._conflicts(item['id'], Path(item['root']), registered=True)
                project = config.registrar.install(
                    staging.registry._compose(item['row'], (item['version'], item['row_sha256'])))
            except RegistryError as exc:
                staging.registry.unavailable[item['id']] = str(exc)
                details.append(refusal(exc, project=item['id'], setting=scope, already_failing=item['id'] in failing))
                continue
            project = staging.preparation.bind(project)
            try:
                project = staging.project_configuration.install_active(
                    project, reference=refs.get(scope), global_reference=global_reference)
            except (ValueError, OSError, JournalError) as exc:
                staging.degraded[item['id']] = getattr(exc, 'code', 'project_configuration_invalid')
                details.append(refusal(exc, project=item['id'], setting=scope, already_failing=item['id'] in failing))
            staging.install(project)
        if any(not item.get('already_failing') for item in details):
            raise ConfigurationConflict('live_configuration_refused', details)
        staging.loaded = ({**{key: global_reference[key] for key in ('scope', 'revision', 'sha256')},
                           'status': 'VALIDATED'} if global_reference else setup.loaded)
        return staging

    def _snapshot(self):
        return (self.config, self.projects, self.registry.unavailable, self.degraded, self.setup.loaded,
                self.setup.startup_error)

    def _restore(self, snapshot) -> None:
        with self._projects_lock:
            (self.config, self.projects, self.registry.unavailable, self.degraded, self.setup.loaded,
             self.setup.startup_error) = snapshot

    def _install_staging(self, staging) -> None:
        """Pointer swaps only, under the promotion's write barrier: no client or file is touched."""
        with self._projects_lock:
            self.config, self.projects = staging.config, staging.projects
            self.registry.unavailable, self.degraded = staging.registry.unavailable, staging.degraded
            self.setup.loaded, self.setup.startup_error = staging.loaded, None

    def try_apply_pending(self) -> str | None:
        """Request-path variant: an apply problem never fails the read or the confirmation that triggered it."""
        try:
            return self.apply_pending()
        except Exception:  # the pending set stays visible; the next boundary check tries again
            logger.exception("Pending configuration could not be applied.")
            return None

    def apply_pending(self) -> str | None:
        """Promote a confirmed live set at the first idle boundary (D238).

        Returns None without a live set, APPLY_PENDING while current work remains, ACTIVE or FAILED.
        Never terminates, retries or rebinds work; a failed candidate leaves the active set in place.
        """
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        from my_harness.storage.backup import is_read_only_archive
        from my_harness.storage.configuration import ConfigurationConflict, live
        from my_harness.storage.models import ConfigurationOperationRow, ConfigurationScopeRow
        setup = self.setup
        if setup is None or setup.legacy or self.repository is None or is_read_only_archive(self.engine):
            return None
        if not self._apply_lock.acquire(blocking=False):
            return None
        try:
            with Session(self.engine) as session:
                activation_id = session.scalar(select(ConfigurationScopeRow.pending_operation_id).where(
                    ConfigurationScopeRow.pending_operation_id.is_not(None)).limit(1))
                activation = session.get(ConfigurationOperationRow, activation_id) if activation_id else None
                if not live(activation):
                    return None
                references = activation.payload['references']
            if setup.repository.waiting(references):
                return 'APPLY_PENDING'
            key = f'live:{activation_id}'
            def withdraw(code, details=None):
                try:
                    setup.repository.fail_pending(activation_id=activation_id, key=key, code=code, details=details)
                except ConfigurationConflict:
                    return None  # cancelled or replaced concurrently: nothing left to withdraw
                return 'FAILED'
            try:
                staging = self._stage(references)
            except ConfigurationConflict as exc:
                return withdraw(exc.code, exc.details)
            previous = self._snapshot()
            try:
                setup.repository.promote_pending(activation_id=activation_id, key=key,
                                                 on_commit=lambda: self._install_staging(staging))
            except ConfigurationConflict as exc:
                self._restore(previous)
                # New work or an unresolved journal operation appeared: wait for the next boundary.
                if exc.code in ('configuration_has_pending_work', 'configuration_recovery_required'):
                    return 'APPLY_PENDING'
                if exc.code in ('pending_configuration_changed', 'unknown_pending_configuration_activation'):
                    return None
                return withdraw(exc.code)
            except BaseException:
                self._restore(previous)
                raise
            if self.worker is None and self.config.supervisor:
                self._start_worker(self.config)
            return 'ACTIVE'
        finally:
            self._apply_lock.release()

    def stop(self) -> None:
        if self.worker is not None:
            self.worker.stop(timeout=self.config.lease_seconds)

    def ready(self) -> None:
        if self.repository is None:
            raise RuntimeError(tr('runtime.not_started'))

    def graph_runner(self, registry):
        """P002-T003 (D280): graph orchestration is owned here; LangGraph is imported on first use, never at start."""
        from my_harness.orchestration import GraphRunner
        return GraphRunner(self.engine, registry)

    def domain_operations(self):
        """P002-T005 (D286): the shared typed-command service. Agent callers, permission state, delegated adoption
        and receipts keep their fail-closed defaults until T006–T010/T016 provide them; reads need only the engine,
        so they also serve restored query-only copies."""
        if self._domain_operations is None:
            from my_harness.services.domain_operations import DomainOperations
            self._domain_operations = DomainOperations(self.engine)
        return self._domain_operations

    def project(self, project_id: str) -> ManagedProject:
        self.ready()
        try:
            return self.projects[project_id]
        except KeyError:
            raise LookupError(tr('runtime.unregistered')) from None

    def resolve_project(self, project_id: str) -> ManagedProject:
        """Admission resolution; read-only project views do not probe provider clients."""
        project = self.project(project_id)
        registrar = self.config.registrar
        if registrar is not None and hasattr(registrar, 'refresh'):
            project = registrar.refresh(project, force=True)
            # CLI recomposition returns base versions; derive the environment binding again from its receipt.
            project = self.preparation.bind(project)
            if self.setup is not None and not self.setup.legacy:
                project = self.project_configuration.install_active(project)
            self.install(project)
            project = self.project(project_id)
        return project

    def install(self, project: ManagedProject) -> None:
        """D076: hot registration or change; a new copy of the map for readers on other threads."""
        project = self.with_work_language(project)
        with self._projects_lock:
            self.projects = {**self.projects, project.id: project}

    def with_work_language(self, project: ManagedProject) -> ManagedProject:
        """P011-T008 (D167): the context carries the work language confirmed in SQLite for its root, if any."""
        from my_harness.storage.work_language import read
        current = read(self.engine, project.context.root)
        if current is None:
            return project
        if project.context.work_language == current['work_language']:
            return project
        if project.context.work_language is not None:
            raise ValueError(tr('runtime.work_language_differs_confirmed', id=project.id,
                                work_language=repr(project.context.work_language),
                                confirmed=repr(current['work_language']), root=project.context.root))
        try:
            return replace(project, context=replace(project.context, work_language=current['work_language']))
        except FileNotFoundError:
            return project  # a vanished root admits nothing anyway; the registry reports it as unavailable

    def _toml_work_language(self, project: ManagedProject) -> ManagedProject:
        """A `local-config-6` project that declares its work language records it once, at startup (D167).

        Loading the TOML stays free of effects; SQLite rules afterwards and another value stops the service."""
        from my_harness.storage.backup import is_read_only_archive
        from my_harness.storage.work_language import WorkLanguageImmutable, associate
        declared = project.context.work_language
        if declared is not None and not is_read_only_archive(self.engine):
            confirmation = {'local_config': project.versions.get('local_config'),
                            'local_config_sha256': project.versions.get('local_config_sha256')}
            try:
                with self.repository._write() as session:
                    associate(session, root=str(project.context.root), project_id=project.id, work_language=declared,
                              source='toml', confirmation=confirmation, now=self.repository._now())
            except WorkLanguageImmutable as exc:
                raise ValueError(f"{project.id}: {exc}") from None
        return self.with_work_language(project)

    def uninstall(self, project_id: str) -> None:
        with self._projects_lock:
            self.projects = {key: value for key, value in self.projects.items() if key != project_id}

    def project_id(self, root: str) -> str | None:
        return next((p.id for p in self.projects.values() if str(p.context.root) == root), None)

    def notify(self) -> None:
        if self.worker is not None:
            self.worker.notify()

    def supervisor_status(self) -> dict:
        from my_harness.storage.backup import is_read_only_archive

        self.ready()
        return {"read_only_archive": is_read_only_archive(self.engine),
                "enabled": self.worker is not None, "alive": bool(self.worker and self.worker.alive()),
                "last_error": self.worker.error() if self.worker else None,
                "ports_configured": self.config.ports_factory is not None,
                "commit_writer_configured": self.config.commit_factory is not None,
                "configuration_mode": self.setup.state()['mode'] if self.setup else None}
