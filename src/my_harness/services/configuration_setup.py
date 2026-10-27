"""Initial global configuration, with passive reads and explicit CLI preflight (D222)."""
import copy
import json
import os
from pathlib import Path
import pwd
import shutil

from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.adapters.cli_agents import EFFORTS
from my_harness.adapters.cli_diagnostics import preflight_config
from my_harness.i18n import tr
from my_harness.services import local_config as legacy
from my_harness.services.configuration import GLOBAL, parse
from my_harness.services.managed_runtime import CONFIG_ENV, ManagedConfig, load_config
from my_harness.storage.backup import is_read_only_archive, RESTORED_USER_VERSION
from my_harness.storage.configuration import ConfigurationConflict, ConfigurationRepository, UNRESOLVED
from my_harness.storage.managed import SQLiteManagedRepository
from my_harness.storage.models import (ConfigurationScopeRow as Scope, ConfigurationOperationRow as Operation,
                                          RegisteredProjectRow as Project)


def toml_document(data):
    """Serialize the editor's JSON form without interpreting strings as TOML syntax."""
    def value(item):
        if isinstance(item, bool):
            return 'true' if item else 'false'
        if isinstance(item, (int, float)):
            return repr(item)
        if isinstance(item, str):
            return json.dumps(item, ensure_ascii=False)
        if isinstance(item, list):
            return '[' + ', '.join(value(x) for x in item) + ']'
        if isinstance(item, dict):
            return '{' + ', '.join(f'{json.dumps(k)} = {value(v)}' for k, v in item.items()) + '}'
        raise ValueError(tr('setup.form_value'))
    return ''.join(f'{json.dumps(k)} = {value(v)}\n' for k, v in data.items())


class ConfigurationSetup:
    def __init__(self, engine, directory, state_dir, source=None):
        self.engine = engine
        self.directory, self.state_dir = Path(directory), Path(state_dir)
        self.source = Path(source) if source else None
        self.repository = ConfigurationRepository(SQLiteManagedRepository(engine), self.directory,
                                                   state_dir=self.state_dir)
        self.repository.derive_projects = True
        from my_harness.services.configuration_editing import verify_revision
        self.repository.project_verifier = lambda session, scope, data: verify_revision(session, scope, data, self.repository)
        self.legacy = False
        self.startup_error = None
        self.loaded = None

    def _new_installation(self):
        from my_harness.services.configuration_import import imported
        with Session(self.engine) as session:
            if imported(session):
                return
            # T007 registrations without an executable profile belong to this v9 authority already.
            if session.scalar(select(Project.id).where(
                    (Project.composition.is_not(None)) | (Project.profile.is_not(None))).limit(1)):
                raise ConfigurationConflict('configuration_import_required')
        if self.legacy:
            raise ConfigurationConflict('configuration_import_required')

    def start(self, explicit=None):
        if is_read_only_archive(self.engine):
            return ManagedConfig()
        try:
            # Creating the selected product directory never changes preexisting permissions.
            for path in (self.directory, self.state_dir):
                if not path.is_absolute() or '..' in path.parts or path.resolve() != path:
                    raise ValueError(tr('setup.invalid'))
            if any(os.path.lexists(parent / '.git') for parent in (self.directory, *self.directory.parents)):
                raise ValueError(tr('setup.invalid'))
            if not self.directory.exists():
                self.directory.mkdir(mode=0o700)
            state = self.repository.read()
            from my_harness.services.configuration_import import imported
            with Session(self.engine) as session:
                importing = imported(session)
            if state['version'] and (state['active'] or state['pending'] or not importing) and (explicit is not None or (self.source is not None
                    and self.source != self.directory / 'global.toml')):
                raise ConfigurationConflict('configuration_source_conflict')
            if state['pending']:
                self._new_installation()
                with Session(self.engine) as session:
                    activation_id = session.get(Scope, 'global').pending_operation_id
                self.repository.promote_pending(activation_id=activation_id, key=f'startup:{activation_id}', restarted=True)
                state = self.repository.read()
            if state['active']:
                if state['status'] != 'READY':
                    return ManagedConfig()
                self._new_installation()
                text = self.repository.document('global', state['active']['revision'])
                data = parse(text, 'global')
                self.loaded = state['active']
                candidate = copy.deepcopy(data)
                candidate.setdefault('compositions', {})
                return legacy._build(candidate, self.directory / 'global.toml',
                                     allow_empty_compositions=True, editor=True)[0]
            if state['status'] == 'RECOVERY_REQUIRED' or state['version'] and not importing:
                return ManagedConfig()
            if explicit is not None:
                self.legacy = True
                return explicit
            if self.source:
                if not self.source.exists():
                    raise ValueError(tr('setup.invalid'))
                # A v9 working copy alone is not authorized. Legacy remains a separate explicit input.
                data = legacy._read(self.source)
                if data.get('format') == GLOBAL:
                    return ManagedConfig()
                config = legacy.build(data, self.source)
                self.legacy = True
                return config
            if os.environ.get(CONFIG_ENV):
                config = load_config()
                if config.registrar is not None:
                    self.source = config.registrar.source
                self.legacy = True
                return config
        except (ValueError, OSError):
            # No raw candidate, environment, path, or exception text enters public diagnostics.
            self.startup_error = 'configuration_invalid'
        return ManagedConfig()

    def state(self):
        try:
            state = self.repository.read()
        except (ValueError, OSError):
            # Keep durable references visible even when private files cannot be inspected.
            with Session(self.engine) as session:
                head = session.get(Scope, 'global')
                state = {'scope': 'global', 'version': head.version if head else 0, 'status': 'INVALID',
                         **{key: self.repository._ref(session, 'global', getattr(head, column)) if head else None
                            for key, column in (('saved', 'saved_revision'), ('active', 'active_revision'),
                                                ('pending', 'pending_revision'))}}
        mode = state['status']
        if mode == 'EXTERNAL_CHANGE':
            mode = 'INVALID'
        if self.startup_error:
            mode = 'INVALID'
        if (self.legacy and not self.startup_error and not state['pending']
                and mode in ('UNCONFIGURED', 'READY')):
            mode = 'READY'
        # Cancelling pending activation must never enable a process that did not load the active version.
        if mode == 'READY' and not self.legacy and self.loaded != state['active']:
            mode = 'RESTART_REQUIRED'
        with Session(self.engine) as session:
            head = session.get(Scope, 'global')
            operations = list(session.scalars(select(Operation.id).where(Operation.status.in_(UNRESOLVED))))
            pending_id = head.pending_operation_id if head else None
        from my_harness.services.configuration_import import imported
        with Session(self.engine) as session:
            importing = imported(session)
        references = []
        pending_versions = {}
        with Session(self.engine) as session:
            from my_harness.storage.models import ConfigurationRevisionRow as Revision
            revision = session.get(Revision, ('global', state['saved']['revision'])) if state['saved'] else None
            operation = session.get(Operation, revision.operation_id) if revision else None
            for change in operation.payload.get('changes', []) if operation else []:
                current = session.get(Scope, change['scope'])
                references.append({'scope': change['scope'], 'revision': change['revision'],
                    'sha256': change['sha256'], 'expected_version': current.version})
            pending = session.get(Operation, pending_id) if pending_id else None
            if pending:
                pending_versions = {ref['scope']: session.get(Scope, ref['scope']).version
                                    for ref in pending.payload['references']}
        if importing and not state['active']:
            with Session(self.engine) as session:
                references = []
                for scope in ['global', *['project:' + p['id'] for p in importing['projects']]]:
                    head = session.get(Scope, scope)
                    if head and head.saved_revision:
                        ref = self.repository._ref(session, scope, head.saved_revision)
                        references.append({k: ref[k] for k in ('scope', 'revision', 'sha256')} | {'expected_version': head.version})
        return {**state, 'mode': mode, 'legacy': self.legacy, 'legacy_source': str(self.source) if self.legacy and self.source else None,
                'imported_projects': [p['id'] for p in importing['projects']] if importing else [],
                'activation_references': references,
                'pending_versions': pending_versions,
                'pending_activation_id': pending_id, 'recovery_operations': operations,
                'blockers': [] if mode == 'READY' else [self.startup_error or mode.lower()]}

    def require_ready(self, session=None):
        if session is None:
            state = self.state()
            if state['mode'] != 'READY':
                raise ConfigurationConflict('configuration_' + state['mode'].lower())
            return
        # The write barrier uses its existing connection: no nested pool checkout or stale snapshot.
        if session.connection().exec_driver_sql('PRAGMA user_version').scalar_one() == RESTORED_USER_VERSION:
            raise ConfigurationConflict('configuration_read_only_archive')
        if self.legacy and not self.startup_error:
            state = self.repository._state(session, self.repository._files(session), 'global')
            if state['status'] not in ('UNCONFIGURED', 'READY'):
                raise ConfigurationConflict('configuration_not_ready')
            return
        state = self.repository._state(session, self.repository._files(session), 'global')
        if self.startup_error or state['status'] != 'READY' or state['active'] != self.loaded:
            raise ConfigurationConflict('configuration_not_ready')

    def editable(self):
        self.repository._writable()
        self._new_installation()
        if self.legacy and self.source:
            from my_harness.services.configuration_import import imported
            from my_harness.storage.backup import _read
            from my_harness.services.configuration import digest
            with Session(self.engine) as session:
                snapshot = imported(session)
            if snapshot and digest(_read(self.source, legacy.MAX_BYTES)) != snapshot['sha256']:
                raise ConfigurationConflict('configuration_import_source_changed')
        # Validation/preview may diagnose an invalid working copy; storage still enforces its CAS.

    def candidate(self, *, text=None, form=None, validated=True):
        self.editable()
        if (text is None) == (form is None):
            raise ValueError(tr('setup.candidate'))
        if form is not None:
            data = copy.deepcopy(form)
            data.setdefault('format', GLOBAL)
            service = data.setdefault('service', {})
            if not isinstance(service, dict):
                raise ValueError(tr('setup.invalid'))
            service.setdefault('state_dir', str(self.state_dir))
            text = toml_document(data)
        parse(text, 'global', validated=validated)
        return text

    def detect(self, path):
        self.repository._writable()
        folders = path.split(os.pathsep)
        if not path or any(not item or not Path(item).is_absolute() for item in folders):
            raise ValueError(tr('setup.path'))
        # No inherited PATH/environment, home scan, Git config, credentials or process execution.
        return {'candidates': {name: shutil.which(name, path=path) for name in ('git', 'codex', 'claude')},
                'user': pwd.getpwuid(os.getuid()).pw_name, 'state_dir': str(self.state_dir),
                'configuration_dir': str(self.directory),
                'providers': {key: list(value) for key, value in EFFORTS.items()}}

    def check_clients(self, **candidate):
        text = self.candidate(**candidate)
        data = parse(text, 'global')
        agents, _ = legacy._agents(data['agents'], automatic=True)
        return {role: preflight_config(cli, access='write' if role == 'executor' else 'read')
                for role, cli in agents.items()}
