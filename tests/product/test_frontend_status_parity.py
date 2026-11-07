"""P002-T022 (T018 §5, D304): the shared list `Status` uses the same classes as the work-map projections.

The frontend table `frontend/src/status-classes.json` must equal T020's mapping (`core/engine/work_map.py`) for the
entities the list pages show (runs, attempt outcomes and phases), and every persisted value of those vocabularies
(read from the real writers by T020's parity helper) must have a class there; a value without one renders as
`unknown` with its raw code, never as a guessed class. Test only: no product behavior is involved.
"""
import json
from pathlib import Path

from my_harness.core.engine import work_map as wm
from test_work_map import vocabularies

FRONTEND = Path(__file__).resolve().parents[2] / 'frontend'
TABLE = json.loads((FRONTEND / 'src/status-classes.json').read_text())
ENTITIES = ('run', 'attempt', 'phase')


def flatten(classes):
    return {code: cls for cls, codes in classes.items() for code in codes}


def test_frontend_status_table_equals_the_work_map_mapping():
    assert set(TABLE) == set(ENTITIES)
    for entity in ENTITIES:
        assert set(TABLE[entity]) <= set(wm.CLASSES) - {'unknown'}, entity
        codes = [code for codes in TABLE[entity].values() for code in codes]
        assert len(codes) == len(set(codes)), f'{entity}: a code with two classes'
        assert flatten(TABLE[entity]) == wm.STATUS[entity], entity


def test_every_persisted_list_status_has_a_frontend_class():
    found = vocabularies()
    for entity in ENTITIES:
        table = flatten(TABLE[entity])
        assert found[entity], entity
        assert sorted(value for value in found[entity] if value not in table) == [], entity


def test_run_and_attempt_codes_never_disagree_where_the_list_shares_them():
    # `Status kind="run"` shows run statuses and stored attempt outcomes; a shared code must keep one class.
    run, attempt = flatten(TABLE['run']), flatten(TABLE['attempt'])
    assert {code: (run[code], attempt[code]) for code in run.keys() & attempt.keys() if run[code] != attempt[code]} == {}


def test_every_mapped_list_status_has_a_label_in_both_catalogs():
    en = json.loads((FRONTEND / 'src/i18n/en.json').read_text())
    es = json.loads((FRONTEND / 'src/i18n/es.json').read_text())
    for entity, prefix in (('run', 'status.run.'), ('attempt', 'status.run.'), ('phase', 'status.phase.')):
        for code in flatten(TABLE[entity]):
            key = prefix + ('TIMEOUT' if code == 'TIMED_OUT' else code)
            assert key in en and key in es, key
