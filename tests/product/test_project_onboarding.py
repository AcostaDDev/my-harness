"""Flow B: synthetic checkouts and sources; no framework or project code is executed."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from my_harness.adapters.git import Git
from my_harness.adapters.project_onboarding import read_inventory
from my_harness.core.tree import ImportInventoryError, TreeEntry
from my_harness.core.project_onboarding import (
    INVENTORY_FORMAT, MAX_ENTRY_BYTES, OnboardingInventoryError, build_inventory, fingerprint,
)
from my_harness.services.local_config import _profile

GIT_ENV = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_AUTHOR_NAME': 'Synthetic Author', 'GIT_AUTHOR_EMAIL': 'author@example.invalid',
           'GIT_COMMITTER_NAME': 'Synthetic Author', 'GIT_COMMITTER_EMAIL': 'author@example.invalid'}

DJANGO = {
    'pyproject.toml': '''[project]
name = "synthetic-library"
dependencies = ["Django>=5", "psycopg"]
[dependency-groups]
dev = ["pytest-django", "pytest", "ruff", "mypy"]
[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings"
''',
    'manage.py': ("def main():\n    from django.core.management import execute_from_command_line\n"
                  "    raise RuntimeError('Must never execute manage.py')\n"),
    'library/models.py': '''from django.db import models as db
raise RuntimeError("Must never import the application")
class Author(db.Model):
    name = db.CharField(max_length=80)
class Book(db.Model):
    title = db.CharField(max_length=100)
    author = db.ForeignKey("library.Author", on_delete=db.CASCADE)
    editors = db.ManyToManyField(to="library.Author", related_name="edited")
class AbstractRecord(db.Model):
    created = db.DateTimeField()
    class Meta:
        abstract = True
class Unrelated:
    author = "Not an entity"
''',
    'config/urls.py': '''from django.urls import path, include
urlpatterns = [path("api/", include("library.urls"))]
''',
    'library/urls.py': '''from django.urls import path as url
from . import views
urlpatterns = [url("books/", views.books), url("books/<int:pk>/", views.book)]
''',
    'library/views.py': "def books(request): pass\ndef book(request, pk): pass\n",
    'tests/test_books.py': 'import pytest\ndef test_books(): assert True\n',
    '.github/workflows/tests.yml': 'name: tests\njobs:\n  test:\n    steps:\n      - run: pytest -q\n',
    'README.md': '# Synthetic library\n',
    '.gitignore': '.env\n.local/\n',
}
TYPESCRIPT = {
    'web/package.json': json.dumps({'name': 'synthetic-web', 'dependencies': {'express': '5', 'typeorm': '0.3'},
        'devDependencies': {'typescript': '5', 'vitest': '3'},
        'scripts': {'test': 'vitest run', 'lint': 'eslint .', 'typecheck': 'tsc --noEmit', 'build': 'tsc'}}),
    'web/src/entities.ts': '''import { Entity, PrimaryGeneratedColumn, Column, ManyToOne, JoinColumn } from "typeorm";
@Entity()
export class Author {
    @PrimaryGeneratedColumn()
    id!: number;
    @Column()
    name!: string;
}
@Entity("books")
export class Book {
    @PrimaryGeneratedColumn() id!: number;
    @Column() title!: string;
    @ManyToOne(() => Author, author => author.books)
    @JoinColumn()
    author!: Author;
}
// @Entity() class Fake {}
const misleading = "@Entity() class AnotherFake {}";
throw new Error("Must never execute TypeScript");
''',
    'web/src/routes.ts': '''import express, { Router as MakeRouter } from "express";
const app = express();
const router = MakeRouter();
app.get("/health", health);
router.post('/books', createBook);
router.get(`/books/${id}`, dynamic);
app.use("/api", router);
// app.delete('/comment', nope)
const example = "app.get('/string', nope)";
''',
    'web/src/books.test.ts': "import { test } from 'vitest'; test('synthetic', () => {});\n",
    'prisma/schema.prisma': '''datasource db {
  provider = "sqlite"
  url = env("DATABASE_URL")
}
model Author {
  id Int @id @default(autoincrement())
  name String
  books Book[]
}
model Book {
  id Int @id
  authorId Int
  author Author @relation(fields: [authorId], references: [id])
  title String?
}
''',
    '.gitlab-ci.yml': 'test:\n  script: npm --prefix web test\n',
    '.gitignore': 'node_modules/\n.env\n',
}


def git(root, *args):
    # Fixture commits must finish without a detached writer changing subsequent byte snapshots.
    return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'gc.auto=0',
                           '-c', 'maintenance.auto=false', *args], cwd=root, env=GIT_ENV,
                          check=True, capture_output=True).stdout.decode().strip()


def checkout(root, files):
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'core.autocrlf', 'false')
    for path, value in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value.encode() if isinstance(value, str) else value)
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'synthetic source')
    return root


def pure(files):
    entries = tuple(TreeEntry(path, '100644', len(data), data) for path, value in files.items()
                    for data in [value.encode() if isinstance(value, str) else value])
    return build_inventory(entries, head='a' * 40, tree='b' * 40)


def test_checkout_fixture_does_not_start_automatic_git_maintenance(tmp_path, monkeypatch):
    trace = tmp_path / 'git-trace.jsonl'
    monkeypatch.setitem(GIT_ENV, 'GIT_TRACE2_EVENT', str(trace))
    checkout(tmp_path / 'repo', {'README.md': '# Synthetic fixture\n'})
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    # Check the real child processes, rather than racing a transient maintenance.lock.
    assert any(event['event'] == 'start' and 'commit' in event['argv'] for event in events)
    children = [event['argv'] for event in events if event['event'] == 'child_start']
    assert not any('maintenance' in argv or 'gc' in argv for argv in children), children


def snapshot(root):
    return {str(p.relative_to(root)): (p.lstat().st_mode, p.lstat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).hexdigest()) for p in root.rglob('*') if p.is_file() and not p.is_symlink()}


def proposed(result):
    proposal = result['profile_proposal']
    assert proposal['format'] == 'local-config-4' and proposal['requires_confirmation'] is True
    name, profile = next(iter(proposal['profiles'].items()))
    assert proposal['ready']
    # T008's parser validates the real proposal, not a parallel representation of the profile.
    parsed = _profile(name, profile)
    return parsed, profile


def test_django_inventory_entities_routes_tests_ci_and_profile(tmp_path):
    root = checkout(tmp_path / 'django', DJANGO)
    before = snapshot(root)
    result = read_inventory(root)
    assert result == read_inventory(root)
    assert snapshot(root) == before
    assert result['format'] == INVENTORY_FORMAT
    assert result['source'] == 'git-head' and result['head'] == git(root, 'rev-parse', 'HEAD')
    assert result['inventory_sha256'] == fingerprint(result)
    assert result['diagnostics'] == []
    assert {s['name'] for s in result['stack']} == {'python', 'django'}
    assert [e['name'] for e in result['entities']] == ['Author', 'Book']
    assert [[f['name'] for f in e['fields']] for e in result['entities']] == [['name'], ['title', 'author', 'editors']]
    assert [(r['source'], r['field'], r['target'], r['kind']) for r in result['relationships']] == [
        ('Book', 'author', 'library.Author', 'ForeignKey'), ('Book', 'editors', 'library.Author', 'ManyToManyField')]
    assert [(r['route'], r['handler']) for r in result['routes']] == [
        ('api/', 'library.urls'), ('books/', 'views.books'), ('books/<int:pk>/', 'views.book')]
    assert result['tests'] == [{'path': 'tests/test_books.py'}]
    assert result['ci'] == [{'path': '.github/workflows/tests.yml'}]
    parsed, profile = proposed(result)
    assert [list(c.argv) for c in parsed.validations] == [
        ['pytest', '-q'], ['ruff', 'check', '.'], ['ruff', 'format', '--check', '.'], ['mypy', '.'],
        ['python', 'manage.py', 'check'], ['python', 'manage.py', 'makemigrations', '--check', '--dry-run', '--noinput']]
    assert profile['data_model_paths'] == ['library/models.py']
    assert len(result['profile_proposal']['command_evidence']) == len(parsed.validations)


def test_typescript_inventory_models_routes_and_commands(tmp_path):
    root = checkout(tmp_path / 'typescript', TYPESCRIPT)
    before = snapshot(root)
    result = read_inventory(root)
    assert result == read_inventory(root)
    assert snapshot(root) == before
    assert result['diagnostics'] == []
    assert {s['name'] for s in result['stack']} == {'node', 'express', 'typeorm', 'typescript', 'prisma'}
    assert [(e['framework'], e['name']) for e in result['entities']] == [
        ('prisma', 'Author'), ('prisma', 'Book'), ('typeorm', 'Author'), ('typeorm', 'Book')]
    assert [(r['framework'], r['source'], r['field'], r['target']) for r in result['relationships']] == [
        ('prisma', 'Author', 'books', 'Book'), ('prisma', 'Book', 'author', 'Author'),
        ('typeorm', 'Book', 'author', 'Author')]
    assert [f['name'] for f in result['entities'][-1]['fields']] == ['id', 'title', 'author']
    assert [f['annotation'] for f in result['entities'][-1]['fields']] == ['number', 'string', 'Author']
    assert [(r['method'], r['route'], r['dynamic']) for r in result['routes']] == [
        ('GET', '/health', False), ('POST', '/books', False), ('GET', None, True), ('USE', '/api', False)]
    assert result['tests'] == [{'path': 'web/src/books.test.ts'}]
    assert result['ci'] == [{'path': '.gitlab-ci.yml'}]
    parsed, profile = proposed(result)
    assert [(c.argv, c.cwd) for c in parsed.validations] == [
        (('npm', 'run', script), 'web') for script in ('test', 'lint', 'typecheck', 'build')]
    assert profile['data_model_paths'] == ['prisma/schema.prisma', 'web/src/entities.ts']


def test_sqlalchemy_and_fastapi_use_ast_and_import_aliases():
    result = pure({'models.py': '''from sqlalchemy import Column as Col, Integer, ForeignKey as FK, String
from sqlalchemy.orm import declarative_base, relationship, Mapped, mapped_column
Base = declarative_base()
class Author(Base):
    __tablename__ = 'authors'
    id = Col(Integer, primary_key=True)
class Book(Base):
    __tablename__ = 'books'
    id: Mapped[int] = mapped_column(primary_key=True)
    name = Col('book_name', String(100))
    author_id = Col(Integer, FK('authors.id'))
    author = relationship('Author')
''', 'api.py': '''from fastapi import FastAPI, APIRouter as Router
app = FastAPI()
router = Router(prefix="/v1")
@app.get('/health')
def health(): pass
@router.post(path='/books')
async def create(): pass
@router.get(dynamic_route)
def unknown(): pass
''', 'unrelated.py': '''class Model: pass
class Base: pass
class Fake(Base):
    id = Column(Integer)
# @app.get('/comment')
example = "class Ghost(models.Model): pass"
'''})
    assert result['diagnostics'] == []
    assert [e['name'] for e in result['entities']] == ['Author', 'Book']
    assert [f['type'] for f in result['entities'][1]['fields']] == ['mapped_column', 'sqlalchemy.String', 'sqlalchemy.Integer', 'relationship']
    assert [r['target'] for r in result['relationships']] == ['authors.id', 'Author']
    assert [(r['route'], r['prefix'], r['handler']) for r in result['routes']] == [
        ('/health', '', 'health'), ('/books', '/v1', 'create'), (None, '/v1', 'unknown')]
    assert result['routes'][-1]['dynamic']


def test_sqlalchemy_imported_base_and_declarativebase():
    result = pure({'models.py': '''import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, mapped_column
class Base(DeclarativeBase): pass
class User(Base):
    __tablename__ = 'users'
    id = mapped_column(sa.Integer, primary_key=True)
''', 'other.py': '''from application.db import Base
from sqlalchemy import Column, Integer
class Account(Base):
    __tablename__ = 'accounts'
    id = Column(Integer)
'''})
    assert [e['name'] for e in result['entities']] == ['User', 'Account']


def test_requirements_go_unittest_and_nested_python_commands():
    result = pure({'backend/requirements-dev.txt': 'django>=5\npytest==9\nruff\nmypy\n-r requirements.txt\n',
                   'backend/requirements.txt': 'Django>=5\n', 'backend/manage.py': 'raise RuntimeError\n',
                   'backend/tests/test_a.py': 'import pytest\n',
                   'service/go.mod': 'module example.invalid/synthetic\n', 'service/foo_test.go': 'package service\n'})
    parsed, _ = proposed(result)
    assert all(c.cwd == 'backend' for c in parsed.validations if c.argv[0] != 'go')
    assert parsed.validations[-1].argv == ('go', 'test', './...') and parsed.validations[-1].cwd == 'service'
    other = pure({'tests/test_a.py': 'import unittest\n'})
    assert proposed(other)[0].validations[0].argv == ('python', '-m', 'unittest', 'discover')
    manage = pure({'manage.py': DJANGO['manage.py']})
    assert {s['name'] for s in manage['stack']} == {'django'}
    assert len(proposed(manage)[0].validations) == 2


def test_dependencies_and_build_outputs_are_never_read_even_if_tracked(tmp_path, monkeypatch):
    files = {**DJANGO, **{path: 'class Fake: pass\n' for path in (
        'node_modules/lib/evil.py', '.venv/lib/evil.py', 'vendor/evil.py', 'dist/bundle.js', 'build/evil.py',
        '.local/evil.py', '__pycache__/evil.py', '.next/routes.ts', 'site-packages/evil.py')},
        'image.png': b'not source', 'secret.pem': 'synthetic private key'}
    # .local is ignored: the rest is versioned to check the tree filter, not just .gitignore.
    root = checkout(tmp_path / 'ignored', files)
    objects, calls = [], []
    original = Git.run

    def read_only(self, *args, **kwargs):
        calls.append(args)
        assert args[0] == '--no-lazy-fetch'
        args = args[1:]
        assert args[0] in ('rev-parse', 'ls-tree', 'cat-file')
        if args[0] == 'cat-file':
            assert args == ('cat-file', '--batch')
            objects.extend(kwargs['input'].decode().splitlines())
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Git, 'run', read_only)
    result = read_inventory(root)
    assert {e['path'] for e in result['entries']} == set(DJANGO) - {'.gitignore'}
    excluded = git(root, 'rev-parse', 'HEAD:node_modules/lib/evil.py')
    assert excluded not in objects
    assert not result['diagnostics']


def test_head_snapshot_does_not_execute_filters_hooks_or_dirty_project(tmp_path, monkeypatch):
    root = checkout(tmp_path / 'head', DJANGO)
    expected = read_inventory(root)
    sentinel = tmp_path / 'must-not-exist'
    trap = root / 'trap.sh'
    trap.write_text(f'#!/bin/sh\ntouch "{sentinel}"\nexit 1\n')
    trap.chmod(0o755)
    git(root, 'config', 'filter.trap.clean', str(trap))
    git(root, 'config', 'filter.trap.smudge', str(trap))
    git(root, 'config', 'core.fsmonitor', str(trap))
    (root / '.gitattributes').write_text('*.py filter=trap\n')
    (root / '.git/hooks/post-index-change').write_text(trap.read_text())
    (root / '.git/hooks/post-index-change').chmod(0o755)
    (root / 'manage.py').write_text('different local code\n')
    (root / '.env').write_text('SYNTHETIC_TOKEN=do-not-read\n')
    original = subprocess.run

    def only_git(argv, **kwargs):
        assert Path(argv[0]).name == 'git'
        return original(argv, **kwargs)

    monkeypatch.setattr(subprocess, 'run', only_git)
    before = snapshot(root)
    assert read_inventory(root) == expected
    assert snapshot(root) == before
    assert not sentinel.exists()


def test_symlinks_and_submodules_are_reported_without_following(tmp_path):
    root = checkout(tmp_path / 'links', DJANGO)
    outside = tmp_path / 'private.py'
    outside.write_text('raise RuntimeError("synthetic outside checkout")\n')
    (root / 'linked.py').symlink_to(outside)
    git(root, 'add', 'linked.py')
    head = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-index', '--add', '--cacheinfo', f'160000,{head},module.py')
    git(root, 'commit', '-qm', 'synthetic nonregular entries')
    result = read_inventory(root)
    entries = {e['path']: e for e in result['entries']}
    assert entries['linked.py']['sha256'] is None and entries['module.py']['status'] == 'rejected'
    assert {d['path'] for d in result['diagnostics']} == {'linked.py', 'module.py'}


@pytest.mark.parametrize('kind', ['not-git', 'no-commits', 'empty-head', 'nested-root'])
def test_invalid_roots_are_rejected(tmp_path, kind):
    root = tmp_path / 'repo'
    root.mkdir()
    if kind != 'not-git':
        git(root, 'init', '-q')
    if kind in ('empty-head', 'nested-root'):
        git(root, 'commit', '--allow-empty', '-qm', 'empty synthetic commit')
    if kind == 'nested-root':
        root = root / 'nested'
        root.mkdir()
    with pytest.raises(OnboardingInventoryError):
        read_inventory(root)


def test_malformed_and_oversized_sources_diagnose_instead_of_inventing():
    result = pure({'broken.py': 'class Invalid(', 'package.json': '{', 'pyproject.toml': '[broken',
                   'binary.ts': b'\x00binary', 'nonutf.py': b'\xff', 'too_big.py': b'x' * (MAX_ENTRY_BYTES + 1),
                   'prisma/schema.prisma': 'model Broken {\n'})
    assert len(result['diagnostics']) == 7
    assert result['entities'] == [] and result['routes'] == []
    assert not result['profile_proposal']['ready']
    assert next(e for e in result['entries'] if e['path'] == 'too_big.py')['status'] == 'rejected'


def test_fingerprint_is_root_and_commit_independent_but_content_sensitive(tmp_path):
    a = read_inventory(checkout(tmp_path / 'a', DJANGO))
    b = read_inventory(checkout(tmp_path / 'b', DJANGO))
    b['head'] = 'c' * 40
    assert fingerprint(a) == fingerprint(b)
    changed = copy.deepcopy(a)
    changed['routes'][0]['route'] = 'different/'
    assert fingerprint(a) != fingerprint(changed)
    entries = tuple(TreeEntry(path, '100644', len(data), data) for path, text in reversed(list(DJANGO.items()))
                    for data in [text.encode()])
    assert build_inventory(entries, head=a['head'], tree=a['tree']) == a


def test_limits_refuse_without_silent_truncation(tmp_path, monkeypatch):
    import my_harness.adapters.project_onboarding as adapter
    root = checkout(tmp_path / 'limits', DJANGO)
    monkeypatch.setattr(adapter, 'MAX_TOTAL_BYTES', 10)
    with pytest.raises(OnboardingInventoryError, match='bytes'):
        read_inventory(root)
    monkeypatch.setattr(adapter, 'MAX_TOTAL_BYTES', 32 * 1024 * 1024)
    monkeypatch.setattr(adapter, 'MAX_ENTRIES', 1)
    with pytest.raises(OnboardingInventoryError, match='entries'):
        read_inventory(root)
    monkeypatch.setattr(adapter, 'MAX_ENTRIES', 50000)

    def missing_blob(*args):
        raise ImportInventoryError('Synthetic object missing; no lazy fetch')

    monkeypatch.setattr(adapter, '_blobs', missing_blob)
    with pytest.raises(OnboardingInventoryError, match='object missing'):
        read_inventory(root)


def test_dynamic_expressions_are_not_evaluated_or_reported_as_static_routes():
    result = pure({'api.py': '''from fastapi import APIRouter
router = APIRouter(prefix=get_prefix())
@router.get(get_path())
def unknown(): pass
''', 'api.js': '''const express = require('express');
const app = express();
app.get(computePath(), handler);
app.get('/base/' + suffix, handler);
''', 'model.ts': '''import { Entity, ManyToOne } from 'typeorm';
@Entity()
class Book {
    @ManyToOne(() => resolveEntity())
    author: unknown;
}
'''})
    assert len(result['routes']) == 3
    assert all(r['route'] is None and r['dynamic'] for r in result['routes'])
    assert result['relationships'][0]['target'] is None


def test_invalid_source_size_and_duplicate_paths_refuse():
    entry = TreeEntry('app.py', '100644', 3, b'pass')
    with pytest.raises(OnboardingInventoryError, match='size mismatch'):
        build_inventory((entry,), head='a', tree='b')
    with pytest.raises(OnboardingInventoryError, match='Duplicate'):
        build_inventory((entry, entry), head='a', tree='b')


def test_comments_strings_regex_and_non_fields_do_not_create_entities_or_routes():
    result = pure({'api.ts': '''import express from 'express';
const app = express();
const regex = /app.get('phantom', handler)/;
const template = `app.post('phantom', handler)`;
/* app.get('phantom', handler); @Entity() class Phantom {} */
app.get('/real', handler);
''', 'models.py': '''from django.db import models
class Item(models.Model):
    objects = models.Manager()
    name = models.CharField(max_length=32)
'''})
    assert [r['route'] for r in result['routes']] == ['/real']
    assert [e['name'] for e in result['entities']] == ['Item']
    assert [f['name'] for f in result['entities'][0]['fields']] == ['name']


def test_profile_is_only_a_proposal_and_reports_missing_validators():
    result = pure({'README.md': '# Existing repository\n', 'app.py': 'print("static source only")\n'})
    assert not result['profile_proposal']['ready']
    assert result['profile_proposal']['requires_confirmation']
    profile = next(iter(result['profile_proposal']['profiles'].values()))
    assert profile['validations'] == [] and profile['preparation'] == []
    assert len(result['inventory_sha256']) == 64


def test_each_source_entry_has_exact_hash_and_findings_have_source_locations():
    result = pure(TYPESCRIPT)
    for entry in result['entries']:
        assert entry['sha256'] == hashlib.sha256(TYPESCRIPT[entry['path']].encode()).hexdigest()
    for field in ('stack', 'entities', 'relationships', 'routes'):
        for item in result[field]:
            assert item['path'] in TYPESCRIPT and item['line'] > 0
