"""Explicit work language for a project that has none yet (P011-T008, D167; T001 §2).

The only valid transition is absent → en/es: a preview names the project, its root and frozen versions and the
chosen value, and its hash, a reason and the unchanged state confirm it. Existing files are kept as they are;
nothing is translated, renamed or inferred from their language. Pending work is resolved first.
"""
from my_harness.i18n import message
from my_harness.services.project_registry import RegistryError, digest
from my_harness.storage import work_language
from my_harness.storage.registry import RegistryConflict, confirm_work_language


class WorkLanguageMigration:
    def __init__(self, runtime):
        self.runtime, self.registry = runtime, runtime.registry

    def _confirmed(self, root):
        current = work_language.read(self.runtime.engine, root)
        if current is not None:
            raise RegistryError(409, 'work_language_immutable',
                                message('work_language.confirmed', self.registry._language()))

    def preview(self, project_id, body):
        project = self.runtime.project(project_id)
        root = str(project.context.root)
        self._confirmed(root)
        language = self.registry.work_language_preview(body.get('work_language'), root, 'migration')
        sealed = {'action': 'confirm_work_language', 'project_id': project_id, 'root': root,
                  'versions': dict(project.versions), **self.registry.work_language_seal(language)}
        return {'project_id': project_id, 'root': root, 'work_language': language, 'files_preserved': True,
                'unfinished_jobs': self.registry.repository.unfinished(root),
                'configuration_blockers': self.registry.repository.configuration_blockers(root),
                'preview_sha256': digest(sealed)}

    def apply(self, project_id, body, *, preview_sha256, reason):
        """Returns `(project, replayed)`; the same confirmation already applied is returned as is."""
        with self.registry._lock:
            project = self.runtime.project(project_id)
            root = str(project.context.root)
            current = work_language.read(self.runtime.engine, root)
            if (current is not None and current['source'] == 'migration'
                    and current['confirmation'].get('preview_sha256') == preview_sha256):
                return self.runtime.project(project_id), True
            shown = self.preview(project_id, body)
            language = self.registry._language()
            if shown['preview_sha256'] != preview_sha256:
                raise RegistryError(409, 'preview_changed', message('work_language.preview_changed', language))
            repository = self.registry.repository
            with self.runtime.repository._write() as session:
                pending = [str(item) for item in repository._unfinished(session, root)]
                pending += repository._configuration_blockers(session, root)
                if pending:
                    raise RegistryError(409, 'pending_work',
                                        message('work_language.pending', language, items='; '.join(pending)))
                try:
                    confirm_work_language(session, project_id, root, shown['work_language'], 'migration',
                                          preview_sha256, reason, self.runtime.repository._now())
                except RegistryConflict as exc:
                    raise RegistryError(409, exc.code, str(exc)) from None
            self.runtime.install(project)
            return self.runtime.project(project_id), False
