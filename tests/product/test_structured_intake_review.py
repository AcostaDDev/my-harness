"""T011 maintained regressions for the three technical-review findings; synthetic only."""
from copy import deepcopy
import json

import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from test_structured_intake import world, onboard_world, proposal
from test_domain_operations import run, put, refused
from test_definition import BRIEF, World
from test_managed_api import git, make_context, IDENTITY, VERSIONS, Ports
from test_profile_proposals import candidate, profile, preview, confirm
from test_project_onboarding import checkout
from my_harness.adapters.git import GitWorkspace
from my_harness.core.engine.context import IntakeContext
from my_harness.core.engine.knowledge import digest
from my_harness.core.engine.definition import text_hash
from my_harness.services.domain_operations import DomainOperations, owner_writer
from my_harness.services.managed import LocalSupervisor
from my_harness.storage.database import make_engine
from my_harness.storage.managed import SQLiteManagedRepository, Conflict
from my_harness.storage.models import ConfigurationOperationRow


def stage(world, cid, data, turn, key):
    return run(DomainOperations(world.repo.engine), owner_writer(str(world.context.root)), 'intake.stage', {
        'conversation_id': cid, 'expected_version': world.view(cid)['version'], 'turn_id': turn['id'],
        'proposal_sha256': digest(data['knowledge'])}, key)


def test_preserve_earlier_owner_answer(world):
    cid = world.planning.create(world.context, kind='definition', title='Synthetic', brief=BRIEF,
                                writer=world.writer, structured=True)
    text = 'Synthetic owner intent for the first round.'
    data = {'answer': 'Synthetic', 'questions': [], 'pending': [], 'knowledge': proposal(text_hash(text))}
    _, turn = world.turn(cid, data, text=text)
    stage(world, cid, data, turn, 'first-stage')
    _, turn = world.turn(cid, data, text='Preserve that intent and refine presentation.')
    stage(world, cid, data, turn, 'second-stage')
    data['knowledge']['items'][0]['source']['sha256'] = 'f' * 64
    _, turn = world.turn(cid, data, text='Do not invent sources')
    refused('knowledge_invalid', lambda: stage(world, cid, data, turn, 'invented'))


def test_originals_survive_followup_without_duplicates_or_collisions(onboard_world):
    world = onboard_world
    original = '# Local rule\n\nPreserve this synthetic rule.\n\n## Child\n\nChild body.\n'
    (world.context.root / 'AGENTS.md').write_text(original)
    git(world.context.root, 'add', 'AGENTS.md')
    git(world.context.root, 'commit', '-m', 'Synthetic original instructions')
    cid = world.create(structured=True)
    data = {'answer': 'Synthetic', 'questions': [], 'pending': [],
            'knowledge': proposal(text_hash('Propón las fusiones'))}
    _, turn = world.turn(cid, data)
    stage(world, cid, data, turn, 'first-stage')
    ops, caller = DomainOperations(world.engine), owner_writer(str(world.context.root))
    def shown():
        return run(ops, caller, 'intake.preview', {'conversation_id': cid,
                   'expected_version': world.view(cid)['version']}).result
    first = shown()
    originals = [m for m in first['members'] if m['code'].startswith('original-')]
    by_id = {m['item_id']: m for m in first['members']}
    for m in originals:
        data['knowledge']['items'].append(put(m['kind'], m['code'], m['content'], document=m['document'],
            source=m['source'], root_position=m['root_position']))
    for l in first['links']:
        if by_id[l['source_item_id']]['code'].startswith('original-'):
            data['knowledge']['links'].append({'kind': l['kind'], 'position': l['position'],
                'source': 'section:instructions:' + by_id[l['source_item_id']]['code'],
                'target': 'section:instructions:' + by_id[l['target_item_id']]['code']})
    _, turn = world.turn(cid, data, text='Keep the original rules')
    stage(world, cid, data, turn, 'second-stage')
    second = shown()
    assert [(m['code'], m['content'], m['source']) for m in second['members'] if m['code'].startswith('original-')] == [
        (m['code'], m['content'], m['source']) for m in originals]
    assert len(second['members']) == len(first['members'])
    for field in ('content', 'source'):
        bad = deepcopy(data)
        item = next(i for i in bad['knowledge']['items'] if i['code'].startswith('original-'))
        item[field]['body' if field == 'content' else 'reference'] = 'Forged'
        _, turn = world.turn(cid, bad)
        refused('knowledge_invalid', lambda: stage(world, cid, bad, turn, 'forged-' + field))
    assert (world.context.root / 'AGENTS.md').read_text() == original


@pytest.fixture(params=['definition', 'onboarding'])
def structured_profile(request, migrated_database, tmp_path):
    kind = request.param
    root = tmp_path / 'synthetic-profile'
    if kind == 'onboarding':
        checkout(root, {'go.mod': 'module example.invalid/synthetic\n\ngo 1.25\n'})
    else:
        root.mkdir()
    context = IntakeContext(root, make_context(root).policy)
    engine = make_engine(migrated_database[0])
    repo, writer, ports = SQLiteManagedRepository(engine), GitWorkspace(IDENTITY), Ports()
    worker = LocalSupervisor(repo, ports, commit_factory=lambda c, v: writer)
    w = World(context, repo, writer, worker, ports)
    cid = w.planning.create(context, kind=kind, title='Synthetic', brief=BRIEF if kind == 'definition' else None,
                            writer=writer, structured=True)
    yield w, cid
    engine.dispose()


def response():
    knowledge = proposal(text_hash('Synthetic owner message'))
    proposed = candidate()
    proposed['evidence'][0]['sources'] = [{'path': 'knowledge:section:architecture:design',
        'sha256': digest(next(i for i in knowledge['items'] if i.get('document') == 'architecture'))}]
    return {'answer': 'Synthetic', 'questions': [], 'pending': [], 'knowledge': knowledge, 'profile': proposed}


def test_structured_profile_proposal_review_confirmation_and_separate_gates(structured_profile):
    w, cid = structured_profile
    data = response()
    job, turn = w.turn(cid, data, text='Synthetic owner message')
    assert turn['status'] == 'ANSWERED', turn
    prompt = json.loads(w.repo.get_run(job.run_id).history.attempts[0].request.prompt_snapshot_json)
    assert 'profile' in prompt['output_schema']['required']
    assert not preview(w, cid)['ready']
    stage(w, cid, data, turn, 'stage')
    shown = preview(w, cid)
    assert shown['ready'], shown
    assert shown['knowledge_binding']['status'] == 'DRAFT'
    result = confirm(w, cid, shown)
    assert confirm(w, cid, shown) == result
    assert not w.view(cid)['created']  # profile confirmation never adopts knowledge
    assert preview(w, cid, next(p for p in w.view(cid)['proposals'] if p['kind'] == 'profile'))['ready']
    ops, caller = DomainOperations(w.repo.engine), owner_writer(str(w.context.root))
    args = {'conversation_id': cid, 'expected_version': w.view(cid)['version']}
    knowledge = run(ops, caller, 'intake.preview', args).result
    run(ops, caller, 'intake.adopt', {**args, 'preview_sha256': knowledge['preview_sha256'], 'reason': 'Owner'}, 'adopt')
    p = next(p for p in w.view(cid)['proposals'] if p['kind'] == 'profile')
    assert preview(w, cid, p)['ready']  # explicit revalidation after knowledge adoption
    with Session(w.repo.engine) as session:
        assert session.scalar(select(func.count()).select_from(ConfigurationOperationRow)) == 0
    from my_harness.storage.profile_intake import documentary_profile
    with pytest.raises(Conflict):
        documentary_profile(w.repo, w.context, cid, w.writer, VERSIONS)


def test_invalid_profile_refuses_complete_turn(structured_profile):
    w, cid = structured_profile
    data = response()
    data['profile']['profile']['validations'][0]['argv'] = ['true']
    _, turn = w.turn(cid, data, text='Synthetic owner message')
    assert turn['status'] == 'FAILED'
    assert not w.view(cid)['proposals']
    refused('preview_stale', lambda: stage(w, cid, data, turn, 'invalid'))


def test_profile_preview_is_stale_after_knowledge_or_version_change(structured_profile):
    w, cid = structured_profile
    data = response()
    _, turn = w.turn(cid, data, text='Synthetic owner message')
    stage(w, cid, data, turn, 'first')
    shown = preview(w, cid)
    data['knowledge']['items'][0]['content']['title'] = 'Updated intent'
    _, turn = w.turn(cid, data, text='Synthetic owner message')
    with pytest.raises(Conflict):
        confirm(w, cid, shown)
    assert not preview(w, cid)['ready']
    stage(w, cid, data, turn, 'second')
    assert preview(w, cid)['ready']


def test_sources_do_not_cross_conversations(onboard_world):
    w = onboard_world
    first = w.create(structured=True)
    data = {'answer': 'Synthetic', 'questions': [], 'pending': [], 'knowledge': proposal(text_hash('Private answer'))}
    _, turn = w.turn(first, data, text='Private answer')
    stage(w, first, data, turn, 'private')
    second = w.create(structured=True)
    _, turn = w.turn(second, data, text='Another conversation')
    refused('knowledge_invalid', lambda: stage(w, second, data, turn, 'cross-conversation'))


def test_profile_questions_and_frozen_versions(structured_profile):
    w, cid = structured_profile
    data = response()
    data['questions'] = [{'text': 'Confirm intent?', 'blocking': True}]
    _, turn = w.turn(cid, data, text='Synthetic owner message')
    stage(w, cid, data, turn, 'stage')
    assert not preview(w, cid)['ready']
    q = w.view(cid)['questions'][0]
    w.planning.defer(cid, w.view(cid)['version'], question_id=q['id'], reason='Owner explicitly postpones')
    assert preview(w, cid)['ready']
    p = profile(w, cid)
    assert not w.planning.profile_preview(w.context, cid, p['id'], w.view(cid)['version'],
        p['proposal_sha256'], w.writer, versions={**VERSIONS, 'synthetic': 'changed'})['ready']


def test_profile_http_contract_and_confirmation(structured_profile, tmp_path):
    from my_harness.services.managed_runtime import ManagedConfig, ManagedProject
    from test_managed_api import client
    w, cid = structured_profile
    cfg = ManagedConfig((ManagedProject('intake', w.context, VERSIONS, bootstrap_enabled=True),),
                       ports_factory=w.ports, commit_factory=lambda c, v: w.writer)
    with client(str(w.repo.engine.url), tmp_path, cfg) as http:
        w.context = http.app.state.runtime.project('intake').context
        data = response()
        _, turn = w.turn(cid, data, text='Synthetic owner message')
        stage(w, cid, data, turn, 'stage')
        p = profile(w, cid)
        base = f'/api/managed/projects/intake/planning/{cid}/profile'
        body = {'proposal_id': p['id'], 'proposal_sha256': p['proposal_sha256'],
                'expected_version': w.view(cid)['version']}
        shown = http.post(base + '/preview', headers={'X-My-Harness': '1'}, json=body)
        assert shown.status_code == 200, shown.text
        assert shown.json()['ready'] and shown.json()['knowledge_binding']
        confirmation = {**body, 'preview_sha256': shown.json()['preview_sha256'], 'reason': 'Owner review', 'confirmed': True}
        headers = {'X-My-Harness': '1', 'Idempotency-Key': 'profile-http'}
        done = http.post(base + '/confirm', headers=headers, json=confirmation)
        assert done.status_code == 200, done.text
        assert http.post(base + '/confirm', headers=headers, json=confirmation).json() == done.json()
        assert not w.view(cid)['created']


def test_profile_refuses_changed_source_or_draft(structured_profile):
    from my_harness.storage.models import PlanningConversationRow
    w, cid = structured_profile
    data = response()
    _, turn = w.turn(cid, data, text='Synthetic owner message')
    stage(w, cid, data, turn, 'stage')
    shown = preview(w, cid)
    assert shown['ready']
    # Synthetic corruption cannot become a new reviewed source or knowledge revision implicitly.
    with w.repo._write() as session:
        row = session.get(PlanningConversationRow, cid)
        row.source = {**row.source, 'unreviewed': True}
    assert not preview(w, cid)['ready']
    with pytest.raises(Conflict):
        confirm(w, cid, shown)


def test_profile_edit_revalidates_exact_knowledge_and_refuses_invalid_evidence(structured_profile):
    w, cid = structured_profile
    data = response()
    _, turn = w.turn(cid, data, text='Synthetic owner message')
    stage(w, cid, data, turn, 'stage')
    p = profile(w, cid)
    changed = deepcopy(data['profile'])
    changed['rationale'] = 'Owner clarified the same bounded Go profile'
    edited = w.planning.edit_profile(w.context, cid, p['id'], w.view(cid)['version'], p['proposal_sha256'],
        changed, 'Owner edit', 'edit-profile', writer=w.writer)
    assert edited['proposal_id'] != p['id']
    shown = preview(w, cid)
    assert shown['ready']
    confirm(w, cid, shown)
    with Session(w.repo.engine) as session:
        from my_harness.storage.models import PlanningProposalRow
        record = session.get(PlanningProposalRow, edited['proposal_id'])
        assert record.decision['origin'] == 'owner_confirmed'
        assert record.decision['knowledge_binding'] == shown['knowledge_binding']


def test_foreign_path_with_local_content_hash_is_refused(world):
    cid = world.planning.create(world.context, kind='definition', title='Synthetic', brief=BRIEF,
                                writer=world.writer, structured=True)
    data = {'answer': 'Synthetic', 'questions': [], 'pending': [], 'knowledge': proposal()}
    data['knowledge']['items'][0]['source']['path'] = 'unobserved/private/file.md'
    _, turn = world.turn(cid, data)
    refused('knowledge_invalid', lambda: stage(world, cid, data, turn, 'foreign-path'))


@pytest.mark.parametrize('profile_first', [False, True])
def test_null_profile_cannot_close_intake_and_later_profile_completes_independent_confirmations(structured_profile, profile_first):
    from my_harness.storage.models import KnowledgeRevisionRow
    from my_harness.services.domain_operations import DomainRefusal
    from my_harness.i18n import message
    w, cid = structured_profile
    data = response()
    data['profile'] = None
    _, turn = w.turn(cid, data, text='Synthetic owner message')
    assert turn['status'] == 'ANSWERED'
    stage(w, cid, data, turn, 'without-profile')
    ops, caller = DomainOperations(w.repo.engine), owner_writer(str(w.context.root))
    args = {'conversation_id': cid, 'expected_version': w.view(cid)['version']}
    shown = run(ops, caller, 'intake.preview', args).result
    body = {**args, 'preview_sha256': shown['preview_sha256'], 'reason': 'Owner knowledge review'}
    with pytest.raises(DomainRefusal) as refused_adoption:
        run(ops, caller, 'intake.adopt', body, 'no-continuation')
    assert refused_adoption.value.code == 'intake_profile_required'
    assert refused_adoption.value.status == 409
    for language in ('en', 'es'):
        assert message('domain.intake_profile_required', language) != 'domain.intake_profile_required'
    assert not w.view(cid)['created'] and 'message' in w.view(cid)['actions']
    assert not w.view(cid)['proposals']
    with Session(w.repo.engine) as session:
        assert not session.scalars(select(KnowledgeRevisionRow).where(KnowledgeRevisionRow.status == 'ACCEPTED')).all()
    # The earlier answer remains a legitimate source; no accepted context is fabricated.
    data = response()
    _, turn = w.turn(cid, data, text='Now propose the profile; preserve earlier owner sources')
    assert turn['status'] == 'ANSWERED'
    stage(w, cid, data, turn, 'with-profile')
    refused('preview_stale', lambda: run(ops, caller, 'intake.adopt', body, 'obsolete'))
    profile_shown = preview(w, cid)
    assert profile_shown['ready']
    if profile_first:
        confirm(w, cid, profile_shown)
        assert not w.view(cid)['created']
    args = {'conversation_id': cid, 'expected_version': w.view(cid)['version']}
    shown = run(ops, caller, 'intake.preview', args).result
    body = {**args, 'preview_sha256': shown['preview_sha256'], 'reason': 'Owner knowledge review'}
    adopted = run(ops, caller, 'intake.adopt', body, 'knowledge-adopt')
    assert run(ops, caller, 'intake.adopt', body, 'knowledge-adopt').replayed
    if not profile_first:
        # Knowledge adoption must not confirm the available profile or silently reuse its old preview.
        assert profile(w, cid)['status'] == 'PROPOSED'
        with pytest.raises(Conflict):
            confirm(w, cid, profile_shown)
        profile_shown = preview(w, cid)
        confirm(w, cid, profile_shown)
    assert confirm(w, cid, profile_shown)['configuration_state'] == 'PROFILE_PROPOSED'
    assert w.view(cid)['created']
    with Session(w.repo.engine) as session:
        assert session.scalar(select(func.count()).select_from(KnowledgeRevisionRow).where(
            KnowledgeRevisionRow.status == 'ACCEPTED')) == 1
        assert session.scalar(select(func.count()).select_from(ConfigurationOperationRow)) == 0
    assert w.worker.run_once() is None
    assert w.ports.roles() == ['definition', 'definition']


def test_null_profile_adoption_http_refuses_with_actionable_diagnostic(structured_profile, tmp_path):
    from my_harness.services.managed_runtime import ManagedConfig, ManagedProject
    from test_managed_api import client
    from my_harness.i18n import message
    w, cid = structured_profile
    cfg = ManagedConfig((ManagedProject('intake', w.context, VERSIONS, bootstrap_enabled=True),),
                       ports_factory=w.ports, commit_factory=lambda c, v: w.writer)
    with client(str(w.repo.engine.url), tmp_path, cfg) as http:
        w.context = http.app.state.runtime.project('intake').context
        data = response()
        data['profile'] = None
        _, turn = w.turn(cid, data, text='Synthetic owner message')
        stage(w, cid, data, turn, 'stage-null-profile')
        base = '/api/managed/projects/intake/intake'
        args = {'conversation_id': cid, 'expected_version': w.view(cid)['version']}
        headers = {'X-My-Harness': '1', 'Idempotency-Key': 'blocked-adoption'}
        shown = http.post(base + '/preview', headers=headers, json=args)
        assert shown.status_code == 200, shown.text
        refused_adoption = http.post(base + '/adopt', headers=headers, json={**args,
            'preview_sha256': shown.json()['preview_sha256'], 'reason': 'Owner knowledge review'})
        assert refused_adoption.status_code == 409, refused_adoption.text
        assert refused_adoption.json()['detail']['code'] == 'intake_profile_required'
        assert refused_adoption.json()['detail']['diagnostic'] == message('domain.intake_profile_required', 'en')
        detail = http.get(f'/api/managed/projects/intake/planning/{cid}').json()
        assert not detail['created'] and 'message' in detail['actions']
