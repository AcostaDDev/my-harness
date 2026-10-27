"""Catalogs of the service's own messages (P011-T007, D166; emission language P011-T021, D171).

English is the base and the fallback. A key names a complete message; parameters are plain `{name}` fields,
never expressions or fragments of another message. Codes, states and original evidence are not translated here.

`tr()` uses the visual language of the current emission: each HTTP request reads the stored preferences, a
worker uses the visual language frozen with its job, and the CLI uses `--ui-language` or the database's preferences.
Outside any of these, English.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cache
from importlib.resources import files
import json
import re

LANGUAGES = ('en', 'es')
DEFAULT_LANGUAGE = 'en'
PARAMETER = re.compile(r'\{([a-z_][a-z0-9_]*)\}')
# A language or a resolver called on first use, so an emission without own messages never reads SQLite.
_emission: ContextVar = ContextVar('my_harness_emission_language', default=None)


@cache
def catalog(language: str) -> dict[str, str]:
    return json.loads(files(__package__).joinpath(f'{language}.json').read_text(encoding='utf-8'))


def supported(language) -> str:
    """The language itself if valid; otherwise the English fallback."""
    return language if language in LANGUAGES else DEFAULT_LANGUAGE


def message(key: str, language, /, **params) -> str:
    """Localized text; a missing translation falls back to English and a missing key returns the key itself.

    An absent parameter keeps its `{name}` field visible: nothing is evaluated and no other value is revealed.
    """
    text = catalog(supported(language)).get(key) or catalog(DEFAULT_LANGUAGE).get(key)
    if text is None:
        return key
    return PARAMETER.sub(lambda match: str(params[match[1]]) if match[1] in params else match[0], text)


def current() -> str:
    """Visual language of the current emission; English without one or if its resolver fails."""
    value = _emission.get()
    if callable(value):
        try:
            value = value()
        except Exception:  # noqa: BLE001  (a message never fails because of its language)
            value = DEFAULT_LANGUAGE
    return supported(value)


@contextmanager
def emission(language):
    """Messages emitted inside this block use `language` (a code, or a callable that returns one).

    A callable is resolved once, on the first message, so every text of one emission shares the same language.
    """
    if callable(language):
        resolve, resolved = language, []

        def language():
            if not resolved:
                resolved.append(resolve())
            return resolved[0]
    token = _emission.set(language)
    try:
        yield
    finally:
        _emission.reset(token)


class Localized(str):
    """An emitted text that remembers its key and fields, so it can be rendered again in another language.

    It is a plain `str` everywhere else; copies, pickles and JSON keep only the text.
    """

    def __new__(cls, key: str, language: str, params: dict):
        value = super().__new__(cls, message(key, language, **params))
        value.key, value.params = key, params
        return value

    def __reduce__(self):
        return str, (str(self),)

    def render(self, language) -> str:
        return message(self.key, language, **self.params)


def rendered(value, language):
    """`value` in `language` when it is an own localized text; any other value as it is."""
    return value.render(language) if isinstance(value, Localized) else value


def tr(key: str, /, **params) -> Localized:
    """`message()` in the visual language of the current emission."""
    return Localized(key, current(), params)
