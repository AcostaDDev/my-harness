"""D294 synthetic rich round trips, hostile input, ownership and deterministic recovery."""
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from my_harness.adapters.local_git import LocalGit
from my_harness.core.engine import knowledge_documents as d
from my_harness.core.engine.commit import GitIdentity
from my_harness.services.domain_operations import DomainOperations, owner_writer
from my_harness.core.engine.domain_catalogue import CATALOGUE
from my_harness.services.knowledge_delivery import KnowledgeDelivery, baseline as disk_baseline
from my_harness.storage.database import make_engine
from my_harness.storage.knowledge import KnowledgeRepository
from my_harness.storage.work_language import associate
from test_knowledge import baseline, OWNER, section

IDENTITY = GitIdentity('Synthetic owner', 'synthetic@example.invalid')


def world(url, root):
    engine = make_engine(url)
    repo = KnowledgeRepository(engine)
    project = repo.project(str(root))
    with Session(engine) as session, session.begin():
        associate(session, root=str(root), project_id=project, work_language='en', source='migration', confirmation={'synthetic': True}, now='2026-10-31T12:00:00+00:00')
    revision = baseline(repo, project)
    return engine, repo, project, repo.revision(project)


def run(engine, root, name, arguments, key=None):
    return DomainOperations(engine).execute(owner_writer(str(root)), CATALOGUE.current(name).ref, arguments, key).body()


def payload(value):
    return {'payload': d.freeze(value)}


def test_rich_roundtrip_and_explicit_edits(migrated_database, tmp_path):
    engine, repo, project, revision = world(migrated_database[0], tmp_path)
    draft = repo.open_draft(project, revision.id)
    repo.put(draft, 'section', 'diagram', section('Queue', '  Prose.\n\n```mermaid\nflowchart LR\n A-->B\n```\n'), document='architecture', root_position=0)
    repo.put(draft, 'section', 'rules', section('Rules', 'Keep all content.\n'), document='instructions', root_position=0)
    repo.adopt(draft, revision.id, origin='owner_confirmed', actor=OWNER)
    data = d.snapshot(repo.revision(project))
    manifest = d.ownership(project, 'en')
    files = d.render(data, manifest)
    parsed, report, _language = d.parse(files)
    assert not any(r['blocking'] for r in report)
    assert sorted(parsed['members'], key=lambda m:m['item_id']) == data['members']
    assert d.render(parsed, manifest) == files
    files['docs/ARCHITECTURE.md'] = files['docs/ARCHITECTURE.md'].replace('Prose.', 'Edited prose.')
    parsed, report, _ = d.parse(files)
    assert not any(r['blocking'] for r in report)
    assert 'Edited prose.' in next(m['content']['body'] for m in parsed['members'] if m['code']=='diagram')
    files['docs/ARCHITECTURE.md'] += '\nUncontained prose.\n'
    assert any(r['blocking'] for r in d.parse(files)[1])


def test_partial_selection_retains_other_members(migrated_database, tmp_path):
    _, _, project, revision = world(migrated_database[0], tmp_path)
    files = d.render(d.snapshot(revision), d.ownership(project, 'en'))
    parsed, report, _ = d.parse({d.META: files[d.META], 'docs/SPECIFICATION.md': files['docs/SPECIFICATION.md']})
    assert {m['kind'] for m in parsed['members']} == {'requirement', 'criterion', 'section'}
    assert any(r['code']=='retained_unselected' for r in report)


@pytest.mark.parametrize('bad', ['../escape.md', '/absolute.md', 'docs/unknown.md'])
def test_hostile_paths_refused(migrated_database, tmp_path, bad):
    _, _, project, revision = world(migrated_database[0], tmp_path)
    files = d.render(d.snapshot(revision), d.ownership(project, 'en'))
    files[bad] = 'hostile'
    with pytest.raises(ValueError): d.parse(files)


def test_portable_integrity_and_forbidden_history(migrated_database, tmp_path):
    _, _, _, revision = world(migrated_database[0], tmp_path)
    original = d.snapshot(revision)
    transfer = d.portable(original, 'en')
    assert d.parse_portable(transfer)[0] == original
    value = d.loads(transfer)
    value['payload']['knowledge']['runs'] = []
    value['sha256'] = d.k.digest(value['payload'])
    with pytest.raises(ValueError): d.parse_portable(d.freeze(value))
    with pytest.raises(ValueError): d.loads('{"a":1,"a":2}')


def prepare_export(engine, root, project):
    manifest = d.ownership(project, 'en')
    captured = disk_baseline(root, [t['path'] for t in manifest['targets']])
    shown = run(engine, root, 'documents.ownership.prepare', payload({'wrappers': [], 'baseline': captured}), 'own-preview')
    adopted = run(engine, root, 'documents.ownership.adopt', {'record_id': shown['record_id'],
        'preview_sha256': shown['preview_sha256'], 'expected_revision_id': shown['revision_id'], 'reason': 'Explicit takeover.'}, 'own')
    captured['ownership_id'] = adopted['record_id']
    return run(engine, root, 'documents.export.prepare', payload(captured), 'export-preview')


def test_partial_export_retry_and_lost_response(migrated_database, tmp_path):
    root = tmp_path / 'checkout'; root.mkdir()
    git = LocalGit(root); git.run('init')
    engine, repo, project, revision = world(migrated_database[0], root)
    shown = prepare_export(engine, root, project)
    delivery = KnowledgeDelivery(engine, root, project)
    def crash(_path): raise RuntimeError('synthetic crash after a target')
    with pytest.raises(RuntimeError): delivery.execute(shown['record_id'], shown['preview_sha256'], IDENTITY, after_write=crash)
    assert delivery.status(shown['record_id'])['pending']
    with pytest.raises(ValueError, match='stopped'): delivery.execute(shown['record_id'], shown['preview_sha256'], IDENTITY)
    result = delivery.execute(shown['record_id'], shown['preview_sha256'], IDENTITY, writer_stopped=True)
    assert result['status'] == 'COMPLETED'
    assert delivery.execute(shown['record_id'], shown['preview_sha256'], IDENTITY) == result
    assert not git.run('status', '--porcelain')
    assert git.text('rev-list', '--count', 'HEAD') == '1'
    assert (root/'docs/SPECIFICATION.md').read_text() == shown['files']['docs/SPECIFICATION.md']


def test_dirty_and_link_refusal(migrated_database, tmp_path):
    root=tmp_path/'checkout';root.mkdir();LocalGit(root).run('init')
    (root/'AGENTS.md').write_text('uncommitted')
    with pytest.raises(ValueError, match='dirty'): disk_baseline(root, ['AGENTS.md'])
    (root/'AGENTS.md').unlink();(root/'docs').symlink_to(tmp_path, target_is_directory=True)
    from my_harness.services.knowledge_delivery import read
    with pytest.raises(ValueError): read(root, 'docs/STATE.md')


def test_staged_update_exact_preview_cas_and_same_consent(migrated_database, tmp_path):
    from my_harness.services.domain_operations import DomainRefusal
    engine, repo, project, revision = world(migrated_database[0], tmp_path)
    files = d.render(d.snapshot(revision), d.ownership(project, 'en'))
    files['docs/SPECIFICATION.md'] = files['docs/SPECIFICATION.md'].replace('Users can sign in.', 'Users can sign out.\n\n```mermaid\nflowchart LR\n A-->B\n```')
    body = {'files': files, 'portable': '', 'mode': 'update', 'choices': {}, 'acknowledged': [], 'expected_revision_id': revision.id}
    staged = run(engine, tmp_path, 'documents.stage', payload(body), 'stage')
    assert staged['draft_id'], staged
    shown = run(engine, tmp_path, 'documents.preview', {'record_id': staged['record_id']})
    consent = {'record_id': staged['record_id'], 'preview_sha256': shown['preview_sha256'],
               'expected_revision_id': revision.id, 'reason': 'Reviewed explicit IDE change.'}
    with pytest.raises(DomainRefusal): run(engine, tmp_path, 'knowledge.adoption.preview', {'draft_id': staged['draft_id']})
    adopted = run(engine, tmp_path, 'documents.adopt', consent, 'adopt')
    again = run(engine, tmp_path, 'documents.adopt', consent, 'adopt')
    assert adopted['revision_id'] == again['revision_id'] and again['replayed']
    assert repo.revision(project).number == 2
    assert 'sign out' in repo.revision(project).item('requirement', 'R001').content['statement']
    assert repo.revision(project,1) == revision
    with pytest.raises(DomainRefusal): run(engine, tmp_path, 'documents.adopt', consent, 'different-consent')


def test_portable_new_project_maps_every_reference(migrated_database, tmp_path):
    engine, repo, project, revision = world(migrated_database[0], tmp_path/'source')
    root = tmp_path/'destination'
    destination = repo.project(str(root))
    with Session(engine) as session, session.begin():
        associate(session, root=str(root), project_id=destination, work_language='en', source='migration',
                  confirmation={'synthetic': True}, now='2026-10-31T12:00:00+00:00')
    body = {'files': {}, 'portable': d.portable(d.snapshot(revision),'en'), 'mode':'new', 'choices':{},
            'acknowledged':[], 'expected_revision_id':None}
    staged = run(engine, root, 'documents.stage', payload(body), 'portable')
    preview = run(engine, root, 'documents.preview', {'record_id':staged['record_id']})
    assert not set(preview['mapping'].values()) & set(revision.members)
    adopted = run(engine, root, 'documents.adopt', {'record_id':staged['record_id'], 'preview_sha256':preview['preview_sha256'],
        'expected_revision_id':None,'reason':'Transfer synthetic knowledge.'}, 'portable-adopt')
    transferred = repo.revision(destination)
    assert len(transferred.links)==len(revision.links)
    assert transferred.number==1 and transferred.origin=='owner_confirmed'
    assert transferred.item('task','P001-T001').content==revision.item('task','P001-T001').content
    assert all(link.source in transferred.members and link.target in transferred.members for link in transferred.links)


def test_unknown_identity_needs_explicit_choice_and_cannot_merge_by_code(migrated_database, tmp_path):
    engine, repo, project, revision = world(migrated_database[0], tmp_path)
    files = d.render(d.snapshot(revision),d.ownership(project,'en'))
    meta=d.loads(files[d.META]); meta['source_project_id']='foreign-project';files[d.META]=d.freeze(meta)
    body={'files':files,'portable':'','mode':'update','choices':{},'acknowledged':[],'expected_revision_id':revision.id}
    staged=run(engine,tmp_path,'documents.stage',payload(body),'unknown')
    assert staged['draft_id'] is None and any(r['code']=='identity_choice_required' for r in staged['report'])
    assert repo.revision(project)==revision


def test_export_rejects_unrelated_edits_after_partial_delivery(migrated_database,tmp_path):
    root=tmp_path/'checkout';root.mkdir();git=LocalGit(root);git.run('init')
    engine,_,project,_=world(migrated_database[0],root)
    shown=prepare_export(engine,root,project);delivery=KnowledgeDelivery(engine,root,project)
    def crash(_): raise RuntimeError('synthetic crash')
    with pytest.raises(RuntimeError): delivery.execute(shown['record_id'],shown['preview_sha256'],IDENTITY,after_write=crash)
    (root/'AGENTS.md').write_text('unrelated edit')
    with pytest.raises(ValueError): delivery.execute(shown['record_id'],shown['preview_sha256'],IDENTITY,writer_stopped=True)
    assert (root/'AGENTS.md').read_text()=='unrelated edit'
    assert not head_exists(git)


def head_exists(git): return git.code('rev-parse','--verify','HEAD')==0


def test_instruction_budget_never_truncates(migrated_database,tmp_path):
    _,repo,project,revision=world(migrated_database[0],tmp_path)
    draft=repo.open_draft(project,revision.id)
    repo.put(draft,'section','long-rules',section('Rules','rule\n'*61),document='instructions',root_position=0)
    repo.adopt(draft,revision.id,origin='owner_confirmed',actor=OWNER)
    with pytest.raises(ValueError,match='instruction_budget'): d.render(d.snapshot(repo.revision(project)),d.ownership(project,'en'))
    assert repo.revision(project).item('section','long-rules','instructions').content['body']=='rule\n'*61


def test_http_import_guards_exact_consent_and_query_only(migrated_database,tmp_path):
    from session_client import TestClient
    from my_harness.api.app import create_app
    from my_harness.storage.backup import create_backup,restore_backup
    from test_managed_api import config,make_context,LOCAL
    root=tmp_path/'checkout';root.mkdir()
    engine,repo,project,revision=world(migrated_database[0],root)
    files=d.render(d.snapshot(revision),d.ownership(project,'en'))
    files['docs/SPECIFICATION.md']=files['docs/SPECIFICATION.md'].replace('Users can sign in.','Changed through explicit HTTP import.')
    selected={'files':files,'portable':'','mode':'update','choices':{},'acknowledged':[],'expected_revision_id':revision.id}
    app=create_app(migrated_database[0],tmp_path/'ui',managed=config(make_context(root)))
    base='/api/managed/projects/synthetic/knowledge/documents'
    headers={'X-My-Harness':'1','Idempotency-Key':'http-stage'}
    with TestClient(app,base_url=LOCAL) as http:
        assert http.post(base+'/stage',json=payload(selected)).status_code==403
        assert http.post(base+'/stage',json=payload(selected),headers={**headers,'Origin':'http://evil.example'}).status_code==403
        staged=http.post(base+'/stage',json=payload(selected),headers=headers)
        assert staged.status_code==200,staged.text
        staged=staged.json()['result']
        preview=http.post(base+'/preview',json={'record_id':staged['record_id']},headers={'X-My-Harness':'1'})
        assert preview.status_code==200,preview.text
        shown=preview.json()['result']
        consent={'record_id':staged['record_id'],'preview_sha256':shown['preview_sha256'],
                 'expected_revision_id':revision.id,'reason':'Synthetic exact HTTP consent.'}
        first=http.post(base+'/adopt',json=consent,headers={**headers,'Idempotency-Key':'http-adopt'})
        assert first.status_code==200,first.text
        again=http.post(base+'/adopt',json=consent,headers={**headers,'Idempotency-Key':'http-adopt'})
        assert again.json()['result']['replayed']
        assert first.json()['result']['revision_id']==again.json()['result']['revision_id']
        assert http.post('/api/managed/projects/foreign/knowledge/documents/preview',json={'record_id':staged['record_id']},headers=headers).status_code==404
    engine.dispose()
    create_backup(migrated_database[0].removeprefix('sqlite:///'),tmp_path/'backup',writers_stopped=True)
    restored=restore_backup(tmp_path/'backup',tmp_path/'restored')
    archive=create_app('sqlite:///'+str(tmp_path/'restored/state.sqlite3'),tmp_path/'ui')
    with TestClient(archive,base_url=LOCAL) as http:
        response=http.post(base+'/stage',json=payload(selected),headers=headers)
        assert response.status_code==409
        assert http.get(f'/api/managed/knowledge/projects/{project}').status_code==200


def test_metadata_hash_cannot_hide_uncontained_content(migrated_database,tmp_path):
    _,_,project,revision=world(migrated_database[0],tmp_path)
    files=d.render(d.snapshot(revision),d.ownership(project,'en'))
    files['docs/ARCHITECTURE.md']+='Do not discard this.\n'
    metadata=d.loads(files[d.META]);metadata['decoration']['docs/ARCHITECTURE.md']=d.sha(d._strip_fields(files['docs/ARCHITECTURE.md']))
    files[d.META]=d.freeze(metadata)
    assert any(r['blocking'] for r in d.parse(files)[1])


def test_empty_root_creation_is_sealed_and_deterministic(migrated_database,tmp_path):
    root=tmp_path/'empty';root.mkdir()
    engine,_,project,_=world(migrated_database[0],root)
    shown=prepare_export(engine,root,project)
    assert shown['baseline']['init_required'] and not (root/'.git').exists()
    result=KnowledgeDelivery(engine,root,project).execute(shown['record_id'],shown['preview_sha256'],IDENTITY)
    assert result['status']=='COMPLETED'
    assert LocalGit(root).text('rev-list','--count','HEAD')=='1'
    assert not LocalGit(root).run('status','--porcelain')


def test_committed_ide_edits_and_committed_missing_targets_regenerate(migrated_database,tmp_path):
    root=tmp_path/'checkout';root.mkdir();git=LocalGit(root);git.run('init')
    engine,_,project,_=world(migrated_database[0],root)
    first=prepare_export(engine,root,project);delivery=KnowledgeDelivery(engine,root,project)
    delivery.execute(first['record_id'],first['preview_sha256'],IDENTITY)
    (root/'docs/SPECIFICATION.md').write_text('Committed synthetic IDE prose is not renderer input.\n')
    (root/'docs/ARCHITECTURE.md').unlink()
    git.run('add','--all')
    env={'GIT_AUTHOR_NAME':IDENTITY.name,'GIT_AUTHOR_EMAIL':IDENTITY.email,
         'GIT_COMMITTER_NAME':IDENTITY.name,'GIT_COMMITTER_EMAIL':IDENTITY.email}
    git.run('commit','-m','Synthetic IDE edit and deletion',env=env)
    owned=run(engine,root,'documents.bundle',{})['ownership_id']
    captured=disk_baseline(root,first['files']);captured['ownership_id']=owned
    shown=run(engine,root,'documents.export.prepare',payload(captured),'second-export')
    assert shown['files']==first['files']
    result=delivery.execute(shown['record_id'],shown['preview_sha256'],IDENTITY)
    assert result['status']=='COMPLETED'
    assert (root/'docs/SPECIFICATION.md').read_text()==first['files']['docs/SPECIFICATION.md']
    assert (root/'docs/ARCHITECTURE.md').exists()
    assert 'Committed synthetic IDE prose' in git.text('show','HEAD^:docs/SPECIFICATION.md')


def test_commit_response_loss_reconciles_existing_commit(migrated_database,tmp_path,monkeypatch):
    root=tmp_path/'checkout';root.mkdir();LocalGit(root).run('init')
    engine,_,project,_=world(migrated_database[0],root)
    shown=prepare_export(engine,root,project);delivery=KnowledgeDelivery(engine,root,project)
    original=LocalGit.run
    def lost(self,*args,**kwargs):
        result=original(self,*args,**kwargs)
        if args[0]=='update-ref': raise RuntimeError('Synthetic lost ref update response')
        return result
    with monkeypatch.context() as patch:
        patch.setattr(LocalGit,'run',lost)
        with pytest.raises(RuntimeError): delivery.execute(shown['record_id'],shown['preview_sha256'],IDENTITY)
    committed=LocalGit(root).text('rev-parse','HEAD')
    result=delivery.execute(shown['record_id'],shown['preview_sha256'],IDENTITY,writer_stopped=True)
    assert result['commit']==committed
    assert LocalGit(root).text('rev-list','--count','HEAD')=='1'
    assert not LocalGit(root).run('status','--porcelain')


def test_plain_instruction_staging_preserves_originals_and_requires_choices(migrated_database,tmp_path):
    engine,_,_,revision=world(migrated_database[0],tmp_path)
    files={'AGENTS.md':'# Rules\n\nKeep this rule.\n', 'CLAUDE.md':'@AGENTS.md\n\n# Notes\n\nKeep client notes.\n'}
    parsed,report,_=d.parse(files)
    assert any(r['code']=='import_directive' for r in report)
    assert any('Keep client notes.' in m['content']['body'] for m in parsed['members'])
    body={'files':files,'portable':'','mode':'update','choices':{},'acknowledged':[d.k.digest(r) for r in report], 'expected_revision_id':revision.id}
    staged=run(engine,tmp_path,'documents.stage',payload(body),'instructions-unknown')
    assert not staged['draft_id']
    assert any(r['code']=='identity_choice_required' for r in staged['report'])


def test_malformed_input_is_retained_without_partial_draft(migrated_database,tmp_path):
    from my_harness.storage.knowledge_exchange import get
    engine,repo,project,revision=world(migrated_database[0],tmp_path)
    malformed='{"selected": "raw synthetic bytes", "selected": 2}'
    result=run(engine,tmp_path,'documents.stage',{'payload':malformed},'malformed')
    assert not result['draft_id'] and result['report'][0]['blocking']
    with Session(engine) as session:
        assert get(session,project,result['record_id']).payload['raw_payload']==malformed
    assert repo.revision(project)==revision


def test_owned_project_cannot_enter_legacy_documentary_workflows(migrated_database,tmp_path):
    from my_harness.storage.knowledge_exchange import require_documentary_lane
    from my_harness.storage.managed import Conflict
    root=tmp_path/'checkout';root.mkdir();LocalGit(root).run('init')
    engine,_,project,_=world(migrated_database[0],root)
    prepare_export(engine,root,project)
    with Session(engine) as session,pytest.raises(Conflict): require_documentary_lane(session,root)


from test_structured_intake_review import structured_profile


@pytest.mark.parametrize('profile_first',[True,False])
def test_intake_export_continuation_keeps_profile_and_readiness_separate(structured_profile,profile_first):
    from test_structured_intake_review import response,stage as intake_stage
    from test_profile_proposals import preview as profile_preview,confirm as profile_confirm
    from my_harness.storage.models import PhaseRow,ConfigurationOperationRow
    from sqlalchemy import func,select
    w,cid=structured_profile
    data=response();_,turn=w.turn(cid,data,text='Synthetic owner message')
    intake_stage(w,cid,data,turn,'stage')
    if profile_first: profile_confirm(w,cid,profile_preview(w,cid))
    args={'conversation_id':cid,'expected_version':w.view(cid)['version']}
    shown=run(w.repo.engine,w.context.root,'intake.preview',args)
    adopted=run(w.repo.engine,w.context.root,'intake.adopt',{**args,'preview_sha256':shown['preview_sha256'],'reason':'Synthetic owner.'},'adopt')
    project=run(w.repo.engine,w.context.root,'knowledge.head',{})['knowledge_project_id']
    export=prepare_export(w.repo.engine,w.context.root,project)
    outcome=KnowledgeDelivery(w.repo.engine,w.context.root,project).execute(export['record_id'],export['preview_sha256'],IDENTITY)
    assert outcome['revision_id']==adopted['revision_id']
    after=profile_preview(w,cid,next(p for p in w.view(cid)['proposals'] if p['kind']=='profile'))
    assert after['ready'],after
    assert after['continuation']=='export_committed'
    if not profile_first: profile_confirm(w,cid,after)
    with Session(w.repo.engine) as session:
        assert session.scalar(select(func.count()).select_from(PhaseRow))==0
        assert session.scalar(select(func.count()).select_from(ConfigurationOperationRow))==0
    assert export['intake_binding']['conversation_id']==cid
    assert LocalGit(w.context.root).text('rev-list','--count','HEAD')==('2' if w.view(cid)['kind']=='onboarding' else '1')


def test_rich_instruction_bodies_and_mermaid_source_roundtrip(migrated_database,tmp_path):
    _,repo,project,revision=world(migrated_database[0],tmp_path)
    draft=repo.open_draft(project,revision.id)
    body='Keep the complete rule.\n\n## A heading within this body\n\n```sh\n# code\n```\n'
    repo.put(draft,'section','rules',section('Rules',body),document='instructions',root_position=0)
    mermaid=section('Graph','flowchart LR\n  A-->B\n');mermaid['format']='mermaid'
    repo.put(draft,'section','graph',mermaid,document='flows',root_position=0)
    repo.adopt(draft,revision.id,origin='owner_confirmed',actor=OWNER)
    data=d.snapshot(repo.revision(project));manifest=d.ownership(project,'en')
    files=d.render(data,manifest)
    assert '```mermaid\nflowchart' in files['docs/flows/knowledge.md']
    parsed,report,_=d.parse(files)
    assert not any(r['blocking'] for r in report)
    assert sorted(parsed['members'],key=lambda m:m['item_id'])==data['members']
    assert d.render(parsed,manifest)==files


def test_preserve_uncontained_document_is_explicit_and_keeps_full_content(migrated_database,tmp_path):
    engine,repo,project,revision=world(migrated_database[0],tmp_path)
    files=d.render(d.snapshot(revision),d.ownership(project,'en'))
    original=files['docs/ARCHITECTURE.md']+'\nUncontained prose with **meaning**.\n'
    files['docs/ARCHITECTURE.md']=original
    body={'files':files,'portable':'','mode':'update','choices':{},'acknowledged':[],
          'expected_revision_id':revision.id,'preserve':[{'path':'docs/ARCHITECTURE.md','document':'architecture','code':'imported-notes'}]}
    report=run(engine,tmp_path,'documents.stage',payload(body),'preservation-report')
    assert not report['draft_id']
    body['acknowledged']=[d.k.digest(r) for r in report['report'] if not r['blocking']]
    staged=run(engine,tmp_path,'documents.stage',payload(body),'preservation-stage')
    assert staged['draft_id'],staged
    preview=run(engine,tmp_path,'documents.preview',{'record_id':staged['record_id']})
    assert any(c['after'] and c['after']['content'].get('body')==original for c in preview['comparison']['items'])
    run(engine,tmp_path,'documents.adopt',{'record_id':staged['record_id'],'preview_sha256':preview['preview_sha256'],
        'expected_revision_id':revision.id,'reason':'Explicitly preserve uncontained source.'},'preservation-adopt')
    assert repo.revision(project).item('section','imported-notes','architecture').content['body']==original


def test_live_delivery_excludes_concurrent_recovery(migrated_database,tmp_path):
    root=tmp_path/'checkout';root.mkdir();LocalGit(root).run('init')
    engine,_,project,_=world(migrated_database[0],root)
    shown=prepare_export(engine,root,project);delivery=KnowledgeDelivery(engine,root,project)
    seen=[]
    def overlapping(_):
        with pytest.raises(ValueError,match='writer_active'):
            KnowledgeDelivery(engine,root,project).execute(shown['record_id'],shown['preview_sha256'],IDENTITY,writer_stopped=True)
        seen.append(True)
    assert delivery.execute(shown['record_id'],shown['preview_sha256'],IDENTITY,after_write=overlapping)['status']=='COMPLETED'
    assert seen


def test_assume_unchanged_does_not_hide_dirty_owned_target(migrated_database,tmp_path):
    root=tmp_path/'checkout';root.mkdir();git=LocalGit(root);git.run('init')
    engine,_,project,_=world(migrated_database[0],root)
    shown=prepare_export(engine,root,project)
    KnowledgeDelivery(engine,root,project).execute(shown['record_id'],shown['preview_sha256'],IDENTITY)
    git.run('update-index','--assume-unchanged','docs/SPECIFICATION.md')
    (root/'docs/SPECIFICATION.md').write_text('Hidden uncommitted bytes must survive.')
    assert not git.run('status','--porcelain')
    with pytest.raises(ValueError,match='dirty_target'): disk_baseline(root,shown['files'])
    assert (root/'docs/SPECIFICATION.md').read_text()=='Hidden uncommitted bytes must survive.'


def test_concurrent_import_previews_have_only_one_winner(migrated_database,tmp_path):
    from my_harness.services.domain_operations import DomainRefusal
    engine,repo,project,revision=world(migrated_database[0],tmp_path)
    files=d.render(d.snapshot(revision),d.ownership(project,'en'))
    files['docs/SPECIFICATION.md']=files['docs/SPECIFICATION.md'].replace('Users can sign in.','Changed requirement.')
    body={'files':files,'portable':'','mode':'update','choices':{},'acknowledged':[],'expected_revision_id':revision.id}
    a=run(engine,tmp_path,'documents.stage',payload(body),'first-stage')
    b=run(engine,tmp_path,'documents.stage',payload(body),'second-stage')
    previews=[run(engine,tmp_path,'documents.preview',{'record_id':r['record_id']}) for r in (a,b)]
    consents=[{'record_id':r['record_id'],'preview_sha256':p['preview_sha256'],'expected_revision_id':revision.id,'reason':'Exact concurrent preview.'} for r,p in zip((a,b),previews)]
    run(engine,tmp_path,'documents.adopt',consents[0],'first-consent')
    with pytest.raises(DomainRefusal): run(engine,tmp_path,'documents.adopt',consents[1],'second-consent')
    assert repo.revision(project).number==2


def test_documents_cannot_silently_discard_embedded_operational_fields(migrated_database,tmp_path):
    engine,repo,project,revision=world(migrated_database[0],tmp_path)
    files=d.render(d.snapshot(revision),d.ownership(project,'en'))
    meta=d.loads(files[d.META]);meta['members'][0]['grants']=[{'authority':'invented'}];files[d.META]=d.freeze(meta)
    report=run(engine,tmp_path,'documents.stage',payload({'files':files,'portable':'','mode':'update','choices':{},
        'acknowledged':[],'expected_revision_id':revision.id}),'embedded-grant')
    assert not report['draft_id'] and report['report'][0]['blocking']
    assert repo.revision(project)==revision


def test_portable_content_hash_is_checked_separately_from_envelope(migrated_database,tmp_path):
    _,_,_,revision=world(migrated_database[0],tmp_path)
    value=d.loads(d.portable(d.snapshot(revision),'en'))
    value['payload']['knowledge']['members'][0]['content_sha256']='0'*64
    value['sha256']=d.k.digest(value['payload'])
    with pytest.raises(ValueError,match='content_integrity'):d.parse_portable(d.freeze(value))


def test_delivery_key_cannot_be_reused_for_different_consent(migrated_database,tmp_path):
    root=tmp_path/'checkout';root.mkdir();LocalGit(root).run('init')
    engine,_,project,_=world(migrated_database[0],root);shown=prepare_export(engine,root,project)
    service=KnowledgeDelivery(engine,root,project)
    result=service.execute(shown['record_id'],shown['preview_sha256'],IDENTITY,key='same-key')
    assert service.execute(shown['record_id'],shown['preview_sha256'],IDENTITY,key='same-key')==result
    with pytest.raises(ValueError,match='idempotency_conflict'):
        service.execute(shown['record_id'],shown['preview_sha256'],IDENTITY,key='same-key',writer_stopped=True)


def test_http_preview_replay_does_not_recapture_changed_disk(migrated_database,tmp_path):
    from session_client import TestClient
    from my_harness.api.app import create_app
    from test_managed_api import config,make_context,LOCAL
    root=tmp_path/'checkout';root.mkdir();LocalGit(root).run('init')
    engine,_,_,_=world(migrated_database[0],root)
    app=create_app(migrated_database[0],tmp_path/'ui',managed=config(make_context(root)))
    base='/api/managed/projects/synthetic/knowledge/documents'
    headers={'X-My-Harness':'1','Idempotency-Key':'lost-preview'}
    with TestClient(app,base_url=LOCAL) as http:
        first=http.post(base+'/ownership/preview',json={'wrappers':[]},headers=headers)
        assert first.status_code==200,first.text
        (root/'unrelated.txt').write_text('Synthetic later uncommitted edit.')
        replay=http.post(base+'/ownership/preview',json={'wrappers':[]},headers=headers)
        assert replay.status_code==200,replay.text
        assert replay.json()['result']['replayed']
        assert first.json()['result']['record_id']==replay.json()['result']['record_id']
        changed=http.post(base+'/ownership/preview',json={'wrappers':['claude']},headers=headers)
        assert changed.status_code==409
