"""D291: exact, versioned permission targets. No resolver, shell or network side effects."""
import hashlib
from my_harness.i18n import tr
import ipaddress
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

from my_harness.core.engine.domain_catalogue import CATALOGUE, digest
from my_harness.core.engine.permissions import KINDS

FORMAT = 'permission-target-1'


def clean(value):
    if not isinstance(value, str) or not value or len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(tr('domain.permission_invalid'))
    return value


def path(value, root, *, directory=False):
    clean(value)
    parts = value.split('/')
    if value.startswith('/') or '\\' in value or '..' in parts or any(c in value for c in '*?[]'):
        raise ValueError(tr('domain.permission_invalid'))
    parts = [p for p in parts if p not in ('', '.')]
    if not parts and not directory:
        raise ValueError(tr('domain.permission_invalid'))
    parent = Path(root)
    if parent.is_symlink() or not parent.is_absolute() or parent.resolve() != parent:
        raise ValueError(tr('domain.permission_invalid'))
    for part in parts:
        if parent.exists():
            names = [p.name for p in parent.iterdir()] if parent.is_dir() else []
            aliases = [n for n in names if unicodedata.normalize('NFC', n).casefold() == unicodedata.normalize('NFC', part).casefold()]
            if aliases and (part not in names or len(aliases) != 1):
                raise ValueError(tr('domain.permission_invalid'))
        parent = parent / part
        if parent.is_symlink():
            raise ValueError(tr('domain.permission_invalid'))
    return '/'.join(parts) or '.'


def normalize(dimension, value, root):
    if dimension not in KINDS or not isinstance(value, dict):
        raise ValueError(tr('domain.permission_invalid'))
    def fields(*names):
        if set(value) != set(names):
            raise ValueError(tr('domain.permission_invalid'))
    if dimension == 'files':
        fields('path', 'operation')
        if value['operation'] not in ('read', 'write'):
            raise ValueError(tr('domain.permission_invalid'))
        target = {**value, 'path': path(value['path'], root)}
    elif dimension == 'tools' and 'domain' in value:
        fields('domain', 'version', 'schema_sha256')
        if type(value['version']) is not int or not isinstance(value['domain'], str):
            raise ValueError(tr('domain.permission_invalid'))
        entry = CATALOGUE.get(value['domain'], value['version'])
        if not entry or entry.schema_sha256 != value['schema_sha256']:
            raise ValueError(tr('domain.permission_invalid'))
        target = dict(value)
    elif dimension == 'tools':
        fields('executable', 'sha256', 'argv', 'cwd', 'environment')
        exe = Path(clean(value['executable']))
        if not exe.is_absolute() or exe.is_symlink() or exe.resolve() != exe or not exe.is_file():
            raise ValueError(tr('domain.permission_invalid'))
        if hashlib.sha256(exe.read_bytes()).hexdigest() != value['sha256']:
            raise ValueError(tr('domain.permission_invalid'))
        argv = value['argv']
        if not isinstance(argv, list) or not argv or argv[0] != str(exe) or not all(isinstance(a, str) and '\x00' not in a for a in argv):
            raise ValueError(tr('domain.permission_invalid'))
        if re.search(r'^(ba|da|z|fi|k|c)?sh$|^(python|node|perl|ruby|env|sudo|xargs)([0-9.]*)$', exe.name):
            raise ValueError(tr('domain.permission_invalid'))
        if not isinstance(value['environment'], dict) or any(not re.fullmatch(r'[A-Z_][A-Z0-9_]*', k) or not isinstance(v, str) or '\x00' in v for k, v in value['environment'].items()):
            raise ValueError(tr('domain.permission_invalid'))
        if any(k.startswith(('LD_', 'DYLD_', 'PYTHON', 'NODE_')) or k in ('PATH', 'ENV', 'BASH_ENV') for k in value['environment']):
            raise ValueError(tr('domain.permission_invalid'))
        target = {**value, 'cwd': path(value['cwd'], root, directory=True)}
    elif dimension == 'network':
        fields('destination')
        raw = clean(value['destination'])
        if any(c in raw for c in '%\\*?#') or not raw.isascii():
            raise ValueError(tr('domain.permission_invalid'))
        url = urlsplit(raw)
        host = url.hostname
        if url.scheme not in ('http', 'https', 'tcp') or not host or url.username is not None or url.password is not None or url.path or url.query or url.fragment or host.endswith('.'):
            raise ValueError(tr('domain.permission_invalid'))
        try:
            host = ipaddress.ip_address(host).compressed
        except ValueError:
            if re.fullmatch(r'[0-9.]+', host) or all(re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)', label) for label in host.split('.')) or len(host) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.')):
                raise ValueError(tr('domain.permission_invalid')) from None
        port = url.port if url.port is not None else {'http': 80, 'https': 443}.get(url.scheme)
        if port is None or not 1 <= port <= 65535 or url.netloc.endswith(':'):
            raise ValueError(tr('domain.permission_invalid'))
        target = {'scheme': url.scheme, 'host': host, 'port': port}
    else:
        fields('capability', 'entity', 'revision', 'evidence')
        for k in value:
            clean(value[k])
        if dimension == 'product' and not re.fullmatch(r'knowledge\.(propose|adopt):[a-z_:]+', value['capability']):
            raise ValueError(tr('domain.permission_invalid'))
        if dimension == 'acceptance' and value['capability'] != 'acceptance.verify':
            raise ValueError(tr('domain.permission_invalid'))
        target = dict(value)
    return {'format': FORMAT, 'dimension': dimension, 'target': target}


def token(target):
    value = target['target']
    if target['dimension'] == 'tools' and 'domain' in value:
        return f"domain:{value['domain']}@{value['version']}"
    if target['dimension'] == 'product':
        return value['capability']
    return 'exact:' + digest(target)


def owner_only(target):
    """Classification is service-owned. Generic command grants never authorize their other effects."""
    value = target['target']
    if target['dimension'] == 'tools':
        # A digest proves identity, not semantics. Opaque native programs (including wrappers/renamed
        # binaries) cannot establish absence of owner-only effects from their filename or argv.
        # Exact owner-authorized native commands keep their independent ManagedCommandRunner path.
        if 'domain' not in value:
            return True
        entry = CATALOGUE.get(value['domain'], value['version'])
        return (entry is None or entry.schema_sha256 != value['schema_sha256'] or
                not any(p in entry.principals for p in ('agent', 'harness')))
    return (target['dimension'] == 'acceptance' or
            target['dimension'] == 'product' and value['capability'] == 'knowledge.adopt:owner_only' or
            target['dimension'] == 'files' and (value['path'].split('/')[0] in ('.git', '.aws', '.ssh', '.codex', '.claude') or
                value['path'].split('/')[-1] in ('AGENTS.md', 'CLAUDE.md', 'GEMINI.md', '.env')))
