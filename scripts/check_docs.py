"""Documentation checks (OT008) with a compact error list.

Usage: scripts/check-docs [FILE.md ...]

- Local Markdown link targets and anchors in tracked `*.md` files (or the given ones): GitHub heading slugs,
  including underscores and `-N` duplicates, and explicit `<a id>`/`<a name>` anchors. External URLs are not fetched.
- Paired code fences.
- Identical en/es key sets in each message catalog pair.
- The Alembic head and table count stated in `docs/DDBB-DIAGRAM.md` against `storage/schema.py`, the migration
  chain and the mapped tables in `storage/models.py`.

Standard library only, offline, read-only. Exit status 1 when any error is reported.
"""
from functools import cache
import json
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = (('src/my_harness/i18n/en.json', 'src/my_harness/i18n/es.json'),
            ('frontend/src/i18n/en.json', 'frontend/src/i18n/es.json'))
DIAGRAM = 'docs/DDBB-DIAGRAM.md'
FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')
INLINE_LINK = re.compile(r'!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*(<[^>]*>|[^\s()]*(?:\([^\s()]*\)[^\s()]*)*)(?:\s+"[^"]*")?\s*\)')
REFERENCE = re.compile(r'^ {0,3}\[[^\]]+\]:\s*(<[^>]*>|\S+)')
HTML_ANCHOR = re.compile(r'<a\s[^>]*\b(?:id|name)=["\']([^"\']+)["\']', re.I)
HEADING = re.compile(r'^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$')
SCHEME = re.compile(r'^[a-z][a-z0-9+.-]*:', re.I)


def slug(text):
    """GitHub's heading anchor: rendered text, lowercase, punctuation removed, each space a hyphen."""
    text = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', text)
    parts = re.split(r'(`+)((?:(?!\1).)+?)\1', re.sub(r'<[^>]+>', '', text))
    # Code spans keep their text; elsewhere emphasis markers go and intra-word underscores stay.
    text = ''.join(part if index % 3 == 2 else '' if index % 3 == 1 else
                   re.sub(r'\*+|(?<!\w)_+|_+(?!\w)', '', part) for index, part in enumerate(parts))
    kept = ''.join(ch for ch in text.lower()
                   if ch.isalnum() or ch in ' -_' or unicodedata.category(ch).startswith('M'))
    return kept.replace(' ', '-')


def masked_lines(text):
    """Lines outside fenced blocks; yields (number, line, line with inline code blanked)."""
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        match = FENCE.match(line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            continue
        if match and not (match[1][0] == '`' and '`' in match[2]):
            fence = match[1]
            continue
        yield number, line, re.sub(r'(`+)(?:(?!\1).)+?\1', lambda code: ' ' * len(code[0]), line)


def unclosed_fence(text):
    fence, opened = None, 0
    for number, line in enumerate(text.splitlines(), 1):
        match = FENCE.match(line)
        if not match:
            continue
        if fence:
            if match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
        elif not (match[1][0] == '`' and '`' in match[2]):
            fence, opened = match[1], number
    return opened if fence else None


@cache
def anchors(path):
    text = path.read_text(errors='replace')
    found, seen = set(), {}
    for _, line, masked in masked_lines(text):
        found.update(HTML_ANCHOR.findall(masked))
        heading = HEADING.match(line)
        if heading:
            base = slug(heading[2])
            count = seen.get(base, 0)
            seen[base] = count + 1
            found.add(base if count == 0 else f'{base}-{count}')
    return found


def link_targets(text):
    for number, _, line in masked_lines(text):
        for match in INLINE_LINK.finditer(line):
            yield number, match[1]
        reference = REFERENCE.match(line)
        if reference:
            yield number, reference[1]


def shown(path):
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def link_errors(path):
    errors = []
    for number, raw in link_targets(path.read_text(errors='replace')):
        target = raw[1:-1] if raw.startswith('<') else raw
        if not target or SCHEME.match(target) or target.startswith('//'):
            continue
        location, _, fragment = target.partition('#')
        location = unquote(location.split('?', 1)[0])
        resolved = (ROOT / location.lstrip('/')) if location.startswith('/') else (path.parent / location)
        resolved = resolved.resolve() if location else path
        where = f'{shown(path)}:{number}'
        if not resolved.exists():
            errors.append(f'{where}: missing target {target}')
        elif fragment and resolved.is_file() and resolved.suffix.lower() == '.md' \
                and unquote(fragment) not in anchors(resolved):
            errors.append(f'{where}: missing anchor #{fragment} in {shown(resolved)}')
    return errors


def catalog_errors(root=ROOT, catalogs=CATALOGS):
    errors = []
    for english, spanish in catalogs:
        keys = {name: set(json.loads((root / name).read_text())) for name in (english, spanish)}
        for name, other in ((english, spanish), (spanish, english)):
            missing = sorted(keys[other] - keys[name])
            if missing:
                more = f' (+{len(missing) - 10} more)' if len(missing) > 10 else ''
                errors.append(f'{name}: missing keys {", ".join(missing[:10])}{more}')
    return errors


def migration_head(versions):
    revisions, parents = set(), set()
    for source in versions.glob('*.py'):
        text = source.read_text()
        revision = re.search(r'^revision\s*=\s*[\'"]([^\'"]+)', text, re.M)
        if revision:
            revisions.add(revision[1])
            parents.update(re.findall(r'[\'"]([^\'"]+)[\'"]', (re.search(r'^down_revision\s*=\s*(.*)$', text, re.M)
                                                                 or [None, ''])[1]))
    heads = sorted(revisions - parents)
    return heads[0] if len(heads) == 1 else ', '.join(heads) or None


def diagram_errors(root=ROOT):
    schema = (root / 'src/my_harness/storage/schema.py').read_text()
    revision = re.search(r'^SCHEMA_REVISION\s*=\s*[\'"]([^\'"]+)', schema, re.M)[1]
    head = migration_head(root / 'src/my_harness/migrations/versions')
    tables = len(re.findall(r'^\s+__tablename__\s*=', (root / 'src/my_harness/storage/models.py').read_text(), re.M))
    errors = [f'storage/schema.py: SCHEMA_REVISION {revision} is not the migration head {head}'] if revision != head else []
    claims = list(re.finditer(r'head `([^`]+)`,\s+(\d+)\s+tables', (root / DIAGRAM).read_text()))
    if not claims:
        errors.append(f'{DIAGRAM}: no "head `…`, N tables" statement')
    for claim in claims:
        if (claim[1], int(claim[2])) != (revision, tables):
            errors.append(f'{DIAGRAM}: states head {claim[1]} with {claim[2]} tables; '
                          f'code has {revision} with {tables} tables')
    return errors


def tracked_markdown(root=ROOT):
    listed = subprocess.run(['git', 'ls-files', '-z', '--', '*.md'], cwd=root, capture_output=True, check=True)
    return [root / name for name in listed.stdout.decode().split('\0') if name and (root / name).is_file()]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    files = [Path(name).resolve() for name in argv] or tracked_markdown()
    errors = []
    for path in files:
        text = path.read_text(errors='replace')
        opened = unclosed_fence(text)
        if opened:
            errors.append(f'{shown(path)}:{opened}: code fence is never closed')
        errors.extend(link_errors(path))
    if not argv:
        errors.extend(catalog_errors())
        errors.extend(diagram_errors())
    for error in errors:
        print(error)
    print(f'check-docs: {len(files)} Markdown files, {len(errors)} errors')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
