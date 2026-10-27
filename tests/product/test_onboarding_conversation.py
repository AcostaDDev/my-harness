"""P008-T014: synthetic repositories, temporary SQLite/Git and a fake reviewer; no real provider."""
from dataclasses import replace
import json
import re
import stat

import pytest
from sqlalchemy.orm import Session

from my_harness.core.engine.definition import KINDS
from my_harness.services.managed import LocalSupervisor
from my_harness.services.managed_runtime import ManagedConfig, ManagedProject
from my_harness.storage.database import make_engine
from my_harness.storage.models import PlanningConversationRow
from my_harness.storage.onboarding import OnboardingDrafts
from my_harness.storage.managed import Conflict
from onboarding_helpers import World as ImportWorld, answer, tree_state
from test_managed_api import VERSIONS, Ports, client, make_context
from test_project_onboarding import DJANGO, TYPESCRIPT, checkout, git

DIAGRAM = '''# Modelo observado

Fuente: library/models.py. Claves implícitas de Django descritas por inferencia, no inventadas en el inventario.
```mermaid
erDiagram
    Author {
        string name
    }
    Book {
        string title
    }
    Author ||--o{ Book : author
    Author }o--o{ Book : editors
```
'''
DRAFTS = {
    'docs/ARCHITECTURE.md': '# Arquitectura\n\nDjango: library/models.py, library/urls.py y library/views.py.\n',
    'docs/DDBB-DIAGRAM.md': DIAGRAM,
    'docs/SPECIFICATION.md': '# Especificación\n\nConsultas de libros observadas en library/urls.py.\n',
    'docs/flows/books.md': '# Libros\n\n```mermaid\nflowchart LR\n  urls --> views\n```\n',
    'docs/ROADMAP.md': '# Roadmap\n\n## P001 — Continuidad\n\n**Objetivo:** Por confirmar.\n',
    'docs/STATE.md': '# Estado\n\n## Base acumulada\n\nBiblioteca Django existente.\n\n## Fase activa — P001 Continuidad\n',
    'docs/NEXT_STEPS.md': '# P001 — Continuidad\n\nPendiente de concretar con el usuario.\n',
    'docs/DECISIONS.md': '# Decisiones\n\n## D001 — Django\n\nEstado: inferida del código.\n\nFuente: pyproject.toml.\n',
    'AGENTS.md': '# Reglas\n\nLeer docs/STATE.md y docs/NEXT_STEPS.md antes de trabajar.\n',
    'CLAUDE.md': '@AGENTS.md\n', 'GEMINI.md': '@AGENTS.md\n',
}


class World(ImportWorld):
    def create(self, **kwargs):
        return self.planning.create(self.context, kind='onboarding', title='Synthetic library', writer=self.writer,
                                    **kwargs)

    def area(self, cid):
        return OnboardingDrafts.of(self.engine, cid).base


@pytest.fixture
def world(migrated_database, tmp_path):
    engine = make_engine(migrated_database[0])
    yield World(checkout(tmp_path / 'django', DJANGO), engine)
    engine.dispose()


def test_django_reverse_engineering_is_pinned_read_only_and_private(world):
    before = tree_state(world.context.root)
    cid = world.create(key='create')
    assert world.create(key='create') == cid
    with Session(world.engine) as session:
        source = session.get(PlanningConversationRow, cid).source
    assert world.view(cid)['source']['inventory_sha256'] == source['inventory']['inventory_sha256']
    assert [e['name'] for e in source['inventory']['entities']] == ['Author', 'Book']
    assert source['inventory']['profile_proposal']['requires_confirmation']
    head = world.view(cid)['source']['head']

    def reviewer(context, request):
        assert context.root != world.context.root and not (context.root / '.git').exists()
        assert (context.root / 'library/models.py').read_text() == DJANGO['library/models.py']
        assert stat.S_IMODE((context.root / 'library/models.py').stat().st_mode) == 0o444
        assert 'AbstractRecord' in (context.root / 'library/models.py').read_text()
        assert head in request.prompt and 'library.Author' in request.prompt
        assert 'inferred from code' in request.prompt
        assert 'ask a blocking question' in request.prompt
        return answer(DRAFTS, questions=[{'text': '¿Qué trabajo debe cubrir P001?', 'blocking': True}])

    job, turn = world.turn(cid, reviewer)
    assert turn['status'] == 'ANSWERED', turn
    assert tree_state(world.context.root) == before
    assert not world.area(cid).exists()
    request = world.repo.get_run(job.run_id).history.attempts[0].request
    assert request.role == 'definition'
    assert json.loads(request.prompt_snapshot_json)['parts'][0]['version']['name'] == 'onboard-project'
    assert 'project_instructions' not in json.loads(request.prompt_snapshot_json)
    assert not list((world.area(cid).parent.parent / 'chat-snapshots').iterdir())
    assert world.view(cid)['questions'][0]['blocking']
    world.apply_all(cid)
    assert tree_state(world.context.root) == before
    actual = (world.area(cid) / 'docs/DDBB-DIAGRAM.md').read_text()
    # The persisted document matches the concrete entities and relations of the sealed inventory.
    assert re.findall(r'^    (\w+) \{', actual, re.M) == [e['name'] for e in source['inventory']['entities']]
    assert re.findall(r'^    Author ([|o}{-]+) Book : (\w+)$', actual, re.M) == [
        ('||--o{', 'author'), ('}o--o{', 'editors')]
    assert re.findall(r'^    Author [|o}{-]+ Book : (\w+)$', actual, re.M) == [
        r['field'] for r in source['inventory']['relationships']]
    assert 'AbstractRecord' not in actual
    assert world.view(cid)['actions'] == ['message', 'edit_draft', 'defer_question']
    assert stat.S_IMODE(world.area(cid).stat().st_mode) == 0o700
    assert (world.context.root / 'README.md').read_text() == DJANGO['README.md']


@pytest.mark.parametrize('response', [
    {}, answer({'library/models.py': '# Illegal\n'}), answer({'../README.md': '# Illegal\n'}),
    answer({'docs/flows/../ARCHITECTURE.md': '# Illegal\n'}), answer({'README.md': '\0'}),
])
def test_invalid_turn_fails_without_fallback(world, response):
    before = tree_state(world.context.root)
    cid = world.create()
    _, turn = world.turn(cid, response)
    assert turn['status'] == 'FAILED'
    assert len(world.ports.agents.requests) == 1 and not world.view(cid)['proposals']
    assert tree_state(world.context.root) == before


def test_frozen_head_survives_live_changes_after_queue(world):
    cid = world.create()
    job = world.message(cid)
    old = world.planning.snapshot(job.run_id)['context']['head']
    (world.context.root / 'library/models.py').write_text('class Changed: pass\n')
    git(world.context.root, 'add', '.')
    git(world.context.root, 'commit', '-qm', 'Synthetic later head')
    (world.context.root / 'README.md').write_text('Local dirty README\n')

    def reviewer(context, request):
        assert (context.root / 'library/models.py').read_text() == DJANGO['library/models.py']
        assert old in request.prompt
        return answer({})

    world.ports.agents.responses.append(reviewer)
    assert world.worker.run_once().status == 'DONE'
    assert world.view(cid)['turns'][-1]['status'] == 'ANSWERED'
    assert (world.context.root / 'README.md').read_text() == 'Local dirty README\n'


@pytest.mark.parametrize('mutate', ['code', 'draft'])
def test_modification_during_turn_discards_result(world, mutate):
    cid = world.create()

    def reviewer(context, request):
        if mutate == 'code':
            path = context.root / 'library/models.py'
            path.chmod(0o644)
            path.write_text('changed\n')
        else:
            world.area(cid).mkdir(parents=True)
            (world.area(cid) / 'AGENTS.md').write_text('# External edit\n')
        return answer(DRAFTS)

    _, turn = world.turn(cid, reviewer)
    assert turn['status'] == 'FAILED' and not world.view(cid)['proposals']
    assert 'changed during a read-only turn' in turn['result']['reasons'][0]


def test_changed_drafts_before_invocation_prevent_call_and_cas_preserves_edits(world):
    cid = world.create()
    world.message(cid)
    world.area(cid).mkdir(parents=True)
    (world.area(cid) / 'AGENTS.md').write_text('# External\n')
    assert world.worker.run_once().status == 'DONE'
    assert world.ports.roles() == []
    assert world.view(cid)['turns'][-1]['status'] == 'FAILED'
    world.turn(cid, answer({'AGENTS.md': '# Proposed\n'}))
    p = world.view(cid)['proposals'][-1]
    world.planning.edit_draft(world.context, cid, world.view(cid)['version'], path='AGENTS.md', content='# User\n',
                              base_sha256=p['base_sha256'], writer=None)
    with pytest.raises(Conflict, match='user edit is preserved'):
        world.planning.apply(world.context, cid, p['id'], world.view(cid)['version'],
                             proposal_sha256=p['proposal_sha256'], confirmed=True, writer=None)
    assert (world.area(cid) / 'AGENTS.md').read_text() == '# User\n'
    job, _ = world.turn(cid, answer({}))
    assert '# User' in world.repo.get_run(job.run_id).history.attempts[0].request.prompt


def test_existing_readme_only_changes_private_draft_after_confirmation(world):
    cid = world.create()
    world.turn(cid, answer({'README.md': '# Replacement\n'}))
    p = world.view(cid)['proposals'][0]
    with pytest.raises(ValueError, match='confirmation'):
        world.planning.apply(world.context, cid, p['id'], world.view(cid)['version'],
                             proposal_sha256=p['proposal_sha256'], confirmed=False, writer=None)
    world.apply_all(cid)
    assert (world.area(cid) / 'README.md').read_text() == '# Replacement\n'
    assert (world.context.root / 'README.md').read_text() == DJANGO['README.md']


def test_missing_objects_fail_without_agent_or_fallback(world):
    cid = world.create()
    job = world.message(cid)
    head = world.view(cid)['source']['head']
    obj = world.context.root / '.git/objects' / head[:2] / head[2:]
    obj.unlink()
    from my_harness.adapters.git import GitError
    with pytest.raises(GitError):
        world.worker.run_once()
    assert world.ports.roles() == []
    claim = world.repo.get_job(job.id)
    world.repo.confirm_stopped(job.id, owner_token=claim.owner_token,
                              expected_version=world.repo.get_run(job.run_id).version, reason='Synthetic worker stopped')
    assert world.view(cid)['turns'][-1]['status'] == 'UNKNOWN'


def test_onboarding_requires_existing_unmanaged_git(world):
    for kwargs in ({'brief': '# Brief'}, {'phase_id': 'x'}):
        with pytest.raises(ValueError, match='no brief or phase'):
            world.create(**kwargs)
    (world.context.root / 'docs').mkdir()
    (world.context.root / 'docs/STATE.md').write_text('# Already managed\n')
    git(world.context.root, 'add', '.')
    git(world.context.root, 'commit', '-qm', 'Synthetic harness docs')
    with pytest.raises(Conflict, match='support has been removed'):
        world.create()
    assert KINDS['onboarding'] == ('onboard-project', 'definition')


def test_http_onboarding_and_private_cas(migrated_database, tmp_path):
    root = checkout(tmp_path / 'typescript', TYPESCRIPT)
    context = replace(make_context(root), documents='v2')
    ports = Ports([answer({'docs/ARCHITECTURE.md': '# TypeScript\n'})])
    config = ManagedConfig((ManagedProject('web', context, VERSIONS),), ports_factory=ports,
                           commit_factory=ports.writer, supervisor=False)
    before = tree_state(root)
    with client(migrated_database[0], tmp_path, config) as http:
        base = '/api/managed/projects/web/planning'
        body = {'kind': 'onboarding', 'title': 'Synthetic web'}
        created = http.post(base, json=body, headers={'Idempotency-Key': 'onboarding'})
        assert created.status_code == 201, created.text
        cid = created.json()['id']
        assert http.post(base, json=body, headers={'Idempotency-Key': 'onboarding'}).json()['id'] == cid
        sent = http.post(base + f'/{cid}/messages', json={'expected_version': 0, 'text': 'Describe el código'},
                         headers={'Idempotency-Key': 'turn'})
        assert sent.status_code == 202, sent.text
        engine = make_engine(migrated_database[0])
        worker = LocalSupervisor(World(root, engine).repo, ports, commit_factory=ports.writer)
        assert worker.run_once().status == 'DONE'
        detail = http.get(base + f'/{cid}').json()
        assert detail['turns'][0]['status'] == 'ANSWERED'
        run = http.get('/api/managed/runs/' + detail['turns'][0]['run_id'])
        assert run.status_code == 200 and run.json()['purpose'] == 'onboarding'
        p = detail['proposals'][0]
        applied = http.post(base + f"/{cid}/proposals/{p['id']}/apply", json={
            'expected_version': detail['version'], 'proposal_sha256': p['proposal_sha256'], 'confirmed': True})
        assert applied.status_code == 200, applied.text
        assert http.get(base + f'/{cid}/drafts/content', params={'path': p['path']}).json()['content'] == '# TypeScript\n'
        assert http.get(base + f'/{cid}/drafts').json()['drafts'][0]['path'] == p['path']
        engine.dispose()
    assert tree_state(root) == before


def test_codex_exported_onboarding_uses_read_only_role_without_git_metadata(tmp_path):
    from my_harness.adapters.cli_agents import CLIConfig, argv_for
    from my_harness.core.engine.contracts import AgentRequest, Selection, context_snapshot
    origin = make_context(tmp_path)
    export = tmp_path / 'export'
    export.mkdir()
    request = AgentRequest('id', 'definition', Selection('m', 'low', 'reason'), 'prompt', None, context_snapshot(origin))
    cfg = CLIConfig('codex', ('/synthetic/codex',), '0.164.0', (), 1)
    argv = argv_for(cfg, replace(origin, root=export), request)
    assert '--skip-git-repo-check' in argv
    assert argv[argv.index('--sandbox') + 1] == 'read-only'
    assert 'project_doc_max_bytes=0' in argv
    assert '--skip-git-repo-check' not in argv_for(cfg, origin, request)


def test_interrupted_export_is_cleaned_only_after_writer_confirmed_stopped(world, monkeypatch):
    from my_harness.adapters.chat_snapshot import HeadSnapshot, snapshot_path
    cid = world.create()
    job = world.message(cid)

    def partial(self, head, destination):
        destination.mkdir()
        (destination / 'partial').write_text('Synthetic partial export\n')
        raise OSError('Synthetic export interruption')

    monkeypatch.setattr(HeadSnapshot, 'export', partial)
    with pytest.raises(OSError, match='interruption'):
        world.worker.run_once()
    claim = world.repo.get_job(job.id)
    path = snapshot_path(world.repo, claim)
    assert path.exists() and world.ports.roles() == []
    assert world.repo.claim() is None
    world.repo.confirm_stopped(job.id, owner_token=claim.owner_token,
                              expected_version=world.repo.get_run(job.run_id).version, reason='Synthetic worker dead')
    assert not path.exists() and world.view(cid)['turns'][-1]['status'] == 'UNKNOWN'
    assert world.repo.claim() is None


def test_question_defer_and_answer_are_explicit_and_contextual(world):
    cid = world.create()
    world.turn(cid, answer({}, questions=[{'text': '¿Cuál es el objetivo de P001?', 'blocking': True}]))
    question = world.view(cid)['questions'][0]
    world.planning.defer(cid, world.view(cid)['version'], question_id=question['id'], reason='Se decide al incorporar')
    assert world.view(cid)['questions'][0]['deferred']['reason'] == 'Se decide al incorporar'
    job, turn = world.turn(cid, answer({}), text='P001 debe documentar el estado actual')
    context = world.planning.snapshot(job.run_id)['context']
    assert context['questions'][0]['deferred'] is not None
    assert world.view(cid)['questions'] == [] and turn['status'] == 'ANSWERED'


def test_context_size_is_bounded(world, monkeypatch):
    from my_harness.storage import onboarding
    cid = world.create()
    monkeypatch.setattr(onboarding, 'MAX_CONTEXT_DRAFT_BYTES', 1)
    with pytest.raises(ValueError, match='exceed'):
        world.message(cid)
    assert world.ports.roles() == []


def test_downgrade_cannot_drop_frozen_onboarding_source(world, migrated_database):
    from alembic import command
    cid = world.create()
    with pytest.raises(RuntimeError, match='cannot be represented'):
        command.downgrade(migrated_database[1], '0018_conversation_keys')
    with Session(world.engine) as session:
        assert session.get(PlanningConversationRow, cid).source['inventory']['head']
