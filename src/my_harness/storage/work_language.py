"""Immutable work language per canonical project root and the language pair frozen per job (P011-T008, D167).

A project's work language (documentation and code) is chosen once: when it is registered or created, declared by
a `local-config-6` TOML, or confirmed explicitly for a project that has none (`migration`). The row is keyed by the
canonical root, so retiring and registering again, or changing id, profile or agents, never chooses it again.
Rows are written once and never updated or deleted.

Every new job freezes the pair `language-context-1` in the transaction that admits it: the current visual language
(global preference) and the project's work language with its provenance. A root without a confirmed work language
admits no new work; continuations of an earlier run keep the context of its first job, null included.
"""
import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.core.engine.contracts import freeze
from my_harness.i18n import LANGUAGES, message, tr
from my_harness.storage.managed import Conflict
from my_harness.storage.models import ProjectWorkLanguageRow as Row

FORMAT = 'work-language-1'
CONTEXT_FORMAT = 'language-context-1'
SOURCES = ('registration', 'creation', 'toml', 'migration')


class WorkLanguageRequired(Conflict):
    """The root has no confirmed work language: new work waits for an explicit confirmation."""


class WorkLanguageImmutable(Conflict):
    """The root already has another work language; it never changes."""


def digest(value) -> str:
    return hashlib.sha256(freeze(value).encode()).hexdigest()


def view(row: Row | None) -> dict | None:
    if row is None:
        return None
    return {'format': row.format, 'root': row.root, 'project_id': row.project_id,
            'work_language': row.work_language, 'source': row.source, 'confirmation': row.confirmation,
            'sha256': row.sha256, 'confirmed_at': row.confirmed_at}


def get(session: Session, root: str) -> dict | None:
    return view(session.get(Row, str(root)))


def read(engine, root) -> dict | None:
    with Session(engine) as session:
        return get(session, root)


def rows(engine) -> dict[str, dict]:
    with Session(engine) as session:
        return {row.root: view(row) for row in session.scalars(select(Row))}


def require_language(value) -> str:
    if value not in LANGUAGES:
        raise ValueError(tr('work_language.work_language_one', languages=list(LANGUAGES)))
    return value


def associate(session: Session, *, root: str, project_id: str, work_language: str, source: str,
              confirmation: dict, now: str) -> tuple[dict, bool]:
    """Records the root's work language once, in the caller's transaction; returns `(row, created)`.

    The same value for an already associated root keeps the original row (a re-registration does not choose it
    again); another value is refused."""
    require_language(work_language)
    if source not in SOURCES:
        raise ValueError(f'Unknown work language source {source!r}')
    current = session.get(Row, str(root))
    if current is not None:
        if current.work_language != work_language:
            raise WorkLanguageImmutable(
                tr('work_language.work_language_since_does', root=root, work_language=repr(current.work_language),
                   confirmed_at=current.confirmed_at))
        return view(current), False
    record = {'format': FORMAT, 'root': str(root), 'project_id': project_id, 'work_language': work_language,
              'source': source, 'confirmation': confirmation, 'confirmed_at': now}
    row = Row(**record, sha256=digest(record))
    session.add(row)
    session.flush()
    return view(row), True


def capture(session: Session, root: str) -> dict:
    """Language pair of a new job, read in the transaction that admits it (D159 §4)."""
    from my_harness.storage.models import ProductPreferencesRow
    from my_harness.storage.preferences import capture as visual, view as preferences
    work = get(session, root)
    if work is None:
        # Diagnostic in the stored visual language (English if the row is unusable); the code stays stable.
        raise WorkLanguageRequired(message('work_language.unconfirmed',
                                           preferences(session.get(ProductPreferencesRow, 1))['ui_language']))
    ui = visual(session)
    return {'format': CONTEXT_FORMAT, 'ui_language': ui['ui_language'], 'preferences_version': ui['preferences_version'],
            'work_language': work['work_language'], 'work_language_source': work['source'],
            'work_language_sha256': work['sha256']}
