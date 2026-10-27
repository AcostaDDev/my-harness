"""Global language preferences of this installation and their capture when a job is admitted (P011-T007, D166).

A single SQLite row, `product-preferences-1`, holds the mutable visual language and the default work language for
future projects. Changes take the managed write lock, so an admission and a change never interleave: each job
freezes the visual language current in its own transaction. Reads never repair or create the row.
"""
import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.core.engine.contracts import freeze
from my_harness.i18n import DEFAULT_LANGUAGE, LANGUAGES, tr
from my_harness.storage.managed import Conflict
from my_harness.storage.models import (
    ManagedJobRow as Job, ProductPreferenceEventRow as Event, ProductPreferencesRow as Row,
)
from my_harness.storage.permissions import actor

FORMAT = 'product-preferences-1'
CONTEXT_FORMAT = 'ui-language-1'


class PreferencesInvalid(Conflict):
    """The stored row is outside the contract: reads fall back to English, new admissions are refused."""


class PreferencesChanged(Conflict):
    pass


class PreferencesKeyReused(Conflict):
    pass


def _digest(value) -> str:
    return hashlib.sha256(freeze(value).encode()).hexdigest()


def view(row: Row | None) -> dict:
    """`default` without a row (factory values), `invalid` with values outside the contract, `stored` otherwise."""
    if row is None:
        return {'format': FORMAT, 'version': 0, 'ui_language': DEFAULT_LANGUAGE,
                'default_work_language': DEFAULT_LANGUAGE, 'updated_at': None, 'status': 'default'}
    valid = row.format == FORMAT and row.ui_language in LANGUAGES and row.default_work_language in LANGUAGES
    return {'format': FORMAT, 'version': row.version, 'updated_at': row.updated_at,
            'ui_language': row.ui_language if valid else DEFAULT_LANGUAGE,
            'default_work_language': row.default_work_language if valid else DEFAULT_LANGUAGE,
            'status': 'stored' if valid else 'invalid'}


def capture(session: Session) -> dict:
    """Visual language for a new job, read in the transaction that admits it."""
    current = view(session.get(Row, 1))
    if current['status'] == 'invalid':
        raise PreferencesInvalid(tr('preferences.stored_language_preferences_invalid'))
    return {'format': CONTEXT_FORMAT, 'ui_language': current['ui_language'], 'preferences_version': current['version']}


def inherited(session: Session, run_id: str) -> dict | None:
    """A continuation of a run keeps the value of its first job, null included: it is never recaptured."""
    return session.scalar(select(Job.language_context).where(Job.run_id == run_id).order_by(Job.id).limit(1))


def language(engine) -> str:
    """Visual language for the service's own messages; English if the database cannot answer."""
    try:
        with Session(engine) as session:
            return view(session.get(Row, 1))['ui_language']
    except Exception:  # noqa: BLE001  (a message never fails because of its language)
        return DEFAULT_LANGUAGE


class PreferencesRepository:
    def __init__(self, managed):
        self.managed = managed

    def read(self) -> dict:
        with Session(self.managed.engine) as session:
            return view(session.get(Row, 1))

    def history(self) -> list[dict]:
        with Session(self.managed.engine) as session:
            return [event.payload for event in session.scalars(select(Event).order_by(Event.version))]

    def update(self, *, expected_version: int, ui_language: str, default_work_language: str, key: str) -> dict:
        """CAS on the version; the same key and the same change return the recorded result without another version."""
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError(tr('preferences.explicit_non_negative_preferences'))
        if ui_language not in LANGUAGES or default_work_language not in LANGUAGES:
            raise ValueError(tr('preferences.languages_one', languages=', '.join(LANGUAGES)))
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            raise ValueError(tr('preferences.idempotency_key_requires_1'))
        request_sha256 = _digest({'expected_version': expected_version, 'ui_language': ui_language,
                                  'default_work_language': default_work_language})
        with self.managed._write() as session:
            previous = session.scalar(select(Event).where(Event.idempotency_key == key))
            if previous is not None:
                if previous.request_sha256 != request_sha256:
                    raise PreferencesKeyReused(tr('preferences.idempotency_key_already_names'))
                return {**previous.payload['after'], 'replayed': True}
            row = session.get(Row, 1)
            before = view(row)
            if before['version'] != expected_version:
                raise PreferencesChanged(tr('preferences.preferences_changed_reload_them'))
            if row is None:
                row = Row(id=1)
                session.add(row)
            row.format, row.ui_language, row.default_work_language = FORMAT, ui_language, default_work_language
            row.version, row.updated_at = before['version'] + 1, self.managed._now()
            after = view(row)
            last = session.scalar(select(Event).order_by(Event.version.desc()).limit(1))
            payload = {'version': row.version, 'before': before, 'after': after, 'actor': actor(),
                       'recorded_at': row.updated_at, 'previous_sha256': last.payload['sha256'] if last else None}
            payload['sha256'] = _digest(payload)
            session.add(Event(version=row.version, idempotency_key=key, request_sha256=request_sha256,
                              payload=payload))
            return {**after, 'replayed': False}
