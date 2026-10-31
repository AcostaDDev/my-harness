"""T013 independent-review regressions: current delivery, partial scope, ordered merge and portability."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from my_harness.core.engine import knowledge_documents as d
from my_harness.storage.knowledge_exchange import completed_at_root
from my_harness.storage.profile_intake import _continuation
from test_knowledge_documents import (world, run, payload, prepare_export, IDENTITY, OWNER, section,
                                      LocalGit, KnowledgeDelivery, disk_baseline)


def adopt_manifest(engine, root, project, wrappers, key):
    paths = [t['path'] for t in d.ownership(project, 'en', wrappers)['targets']]
    shown = run(engine, root, 'documents.ownership.prepare',
                payload({'wrappers': wrappers, 'baseline': disk_baseline(root, paths)}), key + '-preview')
    return run(engine, root, 'documents.ownership.adopt', {
        'record_id': shown['record_id'], 'preview_sha256': shown['preview_sha256'],
        'expected_revision_id': shown['revision_id'], 'reason': 'Explicit reviewed manifest.'}, key)


def stage_acknowledged(engine, root, body, key):
    result = run(engine, root, 'documents.stage', payload(body), key + '-report')
    if not result['draft_id']:
        assert all(not r['blocking'] or r['code'] == 'report_acknowledgement_required' for r in result['report']), result
        body = {**body, 'acknowledged': [d.k.digest(r) for r in result['report'] if not r['blocking']]}
        result = run(engine, root, 'documents.stage', payload(body), key + '-stage')
    assert result['draft_id'], result
    return result, run(engine, root, 'documents.preview', {'record_id': result['record_id']})


def adopt_import(engine, root, staged, shown, base, key):
    return run(engine, root, 'documents.adopt', {'record_id': staged['record_id'],
        'preview_sha256': shown['preview_sha256'], 'expected_revision_id': base,
        'reason': 'Reviewed source, identity and resulting order.'}, key)


def test_new_manifest_invalidates_current_delivery_but_keeps_historical_receipt(migrated_database, tmp_path):
    root = tmp_path / 'checkout'; root.mkdir(); LocalGit(root).run('init')
    engine, repo, project, revision = world(migrated_database[0], root)
    original = prepare_export(engine, root, project)
    delivery = KnowledgeDelivery(engine, root, project)
    old = delivery.execute(original['record_id'], original['preview_sha256'], IDENTITY)
    initial = run(engine, root, 'documents.bundle', {})['delivery']
    assert initial['status'] == 'export_committed'
    assert initial['effect_status'] == 'COMPLETED'
    adopted = adopt_manifest(engine, root, project, ['claude'], 'with-claude')
    assert repo.revision(project) == revision
    assert not (root / 'CLAUDE.md').exists()
    assert run(engine, root, 'documents.bundle', {})['delivery']['status'] == 'export_required'
    with Session(engine) as session:
        assert completed_at_root(session, root) is None
        assert _continuation(session, root) == 'export_required'
    assert delivery.status(original['record_id'])['outcomes'][-1] == old
    baseline = disk_baseline(root, original['files'].keys() | {'CLAUDE.md'})
    baseline['ownership_id'] = adopted['record_id']
    new = run(engine, root, 'documents.export.prepare', payload(baseline), 'new-generation')
    delivered = delivery.execute(new['record_id'], new['preview_sha256'], IDENTITY)
    assert (root / 'CLAUDE.md').read_text() == '@AGENTS.md\n'
    with Session(engine) as session:
        assert completed_at_root(session, root)['result'] == delivered
        assert _continuation(session, root) == 'export_committed'


def test_partial_import_retains_unselected_task_versions_and_links(migrated_database, tmp_path):
    engine, repo, project, first = world(migrated_database[0], tmp_path)
    files = d.render(d.snapshot(first), d.ownership(project, 'en'))
    draft = repo.open_draft(project, first.id)
    source, target = (first.item('task', code).item_id for code in ('P001-T002', 'P001-T001'))
    repo.unlink(draft, 'depends_on', source, target)
    second = repo.adopt(draft, first.id, origin='owner_confirmed', actor=OWNER)
    selected = {d.META: files[d.META], 'docs/SPECIFICATION.md':
                files['docs/SPECIFICATION.md'].replace('Users can sign in.', 'A revised requirement.')}
    parsed, _, _ = d.parse(selected)
    assert not any(l['kind'] == 'depends_on' for l in parsed['links'])
    body = {'files': selected, 'portable': '', 'mode': 'update', 'choices': {}, 'acknowledged': [],
            'expected_revision_id': second.id}
    staged, shown = stage_acknowledged(engine, tmp_path, body, 'partial')
    assert not any(l['kind'] == 'depends_on' for l in shown['comparison']['added_links'])
    adopt_import(engine, tmp_path, staged, shown, second.id, 'partial-consent')
    current = repo.revision(project)
    assert current.item('requirement', 'R001').content['statement'] == 'A revised requirement.'
    assert {i:m for i,m in current.members.items() if m.kind == 'task'} == {i:m for i,m in second.members.items() if m.kind == 'task'}
    assert current.links == second.links


@pytest.mark.parametrize('document', ['instructions', 'architecture'])
def test_create_new_sections_appends_roots_and_children_in_source_order(migrated_database, tmp_path, document):
    engine, repo, project, first = world(migrated_database[0], tmp_path)
    draft = repo.open_draft(project, first.id)
    parent = repo.put(draft, 'section', 'existing', section('Existing', 'Existing root.\n'), document=document, root_position=0)
    child = repo.put(draft, 'section', 'existing-child', section('Existing child', 'Keep this child.\n'), document=document)
    repo.link(draft, 'part_of', child, parent, position=0)
    existing = repo.adopt(draft, first.id, origin='owner_confirmed', actor=OWNER)
    # The plain-instruction parser assigns source root position 0 and child position 0.
    source, _, _ = d.parse({'AGENTS.md': '# Parent\nParent source.\n## New child\nChild source.\n# New root\nNew root source.\n'})
    if document != 'instructions':
        for m in source['members']:
            m['document'] = document
            m['content_sha256'] = d.k.content_sha256(m['kind'], document, m['code'], m['content'], m['provenance'], m['source'])
    # Explicitly map the parent; explicitly create both the child and the other root.
    choices = {m['item_id']: {'action': 'map', 'target': parent, 'code': ''} if m['code'] == 'parent'
               else {'action': 'create', 'target': '', 'code': 'new-' + m['code']} for m in source['members']}
    if document == 'instructions':
        files, portable = {'AGENTS.md': '# Parent\nParent source.\n## New child\nChild source.\n# New root\nNew root source.\n'}, ''
    else:
        files, portable = {}, d.portable(source, 'en')
    staged, shown = stage_acknowledged(engine, tmp_path, {'files': files, 'portable': portable, 'mode': 'update',
        'choices': choices, 'acknowledged': [], 'expected_revision_id': existing.id}, 'ordered')
    roots = [c['after'] for c in shown['comparison']['items'] if c['after'] and c['after']['code'] == 'new-new-root']
    assert roots[0]['root_position'] == 1
    assert any(l['kind'] == 'part_of' and l['position'] == 1 for l in shown['comparison']['added_links'])
    adopt_import(engine, tmp_path, staged, shown, existing.id, 'ordered-consent')
    current = repo.revision(project)
    assert current.members[child] == existing.members[child]
    assert current.roots(document) == [parent, current.item('section', 'new-new-root', document).item_id]
    assert current.children('part_of', parent) == [child, current.item('section', 'new-new-child', document).item_id]


@pytest.mark.parametrize('failure', ['unselected_instruction_wrapper', 'instruction_budget'])
def test_portable_bundle_survives_render_failure_without_ownership(migrated_database, tmp_path, failure):
    from session_client import TestClient
    from my_harness.api.app import create_app
    from test_managed_api import config, make_context, LOCAL
    root = tmp_path / 'checkout'; root.mkdir()
    engine, repo, project, first = world(migrated_database[0], root)
    draft = repo.open_draft(project, first.id)
    target = 'claude' if failure == 'unselected_instruction_wrapper' else 'agents'
    repo.put(draft, 'section', 'client-rules', section('Rules', 'Rule.\n' * (1 if target == 'claude' else 61), target),
             document='instructions', root_position=0)
    revision = repo.adopt(draft, first.id, origin='owner_confirmed', actor=OWNER)
    app = create_app(migrated_database[0], tmp_path / 'ui', managed=config(make_context(root)))
    with TestClient(app, base_url=LOCAL) as http:
        response = http.get('/api/managed/projects/synthetic/knowledge/documents/bundle')
        assert response.status_code == 200, response.text
        value = response.json()['result']
        assert value['files'] is None and value['render_error'] == failure
        assert not value['ownership_adopted'] and value['portable_error'] is None
        assert d.parse_portable(value['portable'])[0] == d.snapshot(revision)
        assert value['delivery']['status'] == 'document_ownership_required'
    assert not (root / 'AGENTS.md').exists() and not (root / 'CLAUDE.md').exists()


from test_structured_intake_review import structured_profile


def test_changed_manifest_is_pending_for_profile_configuration_and_preparation(structured_profile, monkeypatch):
    import json
    from test_structured_intake_review import response, stage as intake_stage
    from test_profile_proposals import preview, confirm
    from test_profile_preparation import technical
    from my_harness.storage.models import RegisteredProjectRow
    from my_harness.services.project_configuration import ProjectConfiguration
    from my_harness.services import profile_preparation as prep
    from my_harness.services.project_registry import RegistryError
    from my_harness.storage.managed import Conflict
    from my_harness.core.engine.definition import text_hash

    w, cid = structured_profile
    engine, root = w.repo.engine, w.context.root
    data = response(); data['profile']['preparation_plan'] = technical()
    _, turn = w.turn(cid, data, text='Synthetic owner message')
    intake_stage(w, cid, data, turn, 'intake-stage')
    confirm(w, cid, preview(w, cid))
    args = {'conversation_id': cid, 'expected_version': w.view(cid)['version']}
    shown = run(engine, root, 'intake.preview', args)
    adopted = run(engine, root, 'intake.adopt', {**args, 'preview_sha256': shown['preview_sha256'], 'reason': 'Owner'}, 'intake-adopt')
    project_id = run(engine, root, 'knowledge.head', {})['knowledge_project_id']
    proposal = next(p for p in w.view(cid)['proposals'] if p['kind'] == 'profile')
    with Session(engine) as session, session.begin():
        session.add(RegisteredProjectRow(id='consumer', version=1, status='ACTIVE', root=str(root),
            row={}, row_sha256=text_hash('{}'), trust={}, created_at='2026-10-31', updated_at='2026-10-31'))
    project = SimpleNamespace(id='consumer', context=w.context)
    runtime = SimpleNamespace(engine=engine, project=lambda _: project, setup=SimpleNamespace(legacy=False),
                              preparation=SimpleNamespace(read=lambda _: {'prepared': False}))
    # Configuration/preparation adapters are isolated; persisted knowledge, profile decisions, receipts and files are real.
    class ConfigurationView(ProjectConfiguration):
        @property
        def repository(self): return SimpleNamespace(read=lambda _: {'saved': None, 'active': None})
        def initial(self, _): return {}
        @staticmethod
        def assistance_documents(_): return []
    view = ConfigurationView(runtime)
    candidate = json.loads(proposal['content'])['candidate']
    settings = {'project': {'id': 'consumer', 'root': str(root)}, 'profile_name': candidate['name'],
                'profile': candidate['profile'], 'global': {'revision': 1, 'sha256': 'b'*64}}
    reference = {'revision': 1, 'sha256': 'a'*64, 'status': 'VALIDATED'}
    config = SimpleNamespace(read=lambda scope: {'status': 'READY', 'saved': reference, 'active': settings['global'] if scope == 'global' else None},
                             document=lambda *_: 'synthetic validated private configuration')
    parent = SimpleNamespace(runtime=runtime, managed=w.repo, repository=None, lock=None, runner_factory=None)
    preparation = prep.ProfilePreparation(parent)
    monkeypatch.setattr(preparation, 'configuration', lambda: config)
    monkeypatch.setattr(prep, 'parse', lambda *_: settings)
    preparation_body = {'expected_version': 1, 'configuration_revision': 1, 'configuration_sha256': 'a'*64,
                        'proposal_id': proposal['id'], 'proposal_sha256': proposal['proposal_sha256']}
    first = prepare_export(engine, root, project_id)
    delivered = KnowledgeDelivery(engine, root, project_id).execute(first['record_id'], first['preview_sha256'], IDENTITY)
    assert view.read('consumer')['configuration_state'] == 'DOCUMENTS_COMMITTED'
    with Session(engine) as session:
        assert preparation._source(session, project, preparation_body)[4] == delivered['commit']
    owner = adopt_manifest(engine, root, project_id, ['claude'], 'changed-wrapper')
    assert view.read('consumer')['configuration_state'] == 'PROFILE_PROPOSED'
    with Session(engine) as session:
        with pytest.raises(RegistryError) as refused:
            preparation._source(session, project, preparation_body)
        assert refused.value.code == 'profile_preparation_documents'
        assert _continuation(session, root) == 'export_required'
    if w.view(cid)['kind'] == 'definition':
        assert preview(w, cid, proposal)['continuation'] == 'export_required'
    else:
        # The original onboarding inventory cannot attest new generated targets either.
        with pytest.raises(Conflict): preview(w, cid, proposal)
    captured = disk_baseline(root, [t['path'] for t in owner['manifest']['targets']]); captured['ownership_id'] = owner['record_id']
    second = run(engine, root, 'documents.export.prepare', payload(captured), 'changed-export')
    receipt = KnowledgeDelivery(engine, root, project_id).execute(second['record_id'], second['preview_sha256'], IDENTITY)
    assert view.read('consumer')['configuration_state'] == 'DOCUMENTS_COMMITTED'
    with Session(engine) as session:
        source = preparation._source(session, project, preparation_body)
        assert source[4] == receipt['commit'] and 'CLAUDE.md' in source[5]
    assert preview(w, cid, proposal)['continuation'] == 'export_committed'
    assert receipt['revision_id'] == adopted['revision_id']


def test_single_new_instruction_root_appends_after_existing_root(migrated_database, tmp_path):
    engine, repo, project, first = world(migrated_database[0], tmp_path)
    draft = repo.open_draft(project, first.id)
    original = repo.put(draft, 'section', 'original-rules', section('Original', 'Keep original.'), document='instructions', root_position=0)
    current = repo.adopt(draft, first.id, origin='owner_confirmed', actor=OWNER)
    files = {'AGENTS.md': '# Additional\nNew instruction.\n'}
    source, _, _ = d.parse(files)
    body = {'files': files, 'portable': '', 'mode': 'update', 'expected_revision_id': current.id,
            'choices': {source['members'][0]['item_id']: {'action':'create', 'target':'', 'code':'additional'}}, 'acknowledged': []}
    staged, shown = stage_acknowledged(engine, tmp_path, body, 'new-root')
    assert shown['comparison']['items'][0]['after']['root_position'] == 1
    adopt_import(engine, tmp_path, staged, shown, current.id, 'new-root-adopt')
    accepted = repo.revision(project)
    assert accepted.members[original] == current.members[original]
    assert accepted.roots('instructions') == [original, accepted.item('section','additional','instructions').item_id]


def test_api_new_ownership_reports_pending_and_keeps_old_receipt(migrated_database, tmp_path):
    from session_client import TestClient
    from my_harness.api.app import create_app
    from test_managed_api import config, make_context, LOCAL
    root = tmp_path / 'checkout'; root.mkdir(); LocalGit(root).run('init')
    engine, _, project, _ = world(migrated_database[0], root)
    original = prepare_export(engine, root, project)
    old = KnowledgeDelivery(engine, root, project).execute(original['record_id'], original['preview_sha256'], IDENTITY)
    app = create_app(migrated_database[0], tmp_path / 'ui', managed=config(make_context(root)))
    base = '/api/managed/projects/synthetic/knowledge/documents'
    headers = {'X-My-Harness': '1', 'Idempotency-Key': 'wrapper-preview'}
    with TestClient(app, base_url=LOCAL) as http:
        assert http.get(base + '/bundle').json()['result']['delivery']['status'] == 'export_committed'
        preview = http.post(base + '/ownership/preview', json={'wrappers': ['claude']}, headers=headers)
        assert preview.status_code == 200, preview.text
        shown = preview.json()['result']
        adopted = http.post(base + '/ownership/adopt', json={'record_id': shown['record_id'],
            'preview_sha256': shown['preview_sha256'], 'expected_revision_id': shown['revision_id'],
            'reason': 'Explicitly add Claude wrapper.'}, headers={**headers, 'Idempotency-Key': 'wrapper-adopt'})
        assert adopted.status_code == 200, adopted.text
        bundle = http.get(base + '/bundle').json()['result']
        assert bundle['delivery'] == {'status': 'export_required'}
        assert bundle['ownership_id'] == adopted.json()['result']['record_id']
        assert not (root / 'CLAUDE.md').exists()
        historical = http.get(base + '/records/' + original['record_id']).json()['result']
        assert not historical['pending'] and old in historical['outcomes']


def test_portable_failure_does_not_suppress_valid_rendering(migrated_database, tmp_path):
    engine, repo, project, first = world(migrated_database[0], tmp_path)
    draft = repo.open_draft(project, first.id)
    old = first.item('requirement', 'R001')
    repo.put(draft, 'requirement', 'R001', old.content, provenance='known', source={
        'kind': 'legacy_document', 'path': '/synthetic-private-original.md', 'sha256': '0'*64})
    repo.adopt(draft, first.id, origin='owner_confirmed', actor=OWNER)
    bundle = run(engine, tmp_path, 'documents.bundle', {})
    assert bundle['files'] and bundle['render_error'] is None
    assert bundle['portable'] is None and bundle['portable_error'] == 'portable_absolute_source'
