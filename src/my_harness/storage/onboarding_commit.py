"""Flow B over the reconcilable intent and the atomic adoption of the imports (0020)."""
from my_harness.adapters.chat_snapshot import HeadSnapshot
from my_harness.adapters.import_git import _blobs
from my_harness.adapters.local_git import LocalGit
from my_harness.core.engine.definition import allowed_draft, definition_layout
from my_harness.core.engine.onboarding_commit import preview as build_preview
from my_harness.storage.managed import Conflict
from my_harness.storage.onboarding import OnboardingDrafts
from my_harness.storage.project_import import ImportRepository
from my_harness.i18n import tr


class OnboardingRepository(ImportRepository):
    kind = 'onboarding'
    drafts_class = OnboardingDrafts

    def _build_preview(self, context, conversation_id, source, record, writer):
        if source.get('authority') == 'structured-intake-1':
            raise Conflict(tr('intake.database_owned'))
        reader = HeadSnapshot(context.root, executable=writer.executable)
        reader.git = LocalGit(context.root, executable=writer.executable)
        head = reader.head()
        if head != source['inventory']['head']:
            raise Conflict(tr('onboarding.checkout_changed_since_onboarding'))
        entries = reader.entries(head)
        target = definition_layout(context)
        selected = {path: entry for path, entry in entries.items() if allowed_draft(target, path)}
        blobs = _blobs(reader.git, sorted({entry[0] for entry in selected.values()}))
        contents = {path: blobs[entry[0]] for path, entry in selected.items()}
        inspection = self.drafts_class.of(self.managed.engine, conversation_id).inspect_definition(context, texts=True)
        drafts = inspection.pop('texts')
        return build_preview(context, source, contents, entries, drafts, record, inspection, writer)
