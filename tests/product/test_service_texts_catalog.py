"""P011-T022: the service texts that were English technical text also follow the visual language (D172).

Every own diagnostic of `core/`, `adapters/`, `storage/`, `services/` and the v2 recipes that an operator can see
(raised to the API/CLI, a stop or acceptance reason, a recorded diagnostic) goes through `tr()`. What stays English
is listed in `tests/fixtures/service_texts/english.json` with its reason: invariants that only fail on a programming
error or on corrupt persisted data, and texts that enter an agent's input. The client tells two refusals apart by
code, never by their text. Temporary SQLite/Git, fake agents and synthetic data only."""
import ast
import json
import re
from pathlib import Path

import pytest

from my_harness import i18n
from my_harness.adapters.bootstrap import DraftChanged
from my_harness.api.managed import call
from my_harness.core.engine.acceptance import assess_acceptance
from my_harness.core.engine.document_ops import ManagedBlocksEdited
from my_harness.storage.managed import Conflict
from test_definition import answer, world  # noqa: F401  (fixture)
from test_documents import STATE, STATE_BEGIN, edit_view, v2, v2checkout  # noqa: F401  (fixtures)
from test_managed import repository  # noqa: F401  (fixture)

SOURCE = Path(i18n.__file__).parents[1]
ENGLISH = Path(__file__).parents[1] / 'fixtures/service_texts/english.json'
LAYERS = ('core/', 'adapters/', 'storage/', 'services/', 'orchestration/', 'recipes/django_2.py',
          'recipes/typescript_web_2.py')
# Calls whose text argument is a stop/acceptance reason or a recorded diagnostic (name -> argument index).
SINKS = {'stopped': 2, 'stop_history': 2, '_invalidated': 0, 'stop': 1, '_invalidate': 5, '_invalidate_batches': 3}
LISTS = {'reasons', 'blockers', 'warnings', 'stale_reasons', 'stale', 'notes'}
FIELD = re.compile(r'\{[a-z_0-9]*\}')
CATEGORIES = {'invariant', 'agent-input', 'technical'}


def template(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return ''.join(v.value if isinstance(v, ast.Constant) else '{}' for v in node.values)
    return None


def own_text(text):
    """A text with own words; codes, bare identifiers and `{where}: {exc}` wrappers are not messages."""
    words = re.findall(r'[A-Za-z]{3,}', FIELD.sub('', text))
    return bool(words) and not re.fullmatch(r'[a-z_]+', text)


def texts(path):
    """Own texts in diagnostic positions that do not go through `tr()`."""
    found = []
    for node in ast.walk(ast.parse(path.read_text())):
        candidates = []
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
            candidates.append(node.exc.args[0])
        elif isinstance(node, ast.Call):
            name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            if name in SINKS and len(node.args) > SINKS[name]:
                arg = node.args[SINKS[name]]
                candidates += arg.values if isinstance(arg, ast.BoolOp) else [arg]
            elif name == 'append' and node.args and getattr(node.func.value, 'id', None) in LISTS:
                candidates.append(node.args[0])
            candidates += [k.value for k in node.keywords if k.arg == 'diagnostic']
        for candidate in candidates:
            text = template(candidate)
            if text is not None and own_text(text):
                found.append(text)
    return found


def modules():
    for path in sorted(SOURCE.rglob('*.py')):
        relative = path.relative_to(SOURCE).as_posix()
        if relative.startswith(LAYERS):
            yield relative, path


def test_own_service_texts_are_cataloged_or_listed_as_english_technical_text():
    english = json.loads(ENGLISH.read_text())
    assert set(english) <= {relative for relative, _ in modules()}
    unlisted, stale = [], []
    for relative, path in modules():
        allowed = english.get(relative, {})
        assert set(allowed.values()) <= CATEGORIES, relative
        found = texts(path)
        unlisted += [(relative, text) for text in found if text not in allowed]
        stale += [(relative, text) for text in allowed if text not in found]
    assert not unlisted, unlisted
    assert not stale, stale


def test_refusals_the_client_compares_have_their_own_codes():
    def refuse(cause):
        def operation():
            raise Conflict(str(cause)) from cause
        with pytest.raises(Exception) as caught:
            call(operation)
        return caught.value.status_code, caught.value.detail['code']
    with i18n.emission('es'):
        blocks = ManagedBlocksEdited(i18n.tr('documents.managed_blocks_generated_harness', path='docs/STATE.md'))
        draft = DraftChanged(i18n.tr('onboarding.changed_since_read_expected', path='README.md', base_sha256='a',
                                     current='b'))
    assert 'managed blocks are generated' not in str(blocks) and 'changed since' not in str(draft)
    assert refuse(blocks) == (409, 'managed_blocks_generated') and refuse(draft) == (409, 'draft_changed')
    assert refuse(ValueError('other')) == (409, 'conflict')


def test_document_and_draft_refusals_carry_their_cause_in_the_emission_language(v2, world):
    v2.create_v2()
    v2.context.path('docs/STATE.md').write_text(STATE.replace(f'{STATE_BEGIN}\n', f'{STATE_BEGIN}\nforged\n'))
    with i18n.emission('es'), pytest.raises(Conflict) as caught:
        edit_view(v2, 'worktree')
    assert isinstance(caught.value.__cause__, ManagedBlocksEdited)
    assert str(caught.value) == i18n.message('documents.managed_blocks_generated_harness', 'es', path='docs/STATE.md')
    cid = world.create()
    world.turn(cid, answer())
    proposal = next(p for p in world.view(cid)['proposals'] if p['path'] == 'README.md')
    world.path('README.md').write_text('# local\n')
    with i18n.emission('es'), pytest.raises(Conflict) as caught:
        world.apply(cid, proposal)
    assert isinstance(caught.value.__cause__, DraftChanged) and 'La edición del usuario se conserva' in str(caught.value)


def test_engine_reasons_follow_the_emission_and_render_back_to_english():
    class Cycle:
        review_json = '{"verdict": "REVISE"}'
        policy = type('Policy', (), {'hard_failure': True})()
        validation = type('Validation', (), {'all_passed': False, 'evidence': None})()
        evidence = type('Evidence', (), {'changed_paths': ()})()

    class Context:
        root = None

    from unittest import mock
    with mock.patch('my_harness.core.engine.acceptance.parity_reasons', return_value=[]):
        with i18n.emission('es'):
            decision = assess_acceptance(Cycle(), None, Context())
    assert decision.reasons[0] == 'La revisión independiente no dio ACCEPT'
    assert [i18n.rendered(r, 'en') for r in decision.reasons] == [
        'Independent review did not ACCEPT', 'File policy failure', 'Deterministic validation failed',
        'Content changed since evidence capture']
    # Persisted copies keep only the text emitted (D171): no retranslation afterwards.
    assert json.loads(json.dumps(list(decision.reasons)))[1] == 'Fallo de la política de archivos'
