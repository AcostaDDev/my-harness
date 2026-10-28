"""P001-T003 (D257/D259): format-3 accounting verification inside one SQLite snapshot.

Every reference, capture, binding, valuation and cohort digest is recomputed from the stored bytes; native links are
covered by foreign keys plus the source-link check constraint. Nothing is repaired, recalculated or backfilled.
A known historical gap (an expected invocation without capture) is retained as a gap, not an error.
"""
from decimal import Decimal, localcontext
import json

from my_harness.core.engine.metric_references import ReferenceError, digest, load_bundle, seal_reference

TABLES = ('usage_invocations', 'usage_captures', 'usage_components', 'metrics_references', 'usage_valuations',
          'usage_valuation_lines', 'valuation_cohorts', 'valuation_cohort_members')


class AccountingMismatch(ValueError):
    pass


def _loads(value):
    return json.loads(value) if isinstance(value, str) else value


def inventory(db):
    return {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in TABLES}


def verify(db):
    """Raise AccountingMismatch on any digest or link inconsistency; return the inventory."""
    for row in db.execute('SELECT id, kind, content FROM metrics_references ORDER BY id'):
        try:
            if row[1] == 'bundle':
                bundle = load_bundle(row[2].encode('utf-8'))
                if bundle.id != row[0]:
                    raise AccountingMismatch('reference')
                for ref in bundle.references:
                    member = db.execute('SELECT content FROM metrics_references WHERE id=?', (ref.id,)).fetchone()
                    if member is None or member[0].encode('utf-8') != ref.content:
                        raise AccountingMismatch('reference')
            else:
                ref = seal_reference(json.loads(row[2]))
                if ref.id != row[0] or ref.content != row[2].encode('utf-8') or ref.document()['kind'] != row[1]:
                    raise AccountingMismatch('reference')
        except (ReferenceError, ValueError, UnicodeError) as exc:
            if isinstance(exc, AccountingMismatch):
                raise
            raise AccountingMismatch('reference') from exc
    for identifier, binding, sha in db.execute('SELECT id, binding, binding_sha256 FROM usage_invocations'):
        binding = _loads(binding)
        if (binding is None) != (sha is None) or binding is not None and digest(binding) != sha:
            raise AccountingMismatch(f'binding:{identifier}')
    captures = {}
    for identifier, sha, document, evidence, evidence_sha in db.execute(
            'SELECT id, digest, document, evidence, evidence_digest FROM usage_captures'):
        document, evidence = _loads(document), _loads(evidence)
        if digest(document) != sha or (evidence is None) != (evidence_sha is None) \
                or evidence is not None and digest(evidence) != evidence_sha:
            raise AccountingMismatch(f'capture:{identifier}')
        captures[identifier] = sha
    for row in db.execute('SELECT id, invocation_id, capture_id, normalization, calculator, profile_digest, '
                          'reference_set_digest, basis, scenario_digest, scenario, exact_sum FROM usage_valuations'):
        identity = {'invocation': row[1], 'capture': captures.get(row[2]), 'normalization': row[3],
                    'calculator': row[4], 'profile': row[5], 'references': row[6], 'basis': row[7],
                    'scenario': row[8]}
        if digest(identity) != row[0] or digest(_loads(row[9])) != row[8]:
            raise AccountingMismatch(f'valuation:{row[0]}')
        lines = [value for (value,) in db.execute(
            'SELECT exact_amount FROM usage_valuation_lines WHERE valuation_id=? ORDER BY number', (row[0],))]
        with localcontext() as ctx:
            ctx.prec = 160
            if (row[10] is None) != (not lines) or lines and sum(map(Decimal, lines), Decimal(0)) != Decimal(row[10]):
                raise AccountingMismatch(f'valuation:{row[0]}')
    for identifier, selection, selection_sha, scenario, scenario_sha, status, expected, built in db.execute(
            'SELECT id, selection, selection_digest, scenario, scenario_digest, status, expected, built '
            'FROM valuation_cohorts'):
        selection, scenario = _loads(selection), _loads(scenario)
        members = db.execute('SELECT count(*) FROM valuation_cohort_members WHERE cohort_id=?', (identifier,)).fetchone()[0]
        if (digest(selection) != selection_sha or (scenario is None) != (scenario_sha is None)
                or scenario is not None and digest(scenario) != scenario_sha
                or expected != len(selection['members']) or not 0 <= built <= expected
                or status == 'CLOSED' and (built != expected or members != expected)):
            raise AccountingMismatch(f'cohort:{identifier}')
    return inventory(db)
