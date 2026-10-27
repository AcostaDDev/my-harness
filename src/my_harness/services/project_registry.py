"""Registration, change and retirement of projects from the UI over `local-config-3` through 8 (D078/D095).

The TOML remains the authority for what runs; the registry only stores
non-executable data (canonical root, trust, named composition, policy,
documents, bootstrap, tag and permission ceiling). Each change goes through a
preview whose hash binds the action, the expected version, the resulting row and the
frozen composition; trust in the root is a separate confirmation. Registering also
fixes the root's work language (D167), sealed in the same preview and never changed. The
project joins the runtime without restarting: the registry version enters
the frozen hash, and a job admitted with another composition is quarantined.
"""
import hashlib
import os
from pathlib import Path
import stat
from threading import RLock

from my_harness.core.engine.contracts import freeze
from my_harness.i18n import LANGUAGES, message, tr
from my_harness.services.managed_runtime import PROJECT_ID, ManagedConfig, validate_projects
from my_harness.storage import work_language
from my_harness.storage.permissions import actor
from my_harness.storage.registry import ProjectRegistryRepository, RegistryConflict

# `/projects/new` is the registration page; the other ids follow the `PROJECT_ID` form.
RESERVED_IDS = frozenset({'new'})
ACTIONS = ('register', 'update', 'retire')
# Formats with per-project agent selections (v5) and their successor that adds the work language (v6).
AGENT_FORMATS = ('local-config-5', 'local-config-6', 'local-config-7', 'local-config-8', 'local-config-9')
def trust_statement():
    """The statement the operator confirms, in the visual language of the preview; the record keeps that text."""
    return tr('registry.trust')


class RegistryError(ValueError):
    def __init__(self, status, code, diagnostic):
        super().__init__(diagnostic)
        self.status, self.code = status, code


def digest(value):
    return hashlib.sha256(freeze(value).encode()).hexdigest()


def _location(path):
    """Identity of the existing ancestor and pending suffix; also recognizes filesystem case aliases."""
    suffix = []
    for current in (path, *path.parents):
        try:
            info = os.lstat(current)
            return info.st_dev, info.st_ino, tuple(reversed(suffix))
        except FileNotFoundError:
            suffix.append(current.name)
        except OSError:
            return None
    return None


def _within(path, parent):
    if path.is_relative_to(parent):
        return True
    boundary = _location(parent)
    return boundary is not None and any(_location(ancestor) == boundary for ancestor in (path, *path.parents))


def _inside(path, other):
    return _within(path, other) or _within(other, path)


def canonical_root(value, authorized):
    """Absolute, existing root, without links in any component and under an authorized root."""
    if not isinstance(value, str) or not value or '\0' in value:
        raise RegistryError(422, 'root_invalid', tr('registry.root_text'))
    path = Path(value)
    if not path.is_absolute():
        raise RegistryError(422, 'root_not_absolute', tr('registry.root_absolute'))
    if str(path) != os.path.normpath(value) or '..' in path.parts:
        raise RegistryError(422, 'root_not_canonical', tr('registry.root_canonical'))
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            raise RegistryError(422, 'root_missing', tr('registry.root_missing', path=current)) from None
        except OSError as exc:
            raise RegistryError(422, 'root_unreadable', f'{current}: {exc.strerror}') from None
        if stat.S_ISLNK(info.st_mode):
            raise RegistryError(422, 'root_symlink', tr('registry.root_symlink', path=current))
    if not stat.S_ISDIR(os.lstat(path).st_mode):
        raise RegistryError(422, 'root_not_directory', tr('registry.root_directory'))
    if path.resolve() != path:
        raise RegistryError(422, 'root_not_canonical', tr('registry.root_real'))
    if not any(path.is_relative_to(root) for root in authorized):
        raise RegistryError(422, 'root_not_authorized', tr('registry.root_unauthorized'))
    return path


class ProjectRegistry:
    """Registry service inside the managed runtime; one change at a time in this process."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.repository = ProjectRegistryRepository(runtime.repository)
        self.engine = runtime.repository.engine
        self.unavailable: dict[str, str] = {}
        self._lock = RLock()

    def _language(self):
        return self.runtime.preferences.read()['ui_language'] if self.runtime.preferences else 'en'

    def work_language_preview(self, value, root, source):
        """The chosen value and its provenance; an already associated root admits only its own value."""
        if value not in LANGUAGES:
            raise RegistryError(422, 'work_language_required', message('work_language.required', self._language()))
        existing = work_language.read(self.engine, root)
        if existing is not None and existing['work_language'] != value:
            raise RegistryError(409, 'work_language_immutable', message(
                'work_language.immutable', self._language(), root=root, language=existing['work_language']))
        preferences = self.runtime.preferences.read()
        return {'work_language': value, 'source': source, 'default_work_language': preferences['default_work_language'],
                'preferences_version': preferences['version'], 'existing': existing}

    @staticmethod
    def work_language_seal(preview):
        """Only the chosen value and the existing association enter the hash: a default changed after the
        preview never replaces the value that is confirmed (D159 §2)."""
        existing = preview['existing']
        return {'work_language': preview['work_language'], 'existing_sha256': existing['sha256'] if existing else None}

    @property
    def registrar(self):
        registrar = self.runtime.config.registrar
        return registrar if registrar is not None and registrar.registrable else None

    def _require(self):
        if self.registrar is None:
            raise RegistryError(409, 'registry_unavailable', tr('registry.unavailable'))
        return self.registrar

    # --- composition ------------------------------------------------------------------

    def _compose(self, row, registry, *, new_directory=False):
        from my_harness.services.local_config import LocalConfigError
        registrar = self._require()
        try:
            composed = registrar.compose(row, 'registro', registry=registry, new_directory=new_directory)
            if new_directory:
                return composed
            # Same checks as a TOML project (permission ceiling, bootstrap, tag).
            validate_projects(ManagedConfig((composed[0],), ports_factory=registrar.ports,
                                            commit_factory=registrar.writer))
        except (LocalConfigError, ValueError) as exc:
            raise RegistryError(422, 'invalid_request', str(exc)) from None
        return composed

    def load(self):
        """At startup: composes the active rows. A row that no longer composes becomes unavailable, with a reason."""
        self.unavailable = {}
        for item in self.repository.rows():
            if item['status'] != 'ACTIVE':
                continue
            if (self.runtime.setup is not None and self.runtime.setup.legacy
                    and item['trust'].get('source') == 'configuration-import'
                    and item['id'] in self.runtime.projects):
                continue
            try:
                self._conflicts(item['id'], Path(item['root']), registered=True)
                composed = self._compose(item['row'], (item['version'], item['row_sha256']))
                installed = self.registrar.install(composed)
                if hasattr(self.runtime, 'preparation'):
                    installed = self.runtime.preparation.bind(installed)
                    if self.runtime.setup is not None and not self.runtime.setup.legacy:
                        installed = self.runtime.project_configuration.install_active(installed)
                self.runtime.install(installed)
            except RegistryError as exc:
                self.unavailable[item['id']] = str(exc)

    def _conflicts(self, project_id, root, *, registered=False, creation_id=None):
        """Ids unique against the TOML; roots neither equal nor nested; service state outside."""
        # Uncertain intents remain reserved, also against the existing D078 registration.
        from my_harness.storage.project_creation import CreationRepository
        for operation in CreationRepository(self.runtime.repository).operations():
            if (operation['reserved'] and operation['id'] != creation_id
                    and (operation['project_id'] == project_id or _inside(root, Path(operation['target'])))):
                raise RegistryError(409, 'target_reserved', tr('registry.target_reserved'))
        for other in self.runtime.projects.values():
            if other.id == project_id:
                if not registered or 'project_registry' not in other.versions:
                    raise RegistryError(409, 'duplicate_id', tr('registry.id_used', id=project_id))
                continue
            if _inside(root, other.context.root):
                raise RegistryError(409, 'root_taken', tr('registry.root_taken', project=other.id))
        for path, key in ((self.runtime.database, 'registry.root_database'),
                          (self.runtime.migrations_dir, 'registry.root_migrations')):
            if path is not None and _inside(root, path):
                raise RegistryError(422, 'root_service_state', tr(key))

    # --- reads ------------------------------------------------------------------------

    def options(self):
        registrar = self.registrar
        rows = self.repository.rows()
        languages = work_language.rows(self.engine)
        return {'available': registrar is not None,
                'format': self.runtime.config.registrar.format if self.runtime.config.registrar else None,
                'creation_available': registrar is not None and registrar.bootstrap_enabled,
                **({key: value for key, value in registrar.options().items() if key != 'format'} if registrar else
                   {'roots': [], 'bootstrap_enabled': False, 'compositions': [], 'executor_provider': None,
                    'reviewer_provider': None, 'executor_effort_vocabulary': []}),
                'reserved_ids': sorted(RESERVED_IDS),
                'operator_projects': sorted(p.id for p in self.runtime.projects.values()
                                            if 'project_registry' not in p.versions),
                'projects': [self._summary(item, languages) for item in rows], 'trust_statement': trust_statement()}

    def _summary(self, item, languages=None):
        work = (languages.get(item['root']) if languages is not None
                else work_language.read(self.engine, item['root']))
        return {**{key: item[key] for key in ('id', 'version', 'status', 'root', 'composition', 'profile',
                                              'row_sha256', 'created_at', 'updated_at', 'creation_id')},
                'available': item['status'] == 'ACTIVE' and item['id'] not in self.unavailable,
                'diagnostic': self.unavailable.get(item['id']), 'work_language': work}

    def read(self, project_id):
        item = self.repository.get(project_id)
        if item is None:
            raise LookupError(tr('registry.unknown'))
        return {**self._summary(item), 'row': item['row'], 'trust': item['trust'],
                'unfinished_jobs': self.repository.unfinished(item['root']) if item['status'] == 'ACTIVE' else [],
                'configuration_blockers': self.repository.configuration_blockers(item['root'])
                if self.registrar and self.registrar.format in AGENT_FORMATS else [],
                'history': self.repository.history(project_id)}

    # --- preview and confirmation -----------------------------------------------------

    def _target(self, body, current):
        action = body['action']
        if action == 'retire':
            return dict(current['row'])
        registrar = self._require()
        if action == 'register':
            project_id = body['project_id']
            root = str(canonical_root(body.get('root'), registrar.roots))
        else:
            project_id, root = current['id'], current['root']
            if body.get('root') not in (None, root):
                raise RegistryError(422, 'root_immutable', tr('registry.root_immutable'))
        if body.get('bootstrap_enabled') and not registrar.bootstrap_enabled:
            raise RegistryError(422, 'bootstrap_not_allowed', tr('registry.bootstrap'))
        row = {'id': project_id, 'root': root, 'repository_trusted': True, 'composition': body.get('composition'),
               'policy': body.get('policy'), 'tag_kind': body.get('tag_kind', 'lightweight'),
               'bootstrap_enabled': bool(body.get('bootstrap_enabled', False))}
        if body.get('documents') is not None:
            row['documents'] = body['documents']
        if body.get('permission_authority') is not None:
            row['permission_authority'] = body['permission_authority']
        if body.get('agent_selection') is not None:
            row['agent_selection'] = body['agent_selection']
        return row

    def preview(self, body):
        action, project_id = body['action'], body['project_id']
        if action not in ACTIONS:
            raise RegistryError(422, 'invalid_request', tr('registry.action', action=repr(action)))
        registrar = self._require()
        if not isinstance(project_id, str) or not PROJECT_ID.fullmatch(project_id):
            raise RegistryError(422, 'invalid_id', tr('registry.id_form', pattern=PROJECT_ID.pattern))
        if project_id in RESERVED_IDS:
            raise RegistryError(422, 'invalid_id', tr('registry.id_reserved', id=repr(project_id)))
        current = self.repository.get(project_id)
        expected = body['expected_version']
        if action == 'register':
            if current is not None:
                raise RegistryError(409, 'duplicate_id', tr('registry.id_registered' if current['status'] == 'ACTIVE'
                                                         else 'registry.id_retired', id=project_id))
            if project_id in self.runtime.projects:
                raise RegistryError(409, 'duplicate_id', tr('registry.id_toml', id=project_id))
        elif current is None:
            raise LookupError(tr('registry.unknown_toml'))
        elif current['status'] != 'ACTIVE':
            raise RegistryError(409, 'retired', tr('registry.retired'))
        if (current['version'] if current else 0) != expected:
            raise RegistryError(409, 'stale_version', tr('registry.stale'))
        if action != 'register' and body.get('work_language') is not None:
            raise RegistryError(409, 'work_language_immutable', message('work_language.confirmed', self._language()))
        row = self._target(body, current)
        language = (self.work_language_preview(body.get('work_language'), row['root'], 'registration')
                    if action == 'register' else None)
        version = expected + 1
        if action == 'retire':
            versions = None
        else:
            self._conflicts(project_id, Path(row['root']), registered=action == 'update')
            composed = self._compose(row, (version, digest(row)))
            versions = dict(composed[0].versions)
        row_sha256 = digest(row)
        status = 'RETIRED' if action == 'retire' else 'ACTIVE'
        before = current['row'] if current else {}
        changes = [{'field': key, 'before': before.get(key), 'after': row.get(key)}
                   for key in sorted(set(before) | set(row)) if before.get(key) != row.get(key)]
        if action == 'retire':
            changes = [{'field': 'status', 'before': 'ACTIVE', 'after': 'RETIRED'}]
        unfinished = self.repository.unfinished(row['root']) if action != 'register' else []
        blockers = self.repository.configuration_blockers(row['root']) if (
            action != 'register' and registrar.format in AGENT_FORMATS) else []
        preview_sha256 = digest({'action': action, 'project_id': project_id, 'expected_version': expected,
                                 'current_sha256': current['row_sha256'] if current else None, 'status': status,
                                 'row_sha256': row_sha256, 'versions': versions,
                                 **({'work_language': self.work_language_seal(language)} if language else {})})
        return {'action': action, 'project_id': project_id, 'expected_version': expected, 'version': version,
                'status': status, 'row': row, 'row_sha256': row_sha256, 'changes': changes, 'versions': versions,
                'profile': (current['profile'] if action == 'retire' else
                            registrar.compositions[row['composition']][0] if row['composition'] else None),
                'trust_required': action == 'register', 'trust_statement': trust_statement() if action == 'register' else None,
                'unfinished_jobs': unfinished, 'configuration_blockers': blockers, 'work_language': language,
                'preview_sha256': preview_sha256}

    def apply(self, body, *, preview_sha256, trust_root=None, reason=None):
        with self._lock:
            replayed = self.repository.replay(body['project_id'], body['expected_version'], preview_sha256)
            if replayed is not None:
                return {'project': self._summary(replayed), 'replayed': True}
            shown = self.preview(body)
            if shown['preview_sha256'] != preview_sha256:
                raise RegistryError(409, 'preview_changed', tr('registry.preview_changed'))
            if shown['unfinished_jobs']:
                raise RegistryError(409, 'pending_jobs', tr('registry.pending_jobs', jobs=shown['unfinished_jobs']))
            if shown['configuration_blockers']:
                raise RegistryError(409, 'pending_configuration', '; '.join(shown['configuration_blockers']))
            trust = None
            if shown['trust_required']:
                if trust_root != shown['row']['root']:
                    raise RegistryError(409, 'trust_unconfirmed', tr('registry.trust_unconfirmed'))
                trust = {'confirmed': True, 'root': trust_root, 'statement': shown['trust_statement'], 'actor': actor()}
            try:
                saved = self.repository.apply(shown['action'], shown['project_id'],
                                              expected_version=shown['expected_version'], row=shown['row'],
                                              row_sha256=shown['row_sha256'], profile=shown['profile'],
                                              preview_sha256=preview_sha256, trust=trust, reason=reason,
                                              protect_agents=self.registrar.format in AGENT_FORMATS,
                                              work_language=shown['work_language'])
            except RegistryConflict as exc:
                raise RegistryError(409, exc.code, str(exc)) from None
            self.unavailable.pop(saved['id'], None)
            if saved['status'] == 'ACTIVE':
                composed = self._compose(saved['row'], (saved['version'], saved['row_sha256']))
                installed = self.registrar.install(composed)
                if hasattr(self.runtime, 'preparation'):
                    installed = self.runtime.preparation.bind(installed)
                    if self.runtime.setup is not None and not self.runtime.setup.legacy:
                        installed = self.runtime.project_configuration.install_active(installed)
                self.runtime.install(installed)
            else:
                self.runtime.uninstall(saved['id'])
                self.registrar.forget(Path(saved['root']))
            return {'project': self._summary(saved), 'replayed': False}
