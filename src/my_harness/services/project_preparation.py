"""D119: confirmed, deterministic preparation after the documentary root commit.

The core (CAS, intention, steps, lease, journal, commit and recovery) is shared; each packaged recipe
contributes its manifest, steps, source rules and receipt: Django (D119) and TypeScript web (D142).
Their v2 successors (P011-T020, D168) prepare with the project's work language and dispatch checks by step `id`."""
from dataclasses import asdict, replace
from difflib import unified_diff
import json
import os
from pathlib import Path
import secrets
import stat
from threading import Event as ThreadEvent, Thread
from uuid import uuid4

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from my_harness.adapters.commands import CommandConfig
from my_harness.adapters.git import GitWorkspace
from my_harness.adapters.preparation import (
    PreparationCommandRunner, environment_snapshot, file_hash, sha, verify_files, verify_receipt, write_new,
    parent as file_parent,
)
from my_harness.adapters.import_git import check_filters, check_submodules
from my_harness.core.engine.context import Command
from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.evidence import matches
from my_harness.core.engine.journal import JournalError
from my_harness.i18n import emission, message, tr
from my_harness.recipes import django, django_2, typescript_web, typescript_web_2
from my_harness.services.project_creation import directory, identity
from my_harness.services.project_registry import RegistryError, digest
from my_harness.storage.managed import Conflict
from my_harness.storage.models import (
    CheckoutLockRow as Lock, RegisteredProjectRow as Project, ManagedJobRow as Job, ManagedRunRow as Run,
    ProjectBootstrapRow as Bootstrap, ProjectPreparationOperationRow as Operation,
    ProjectPreparationStepRow as Step, ProjectPreparationEventRow as PreparationEvent,
)
from my_harness.storage.preferences import language as stored_language
from my_harness.storage.preparation import PreparationRepository, PreparationJournal
from my_harness.storage.registry import ProjectRegistryRepository, UNFINISHED
from my_harness.storage import work_language as work_languages

CONTRACT = 'project-preparation-1'


def django_link(root, key, path):
    """Only the environment's known interpreter aliases; caches may not redirect effects."""
    cache = root / django.WORK / 'cache'
    cache_link = key.startswith(django.WORK + '/cache/') and path.resolve(strict=True).is_relative_to(cache)
    return key.startswith('.venv/bin/python') or key == '.venv/lib64' or cache_link


def typescript_link(root, key, path):
    """npm links package binaries (`node_modules/.bin/tsc`); none may leave `node_modules`."""
    return key.startswith('node_modules/') and path.resolve(strict=True).is_relative_to(root / 'node_modules')


def snapshot(root, links=django_link):
    """All checkout bytes/links/modes outside Git, including ignored files. Never follows a link."""
    result, size = {}, 0
    with directory(root):
        for folder, dirs, files in os.walk(root, followlinks=False):
            if Path(folder) == root:
                dirs[:] = [d for d in dirs if d != '.git']
            for name in sorted(dirs + files):
                path = Path(folder) / name
                key, info = str(path.relative_to(root)), path.lstat()
                if stat.S_ISLNK(info.st_mode):
                    if not links(root, key, path):
                        raise ValueError(tr('preparation.unexpected_symlink', key=key))
                    result[key] = {'link': os.readlink(path)}
                elif stat.S_ISDIR(info.st_mode):
                    result[key] = {'directory': identity(info)}
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    size += info.st_size
                    result[key] = {'sha256': file_hash(path), 'executable': bool(info.st_mode & 0o111)}
                else:
                    raise ValueError(tr('preparation.unexpected_file', key=key))
                if len(result) > 40000 or size > 1024 * 1024 * 1024:
                    raise ValueError(tr('preparation.preparation_workspace_evidence_limit'))
    return result


def hashes(files):
    return {path: sha(content.encode()) for path, content in files.items()}


class DjangoRecipe:
    """D119: templates through startproject/startapp, a pinned venv and a local secret."""
    module, label, links = django, 'Django', staticmethod(django_link)
    by_work_language = False
    tools = ('python_executable', 'installer_executable')
    environment = '.venv'
    reflog = 'harness: prepare Django'
    local_prefixes = ('.venv/', django.WORK + '/', 'reports/', '.pytest_cache/', '.mypy_cache/', '.ruff_cache/')

    @staticmethod
    def manifest(project_id, config, language):
        return django.scaffold()

    @staticmethod
    def targets(files):
        return (*files, '.venv', django.WORK, '.django-secret', 'db.sqlite3')

    @staticmethod
    def plan(files, config, mode):
        return {'templates': django.templates(files), 'packages': django.PACKAGES,
                'lock_sha256': sha(django.LOCK.encode()),
                'network': {'enabled': mode == 'network', 'index': 'https://pypi.org/simple',
                            'files_host': 'files.pythonhosted.org', 'automatic_retry': False},
                'local_only': ['.venv/', django.WORK + '/', '.django-secret', 'db.sqlite3', 'reports/'],
                'message': 'harness: prepare Django (django-recipe-1)'}

    @staticmethod
    def uncertain(spec):
        return spec['label'] == 'Crear entorno aislado'

    @staticmethod
    def source_check(spec, number):
        """Before generation the scaffold is partial; after publishing, it is complete."""
        return None if number < 7 else number < 10

    @staticmethod
    def extra_allowed(plan):
        return set(plan['templates']) | {'.django-secret', 'db.sqlite3'}

    @staticmethod
    def verify_staging(root, plan, files):
        verify_files(root, hashes(plan['templates']))
        for path, expected in files.items():
            generated = root / django.WORK / 'output' / path
            if os.path.lexists(generated):
                verify_files(root, {str(generated.relative_to(root)): expected})

    # v1 plans froze Spanish labels without ids; their checks stay keyed on those labels.
    CHECKS = {'Verificar intérprete base': 'python-version', 'Verificar instalador uv': 'installer-version',
              'Acreditar versiones instaladas': 'installed-versions'}

    @classmethod
    def step(cls, spec):
        return cls.CHECKS.get(spec['label'])

    @classmethod
    def check_output(cls, spec, stdout, plan):
        step = cls.step(spec)
        if step == 'python-version' and stdout.strip() != 'Python ' + plan['config']['python_version']:
            raise ValueError(tr('preparation.base_python_version_differs'))
        if step == 'installer-version' and stdout.strip().split()[:2] != ['uv', plan['config']['installer_version']]:
            raise ValueError(tr('preparation.uv_version_differs_confirmed'))
        if step == 'installed-versions':
            actual = json.loads(stdout)
            normalize = lambda name: name.lower().replace('_', '-')
            installed = {normalize(k): v for k, v in actual['packages'].items()}
            if installed != {normalize(k): v for k, v in plan['packages'].items()}:
                raise ValueError(tr('preparation.installed_distributions_differ_pinned'))
            if '.'.join(map(str, actual['python'])) != plan['config']['python_version']:
                raise ValueError(tr('preparation.environment_python_version_differs'))

    @staticmethod
    def receipt(root, plan):
        return {'packages': plan['packages'], 'environment': environment_snapshot(root, plan['config'])}

    @staticmethod
    def local_secrets(root):
        return {'.django-secret': file_hash(root / '.django-secret')}


class TypeScriptRecipe:
    """D142: the packaged manifest, `npm ci` from the declared cache and the profile validations."""
    module, label, links = typescript_web, 'TypeScript web', staticmethod(typescript_link)
    by_work_language = False
    tools = ('node_executable', 'npm_executable')
    environment = 'node_modules'
    reflog = 'harness: prepare TypeScript web'
    local_prefixes = typescript_web.LOCAL

    @staticmethod
    def manifest(project_id, config, language):
        return typescript_web.manifest(project_id, config)

    @staticmethod
    def targets(files):
        return (*files, *(path.rstrip('/') for path in typescript_web.LOCAL))

    @staticmethod
    def plan(files, config, mode):
        return {'lock_sha256': sha(files['package-lock.json'].encode()),
                'network': {'enabled': mode == 'network', 'registry': typescript_web.REGISTRY,
                            'cache': config['npm_cache'], 'automatic_retry': False,
                            'notice': 'Con red, npm descarga del registro y escribe en la caché del operador.'},
                'local_only': list(typescript_web.LOCAL),
                'message': 'harness: prepare TypeScript web (typescript-web-recipe-1)'}

    @staticmethod
    def uncertain(spec):
        return False

    @staticmethod
    def source_check(spec, number):
        return False  # The whole manifest exists from the first step on.

    @staticmethod
    def extra_allowed(plan):
        return set()

    @staticmethod
    def verify_staging(root, plan, files):
        pass

    CHECKS = {'Verificar Node': 'node-version', 'Verificar npm': 'npm-version'}

    @classmethod
    def step(cls, spec):
        return cls.CHECKS.get(spec['label'])

    @classmethod
    def check_output(cls, spec, stdout, plan):
        step = cls.step(spec)
        if step == 'node-version' and stdout.strip() != 'v' + plan['config']['node_version']:
            raise ValueError(tr('preparation.node_version_differs_confirmed'))
        if step == 'npm-version' and stdout.strip() != plan['config']['npm_version']:
            raise ValueError(tr('preparation.npm_version_differs_confirmed'))

    @staticmethod
    def receipt(root, plan):
        # node_modules is not frozen: the profile reinstalls it from the lock before every task.
        return {'tools': plan['tool_files']}

    @staticmethod
    def local_secrets(root):
        return {}


class DjangoRecipe2(DjangoRecipe):
    """P011-T020 (D168): `django-recipe-2`, same effects as v1; scaffold prose follows the work language."""
    module, by_work_language = django_2, True
    # Steps from generation until publishing see a partial scaffold; local commands after it, a complete one.
    PARTIAL, COMPLETE = ('generate-project', 'generate-app'), ('migrate',)

    @staticmethod
    def manifest(project_id, config, language):
        return django_2.scaffold(language)

    @staticmethod
    def plan(files, config, mode):
        return {**DjangoRecipe.plan(files, config, mode), 'templates': django_2.templates(files),
                'packages': django_2.PACKAGES, 'lock_sha256': sha(django_2.LOCK.encode()),
                'message': 'harness: prepare Django (django-recipe-2)'}

    @staticmethod
    def step(spec):
        return spec['id']

    @staticmethod
    def uncertain(spec):
        return spec['id'] == 'create-environment'

    @classmethod
    def source_check(cls, spec, number):
        if spec['id'] in cls.PARTIAL:
            return True
        return False if spec['id'] in cls.COMPLETE or spec['id'].startswith('validate-') else None


class TypeScriptRecipe2(TypeScriptRecipe):
    """P011-T020 (D168): `typescript-web-recipe-2`, same effects as v1; test prose follows the work language."""
    module, by_work_language = typescript_web_2, True

    @staticmethod
    def manifest(project_id, config, language):
        return typescript_web_2.manifest(project_id, config, language)

    @staticmethod
    def plan(files, config, mode):
        return {**TypeScriptRecipe.plan(files, config, mode),
                'network': {'enabled': mode == 'network', 'registry': typescript_web_2.REGISTRY,
                            'cache': config['npm_cache'], 'automatic_retry': False,
                            'notice': 'With network, npm downloads from the registry and writes to the operator '
                                      'cache.'},
                'message': 'harness: prepare TypeScript web (typescript-web-recipe-2)'}

    @staticmethod
    def step(spec):
        return spec['id']


RECIPES = {django.VERSION: DjangoRecipe, typescript_web.VERSION: TypeScriptRecipe,
           django_2.VERSION: DjangoRecipe2, typescript_web_2.VERSION: TypeScriptRecipe2}


class ProjectPreparation:
    def __init__(self, runtime):
        self.runtime, self.managed = runtime, runtime.repository
        self.repository = PreparationRepository(self.managed)
        self.lock = runtime.registry._lock
        self.runner_factory = PreparationCommandRunner

    def require(self, project_id):
        project = self.runtime.project(project_id)
        registrar = self.runtime.registry.registrar
        if not registrar or project.versions.get('project_recipe') not in RECIPES:
            raise RegistryError(409, 'recipe_unavailable', tr('preparation.no_recipe'))
        config = registrar._recipe_roots.get(project.context.root)
        if not config or 'project_registry' not in project.versions:
            raise RegistryError(409, 'recipe_unavailable', tr('preparation.new_child'))
        return project, config

    def writer(self, project):
        registrar = self.runtime.config.registrar
        writer = GitWorkspace(registrar.identity, executable=registrar.git_executable)
        writer.local_objects_only = True
        git = writer._git(project.context.root)
        check_filters(git)
        check_submodules(git)
        with directory(project.context.root / '.git'):
            pass
        assessment = self.managed.guard.assess(project.context.root)
        if assessment.refusal or assessment.activation is not None:
            raise RegistryError(409, 'mode_refused', tr('preparation.legacy'))
        return writer, git

    def work_language(self, session, project, recipe):
        """D168: a v2 recipe prepares with the root's confirmed work language (D167), never an inferred one."""
        if not recipe.by_work_language:
            return {}
        row = work_languages.get(session, str(project.context.root))
        if row is None:
            raise RegistryError(409, 'work_language_required',
                                message('work_language.unconfirmed', self.runtime.registry._language()))
        language = row['work_language']
        return {'work_language': language, 'work_language_sha256': row['sha256'],
                'recipe_sha256': recipe.module.fingerprint(language)}

    def latest(self, project_id, session):
        return session.scalar(select(Operation).where(Operation.project_id == project_id)
                              .order_by(Operation.created_at.desc(), Operation.id.desc()).limit(1))

    def read(self, project_id):
        project = self.runtime.project(project_id)
        from my_harness.core.engine.context import IntakeContext
        available = bool(project.versions.get('project_recipe') or project.versions.get('project_configuration')) or isinstance(project.context, IntakeContext)
        with Session(self.runtime.engine) as session:
            row = self.latest(project_id, session)
            receipt = session.scalar(select(Operation.receipt).where(Operation.project_id == project_id,
                                                                     Operation.status == 'COMPLETED').order_by(Operation.created_at.desc(), Operation.id.desc()).limit(1))
        diagnostic = None
        if receipt:
            try:
                if receipt.get('contract') == 'project-profile-preparation-1':
                    from my_harness.services.configuration import parse
                    from my_harness.services.configuration_editing import prepared
                    config = self.generic().configuration()
                    state = config.read('project:' + project_id)
                    reference = state['saved']
                    if reference:
                        data = parse(config.document(state['scope'], reference['revision']), state['scope'])
                        with Session(self.runtime.engine) as session:
                            receipt = prepared(session, state['scope'], data, reference=reference, verify=False).receipt
                    self.generic().verify_configuration(project, receipt)
                    available = True
                else:
                    verify_receipt(project.context.root, receipt)
            except (JournalError, ValueError) as exc:
                diagnostic = str(exc)
        return {'available': available, 'prepared': bool(receipt and not diagnostic), 'diagnostic': diagnostic,
                'recipe': project.versions.get('project_recipe'),
                'operation': self.repository.read(row.id, summary=True) if row else None,
                'project_version': int(project.versions.get('project_registry', 0))}

    def bind(self, project):
        if not project.versions.get('project_recipe'):
            return project
        with Session(self.runtime.engine) as session:
            row = session.scalar(select(Operation).where(Operation.project_id == project.id,
                Operation.status == 'COMPLETED',
                Operation.receipt['recipe'].as_string() == project.versions['project_recipe'],
                Operation.receipt['recipe_config_sha256'].as_string() == project.versions['recipe_config_sha256'])
                .order_by(Operation.created_at.desc(), Operation.id.desc()).limit(1))
            receipt = row.receipt if row else None
        registrar = self.runtime.registry.registrar
        if receipt and receipt.get('recipe_config_sha256') == project.versions['recipe_config_sha256']:
            registrar._receipts[project.context.root] = receipt
            project = replace(project, versions={**project.versions, 'project_environment_sha256': digest(receipt)})
        else:
            registrar._receipts.pop(project.context.root, None)
        self.runtime.install(project)
        return project

    def _idle(self, session, root, *, previous=None):
        if session.scalar(select(Job.id).join(Run, Run.id == Job.run_id).where(
                Run.root == root, Job.status.in_(UNFINISHED))):
            raise RegistryError(409, 'pending_jobs', tr('preparation.pending'))
        lock = session.get(Lock, root)
        if lock and lock.preparation_id != previous:
            raise RegistryError(409, 'pending_jobs', tr('preparation.locked'))
        active = session.scalar(select(Operation).where(Operation.root == root, Operation.reserved.is_(True)))
        if active and active.id != previous:
            raise RegistryError(409, 'recovery_required', tr('preparation.unresolved'))
        # Exclude the already completed definition; preserve pending acceptance/commit/chat barriers.
        blockers = [value for value in ProjectRegistryRepository._configuration_blockers(session, root)
                    if value != tr('registry.blocker_preparation', id=previous)]
        if blockers:
            raise RegistryError(409, 'pending_jobs', '; '.join(blockers))

    def preview(self, project_id, body, *, session=None):
        if body.get('contract') == 'project-profile-preparation-1':
            return self.generic().preview(project_id, body, session=session)
        if session is None:
            with Session(self.runtime.engine) as read:
                return self.preview(project_id, body, session=read)
        project, config = self.require(project_id)
        root = project.context.root
        recipe = RECIPES[project.versions['project_recipe']]
        current = session.get(Project, project_id)
        if not current or current.status != 'ACTIVE' or current.version != body['expected_version']:
            raise RegistryError(409, 'stale_version', tr('preparation.project_stale'))
        previous_id = body.get('previous_id')
        self._idle(session, str(root), previous=previous_id)
        language = self.work_language(session, project, recipe)
        if body['mode'] == 'network' and not config['allow_network']:
            raise RegistryError(409, 'network_not_allowed', tr('preparation.offline_only'))
        writer, git = self.writer(project)
        with directory(root) as fd:
            info = identity(os.fstat(fd))
        if previous_id:
            previous = self.repository.require(session, previous_id)
            if (previous.project_id != project_id or previous.status not in ('FAILED', 'CANCELLED', 'RECOVERY_REQUIRED')
                    or previous.status != 'CANCELLED' and not previous.reserved):
                raise RegistryError(409, 'recovery_required', tr('preparation.previous'))
            self.repository.stopped(session, previous)
            if (previous.plan['versions'] != dict(project.versions) or previous.plan['identity'] != info
                    or any(previous.plan.get(key) != value for key, value in language.items())):
                raise RegistryError(409, 'preview_changed', tr('preparation.original_changed'))
            steps = list(session.scalars(select(Step).where(Step.operation_id == previous.id).order_by(Step.number)))
            first = next((s.number for s in steps if s.status != 'DONE'), len(steps) - 1)
            if body.get('retry_step') != first:
                raise RegistryError(409, 'recovery_required', tr('preparation.first_step'))
            if recipe.uncertain(steps[first].spec):
                raise RegistryError(409, 'recovery_required', tr('preparation.environment_uncertain'))
            old = previous.plan
            verify_files(root, old['base_files'])
            if first == 0:
                if snapshot(root, recipe.links) != old['initial_workspace']:
                    raise RegistryError(409, 'recovery_required', tr('preparation.files_uncertain'))
            else:
                self._verify_source(root, old, allow_partial=True)
                # A failed command cannot establish ownership of new environment bytes. Reuse only the
                # environment accredited by the completed prefix; partial installations need external repair.
                before = steps[first - 1].evidence['workspace']
                now = snapshot(root, recipe.links)
                env = lambda values: {p: v for p, v in values.items()
                                      if p == recipe.environment or p.startswith(recipe.environment + '/')}
                if env(now) != env(before):
                    raise RegistryError(409, 'recovery_required', tr('preparation.environment_changed'))
            expected_head = previous.commit_intent['expected_commit'] if previous.commit_intent else old['base_head']
            head = git.text('rev-parse', 'HEAD')
            if head not in {old['base_head'], expected_head}:
                raise RegistryError(409, 'preview_changed', tr('preparation.head_changed'))
            plan = {**old, 'mode': body['mode'], 'steps': self.steps(root, config, body['mode'], recipe),
                    'recovery': {'previous_id': previous.id, 'previous_version': previous.version,
                                 'retry_step': first, 'workspace': snapshot(root, recipe.links)},
                    'inherited_commit': previous.commit_intent,
                    'network': {**old['network'], 'enabled': body['mode'] == 'network'}}
            # Changing network mode changes only the pending install command; completed effects remain frozen.
            for s in steps[:first]:
                plan['steps'][s.number] = s.spec
            plan.pop('preview_sha256', None)
        else:
            if body.get('retry_step') is not None:
                raise RegistryError(422, 'invalid_request', tr('preparation.retry_previous'))
            if self.latest(project_id, session):
                raise RegistryError(409, 'recovery_required', tr('preparation.exists'))
            if not current.creation_id:
                raise RegistryError(409, 'recipe_unavailable', tr('preparation.created_only'))
            bootstrap = session.scalar(select(Bootstrap).where(Bootstrap.root == str(root), Bootstrap.status == 'COMPLETED'))
            if not bootstrap or git.text('rev-parse', 'HEAD') != bootstrap.result['commit']:
                raise RegistryError(409, 'definition_required', tr('preparation.definition_first'))
            captured = writer.capture(project.context)
            provenance = json.loads(captured.provenance_json)
            if provenance['base_tree'] != provenance['index_tree'] or captured.changed_paths:
                raise RegistryError(409, 'checkout_changed', tr('preparation.clean'))
            tracked = set(git.run('ls-files', '-z').decode().strip('\0').split('\0'))
            if tracked != set(bootstrap.result['documents']):
                raise RegistryError(409, 'definition_required', tr('preparation.initial_tree'))
            workspace = snapshot(root, recipe.links)
            if any('sha256' in v and p not in tracked for p, v in workspace.items()):
                raise RegistryError(409, 'target_exists', tr('preparation.foreign_files'))
            files = recipe.manifest(project_id, config, language.get('work_language'))
            for path in recipe.targets(files):
                if os.path.lexists(root / path):
                    raise RegistryError(409, 'target_exists', tr('preparation.target_exists', path=path))
            # Every new tracked path must actually enter Git; a parent exclude cannot hide part of the manifest.
            for path in files:
                if git.code('check-ignore', '--no-index', '--', path) == 0:
                    raise RegistryError(409, 'target_ignored', tr('preparation.target_ignored', path=path))
            specific = recipe.plan(files, config, body['mode'])
            message = specific.pop('message')
            plan = {'contract': CONTRACT, 'recipe': recipe.module.VERSION, 'preparation_commands': 'preparation-commands-1',
                    'project_id': project_id, 'root': str(root), 'identity': info,
                    'expected_version': current.version, 'versions': dict(project.versions), **language,
                    'config': config,
                    'tool_files': {key: {'resolved': str(Path(config[key]).resolve(strict=True)),
                                         'sha256': file_hash(Path(config[key]).resolve(strict=True))}
                                   for key in recipe.tools},
                    'base_head': captured.base_revision, 'base_tree': provenance['base_tree'],
                    'base_files': bootstrap.result['documents'], 'initial_workspace': workspace,
                    'files': [{'path': p, 'content': c, 'sha256': sha(c.encode()),
                               'diff': ''.join(unified_diff([], c.splitlines(keepends=True),
                                                            fromfile='/dev/null', tofile=p))}
                              for p, c in sorted(files.items())],
                    **specific, 'mode': body['mode'],
                    'steps': self.steps(root, config, body['mode'], recipe),
                    'commit': {'message': message,
                               'author_name': writer.identity.name, 'author_email': writer.identity.email}}
        return {**plan, 'preview_sha256': digest(plan)}

    def confirm(self, project_id, body, key):
        if body['change'].get('contract') == 'project-profile-preparation-1' and (
                body.get('confirmed') is not True or not isinstance(body.get('reason'), str) or not body['reason'].strip()):
            from my_harness.services.profile_preparation import refuse
            raise refuse()
        request_sha = digest({'project_id': project_id, **body})
        with self.lock, self.managed._write() as session:
            old = session.scalar(select(Operation).where(Operation.idempotency_key == key))
            if old:
                if old.request_sha256 != request_sha:
                    raise RegistryError(409, 'idempotency_conflict', tr('preparation.key_reused'))
                return self.repository.read(old.id)
            preview = self.preview(project_id, body['change'], session=session)
            if preview['preview_sha256'] != body['preview_sha256']:
                raise RegistryError(409, 'preview_changed', tr('preparation.plan_changed'))
            operation_id, now = str(uuid4()), self.managed._now()
            previous_id = body['change'].get('previous_id')
            if previous_id:
                previous = self.repository.require(session, previous_id)
                previous.reserved = False
                self.repository.event(session, previous, 'successor_confirmed', {'successor_id': operation_id})
                session.execute(delete(Lock).where(Lock.preparation_id == previous_id))
                session.flush()
            row = Operation(id=operation_id, project_id=project_id, root=preview['root'], version=0,
                status='QUEUED', reserved=True, idempotency_key=key, request_sha256=request_sha,
                previous_id=previous_id, plan=preview, plan_sha256=digest(preview),
                commit_intent=preview.get('inherited_commit'), created_at=now, updated_at=now)
            session.add(row)
            session.flush()
            session.add(Lock(root=row.root, preparation_id=row.id))
            inherited = {}
            if previous_id:
                inherited = {s.number: s for s in session.scalars(select(Step).where(Step.operation_id == previous_id))}
            first = preview.get('recovery', {}).get('retry_step', 0)
            for n, spec in enumerate(preview['steps']):
                done = n < first
                session.add(Step(id=str(uuid4()), operation_id=row.id, number=n, spec=spec,
                                 status='DONE' if done else 'PENDING',
                                 evidence=inherited[n].evidence if done else None))
            self.repository.event(session, row, 'intended', {'reason': body.get('reason'),
                                                           'preview_sha256': preview['preview_sha256']})
        self.runtime.notify()
        return self.repository.read(operation_id)

    def _verify_source(self, root, plan, *, allow_partial=False):
        recipe = RECIPES[plan['recipe']]
        files = {f['path']: f['sha256'] for f in plan['files']}
        for path, expected in files.items():
            if os.path.lexists(root / path):
                verify_files(root, {path: expected})
            elif not allow_partial:
                raise ValueError(tr('preparation.scaffold_missing', path=path))
        allowed = set(files) | set(plan['base_files']) | recipe.extra_allowed(plan)
        for path, value in snapshot(root, recipe.links).items():
            if 'sha256' in value and path not in allowed and not path.startswith(recipe.local_prefixes):
                raise ValueError(tr('preparation.foreign_code_file', path=path))
        recipe.verify_staging(root, plan, files)
        verify_files(root, plan['base_files'])

    def _check(self, row, project, expected_workspace):
        root = project.context.root
        if digest(row['plan']) != row['plan_sha256'] or row['plan']['contract'] != CONTRACT:
            raise ValueError('Preparation intent corrupt/incompatible')
        if (len(row['steps']) != len(row['plan']['steps']) or any(
                step['number'] != number or step['spec'] != row['plan']['steps'][number]
                for number, step in enumerate(row['steps']))):
            raise ValueError(tr('preparation.preparation_step_argv_differs'))
        if dict(project.versions) != row['plan']['versions']:
            raise ValueError(tr('preparation.frozen_project_composition_changed'))
        if 'work_language' in row['plan']:
            current = work_languages.read(self.runtime.engine, root)
            if not current or (current['work_language'], current['sha256']) != (
                    row['plan']['work_language'], row['plan']['work_language_sha256']):
                raise ValueError(tr('preparation.work_language_differs_confirmed'))
        with directory(root) as fd:
            if identity(os.fstat(fd)) != row['plan']['identity']:
                raise ValueError(tr('preparation.checkout_identity_changed'))
        _, git = self.writer(project)
        inherited = row['plan'].get('inherited_commit')
        heads = {row['plan']['base_head']}
        if inherited:
            heads.add(inherited['expected_commit'])
        if git.text('rev-parse', 'HEAD') not in heads:
            raise ValueError(tr('preparation.head_changed_since_preparation'))
        for key, evidence in row['plan']['tool_files'].items():
            path = Path(row['plan']['config'][key]).resolve(strict=True)
            if str(path) != evidence['resolved'] or file_hash(path) != evidence['sha256']:
                raise ValueError(tr('preparation.authorized_service_executable_changed'))
        if snapshot(root, RECIPES[row['plan']['recipe']].links) != expected_workspace:
            raise ValueError(tr('preparation.checkout_bytes_identity_changed'))

    def _files(self, root, plan):
        # All targets were absent. Any interrupted write is left for conservative recovery.
        if RECIPES[plan['recipe']].environment == 'node_modules':
            return self._typescript_files(root, plan)
        for path in (django.WORK, django.WORK + '/home', django.WORK + '/tmp', django.WORK + '/cache',
                     django.WORK + '/output', django.WORK + '/output/core'):
            with file_parent(root, path, expected_identity=plan['identity']) as (fd, name):
                os.mkdir(name, 0o700, dir_fd=fd)
                os.fsync(fd)
        for path, content in plan['templates'].items():
            write_new(root, path, content.encode(), expected_identity=plan['identity'])
        files = {f['path']: f['content'] for f in plan['files']}
        for path in ('.gitignore', 'requirements.lock', 'pyproject.toml'):
            write_new(root, path, files[path].encode(), expected_identity=plan['identity'])
        # The random local secret is deliberately absent from plans, logs, Git and fixtures.
        write_new(root, '.django-secret', secrets.token_urlsafe(64).encode(), expected_identity=plan['identity'])

    def _typescript_files(self, root, plan):
        for path in (typescript_web.WORK, typescript_web.WORK + '/home', typescript_web.WORK + '/tmp'):
            with file_parent(root, path, expected_identity=plan['identity']) as (fd, name):
                os.mkdir(name, 0o700, dir_fd=fd)
                os.fsync(fd)
        for name in ('user.npmrc', 'global.npmrc'):
            write_new(root, f'{typescript_web.WORK}/{name}', b'', expected_identity=plan['identity'])
        for item in plan['files']:
            write_new(root, item['path'], item['content'].encode(), expected_identity=plan['identity'])

    def _publish(self, root, plan):
        # The confirmed manifest: v1 froze `django.scaffold()`; v2 the scaffold of the work language.
        generated = {f['path']: f['content'] for f in plan['files'] if f['path'].endswith('.py')}
        # The generator's complete file set must match, including empty package/migration markers.
        output = root / django.WORK / 'output'
        observed = {str(p.relative_to(output)) for p in output.rglob('*') if p.is_file()}
        if observed != set(generated):
            raise ValueError(tr('preparation.generated_scaffold_differs_confirmed'))
        verify_files(root, {f'{django.WORK}/output/{p}': sha(c.encode()) for p, c in generated.items()})
        for item in plan['files']:
            if item['path'] not in ('.gitignore', 'requirements.lock', 'pyproject.toml'):
                write_new(root, item['path'], item['content'].encode(), expected_identity=plan['identity'])
        self._verify_source(root, plan)

    @staticmethod
    def command_config(root, operator, spec):
        command = Command(('tool', *spec['argv'][1:]), timeout_seconds=spec['timeout_seconds'])
        config = CommandConfig(str(root), True, (command,), (('tool', spec['argv'][0]),),
                               tuple(sorted(spec['environment'].items())),
                               max_timeout_seconds=operator['timeout_seconds'],
                               max_output_bytes=spec['max_output_bytes'])
        return command, config

    def steps(self, root, config, mode, recipe):
        steps = recipe.module.steps(root, config, mode)
        for spec in steps:
            if spec['kind'] == 'command':
                _, binding = self.command_config(root, config, spec)
                spec['binding'] = PreparationCommandRunner(binding).frozen_versions()
        return steps

    def _command(self, root, plan, step, journal):
        spec = step['spec']
        command, config = self.command_config(root, plan['config'], spec)
        runner = self.runner_factory(config)
        runner.bind_preparation(journal, spec['binding'])
        context = self.runtime.project(plan['project_id']).context
        result = runner.run_managed(context, command, step['id'])
        if result.error or result.timed_out or result.exit_code != 0:
            raise ValueError(tr('preparation.step_failed', step=spec['label']))
        recipe = RECIPES[plan['recipe']]
        recipe.check_output(spec, result.stdout, plan)
        evidence = {'result': asdict(result)}
        # The profile's JUnit command, by its arguments: the recipe runs it through its own executable path.
        declaration = next((item for item in recipe.module.profile().junit_reports
                            if list(item.command.argv[1:]) == spec['argv'][1:]), None)
        if declaration is not None:
            from my_harness.core.engine.junit import parse_junit
            report = root / declaration.path
            if report.is_symlink() or not report.is_file() or report.stat().st_size > 1048576:
                raise ValueError(tr('preparation.junit_evidence_missing_unsafe'))
            parsed = parse_junit(report.read_bytes(), declaration)
            if parsed.status != 'complete' or not any(c.result == 'passed' for c in parsed.cases) or any(
                    c.result not in ('passed', 'skipped') for c in parsed.cases):
                raise ValueError(tr('preparation.junit_evidence_contain_successful'))
            evidence['junit'] = asdict(parsed)
        return evidence

    def _commit(self, operation_id, token, project, plan):
        root = project.context.root
        self._verify_source(root, plan)
        writer, git = self.writer(project)
        with Session(self.runtime.engine) as session:
            pending = self.repository.require(session, operation_id).commit_intent
        if pending is None:
            captured = writer.capture(project.context)
            trees = json.loads(captured.provenance_json)
            expected_files = {f['path']: f['sha256'] for f in plan['files']}
            if (captured.base_revision != plan['base_head'] or trees['index_tree'] != plan['base_tree']
                    or set(captured.changed_paths) != set(expected_files)):
                raise ValueError(tr('preparation.commit_contains_paths_outside'))
            verify_files(root, expected_files)
            for path, expected in expected_files.items():
                if sha(git.run('cat-file', 'blob', f'{trees["worktree_tree"]}:{path}')) != expected:
                    raise ValueError(tr('preparation.git_normalization_changed_confirmed'))
            timestamp = int(self.managed.clock().timestamp())
            message = plan['commit']['message'] + '\n\nHarness-Preparation: ' + operation_id + '\n'
            raw = writer._commit_text(trees['worktree_tree'], plan['base_head'], message,
                                     plan['commit']['author_name'], plan['commit']['author_email'], timestamp)
            pending = {'base_head': plan['base_head'], 'base_tree': plan['base_tree'],
                       'tree': trees['worktree_tree'], 'expected_commit': git.text('hash-object', '-t', 'commit', '--stdin', input=raw),
                       'message': message, 'author_name': plan['commit']['author_name'],
                       'author_email': plan['commit']['author_email'], 'timestamp': timestamp}
            with self.managed._write() as session:
                row = self.repository.owned(session, operation_id, token)
                row.commit_intent = pending
                self.repository.event(session, row, 'commit_intended', pending)
        raw = writer._commit_text(pending['tree'], pending['base_head'], pending['message'],
                                 pending['author_name'], pending['author_email'], pending['timestamp'])
        if git.text('hash-object', '-t', 'commit', '--stdin', input=raw) != pending['expected_commit']:
            raise ValueError('Sealed commit intent corrupt')
        head = git.text('rev-parse', 'HEAD')
        index = writer._index_tree(git)
        if head == pending['base_head']:
            captured = writer.capture(project.context)
            tree = json.loads(captured.provenance_json)
            if tree['worktree_tree'] != pending['tree'] or index != pending['base_tree']:
                raise ValueError(tr('preparation.content_index_changed_before'))
            git.run('hash-object', '-t', 'commit', '-w', '--stdin', input=raw)
            git.run('update-ref', '-m', RECIPES[plan['recipe']].reflog, 'HEAD', pending['expected_commit'], pending['base_head'])
        elif head != pending['expected_commit'] or git.run('cat-file', 'commit', head) != raw:
            raise ValueError(tr('preparation.sealed_commit_cannot_reconciled'))
        if index == pending['base_tree']:
            git.run('read-tree', '--reset', pending['tree'])
        elif index != pending['tree']:
            raise ValueError(tr('preparation.index_changed_leave_untouched'))
        captured = writer.capture(project.context)
        if captured.changed_paths:
            raise ValueError(tr('preparation.checkout_drift_after_technical'))
        recipe = RECIPES[plan['recipe']]
        receipt = {'contract': CONTRACT, 'recipe': plan['recipe'], 'identity': plan['identity'],
                   'recipe_config_sha256': plan['versions']['recipe_config_sha256'], 'config': plan['config'],
                   'lock_sha256': plan['lock_sha256'],
                   'commit': pending['expected_commit'], 'operation_id': operation_id,
                   **{key: plan[key] for key in ('work_language', 'work_language_sha256', 'recipe_sha256')
                      if key in plan},
                   **recipe.receipt(root, plan),
                   # Same glob semantics as the profile (`scripts/**`); Django's literal paths match themselves.
                   'protected_files': {f['path']: f['sha256'] for f in plan['files']
                                       if matches(f['path'], project.context.profile.protected_paths)}}
        receipt['protected_files'].update(recipe.local_secrets(root))
        return receipt

    def run_once(self):
        claim = self.repository.claim(self.runtime.config.lease_seconds)
        if claim is None:
            return None
        # P011-T021: a preparation freezes no visual language; its texts use the stored one when emitted.
        with emission(lambda: stored_language(self.managed.engine)):
            operation = self.repository.read(claim[0])
            service = self.generic() if operation['plan']['contract'] == 'project-profile-preparation-1' else self
            return service._run_claimed(claim)

    def generic(self):
        from my_harness.services.profile_preparation import ProfilePreparation
        return ProfilePreparation(self)

    def _links(self, plan):
        return RECIPES[plan['recipe']].links

    def _execute_step(self, operation_id, token, project, plan, step):
        root, kind = project.context.root, step['spec']['kind']
        if kind == 'files':
            self._files(root, plan)
        elif kind == 'publish':
            self._publish(root, plan)
        elif kind == 'command':
            partial = RECIPES[plan['recipe']].source_check(step['spec'], step['number'])
            if partial is not None:
                self._verify_source(root, plan, allow_partial=partial)
            return self._command(root, plan, step, PreparationJournal(self.repository, operation_id, token)), None
        elif kind == 'commit':
            return {}, self._commit(operation_id, token, project, plan)
        else:
            raise ValueError('Unknown preparation step')
        return {}, None

    def _run_claimed(self, claim):
        operation_id, token = claim
        stopping = ThreadEvent()
        def heartbeat():
            while not stopping.wait(self.runtime.config.lease_seconds / 3):
                try:
                    self.repository.heartbeat(operation_id, token, self.runtime.config.lease_seconds)
                except Exception:
                    return
        thread = Thread(target=heartbeat, daemon=True, name='preparation-heartbeat')
        thread.start()
        receipt, error = None, None
        try:
            operation = self.repository.read(operation_id)
            plan = operation['plan']
            project = self.runtime.project(operation['project_id'])
            root = project.context.root
            expected = plan.get('recovery', {}).get('workspace', plan.get('initial_workspace'))
            for step in operation['steps']:
                if step['status'] == 'DONE':
                    if not plan.get('recovery'):
                        expected = step['evidence']['workspace']
                    continue
                if self.repository.cancelled(operation_id, token):
                    raise InterruptedError(tr('preparation.cancelled'))
                self._check(operation, project, expected)
                with self.managed._write() as session:
                    row = self.repository.owned(session, operation_id, token)
                    session.get(Step, step['id']).status = 'STARTED'
                    self.repository.event(session, row, 'step_started', {'number': step['number'], 'spec': step['spec']})
                evidence, completed_receipt = self._execute_step(operation_id, token, project, plan, step)
                if completed_receipt is not None:
                    receipt = completed_receipt
                expected = snapshot(root, self._links(plan))
                with self.managed._write() as session:
                    row = self.repository.owned(session, operation_id, token)
                    saved = session.get(Step, step['id'])
                    saved.status, saved.evidence = 'DONE', {**evidence, 'workspace': expected}
                    self.repository.event(session, row, 'step_completed', {'number': step['number'],
                                                                         'workspace_sha256': digest(expected)})
        except Exception as exc:
            error = exc
        finally:
            stopping.set()
            thread.join()
            with self.managed._write() as session:
                row = self.repository.require(session, operation_id)
                row.owner_closed = True
                self.repository.event(session, row, 'owner_closed')
                try:
                    self.repository.stopped(session, row)
                    stopped = True
                except Conflict:
                    stopped = False
                if receipt and error is None and stopped and row.status == 'ACTIVE':
                    row.receipt, row.status, row.reserved = receipt, 'COMPLETED', False
                elif row.cancel_requested and stopped:
                    row.status = 'CANCELLED'
                    # Releasing a reservation requires an explicit successor once any effect exists.
                    row.diagnostic = tr('preparation.cancelled_bytes')
                else:
                    row.status = 'FAILED' if stopped and row.status == 'ACTIVE' else 'RECOVERY_REQUIRED'
                    row.diagnostic = tr('preparation.stopped', reason=(
                        str(error) if isinstance(error, (ValueError, JournalError))
                        else type(error).__name__ if error else tr('preparation.uncertain_effect')))
                if stopped:
                    session.execute(delete(Lock).where(Lock.preparation_id == row.id))
                self.repository.event(session, row, 'settled', {'status': row.status, 'diagnostic': row.diagnostic})
            if receipt and error is None:
                self.bind(self.runtime.project(operation['project_id']))
        return operation_id

    def control(self, operation_id, body, action, key=None):
        with self.lock, self.managed._write() as session:
            request_sha = digest({'operation_id': operation_id, 'action': action, **body})
            replay = session.scalar(select(PreparationEvent).where(
                PreparationEvent.payload['idempotency_key'].as_string() == key)) if key else None
            if replay:
                if replay.payload['request_sha256'] != request_sha:
                    raise RegistryError(409, 'idempotency_conflict', tr('preparation.key_reused'))
                return self.repository.read(operation_id)
            row = self.repository.require(session, operation_id)
            if row.version != body['expected_version'] or row.plan_sha256 != body['plan_sha256']:
                raise RegistryError(409, 'stale_version', tr('preparation.stale'))
            if action == 'cancel':
                if row.status == 'COMPLETED':
                    raise RegistryError(409, 'already_completed', tr('preparation.finished'))
                row.cancel_requested = True
                if row.status == 'QUEUED':
                    row.status, row.reserved, row.owner_closed = 'CANCELLED', False, True
                    session.execute(delete(Lock).where(Lock.preparation_id == row.id))
                elif row.status != 'ACTIVE':
                    self.repository.stopped(session, row)
                    row.status = 'CANCELLED'
                    session.execute(delete(Lock).where(Lock.preparation_id == row.id))
            elif action == 'confirm-stopped':
                if row.status not in ('RECOVERY_REQUIRED', 'FAILED', 'CANCELLED'):
                    raise RegistryError(409, 'recovery_required', tr('preparation.stop_first'))
                self.repository.stopped(session, row)
                row.owner_closed = True
                session.execute(delete(Lock).where(Lock.preparation_id == row.id))
            self.repository.event(session, row, action, {'reason': body.get('reason'),
                                                       'idempotency_key': key, 'request_sha256': request_sha})
        return self.repository.read(operation_id)
