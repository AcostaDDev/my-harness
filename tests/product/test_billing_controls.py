"""P001-T005b (D263): reference API and save-time billing validation.

Synthetic configuration, temporary SQLite and bundles built from the packaged pinned references only; no provider.
"""
import copy
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from session_client import TestClient
from my_harness.core.engine.metric_references import canonical, load_packaged_bundle, make_bundle
from my_harness.services.configuration import digest
from my_harness.storage.backup import RESTORED_USER_VERSION
from my_harness.storage.configuration import ConfigurationConflict
from my_harness.storage.models import MetricsReferenceRow
from test_configuration import activate, active_global, change, dumps, project_data, register, save, setup  # noqa: F401
from test_configuration_api import BASE, LOCAL, app_for
from test_usage_accounting import CLAUDE_API, CODEX_CREDITS, PACKAGED, billing_data

REFERENCES = BASE + '/references'


def claude_only():
    """A distinct valid bundle: the packaged Claude references alone."""
    bundle = make_bundle([ref for ref in load_packaged_bundle().references if ref.document()['provider'] == 'claude'])
    return bundle.id, canonical(bundle.envelope()).decode('utf-8')


def stored(repo):
    with Session(repo.managed.engine) as session:
        return session.scalar(select(func.count()).select_from(MetricsReferenceRow))


def refused(error):
    assert error.value.code == 'billing_configuration_refused'
    return error.value.details


# --- reference API ------------------------------------------------------------------------------


def test_reference_list_preview_and_idempotent_import(setup):
    repo, _, _ = setup
    identifier, content = claude_only()
    with TestClient(app_for(repo)) as http:
        listed = http.get(REFERENCES)
        assert listed.status_code == 200, listed.text
        [packaged] = listed.json()['items']
        assert (packaged['id'], packaged['source'], packaged['recorded_at']) == (PACKAGED, 'packaged', None)
        assert packaged['effective_period'] == 'unknown' and packaged['providers'] == ['claude', 'codex']
        credits = next(item for item in packaged['schemes'] if item['scheme'] == 'chatgpt_work_codex_credit')
        assert credits['bases'] == ['subscription_equivalent', 'token_credit']
        assert 'standard' in credits['conditions']['speed'] and 'eligibility' in credits['conditions']
        assert stored(repo) == 0  # listing never inserts the packaged rows

        preview = http.post(REFERENCES + '/preview', json={'content': content}, headers=LOCAL)
        assert preview.status_code == 200, preview.text
        report = preview.json()
        assert (report['bundle'], report['conflicts'], report['new_rows']) == (identifier, [], report['references'] + 1)
        stale = http.post(REFERENCES + '/import', json={'content': content, 'preview_sha256': '0' * 64}, headers=LOCAL)
        assert (stale.status_code, stale.json()['detail']['code']) == (409, 'stale_accounting_preview')
        body = {'content': content, 'preview_sha256': report['sha256']}
        first = http.post(REFERENCES + '/import', json=body, headers=LOCAL)
        assert first.status_code == 200, first.text
        assert first.json()['inserted_rows'] == report['new_rows']
        # A retried confirmation after the rows exist is the same sealed report with nothing inserted.
        again = http.post(REFERENCES + '/import', json=body, headers=LOCAL)
        assert again.status_code == 200, again.text
        assert (again.json()['sha256'], again.json()['inserted_rows'], again.json()['existing_rows']) == (
            report['sha256'], 0, report['new_rows'])
        assert repo.read('global')['saved'] is None  # an import is not a configuration revision

        page = http.get(REFERENCES, params={'limit': 1}).json()
        assert [item['id'] for item in page['items']] == [PACKAGED] and page['next_offset'] == 1
        imported = http.get(REFERENCES, params={'offset': 1}).json()
        assert [(item['id'], item['source'], item['providers']) for item in imported['items']] == [
            (identifier, 'import', ['claude'])] and imported['next_offset'] is None

        for bad, code in (('{"format": "metrics-reference-1"}', 'reference_bundle_invalid'),
                          (content.replace('"claude_api"', '"other_product"', 1), 'reference_bundle_invalid')):
            response = http.post(REFERENCES + '/preview', json={'content': bad}, headers=LOCAL)
            assert (response.status_code, response.json()['detail']['code']) == (422, code)
        assert http.post(REFERENCES + '/preview', json={'content': 'x' * 1048577}, headers=LOCAL).status_code == 422


def test_reference_list_works_on_a_restored_archive_and_mutations_are_refused(setup, monkeypatch):
    repo, _, _ = setup
    _, content = claude_only()
    with repo.managed.engine.begin() as connection:
        connection.exec_driver_sql(f'PRAGMA user_version={RESTORED_USER_VERSION}')
    monkeypatch.setattr('my_harness.api.app.verify_bundle', lambda path: None)
    with TestClient(app_for(repo, config_source=Path('/missing/private/config.toml'))) as http:
        assert http.get(BASE).json()['mode'] == 'READ_ONLY_ARCHIVE'
        assert [item['source'] for item in http.get(REFERENCES).json()['items']] == ['packaged']
        for suffix, body in (('/preview', {'content': content}), ('/import', {'content': content, 'preview_sha256': '0' * 64})):
            response = http.post(REFERENCES + suffix, json=body, headers=LOCAL)
            assert (response.status_code, response.json()['code']) == (409, 'restored_read_only')
    assert stored(repo) == 0


# --- save-time billing validation ---------------------------------------------------------------


def test_global_profile_must_pin_an_available_bundle(setup):
    repo, data, _ = setup
    missing = billing_data(data, profiles={'credits': {**CODEX_CREDITS, 'references': 'f' * 64}})
    with pytest.raises(ConfigurationConflict) as error:
        repo.preview([change(repo, dumps(missing))], reason='Synthetic change')
    assert refused(error) == [{'setting': 'billing.profiles.credits.references', 'code': 'reference_unavailable'}]
    save(repo, [change(repo, dumps(billing_data(data)))])  # the packaged bundle is always available
    # An imported bundle is available once its rows exist.
    from my_harness.storage import accounting_operations as operations
    identifier, content = claude_only()
    imported = billing_data(data, defaults={}, profiles={'api': {**CLAUDE_API, 'references': identifier}})
    with pytest.raises(ConfigurationConflict):
        repo.preview([change(repo, dumps(imported))], reason='Synthetic change')
    raw = content.encode()
    operations.reference_import(repo.managed.engine, raw,
                                preview_sha256=operations.reference_preview(repo.managed.engine, raw)['sha256'])
    assert repo.preview([change(repo, dumps(imported))], reason='Synthetic change')['kind'] == 'SAVE'


def test_project_selection_refusals_and_inherited_unknown_effects(setup, tmp_path):
    repo, data, _ = setup
    profiles = {'credits': CODEX_CREDITS, 'api': CLAUDE_API}
    active_global(repo, billing_data(data, defaults={'executor': 'credits'}, profiles=profiles))
    register(repo, tmp_path / 'one', 'one')
    project = {**project_data(data, repo, tmp_path / 'one', 'one'), 'format': 'project-config-2'}
    for selection, code in (('missing', 'billing_profile_missing'), ('api', 'billing_provider_mismatch')):
        project['billing'] = {'reviewer': selection}
        with pytest.raises(ConfigurationConflict) as error:
            repo.preview([change(repo, dumps(project), 'project:one')], reason='Synthetic change')
        assert refused(error) == [{'project': 'one', 'role': 'reviewer', 'setting': 'billing.reviewer', 'code': code}]
    # The executor inherits `credits`; the reviewer has no default: reported, not refused.
    project['billing'] = {}
    preview = repo.preview([change(repo, dumps(project), 'project:one')], reason='Synthetic change')
    assert preview['effects']['billing_unknown'] == [
        {'scope': 'project:one', 'role': 'reviewer', 'profile': None, 'reason': 'billing_profile_unknown'}]
    project['billing'] = {'reviewer': 'credits'}
    assert 'billing_unknown' not in repo.preview([change(repo, dumps(project), 'project:one')],
                                                 reason='Synthetic change')['effects']
    # A project-config-1 document keeps its meaning: the inherited default is only reported.
    legacy = project_data(data, repo, tmp_path / 'one', 'one')
    assert repo.preview([change(repo, dumps(legacy), 'project:one')], reason='Synthetic change')['effects'][
        'billing_unknown'][0]['role'] == 'reviewer'
    # A global revision without billing metadata lacks every explicitly selected profile.
    save(repo, [change(repo, dumps(data))], key='plain-global')
    plain = repo.read('global')['saved']
    project['global'] = {'revision': plain['revision'], 'sha256': plain['sha256']}
    with pytest.raises(ConfigurationConflict) as error:
        repo.preview([change(repo, dumps(project), 'project:one')], reason='Synthetic change')
    assert refused(error)[0]['code'] == 'billing_profile_missing'


def test_global_save_names_projects_whose_derived_selection_it_breaks(setup, tmp_path):
    repo, data, _ = setup
    profiles = {'credits': CODEX_CREDITS, 'api': CLAUDE_API}
    active_global(repo, billing_data(data, defaults={}, profiles=profiles))
    register(repo, tmp_path / 'one', 'one')
    project = {**project_data(data, repo, tmp_path / 'one', 'one'), 'format': 'project-config-2',
               'billing': {'executor': 'credits'}}
    repo.project_verifier = lambda *args: {'synthetic_receipt': 'unchanged-technical-content'}
    save(repo, [change(repo, dumps(project), 'project:one')], key='project')
    activate(repo, ('project:one',), key='activate-project')
    repo.derive_projects = True
    for alter, code in ((lambda p: p.pop('credits'), 'billing_profile_missing'),
                        (lambda p: p.__setitem__('credits', {**CLAUDE_API}), 'billing_provider_mismatch')):
        changed = copy.deepcopy(profiles)
        alter(changed)
        candidate = billing_data(data, defaults={}, profiles=changed)
        with pytest.raises(ConfigurationConflict) as error:
            repo.preview([change(repo, dumps(candidate))], reason='Synthetic change')
        assert refused(error) == [{'project': 'one', 'role': 'executor', 'setting': 'billing.executor', 'code': code}]
    # Other billing edits derive the project copy; its unselected reviewer reports the unknown default.
    candidate = billing_data(data, defaults={}, profiles={**profiles, 'spare': CODEX_CREDITS})
    preview = repo.preview([change(repo, dumps(candidate))], reason='Synthetic change')
    assert [item['scope'] for item in preview['changes']] == ['global', 'project:one']
    assert preview['effects']['billing_unknown'] == [
        {'scope': 'project:one', 'role': 'reviewer', 'profile': None, 'reason': 'billing_profile_unknown'}]


def test_billing_only_conversion_keeps_the_technical_receipt(setup, tmp_path):
    repo, data, _ = setup
    active_global(repo, billing_data(data, defaults={}))
    register(repo, tmp_path / 'one', 'one')
    project = project_data(data, repo, tmp_path / 'one', 'one')
    repo.project_verifier = lambda *args: {'synthetic_receipt': 'unchanged-technical-content'}
    save(repo, [change(repo, dumps(project), 'project:one')], key='project')
    activate(repo, ('project:one',), key='activate-project')
    converted = {**project, 'format': 'project-config-2', 'billing': {'executor': 'credits'}}
    preview = repo.preview([change(repo, dumps(converted), 'project:one')], reason='Synthetic change')
    [effect] = preview['effects']['projects']
    assert effect['preparation_required'] is False and 'billing_unknown' in preview['effects']
    assert '+"format" = "project-config-2"' in preview['changes'][0]['diff']
    save(repo, [change(repo, dumps(converted), 'project:one')], key='converted')
    activate(repo, ('project:one',), key='activate-converted')
    assert repo.read('project:one')['active']['sha256'] == digest(dumps(converted).encode())
