"""P002-T006 (TM15, TM17, B10): bounded, sanitized trace event payloads. No I/O.

An event carries identities, codes and small values only. Keys that name credentials, environments, argv or prompts
are replaced by a marker without their value; secret-looking substrings of any string are masked before anything
else, so neither the payload nor an offloaded artifact keeps them. No digest of a redacted secret is kept: a hash of
a short secret could confirm a guess. Strings longer than `MAX_STRING` become content-addressed artifact references
whose bytes the caller stores with the event (`trace_artifacts`); a payload still over `MAX_PAYLOAD` becomes one
reference.
Collections, depth and keys are bounded with explicit truncation markers, never silently.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import re

FORMAT = 'trace-payload-1'
MAX_PAYLOAD = 8192
MAX_STRING = 1024
MAX_ITEMS = 100
MAX_DEPTH = 8
MAX_KEY = 120
MASK = '[REDACTED]'
SENSITIVE_KEY = re.compile(
    r'(?i)^(env|environment|argv|prompt|prompt_text|stdin|password|passwd|secret|client_secret|api_?key|'
    r'authorization|cookie|set_cookie|credentials?|private_?key|(access|auth|bearer|refresh|session|id)_?token)$')
SECRET_VALUES = (
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----|$)'),
    re.compile(r'\bsk-(?:ant-)?[A-Za-z0-9_-]{16,}'),
    re.compile(r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}'),
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{20,}'),
    re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    re.compile(r'\bxox[abposr]-[A-Za-z0-9-]{10,}'),
    re.compile(r'\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}'),
    re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}'),
)


@dataclass(frozen=True)
class Bounded:
    payload: dict
    artifacts: tuple  # ((reference, bytes), ...) to store outside the event
    redactions: int
    truncated: bool


def _reference(data: bytes, media: str) -> dict:
    return {'artifact': {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data), 'media': media}}


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class _Sanitizer:
    def __init__(self):
        self.artifacts, self.redactions, self.truncated = [], 0, False

    def mask(self, text: str) -> str:
        for pattern in SECRET_VALUES:
            text, found = pattern.subn(MASK, text)
            self.redactions += found
        return text

    def value(self, value, depth):
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, str):
            text = self.mask(value)
            if len(text) > MAX_STRING:
                data = text.encode('utf-8')
                reference = _reference(data, 'text/plain; charset=utf-8')
                self.artifacts.append((reference['artifact'], data))
                return reference
            return text
        if depth >= MAX_DEPTH:
            self.truncated = True
            return {'truncated': 'depth'}
        if isinstance(value, (list, tuple)):
            items = [self.value(item, depth + 1) for item in list(value)[:MAX_ITEMS]]
            if len(value) > MAX_ITEMS:
                self.truncated = True
                items.append({'truncated': 'items', 'omitted': len(value) - MAX_ITEMS})
            return items
        if isinstance(value, dict):
            result = {}
            for index, (key, item) in enumerate(sorted(value.items(), key=lambda pair: str(pair[0]))):
                if index >= MAX_ITEMS:
                    self.truncated = True
                    result['_truncated'] = {'truncated': 'keys', 'omitted': len(value) - MAX_ITEMS}
                    break
                key = self.mask(str(key))[:MAX_KEY]
                if SENSITIVE_KEY.match(key):
                    self.redactions += 1
                    result[key] = {'redacted': 'sensitive_key'}
                else:
                    result[key] = self.value(item, depth + 1)
            return result
        self.truncated = True
        return {'unsupported': type(value).__name__}


def bound(payload) -> Bounded:
    """Sanitized and bounded copy of `payload` (a mapping); the input is never modified."""
    if not isinstance(payload, dict):
        raise TypeError('trace_payload_not_mapping')
    sanitizer = _Sanitizer()
    clean = sanitizer.value(payload, 0)
    text = _canonical(clean)
    if len(text.encode('utf-8')) > MAX_PAYLOAD:
        data = text.encode('utf-8')
        reference = _reference(data, 'application/json')
        sanitizer.artifacts.append((reference['artifact'], data))
        clean, sanitizer.truncated = {**reference, 'truncated': 'payload'}, True
    return Bounded(clean, tuple(sanitizer.artifacts), sanitizer.redactions, sanitizer.truncated)


def artifact_references(value):
    """Artifact references inside a bounded payload, in order (for storage and verification)."""
    if isinstance(value, dict):
        if set(value) >= {'artifact'} and isinstance(value['artifact'], dict) and 'sha256' in value['artifact']:
            yield value['artifact']
        for item in value.values():
            yield from artifact_references(item)
    elif isinstance(value, list):
        for item in value:
            yield from artifact_references(item)


def contained_references(payload, artifacts):
    """Every reference of an event: those of its payload and those inside its offloaded `application/json` artifacts
    (a whole payload offloaded over `MAX_PAYLOAD` keeps the references of the strings offloaded before it).

    `artifacts` maps sha256 to (media, bytes) of the event's stored artifacts; a JSON artifact that does not parse
    raises ValueError, so its references cannot escape verification."""
    pending, seen = list(artifact_references(payload)), set()
    while pending:
        reference = pending.pop()
        yield reference
        sha256 = reference.get('sha256')
        stored = artifacts.get(sha256)
        if sha256 in seen or stored is None or not stored[0].startswith('application/json'):
            continue
        seen.add(sha256)
        pending.extend(artifact_references(json.loads(stored[1].decode('utf-8'))))
