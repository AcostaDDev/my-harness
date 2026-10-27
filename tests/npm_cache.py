"""Offline npm cache that the tests with real Node/npm need (README, Development).

The TypeScript fixture runs `npm ci --offline` against `.local/npm-cache`; an empty cache does not download anything
and stops preparation with ENOTCACHED, which the affected tests only show as "Environment preparation failed".
"""
import base64
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NPM_CACHE = ROOT / '.local/npm-cache'
FIXTURE_LOCK = ROOT / 'tests/fixtures/typescript_web/package-lock.json'
SETUP = 'npm --prefix frontend ci --ignore-scripts --cache .local/npm-cache'


def missing_npm_packages(lock=FIXTURE_LOCK, cache=NPM_CACHE):
    """Locked packages without both their cacache index entry (by URL) and content (by integrity).

    Reads npm's cache layout only: no npm process, network access or write.
    """
    missing = []
    for path, entry in json.loads(Path(lock).read_text()).get('packages', {}).items():
        if not path or 'resolved' not in entry:
            continue
        key = hashlib.sha256(f"make-fetch-happen:request-cache:{entry['resolved']}".encode()).hexdigest()
        algorithm, _, digest = entry['integrity'].partition('-')
        content = base64.b64decode(digest).hex()
        index = Path(cache) / '_cacache/index-v5' / key[:2] / key[2:4] / key[4:]
        stored = Path(cache) / '_cacache/content-v2' / algorithm / content[:2] / content[2:4] / content[4:]
        if not (index.is_file() and stored.is_file()):
            missing.append(f"{path.removeprefix('node_modules/')}@{entry.get('version', '?')}")
    return missing


def notice():
    """One line for the pytest header and summary, or None when the cache is ready."""
    missing = missing_npm_packages()
    if not missing:
        return None
    return (f"{NPM_CACHE.relative_to(ROOT)} lacks {', '.join(missing)}: tests with real Node/npm will stop at "
            f"'Environment preparation failed' (ENOTCACHED). Fill the cache once with: {SETUP}")
