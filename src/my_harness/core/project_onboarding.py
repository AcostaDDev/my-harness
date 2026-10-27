"""P008-T013: static facts of a repository without a harness, without importing or executing its code.

Python AST and a JS/TS/Prisma lexer (explicit subset, without resolving dynamic code). Each finding cites
path and line. The profile proposal is a local-config-4 value pending confirmation, never active
configuration or authorization. No access to disk, processes, providers or SQLite.
"""

import ast
import hashlib
import json
from pathlib import PurePosixPath
import re
import tomllib

from my_harness.core.engine.contracts import freeze
from my_harness.core.tree import TreeEntry
from my_harness.i18n import tr

INVENTORY_FORMAT = 'harness-local/onboarding-inventory/1'
MAX_ENTRIES = 50000
MAX_ENTRY_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
IGNORED = {'.git', '.harness', '.venv', 'venv', 'env', 'node_modules', 'vendor', 'dist', 'build', 'coverage',
           '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.tox', '.nox', '.next', '.nuxt',
           '.output', '.local', 'site-packages', 'htmlcov', 'target'}
SOURCE_SUFFIXES = {'.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.prisma', '.go'}
MANIFESTS = {'pyproject.toml', 'package.json', 'go.mod', 'pytest.ini', 'tox.ini', 'setup.cfg', 'mypy.ini',
             'ruff.toml', '.ruff.toml', 'tsconfig.json', 'Jenkinsfile', '.gitlab-ci.yml', '.travis.yml',
             'README.md', 'AGENTS.md', 'CLAUDE.md', 'GEMINI.md'}


class OnboardingInventoryError(ValueError):
    """A bounded, verifiable snapshot of the repository cannot be obtained."""


def in_scope(path: str) -> bool:
    pure = PurePosixPath(path)
    if (pure.is_absolute() or '..' in pure.parts or '\\' in path
            or any(part in IGNORED for part in pure.parts)):
        return False
    return (pure.suffix in SOURCE_SUFFIXES or pure.name in MANIFESTS
            or (pure.name.startswith('requirements') and pure.suffix == '.txt')
            or path.startswith(('.github/workflows/', '.circleci/')))


def fingerprint(inventory: dict) -> str:
    body = {key: value for key, value in inventory.items() if key not in ('head', 'inventory_sha256')}
    return hashlib.sha256(freeze(body).encode('utf-8')).hexdigest()


def _dotted(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _dotted(node.value) + '.' + node.attr
    return ''


def _literal(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _python(path: str, text: str, result: dict, tools: dict):
    module = ast.parse(text, filename=path)
    aliases = {}
    for node in module.body:
        if isinstance(node, ast.Import):
            for name in node.names:
                aliases[name.asname or name.name.split('.')[0]] = name.name if name.asname else name.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for name in node.names:
                aliases[name.asname or name.name] = node.module + '.' + name.name

    def resolve(node):
        dotted = _dotted(node)
        first, sep, rest = dotted.partition('.')
        return aliases.get(first, first) + (sep + rest if sep else '')

    def stack(name, line):
        result['stack'].append({'name': name, 'path': path, 'line': line})

    # Imports inside main()/tests are stack evidence too (manage.py usually imports it there).
    # Only module-level imports feed resolve(): a local binding is not assumed to exist outside its scope.
    for node in ast.walk(module):
        targets = ([name.name for name in node.names] if isinstance(node, ast.Import) else
                   [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
        for target in targets:
            package = target.split('.')[0]
            if package in ('django', 'sqlalchemy', 'fastapi'):
                stack(package, node.lineno)
            if package in ('pytest', 'unittest'):
                tools.setdefault(package, set()).add(path)

    # SQLAlchemy declarative roots verified within the module; a class is not guessed just for being named Base.
    bases = {name for name, target in aliases.items() if target in
             ('sqlalchemy.orm.DeclarativeBase', 'sqlalchemy.ext.declarative.DeclarativeMeta')}
    for node in module.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and resolve(node.value.func) in (
                'sqlalchemy.orm.declarative_base', 'sqlalchemy.ext.declarative.declarative_base'):
            bases.update(target.id for target in node.targets if isinstance(target, ast.Name))
    for node in module.body:
        if isinstance(node, ast.ClassDef) and any(_dotted(base) in bases or resolve(base) == 'sqlalchemy.orm.DeclarativeBase'
                                                 for base in node.bases):
            bases.add(node.name)

    routers = {}
    for node in module.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call):
            constructor = resolve(node.value.func)
            if constructor in ('fastapi.FastAPI', 'fastapi.APIRouter', 'fastapi.routing.APIRouter'):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                prefix = next((_literal(k.value) for k in node.value.keywords if k.arg == 'prefix'), '')
                for target in targets:
                    if isinstance(target, ast.Name):
                        routers[target.id] = prefix

    for node in module.body:
        if isinstance(node, ast.ClassDef):
            django = any(resolve(base) == 'django.db.models.Model' for base in node.bases)
            table = any(isinstance(s, ast.Assign) and any(_dotted(t) == '__tablename__' for t in s.targets)
                        for s in node.body)
            sqlalchemy = any(_dotted(base) in bases for base in node.bases) or (table and any(
                isinstance(s, (ast.Assign, ast.AnnAssign)) and isinstance(s.value, ast.Call)
                and resolve(s.value.func) in ('sqlalchemy.Column', 'sqlalchemy.orm.mapped_column') for s in node.body))
            if not django and not sqlalchemy:
                continue
            framework = 'django' if django else 'sqlalchemy'
            fields = []
            for statement in node.body:
                if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                value = statement.value
                if not isinstance(value, ast.Call):
                    continue
                constructor = resolve(value.func)
                short = constructor.rsplit('.', 1)[-1]
                if django and (not constructor.startswith('django.db.models.')
                               or not (short.endswith('Field') or short == 'ForeignKey')):
                    continue
                if sqlalchemy and constructor not in ('sqlalchemy.Column', 'sqlalchemy.orm.mapped_column',
                                                        'sqlalchemy.orm.relationship'):
                    continue
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    field = {'name': target.id, 'type': short, 'line': statement.lineno}
                    if short in ('ForeignKey', 'OneToOneField', 'ManyToManyField', 'relationship'):
                        target_node = value.args[0] if value.args else next(
                            (keyword.value for keyword in value.keywords if keyword.arg in ('to', 'argument')), None)
                        field.update(relation=short, target=_literal(target_node) or _dotted(target_node) or None)
                    elif sqlalchemy:
                        field['type'] = next((resolve(arg.func) if isinstance(arg, ast.Call) else resolve(arg)
                                              for arg in value.args
                                              if not isinstance(arg, ast.Constant)
                                              and not (isinstance(arg, ast.Call)
                                                       and resolve(arg.func) == 'sqlalchemy.ForeignKey')), short)
                        if isinstance(statement, ast.AnnAssign):
                            field['annotation'] = ast.unparse(statement.annotation)
                        foreign = next((arg for arg in value.args if isinstance(arg, ast.Call)
                                        and resolve(arg.func) == 'sqlalchemy.ForeignKey'), None)
                        if foreign is not None:
                            field.update(relation='ForeignKey', target=_literal(foreign.args[0]) if foreign.args else None)
                    fields.append(field)
            # A table-less DeclarativeBase and abstract bases are not persisted entities.
            abstract = any(isinstance(s, ast.Assign) and any(_dotted(t) == '__abstract__' for t in s.targets)
                           and isinstance(s.value, ast.Constant) and s.value.value is True for s in node.body)
            meta_abstract = any(isinstance(s, ast.ClassDef) and s.name == 'Meta' and any(
                isinstance(a, ast.Assign) and any(_dotted(t) == 'abstract' for t in a.targets)
                and isinstance(a.value, ast.Constant) and a.value.value is True for a in s.body) for s in node.body)
            if (django and not meta_abstract) or (sqlalchemy and not abstract and (table or fields)):
                result['entities'].append({'framework': framework, 'name': node.name, 'path': path,
                                           'line': node.lineno, 'fields': fields})
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                method, owner = decorator.func.attr, _dotted(decorator.func.value)
                if owner not in routers or method not in ('get', 'post', 'put', 'patch', 'delete', 'options', 'head', 'api_route'):
                    continue
                route = _literal(decorator.args[0]) if decorator.args else next(
                    (_literal(k.value) for k in decorator.keywords if k.arg == 'path'), None)
                result['routes'].append({'framework': 'fastapi', 'path': path, 'line': decorator.lineno,
                                         'method': method.upper(), 'route': route, 'prefix': routers[owner],
                                         'handler': node.name, 'dynamic': route is None or routers[owner] is None})
    for node in ast.walk(module):
        if isinstance(node, ast.Call) and resolve(node.func) in ('django.urls.path', 'django.urls.re_path'):
            route = _literal(node.args[0]) if node.args else None
            target = node.args[1] if len(node.args) > 1 else None
            include = isinstance(target, ast.Call) and resolve(target.func) == 'django.urls.include'
            result['routes'].append({'framework': 'django', 'path': path, 'line': node.lineno,
                                     'method': None, 'route': route,
                                     'kind': 'include' if include else resolve(node.func).rsplit('.', 1)[-1],
                                     'handler': (_literal(target.args[0]) if target.args else None) if include else _dotted(target),
                                     'dynamic': route is None})


# Tokens (value, type, line). Comments and strings are recognized before identifiers.
_TOKEN = re.compile(r'(?P<space>\s+)|(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)|'
                    r'(?P<string>"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`)|'
                    r'(?P<word>[A-Za-z_$][\w$]*)|(?P<punct>.)')


def _tokens(text):
    tokens, line, position = [], 1, 0
    regex = re.compile(r'/(?:\\.|\[(?:\\.|[^\]\\])*\]|[^/\n\\])+/[a-z]*')
    while position < len(text):
        match = _TOKEN.match(text, position)
        kind, value = match.lastgroup, match.group()
        # Regexp literals in expression position; their characters are not route/decorator code.
        if value == '/' and (not tokens or tokens[-1][0] in ('=', '(', ':', ',', '[', 'return', '!', '>')):
            literal = regex.match(text, position)
            if literal:
                value, kind = literal.group(), 'regex'
        if kind not in ('space', 'comment'):
            tokens.append((value, kind, line))
        line += value.count('\n')
        position += len(value)
    return tokens


def _string(token):
    value, kind, _ = token
    if kind != 'string' or (value.startswith('`') and '${' in value):
        return None
    # Do not interpret JS escapes as Python nor confuse them with exact literal routes.
    return value[1:-1] if '\\' not in value else None


def _close(tokens, index):
    pairs = {'(': ')', '[': ']', '{': '}'}
    stack = []
    for i in range(index, len(tokens)):
        value, kind, _ = tokens[i]
        if kind == 'string':
            continue
        if value in pairs:
            stack.append(pairs[value])
        elif value in pairs.values():
            if not stack or stack.pop() != value:
                return None
            if not stack:
                return i
    return None


def _javascript(path, text, result):
    tokens = _tokens(text)
    values = [token[0] for token in tokens]
    imports = {}
    # Explicit ESM imports, including aliases; require('express') is recognized for the common factory.
    for i, value in enumerate(values):
        if value == 'import':
            end = next((j for j in range(i + 1, min(i + 60, len(tokens))) if values[j] == 'from'), None)
            if end is None or end + 1 >= len(tokens):
                continue
            package = _string(tokens[end + 1])
            if package not in ('typeorm', 'express'):
                continue
            result['stack'].append({'name': package, 'path': path, 'line': tokens[i][2]})
            j = i + 1
            while j < end:
                if tokens[j][1] == 'word' and values[j] not in ('type', 'as'):
                    original = values[j]
                    alias = values[j + 2] if j + 2 < end and values[j + 1] == 'as' else original
                    imports[alias] = (package, original)
                    if alias != original:
                        j += 2
                j += 1
        if value == 'require' and i >= 2 and i + 3 < len(tokens) and values[i - 1] == '=':
            package = _string(tokens[i + 2]) if values[i + 1] == '(' else None
            if package == 'express':
                imports[values[i - 2]] = ('express', 'default')
                result['stack'].append({'name': package, 'path': path, 'line': tokens[i][2]})
    routers = set()
    for i in range(len(tokens) - 4):
        if values[i + 1] == '=' and imports.get(values[i + 2], ('',))[0] == 'express':
            if values[i + 3] == '(' or values[i + 3:i + 6] == ['.', 'Router', '(']:
                routers.add(values[i])
    decorators = {name: original for name, (package, original) in imports.items() if package == 'typeorm'}
    relations = {'ManyToOne', 'OneToMany', 'OneToOne', 'ManyToMany'}
    for i in range(len(tokens) - 3):
        if values[i] == '@' and decorators.get(values[i + 1]) == 'Entity':
            end = _close(tokens, i + 2) if values[i + 2] == '(' else i + 1
            if end is None:
                continue
            j = end + 1
            while j < len(tokens) and values[j] in ('export', 'default', 'abstract'):
                j += 1
            if j + 2 >= len(tokens) or values[j] != 'class':
                continue
            name = values[j + 1]
            start = next((k for k in range(j + 2, len(tokens)) if values[k] == '{'), None)
            stop = _close(tokens, start) if start is not None else None
            if stop is None:
                continue
            fields = []
            k = start + 1
            while k + 2 < stop:
                if values[k] != '@' or values[k + 1] not in decorators or values[k + 2] != '(':
                    # Skip methods/objects so nested decorators are not read as fields.
                    if values[k] == '{':
                        close = _close(tokens, k)
                        k = (close + 1) if close is not None else stop
                    else:
                        k += 1
                    continue
                decorator, line = decorators[values[k + 1]], tokens[k][2]
                close = _close(tokens, k + 2)
                if close is None:
                    break
                args = tokens[k + 3:close]
                field_start = close + 1
                # Other decorators on the same field (JoinColumn, Index…).
                while field_start + 2 < stop and values[field_start] == '@' and values[field_start + 2] == '(':
                    next_close = _close(tokens, field_start + 2)
                    if next_close is None:
                        break
                    field_start = next_close + 1
                while field_start < stop and values[field_start] in ('public', 'private', 'protected', 'readonly', 'declare'):
                    field_start += 1
                if field_start + 1 < stop and decorator in relations | {'Column', 'PrimaryColumn', 'PrimaryGeneratedColumn',
                                                                         'CreateDateColumn', 'UpdateDateColumn', 'DeleteDateColumn', 'VersionColumn'}:
                    field = {'name': values[field_start], 'type': decorator, 'line': line}
                    annotation = field_start + 1
                    if values[annotation] in ('!', '?'):
                        annotation += 1
                    if annotation < stop and values[annotation] == ':':
                        end_annotation = annotation + 1
                        while end_annotation < stop and values[end_annotation] not in (';', '=', '@', '}'):
                            end_annotation += 1
                        field['annotation'] = ''.join(values[annotation + 1:end_annotation])
                    if decorator in relations:
                        av = [t[0] for t in args]
                        arrow = next((a for a in range(len(av) - 1) if av[a:a + 2] == ['=', '>']), None)
                        target_tokens = args[arrow + 2:] if arrow is not None else args
                        first_arg = target_tokens[:next((n for n, t in enumerate(target_tokens) if t[0] == ','), len(target_tokens))]
                        dotted = ''.join(t[0] for t in first_arg)
                        target = (dotted if re.fullmatch(r'[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*', dotted)
                                  else _string(first_arg[0]) if len(first_arg) == 1 else None)
                        field.update(relation=decorator, target=target)
                    fields.append(field)
                k = close + 1
            result['entities'].append({'framework': 'typeorm', 'name': name, 'path': path,
                                       'line': tokens[j][2], 'fields': fields})
        if (values[i] in routers and values[i + 1] == '.'
                and values[i + 2] in ('get', 'post', 'put', 'patch', 'delete', 'options', 'head', 'all', 'use')
                and values[i + 3] == '('):
            # A string followed by +/another expression is not a literal route, even if it starts with a string.
            route = _string(tokens[i + 4]) if i + 5 < len(tokens) and values[i + 5] in (',', ')') else None
            result['routes'].append({'framework': 'express', 'path': path, 'line': tokens[i][2],
                                     'method': values[i + 2].upper(), 'route': route, 'dynamic': route is None})


def _prisma(path, text, result):
    result['stack'].append({'name': 'prisma', 'path': path, 'line': 1})
    tokens = _tokens(text)
    values = [token[0] for token in tokens]
    for i in range(len(tokens) - 2):
        if values[i] != 'model' or values[i + 2] != '{':
            continue
        end = _close(tokens, i + 2)
        if end is None:
            raise ValueError('Unclosed Prisma model block')
        fields, cursor = [], i + 3
        while cursor < end:
            line = tokens[cursor][2]
            row = []
            while cursor < end and tokens[cursor][2] == line:
                row.append(tokens[cursor])
                cursor += 1
            if len(row) < 2 or row[0][1] != 'word' or row[1][1] != 'word':
                continue
            # Nullability and list belong to the type, before the attributes.
            type_end = next((j for j, t in enumerate(row[2:], 2) if t[0] == '@'), len(row))
            suffix = ''.join(t[0] for t in row[2:type_end])
            fields.append({'name': row[0][0], 'type': row[1][0] + suffix, 'line': line})
        result['entities'].append({'framework': 'prisma', 'name': values[i + 1], 'path': path,
                                   'line': tokens[i][2], 'fields': fields})


def _manifest(path, text, result, tools, packages):
    name = PurePosixPath(path).name
    dependencies = []
    if name == 'package.json':
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError('package.json must be an object')
        for key in ('dependencies', 'devDependencies', 'peerDependencies'):
            group = data.get(key, {})
            if not isinstance(group, dict):
                raise ValueError(f'{key} must be an object')
            dependencies.extend(group)
        scripts = data.get('scripts', {})
        if not isinstance(scripts, dict) or not all(isinstance(v, str) for v in scripts.values()):
            raise ValueError('scripts must map names to strings')
        packages.append({'path': path, 'scripts': dict(sorted(scripts.items()))})
        result['stack'].append({'name': 'node', 'path': path, 'line': 1})
    elif name == 'pyproject.toml':
        data = tomllib.loads(text)
        dependencies.extend(data.get('project', {}).get('dependencies', []))
        for group in data.get('project', {}).get('optional-dependencies', {}).values():
            dependencies.extend(group)
        for group in data.get('dependency-groups', {}).values():
            dependencies.extend(item for item in group if isinstance(item, str))
        poetry = data.get('tool', {}).get('poetry', {})
        dependencies.extend(poetry.get('dependencies', {}))
        for group in poetry.get('group', {}).values():
            dependencies.extend(group.get('dependencies', {}))
        for tool in data.get('tool', {}):
            tools.setdefault(tool, set()).add(path)
        result['stack'].append({'name': 'python', 'path': path, 'line': 1})
    elif name.startswith('requirements') and name.endswith('.txt'):
        dependencies.extend(line.split('#', 1)[0].strip() for line in text.splitlines()
                            if line.strip() and not line.lstrip().startswith(('#', '-')))
        result['stack'].append({'name': 'python', 'path': path, 'line': 1})
    elif name == 'go.mod':
        result['stack'].append({'name': 'go', 'path': path, 'line': 1})
    for dependency in dependencies:
        if not isinstance(dependency, str):
            raise ValueError('Dependency names must be strings')
        match = re.match(r'([A-Za-z0-9_@/.-]+)', dependency)
        if not match:
            continue
        tool = match[1].lower().replace('_', '-')
        tools.setdefault(tool, set()).add(path)
        if tool in ('django', 'fastapi', 'sqlalchemy', 'typescript', 'express', 'typeorm', 'prisma', '@prisma/client', 'react', 'vue'):
            result['stack'].append({'name': tool, 'path': path, 'line': 1})
    config_tools = {'pytest.ini': 'pytest', 'mypy.ini': 'mypy', 'ruff.toml': 'ruff', '.ruff.toml': 'ruff'}
    if name in config_tools:
        tools.setdefault(config_tools[name], set()).add(path)


def _profile(result, tools, packages):
    commands, evidence = [], []

    def add(argv, paths, cwd='.'):
        command = {'argv': argv, 'cwd': cwd, 'timeout_seconds': 900}
        if command not in commands:
            commands.append(command)
            evidence.append({'argv': argv, 'cwd': cwd, 'paths': sorted(paths)})

    python_roots = {str(PurePosixPath(e['path']).parent) for e in result['entries'] if e['status'] == 'read'
                    and (PurePosixPath(e['path']).name == 'pyproject.toml'
                         or PurePosixPath(e['path']).name.startswith('requirements'))}

    def python_commands(argv, paths):
        grouped = {}
        for path in paths:
            parents = [p for p in python_roots if p == '.' or path.startswith(p + '/')]
            cwd = max(parents, key=len) if parents else '.'
            grouped.setdefault(cwd, []).append(path)
        for cwd, proofs in sorted(grouped.items()):
            add(argv, proofs, cwd)

    for tool, argv in (('pytest', ['pytest', '-q']), ('ruff', ['ruff', 'check', '.']),
                       ('ruff', ['ruff', 'format', '--check', '.']), ('mypy', ['mypy', '.'])):
        if tool in tools:
            python_commands(argv, tools[tool])
    if 'unittest' in tools and 'pytest' not in tools:
        python_commands(['python', '-m', 'unittest', 'discover'], tools['unittest'])
    django = any(item['name'] == 'django' for item in result['stack'])
    if django:
        for entry in result['entries']:
            if PurePosixPath(entry['path']).name == 'manage.py' and entry['status'] == 'read':
                cwd = str(PurePosixPath(entry['path']).parent)
                add(['python', 'manage.py', 'check'], [entry['path']], cwd)
                add(['python', 'manage.py', 'makemigrations', '--check', '--dry-run', '--noinput'], [entry['path']], cwd)
    for package in packages:
        for script in ('test', 'lint', 'typecheck', 'check', 'build'):
            if script in package['scripts']:
                add(['npm', 'run', script], [package['path']], str(PurePosixPath(package['path']).parent))
    for entry in result['entries']:
        if PurePosixPath(entry['path']).name == 'go.mod' and entry['status'] == 'read':
            add(['go', 'test', './...'], [entry['path']], str(PurePosixPath(entry['path']).parent))
    names = {item['name'] for item in result['stack']}
    name = 'onboarding-django' if django else ('onboarding-typescript' if 'typescript' in names else 'onboarding-project')
    profile = {
        'preparation': [], 'validations': commands,
        'allowed_command_prefixes': sorted({tuple(c['argv']) for c in commands}),
        'protected_paths': ['docs/STATE.md', 'docs/NEXT_STEPS.md', 'docs/ROADMAP.md', 'docs/DECISIONS.md',
                            'docs/archive/**', 'AGENTS.md', 'CLAUDE.md', 'GEMINI.md', '.harness/**', '.codex/**',
                            '.claude/**', 'pyproject.toml', '**/package.json', 'package.json', '*lock*', '**/*lock*',
                            'requirements*.txt', '.github/**', '.gitignore'],
        'sensitive_paths': ['.env', '.env.*', '**/.env', '**/.env.*', '*.pem', '**/*.pem', '*.key', '**/*.key',
                            '*.sqlite3', '**/*.sqlite3'],
        'data_model_paths': sorted({item['path'] for item in result['entities']}),
        'executor_instructions': ('Work within the frozen task paths. Keep the confirmed validations passing. '
                                  'Update docs/DDBB-DIAGRAM.md when data models change and docs/flows/ when flows change. '
                                  'Do not weaken tests or tool configuration. Installation and network need separate authorization.'),
    }
    profile['allowed_command_prefixes'] = [list(argv) for argv in profile['allowed_command_prefixes']]
    return {'format': 'local-config-4', 'profiles': {name: profile}, 'requires_confirmation': True,
            'ready': bool(commands), 'command_evidence': evidence,
            'notes': ['Review argv, cwd, timeouts, model patterns and scripts before declaring the profile.',
                      'Executable paths, environment and composition must be supplied by the operator.',
                      'No commands authorized or executed; no TOML written.']}


def build_inventory(entries: tuple[TreeEntry, ...], *, head: str, tree: str) -> dict:
    selected = sorted((entry for entry in entries if in_scope(entry.path)), key=lambda item: item.path)
    if len(entries) > MAX_ENTRIES or sum(len(e.data) for e in selected if e.data is not None) > MAX_TOTAL_BYTES:
        raise OnboardingInventoryError(tr('onboarding.inventory_limits_exceeded'))
    if len({entry.path for entry in selected}) != len(selected):
        raise OnboardingInventoryError(tr('onboarding.duplicate_source_paths'))
    result = {'format': INVENTORY_FORMAT, 'head': head, 'tree': tree, 'source': 'git-head',
              'entries': [], 'stack': [], 'entities': [], 'relationships': [], 'routes': [], 'tests': [],
              'ci': [], 'packages': [], 'diagnostics': [],
              'limitations': ['Static declarations only; dynamic expressions and cross-module resolution are not evaluated.',
                              'JS/TS/Prisma use a lexical subset; this is not a complete type checker or runtime schema.',
                              'Routes are local declarations; mounts, includes and imported prefixes are not expanded.',
                              'Only selected tracked HEAD sources; local changes and untracked files are not inspected.']}
    tools, packages = {}, []
    for entry in selected:
        data = entry.data
        diagnostic = entry.diagnostic
        if entry.mode not in ('100644', '100755'):
            diagnostic = diagnostic or 'Symbolic link or submodule: not read.'
        elif data is None:
            diagnostic = diagnostic or 'Source bytes unavailable.'
        elif len(data) > MAX_ENTRY_BYTES:
            diagnostic = f'Entry over {MAX_ENTRY_BYTES} bytes: not analysed.'
        elif entry.size != len(data):
            raise OnboardingInventoryError(f'Source size mismatch: {entry.path}')
        item = {'path': entry.path, 'size': entry.size, 'mode': entry.mode,
                'sha256': hashlib.sha256(data).hexdigest() if data is not None and not diagnostic else None,
                'status': 'rejected' if diagnostic else 'read'}
        result['entries'].append(item)
        if diagnostic:
            result['diagnostics'].append({'path': entry.path, 'diagnostic': diagnostic})
            continue
        try:
            text = data.decode('utf-8-sig')
            if '\0' in text:
                raise ValueError('Binary source: not analysed')
            path, pure = entry.path, PurePosixPath(entry.path)
            _manifest(path, text, result, tools, packages)
            if pure.suffix == '.py':
                _python(path, text, result, tools)
            elif pure.suffix in ('.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs'):
                _javascript(path, text, result)
            elif pure.suffix == '.prisma':
                _prisma(path, text, result)
            test = (pure.name.startswith('test_') or pure.name in ('tests.py', 'conftest.py')
                    or pure.name.endswith(('_test.py', '_test.go'))
                    or re.search(r'\.(?:test|spec)\.[cm]?[jt]sx?$', pure.name)
                    or any(part in ('tests', '__tests__') for part in pure.parts))
            if test and pure.suffix in SOURCE_SUFFIXES:
                result['tests'].append({'path': path})
            if (path.startswith(('.github/workflows/', '.circleci/'))
                    or pure.name in ('.gitlab-ci.yml', '.travis.yml', 'Jenkinsfile')):
                result['ci'].append({'path': path})
        except (ValueError, SyntaxError, TypeError, AttributeError, RecursionError) as exc:
            result['diagnostics'].append({'path': entry.path, 'diagnostic': f'Static analysis incomplete: {exc}'})
    prisma_names = {e['name'] for e in result['entities'] if e['framework'] == 'prisma'}
    for entity in result['entities']:
        for field in entity['fields']:
            if entity['framework'] == 'prisma' and field['type'].rstrip('[]?') in prisma_names:
                field.update(relation='list' if '[]' in field['type'] else 'reference', target=field['type'].rstrip('[]?'))
            if 'relation' in field:
                result['relationships'].append({'framework': entity['framework'], 'path': entity['path'],
                    'source': entity['name'], 'field': field['name'], 'target': field['target'],
                    'kind': field['relation'], 'line': field['line']})
    result['packages'] = packages
    result['stack'] = sorted({(s['name'], s['path'], s['line']) for s in result['stack']})
    result['stack'] = [dict(zip(('name', 'path', 'line'), row)) for row in result['stack']]
    result['profile_proposal'] = _profile(result, tools, packages)
    result['inventory_sha256'] = fingerprint(result)
    return result
