"""Prompt authority. Every mutation uses an optimistic generation in one transaction."""
from dataclasses import asdict
from datetime import datetime, timezone
from difflib import unified_diff
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from my_harness.core.engine.prompts import VARIABLES, Template, builtin_catalog, digest, dump_catalog, validate
from my_harness.core.engine.context import IntakeContext, profile_name
from my_harness.storage.managed import Conflict
from my_harness.storage.models import PromptHeadRow as Head, PromptVersionRow as Version, PromptActivationRow as Activation
from my_harness.i18n import tr


def now():
    return datetime.now(timezone.utc).isoformat()


def template(row):
    return Template(**{key: getattr(row, key) for key in Template.__dataclass_fields__})


class PromptRepository:
    def __init__(self, engine):
        self.engine = engine

    def owner(self, context, scope):
        if scope not in {'core', 'profile', 'project'}:
            raise ValueError(tr('prompts.unknown_prompt_scope'))
        if scope == 'profile' and profile_name(context) is None:
            raise ValueError(tr('profile_proposal.required'))
        return {'core': 'core', 'profile': profile_name(context), 'project': str(context.root)}[scope]

    def key(self, context, scope, name):
        if name not in VARIABLES:
            raise LookupError(tr('prompts.unknown_prompt'))
        return {'scope': scope, 'owner': self.owner(context, scope), 'name': name}

    def _catalog(self, session, context):
        catalog = builtin_catalog()
        for scope in ('core', 'profile', 'project'):
            if scope == 'profile' and isinstance(context, IntakeContext):
                continue
            heads = session.scalars(select(Head).where(Head.scope == scope, Head.owner == self.owner(context, scope))).all()
            for head in heads:
                if head.name not in VARIABLES:
                    continue  # Retired prompt heads remain data, never a current catalog entry.
                if head.active_id:
                    row = session.get(Version, head.active_id)
                    if row is None or (row.scope, row.owner, row.name) != (head.scope, head.owner, head.name):
                        raise ValueError('Broken prompt activation')
                    catalog[head.name] = template(row)
        dump_catalog(catalog)
        return catalog

    def catalog(self, context):
        # A single SQLite read transaction: no mixture of activations across the hierarchy.
        with Session(self.engine) as session:
            return self._catalog(session, context)

    def _version(self, session, context, name, version_id):
        base = builtin_catalog()[name]
        if version_id == base.id:
            return base
        row = session.get(Version, version_id)
        if row is None or row.name != name or row.owner != self.owner(context, row.scope):
            raise LookupError(tr('prompts.version_not_available_project'))
        value = template(row)
        value.check()
        return value

    def detail(self, context, scope, name):
        key = self.key(context, scope, name)
        with Session(self.engine) as session:
            head = session.get(Head, tuple(key.values()))
            versions = session.scalars(select(Version).where(
                Version.name == name,
                ((Version.scope == 'core') & (Version.owner == 'core')) |
                ((Version.scope == 'profile') & (Version.owner == profile_name(context))) |
                ((Version.scope == 'project') & (Version.owner == str(context.root))))
                .order_by(Version.created_at, Version.id)).all()
            activations = session.scalars(select(Activation).filter_by(**key).order_by(Activation.generation)).all()
            return {'name': name, 'scope': scope, 'owner': key['owner'],
                    'generation': head.generation if head else 0, 'active_id': head.active_id if head else None,
                    'effective': asdict(self._catalog(session, context)[name]), 'variables': list(VARIABLES[name]),
                    'versions': [asdict(builtin_catalog()[name])] + [asdict(template(v)) for v in versions],
                    'activations': [{'previous_id': a.previous_id, 'version_id': a.version_id,
                                     'reason': a.reason, 'generation': a.generation, 'created_at': a.created_at} for a in activations]}

    def _advance(self, session, key, expected):
        session.execute(insert(Head).values(**key, generation=0, active_id=None).on_conflict_do_nothing())
        changed = session.execute(update(Head).filter_by(**key, generation=expected).values(generation=Head.generation + 1))
        if changed.rowcount != 1:
            raise Conflict(tr('prompts.prompt_generation_changed_reload'))
        return session.get(Head, tuple(key.values()))

    def draft(self, context, scope, name, expected, *, text=None, from_version=None):
        key = self.key(context, scope, name)
        if (text is None) == (from_version is None):
            raise ValueError(tr('prompts.provide_template_rollback_source'))
        with Session(self.engine) as session, session.begin():
            self._advance(session, key, expected)
            source = 'editor'
            if from_version is not None:
                previous = self._version(session, context, name, from_version)
                text, source = previous.template, 'rollback:' + previous.id
            validate(name, text)
            row = Version(**key, id=str(uuid4()), template=text, sha256=digest(text), source=source, created_at=now())
            session.add(row)
            return asdict(template(row))

    def activate(self, context, scope, name, expected, version_id, reason):
        key = self.key(context, scope, name)
        if not reason.strip():
            raise ValueError(tr('prompts.activation_requires_reason'))
        with Session(self.engine) as session, session.begin():
            head = self._advance(session, key, expected)
            version = self._version(session, context, name, version_id)
            if (version.scope, version.owner) != (scope, key['owner']) or version.id.startswith('builtin-'):
                raise ValueError(tr('prompts.activate_saved_draft_selected'))
            version.check()
            session.add(Activation(**key, id=str(uuid4()), previous_id=head.active_id, version_id=version.id,
                                   generation=head.generation, reason=reason, created_at=now()))
            head.active_id = version.id

    def diff(self, context, name, before, after):
        self.key(context, 'project', name)
        with Session(self.engine) as session:
            a, b = (self._version(session, context, name, v) for v in (before, after))
            return ''.join(unified_diff(a.template.splitlines(keepends=True), b.template.splitlines(keepends=True),
                                        fromfile=a.id, tofile=b.id))
