"""H6.2 E3: viewer reads (tree and images), base hash CAS and regeneration of blocks edited locally.

Temporary Git/SQLite and fake agents, no providers. Builds on the v2 world of `test_documents`.
"""
import os

import pytest

from my_harness.core.engine.document_ops import BaseChanged, text_hash
from my_harness.core.engine.journal import JournalError
from my_harness.storage.managed import Conflict
from test_documents import (  # noqa: F401  (fixtures)
    PLAN_P001, STATE, STATE_BEGIN, STATE_END, confirm, edit_view, editor, queue_edit, text, v2, v2checkout,
)
from test_managed import repository  # noqa: F401  (fixture)
from test_managed_api import VERSIONS, client, git
from test_phases import head

PNG = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
                    '1f15c4890000000d49444154789c63000100000500010d0a2db40000000049454e44ae426082')


def test_content_edit_compares_the_base_hash_the_editor_opened(v2):
    v2.create_v2()
    spec = text(v2, 'docs/SPECIFICATION.md')
    change = {'path': 'docs/SPECIFICATION.md', 'content': '# Especificación\n\nEditada.\n', 'base_sha256': text_hash(spec)}
    view = edit_view(v2, changes=[change])
    assert [doc['before_sha256'] for doc in view['documents']] == [text_hash(spec)]
    # Another writer changes the document and commits it: the editor no longer has the base.
    v2.context.path('docs/SPECIFICATION.md').write_text('# Externa\n', encoding='utf-8')
    git(v2.context.root, 'commit', '-qam', 'external edit')
    with pytest.raises(Conflict, match='changed since it was opened') as caught:
        edit_view(v2, changes=[change])
    assert isinstance(caught.value.__cause__, BaseChanged)
    before = head(v2)
    with pytest.raises(Conflict, match='changed since it was opened'):
        queue_edit(v2, changes=[change], view=view)
    assert head(v2) == before and text(v2, 'docs/SPECIFICATION.md') == '# Externa\n'
    # null: new document that must not exist; without the field nothing is compared (previous contract).
    new = {'path': 'docs/research/nota.md', 'content': '# Nota\n', 'base_sha256': None}
    assert [doc['before_sha256'] for doc in edit_view(v2, changes=[new])['documents']] == [None]
    with pytest.raises(Conflict, match='changed since it was opened'):
        edit_view(v2, changes=[{**new, 'path': 'docs/ARCHITECTURE.md'}])
    assert edit_view(v2, changes=[{key: change[key] for key in ('path', 'content')}])['documents']


def forge_block(world, prose='Nota escrita en el editor.'):
    local = STATE.replace('Sin notas todavía.', prose).replace(f'{STATE_BEGIN}\n', f'{STATE_BEGIN}\nforged\n')
    world.context.path('docs/STATE.md').write_text(local, encoding='utf-8')
    return local


def test_regenerate_keeps_local_prose_restores_blocks_and_adopts(v2):
    pid = v2.create_v2()
    local = forge_block(v2)
    with pytest.raises(Conflict, match='managed blocks are generated'):
        edit_view(v2, 'worktree')
    view = editor(v2).preview(v2.context, v2.ports.writer(v2.context, VERSIONS), source='worktree', changes=None,
                              regenerate_blocks=True)
    expected = STATE.replace('Sin notas todavía.', 'Nota escrita en el editor.')
    [doc] = view['documents']
    assert doc['content'] == expected and doc['before_sha256'] == text_hash(STATE)
    assert doc['disk_sha256'] == text_hash(local)
    [regenerated] = view['regenerated']
    assert regenerated['path'] == 'docs/STATE.md' and '-forged' in regenerated['diff']
    assert 'forged' not in view['diff'] and '+Nota escrita en el editor.' in view['diff']
    assert text(v2, 'docs/STATE.md') == local  # the preview does not write
    job = editor(v2).submit(v2.context, key='regen', versions=VERSIONS, preview_sha256=view['preview_sha256'],
                            reason='Regenerar bloques', confirmed=True, git=v2.ports.writer(v2.context, VERSIONS),
                            source='worktree', changes=None, regenerate_blocks=True)
    v2.run()
    assert v2.repository.get_run(job.run_id).status == 'COMMITTED'
    assert text(v2, 'docs/STATE.md') == expected and git(v2.context.root, 'status', '--porcelain') == ''
    detail = v2.get(pid)
    assert detail['documents']['drift'] == []
    assert detail['operations'][-1]['result']['adopted'] == {'docs/STATE.md': text_hash(expected)}


def test_regenerate_without_a_hash_mismatch_or_markers_is_refused(v2):
    v2.create_v2()
    writer = v2.ports.writer(v2.context, VERSIONS)
    v2.context.path('docs/STATE.md').write_text(STATE.replace('Sin notas todavía.', 'Solo prosa.'), encoding='utf-8')
    with pytest.raises(Conflict, match='No local change touches a managed block'):
        editor(v2).preview(v2.context, writer, source='worktree', changes=None, regenerate_blocks=True)
    v2.context.path('docs/STATE.md').write_text(STATE.replace(f'{STATE_END}\n', ''), encoding='utf-8')
    with pytest.raises(Conflict, match='restore the markers by hand'):
        editor(v2).preview(v2.context, writer, source='worktree', changes=None, regenerate_blocks=True)
    with pytest.raises(Conflict, match='Only a worktree edit'):
        editor(v2).preview(v2.context, writer, source='content', changes=[{'path': 'README.md', 'content': 'x'}],
                           regenerate_blocks=True)


def test_regenerate_never_overwrites_bytes_changed_after_the_preview(v2):
    v2.create_v2()
    forge_block(v2)
    view = editor(v2).preview(v2.context, v2.ports.writer(v2.context, VERSIONS), source='worktree', changes=None,
                              regenerate_blocks=True)
    job = editor(v2).submit(v2.context, key='regen-late', versions=VERSIONS, preview_sha256=view['preview_sha256'],
                            reason='Regenerar', confirmed=True, git=v2.ports.writer(v2.context, VERSIONS),
                            source='worktree', changes=None, regenerate_blocks=True)
    later = forge_block(v2, 'Otra nota posterior.')
    before = head(v2)
    v2.run()
    assert v2.repository.get_run(job.run_id).status == 'STOPPED'
    assert text(v2, 'docs/STATE.md') == later and head(v2) == before


def test_regenerate_recovers_after_a_crash_between_document_write_and_commit(v2, monkeypatch):
    from my_harness.adapters.git import GitWorkspace
    v2.create_v2()
    forge_block(v2)
    view = editor(v2).preview(v2.context, v2.ports.writer(v2.context, VERSIONS), source='worktree', changes=None,
                              regenerate_blocks=True)
    job = editor(v2).submit(v2.context, key='regen-crash', versions=VERSIONS, preview_sha256=view['preview_sha256'],
                            reason='Regenerar', confirmed=True, git=v2.ports.writer(v2.context, VERSIONS),
                            source='worktree', changes=None, regenerate_blocks=True)
    original = GitWorkspace.execute

    def crash(self, context, intent):
        raise RuntimeError('synthetic crash after writing documents')
    monkeypatch.setattr(GitWorkspace, 'execute', crash)
    with pytest.raises((RuntimeError, JournalError), match='synthetic'):
        v2.run()
    expected = view['documents'][0]['content']
    assert text(v2, 'docs/STATE.md') == expected  # written, no commit
    monkeypatch.setattr(GitWorkspace, 'execute', original)
    confirm(v2, job)
    resumed = editor(v2).preview(v2.context, v2.ports.writer(v2.context, VERSIONS), source='worktree', changes=None,
                                 regenerate_blocks=True)
    assert resumed['resume_operation_id'] is not None and resumed['preview_sha256'] == view['preview_sha256']
    again = editor(v2).submit(v2.context, key='regen-resume', versions=VERSIONS,
                              preview_sha256=resumed['preview_sha256'], reason='Reanudar', confirmed=True,
                              git=v2.ports.writer(v2.context, VERSIONS), source='worktree', changes=None,
                              regenerate_blocks=True, resume_operation_id=resumed['resume_operation_id'])
    assert again.run_id == job.run_id
    v2.run()
    assert v2.repository.get_run(again.run_id).status == 'COMMITTED'
    assert text(v2, 'docs/STATE.md') == expected and git(v2.context.root, 'status', '--porcelain') == ''


def test_tree_lists_markdown_without_links_hidden_folders_or_other_files(v2):
    v2.create_v2()
    root = v2.context.root
    (root / 'docs/archive/phase-001').mkdir(parents=True)
    (root / 'docs/archive/phase-001/STATE.md').write_text('# Archivado\n')
    (root / 'docs/.hidden').mkdir()
    (root / 'docs/.hidden/secret.md').write_text('# Oculto\n')
    (root / 'docs/img.png').write_bytes(PNG)
    (root / 'docs/flows').mkdir()
    (root / 'docs/flows/tareas.md').write_text('# Flujo de tareas\n')
    os.symlink(root / 'docs/STATE.md', root / 'docs/enlace.md')
    tree = editor(v2).tree(v2.context)
    paths = {item['path']: item for item in tree['files']}
    assert paths['README.md']['kind'] == 'product' and paths['docs/STATE.md']['kind'] == 'phase'
    assert paths['docs/DDBB-DIAGRAM.md']['kind'] == 'product'  # D088
    assert paths['docs/flows/tareas.md'] == {
        'path': 'docs/flows/tareas.md', 'kind': 'other', 'editable': True, 'archived': False,
        'bytes': len(text(v2, 'docs/flows/tareas.md').encode())}
    assert paths['docs/archive/phase-001/STATE.md']['kind'] == 'archive'
    assert paths['docs/archive/phase-001/STATE.md']['editable'] is False
    assert not {'docs/.hidden/secret.md', 'docs/img.png', 'docs/enlace.md'} & set(paths)
    assert tree['skipped'] == ['docs/enlace.md'] and tree['truncated'] is False


def test_http_tree_image_and_cas_conflict(v2, tmp_path):
    from my_harness.services.managed_runtime import ManagedConfig, ManagedProject
    v2.create_v2()
    root = v2.context.root
    (root / 'docs/img').mkdir()
    (root / 'docs/img/uno.png').write_bytes(PNG)
    (root / 'docs/img/hostil.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>')
    (root / 'docs/img/notas.txt').write_text('no es imagen')
    (root / 'docs/img/enorme.png').write_bytes(b'\0' * (8 * 1024 * 1024 + 1))
    os.symlink(root / 'docs/img/uno.png', root / 'docs/img/enlace.png')
    (root / 'docs/img/dos.png').write_bytes(PNG)
    os.link(root / 'docs/img/dos.png', root / 'docs/img/duro.png')
    os.symlink(root / 'docs/img', root / 'docs/carpeta')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'images')
    configuration = ManagedConfig((ManagedProject('synthetic', v2.context, VERSIONS),),
                                  ports_factory=v2.ports, commit_factory=v2.ports.writer, supervisor=False)
    with client(str(v2.repository.engine.url), tmp_path, configuration) as http:
        base = '/api/managed/projects/synthetic/documents'
        tree = http.get(f'{base}/tree')
        assert tree.status_code == 200 and 'docs/carpeta' in tree.json()['skipped']
        image = http.get(f'{base}/image', params={'path': 'docs/img/uno.png'})
        assert image.status_code == 200 and image.content == PNG and image.headers['content-type'] == 'image/png'
        assert 'sandbox' in image.headers['content-security-policy']
        assert image.headers['x-content-type-options'] == 'nosniff'
        svg = http.get(f'{base}/image', params={'path': 'docs/img/hostil.svg'})
        assert svg.status_code == 200 and svg.headers['content-type'] == 'image/svg+xml'
        assert "default-src 'none'" in svg.headers['content-security-policy']
        for path, status in (('docs/img/notas.txt', 404), ('docs/img/enlace.png', 404), ('docs/carpeta/uno.png', 404),
                             ('docs/img/duro.png', 404), ('.git/x.png', 404), ('docs/img/falta.png', 404),
                             ('../fuera.png', 422), ('/etc/x.png', 422), ('docs/img/enorme.png', 422)):
            assert http.get(f'{base}/image', params={'path': path}).status_code == status, path
        spec = http.get(f'{base}/content', params={'path': 'docs/SPECIFICATION.md'}).json()
        body = {'source': 'content', 'changes': [{'path': spec['path'], 'content': '# Nueva\n', 'base_sha256': '0' * 64}]}
        conflict = http.post(f'{base}/edit/preview', json=body)
        assert conflict.status_code == 409 and conflict.json()['detail']['code'] == 'document_changed'
        body['changes'][0]['base_sha256'] = spec['sha256']
        assert http.post(f'{base}/edit/preview', json=body).status_code == 200
        bad = {**body, 'changes': [{**body['changes'][0], 'base_sha256': 'nope'}]}
        assert http.post(f'{base}/edit/preview', json=bad).status_code == 422
        regen = http.post(f'{base}/edit/preview', json={'source': 'worktree', 'regenerate_blocks': True})
        assert regen.status_code == 409  # clean checkout: nothing to regenerate


@pytest.mark.parametrize('docs', ['docs', 'manual'])
def test_http_unified_document_classes_instructions_and_decision_register(v2, tmp_path, docs):
    """The API projects D088 also with a different configured documents folder."""
    from dataclasses import replace
    from my_harness.services.managed_runtime import ManagedConfig, ManagedProject

    root = v2.context.root
    if docs != 'docs':
        (root / 'docs').rename(root / docs)
    context = replace(v2.context, state_file=f'{docs}/STATE.md', next_steps_file=f'{docs}/NEXT_STEPS.md')
    for name in ('AGENTS.md', 'CLAUDE.md', 'GEMINI.md'):
        (root / name).write_text('# Instrucciones sintéticas\n', encoding='utf-8')
    for folder in ('flows', 'phase'):
        (root / docs / folder).mkdir(exist_ok=True)
        (root / docs / folder / 'tareas.md').write_text('# Tareas sintéticas\n', encoding='utf-8')
    (root / docs / 'DECISIONS.md').write_text(
        '# Decisiones\n\n## D007 — Persistencia sintética\n\nEstado: aceptada.\n', encoding='utf-8')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'synthetic document contract')
    before = git(root, 'rev-parse', 'HEAD')
    configuration = ManagedConfig((ManagedProject('synthetic', context, VERSIONS),),
                                  commit_factory=v2.ports.writer, supervisor=False)
    with client(str(v2.repository.engine.url), tmp_path, configuration) as http:
        base = '/api/managed/projects/synthetic/documents'
        response = http.get(base)
        assert response.status_code == 200, response.text
        status = response.json()
        assert status['decisions'] == [{'id': 'D007', 'title': 'Persistencia sintética', 'status': 'aceptada.'}]
        assert [folder['path'] for folder in status['folders']] == [f'{docs}/flows', f'{docs}/phase']
        documents = {document['path']: document for document in status['documents']}
        assert documents[f'{docs}/DDBB-DIAGRAM.md']['kind'] == 'diagram'
        for path in ('AGENTS.md', 'CLAUDE.md', 'GEMINI.md'):
            assert documents[path]['kind'] == 'instructions' and documents[path]['exists']
            assert documents[path]['adopted_sha256'] is None and not documents[path]['drift']
            assert http.get(base + '/content', params={'path': path}).json()['editable']
        response = http.get(base + '/tree')
        assert response.status_code == 200, response.text
        tree = {document['path']: document for document in response.json()['files']}
        assert tree[f'{docs}/flows/tareas.md']['kind'] == 'flow'
        assert tree[f'{docs}/phase/tareas.md']['kind'] == 'phase_work'
        assert tree[f'{docs}/DDBB-DIAGRAM.md']['kind'] == 'diagram'
        assert tree['AGENTS.md']['kind'] == 'instructions'
        # Neither reading nor classification follows links in the root instruction files.
        (root / 'CLAUDE.md').unlink()
        os.symlink(root / 'AGENTS.md', root / 'CLAUDE.md')
        linked = http.get(base + '/tree').json()
        assert 'CLAUDE.md' in linked['skipped']
        assert 'CLAUDE.md' not in {entry['path'] for entry in linked['files']}
        linked_status = http.get(base).json()
        assert next(entry for entry in linked_status['documents'] if entry['path'] == 'CLAUDE.md')['error']
        assert http.get(base + '/content', params={'path': 'CLAUDE.md'}).status_code == 422
        (root / 'CLAUDE.md').unlink()
        (root / 'CLAUDE.md').write_text('# Instrucciones sintéticas\n', encoding='utf-8')
    assert git(root, 'rev-parse', 'HEAD') == before
    assert git(root, 'status', '--porcelain') == ''


@pytest.mark.parametrize('path', ['AGENTS.md', 'CLAUDE.md', 'GEMINI.md'])
def test_http_instruction_edit_uses_confirmed_diff_and_cas(v2, tmp_path, path):
    from my_harness.services.managed_runtime import ManagedConfig, ManagedProject

    v2.context.path(path).write_text('# Instrucciones sintéticas\n', encoding='utf-8')
    git(v2.context.root, 'add', '-A')
    git(v2.context.root, 'commit', '-qm', 'synthetic instructions')
    pid = v2.create_v2()
    configuration = ManagedConfig((ManagedProject('synthetic', v2.context, VERSIONS),),
                                  ports_factory=v2.ports, commit_factory=v2.ports.writer, supervisor=False)
    with client(str(v2.repository.engine.url), tmp_path, configuration) as http:
        base = '/api/managed/projects/synthetic/documents'
        current = http.get(base + '/content', params={'path': path}).json()
        body = {'source': 'content', 'changes': [{'path': path, 'content': current['content'] + '\nRegla confirmada.\n',
                                                'base_sha256': current['sha256']}]}
        shown = http.post(base + '/edit/preview', json=body)
        assert shown.status_code == 200, shown.text
        body.update(preview_sha256=shown.json()['preview_sha256'], confirmed=True, reason='Synthetic instruction edit')
        queued = http.post(base + '/edit', json=body, headers={'Idempotency-Key': 'instruction-edit'})
        assert queued.status_code == 202, queued.text
        v2.run()
        assert v2.repository.get_run(queued.json()['run_id']).status == 'COMMITTED'
        assert text(v2, path).endswith('Regla confirmada.\n')
        assert http.post(base + '/edit/preview', json={'source': 'content', 'changes': body['changes']}).status_code == 409
        assert v2.get(pid)['documents']['drift'] == []
