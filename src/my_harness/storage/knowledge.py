"""P002-T004 (D284, D285): structured knowledge repository.

Drafts are complete copy-on-write manifests of a base revision; adoption is a compare-and-set against the current
accepted head that seals the next number and hashes. Accepted state is immutable in the database (triggers of 0030);
retrieval recomputes every hash and the chain to the root and refuses to serve anything that does not match.
Product paths reach it only through the P002-T005 domain service (D286), which checks authority and shares its
transaction through `KnowledgeSession`.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from my_harness.core.engine import knowledge as core
from my_harness.core.engine.contracts import ContractError
from my_harness.i18n import tr
from my_harness.storage.models import (
    KnowledgeIdentityRow, KnowledgeItemRow, KnowledgeItemVersionRow, KnowledgeProjectRow, KnowledgeRevisionLinkRow,
    KnowledgeRevisionMemberRow, KnowledgeRevisionRow,
)


def now() -> str:
    return datetime.now(UTC).isoformat()


class StaleRevision(ValueError):
    """The draft's base is no longer the accepted head (or the expected revision was wrong)."""


class KnowledgeIntegrityError(RuntimeError):
    """Stored knowledge does not match its hashes, chain or structural rules; nothing is served."""


@dataclass(frozen=True)
class Revision:
    id: str
    project_id: str
    number: int
    base_revision_id: str | None
    knowledge_sha256: str
    revision_sha256: str
    origin: str
    actor: dict
    reason: str | None
    changes: dict
    accepted_at: str
    members: dict[str, core.Member]
    links: tuple[core.Link, ...]

    def item(self, kind: str, code: str, document: str | None = None) -> core.Member | None:
        return next((m for m in self.members.values()
                     if m.kind == kind and m.code == code and m.document == document), None)

    def children(self, kind: str, target: str) -> list[str]:
        return [l.source for l in sorted((l for l in self.links if l.kind == kind and l.target == target),
                                         key=lambda l: l.position)]

    def roots(self, document: str) -> list[str]:
        return [m.item_id for m in sorted((m for m in self.members.values()
                                           if m.document == document and m.root_position is not None),
                                          key=lambda m: m.root_position)]


class KnowledgeSession:
    """The repository's operations inside a caller's transaction (P002-T005, D286): the domain service shares one
    session for the mutation, its capability state and its outcome record. Nothing here commits."""

    def __init__(self, session: Session):
        self.session = session

    def writable(self) -> None:
        if self.session.execute(text("PRAGMA query_only")).scalar():
            raise PermissionError(tr('knowledge.query_only'))

    def project_id(self, root: str) -> str | None:
        return self.session.scalar(select(KnowledgeProjectRow.id).where(KnowledgeProjectRow.root == root))

    def create_project(self, root: str) -> str:
        project_id = str(uuid4())
        self.session.add(KnowledgeProjectRow(id=project_id, root=root, created_at=now()))
        self.session.flush()
        return project_id

    def _item(self, project_id: str, kind: str, code: str, document: str | None) -> KnowledgeItemRow:
        core.validate_item(kind, code, document)
        query = select(KnowledgeItemRow).where(KnowledgeItemRow.project_id == project_id,
                                               KnowledgeItemRow.kind == kind, KnowledgeItemRow.code == code)
        query = query.where(KnowledgeItemRow.document.is_(None) if document is None
                            else KnowledgeItemRow.document == document)
        row = self.session.scalar(query)
        if row is None:
            row = KnowledgeItemRow(id=str(uuid4()), project_id=project_id, kind=kind, document=document, code=code,
                                   created_at=now())
            self.session.add(row)
            self.session.flush()
        return row

    def head(self, project_id: str) -> KnowledgeRevisionRow | None:
        return self.session.scalar(select(KnowledgeRevisionRow).where(
            KnowledgeRevisionRow.project_id == project_id, KnowledgeRevisionRow.status == 'ACCEPTED')
            .order_by(KnowledgeRevisionRow.number.desc()).limit(1))

    def open_draft(self, project_id: str, base_revision_id: str | None) -> str:
        session = self.session
        draft = str(uuid4())
        session.add(KnowledgeRevisionRow(id=draft, project_id=project_id, base_revision_id=base_revision_id,
                                         status='DRAFT', created_at=now()))
        session.flush()
        if base_revision_id is not None:
            for row in session.scalars(select(KnowledgeRevisionMemberRow).where(
                    KnowledgeRevisionMemberRow.revision_id == base_revision_id)):
                session.add(KnowledgeRevisionMemberRow(revision_id=draft, item_id=row.item_id,
                                                       project_id=row.project_id, version_id=row.version_id,
                                                       root_position=row.root_position))
            session.flush()
            for row in session.scalars(select(KnowledgeRevisionLinkRow).where(
                    KnowledgeRevisionLinkRow.revision_id == base_revision_id)):
                session.add(KnowledgeRevisionLinkRow(revision_id=draft, kind=row.kind,
                                                     source_item_id=row.source_item_id,
                                                     target_item_id=row.target_item_id, position=row.position,
                                                     qualifier=row.qualifier))
            session.flush()
        return draft

    def draft(self, draft_id: str) -> KnowledgeRevisionRow:
        row = self.session.get(KnowledgeRevisionRow, draft_id)
        if row is None or row.status != 'DRAFT':
            raise ValueError(tr('knowledge.not_draft', revision=draft_id))
        return row

    def put(self, draft_id: str, kind: str, code: str, content: dict, *, document: str | None = None,
            provenance: str = 'known', source: dict | None = None, root_position: int | None = None) -> str:
        session = self.session
        content = core.validate_content(kind, document, content)
        source = core.validate_source(provenance, source)
        draft = self.draft(draft_id)
        item = self._item(draft.project_id, kind, code, document)
        digest = core.content_sha256(kind, document, code, content, provenance, source)
        member = session.get(KnowledgeRevisionMemberRow, (draft_id, item.id))
        current = member and session.get(KnowledgeItemVersionRow, member.version_id)
        if current is not None and current.content_sha256 == digest:
            version_id = current.id
        else:
            number = (session.scalar(select(func.max(KnowledgeItemVersionRow.number))
                                     .where(KnowledgeItemVersionRow.item_id == item.id)) or 0) + 1
            core.validate_version(kind, number, content, provenance, source)
            version_id = str(uuid4())
            session.add(KnowledgeItemVersionRow(id=version_id, item_id=item.id, number=number, content=content,
                                                content_sha256=digest, provenance=provenance, source=source,
                                                created_at=now()))
            session.flush()
        if member is None:
            session.add(KnowledgeRevisionMemberRow(revision_id=draft_id, item_id=item.id,
                                                   project_id=draft.project_id, version_id=version_id,
                                                   root_position=root_position))
        else:
            member.version_id, member.root_position = version_id, root_position
        session.flush()
        return item.id

    def remove(self, draft_id: str, item_id: str) -> None:
        self.draft(draft_id)
        self.session.execute(delete(KnowledgeRevisionLinkRow).where(
            KnowledgeRevisionLinkRow.revision_id == draft_id,
            (KnowledgeRevisionLinkRow.source_item_id == item_id)
            | (KnowledgeRevisionLinkRow.target_item_id == item_id)))
        self.session.execute(delete(KnowledgeRevisionMemberRow).where(
            KnowledgeRevisionMemberRow.revision_id == draft_id, KnowledgeRevisionMemberRow.item_id == item_id))

    def link(self, draft_id: str, kind: str, source: str, target: str, *, position: int | None = None,
             qualifier: str | None = None) -> None:
        self.draft(draft_id)
        self.session.merge(KnowledgeRevisionLinkRow(revision_id=draft_id, kind=kind, source_item_id=source,
                                                    target_item_id=target, position=position, qualifier=qualifier))
        self.session.flush()

    def unlink(self, draft_id: str, kind: str, source: str, target: str) -> None:
        self.draft(draft_id)
        self.session.execute(delete(KnowledgeRevisionLinkRow).where(
            KnowledgeRevisionLinkRow.revision_id == draft_id, KnowledgeRevisionLinkRow.kind == kind,
            KnowledgeRevisionLinkRow.source_item_id == source, KnowledgeRevisionLinkRow.target_item_id == target))

    def discard(self, draft_id: str) -> None:
        result = self.session.execute(update(KnowledgeRevisionRow).where(
            KnowledgeRevisionRow.id == draft_id, KnowledgeRevisionRow.status == 'DRAFT')
            .values(status='DISCARDED', closed_at=now()))
        if result.rowcount != 1:
            raise ValueError(tr('knowledge.not_draft', revision=draft_id))

    def lock(self) -> None:
        """A write statement first takes SQLite's write lock before the head is read, so a concurrent adoption
        waits and then sees the new head instead of failing later on a stale snapshot."""
        self.session.execute(text('DELETE FROM knowledge_revision_links WHERE 0'))

    def adopt(self, draft_id: str, expected_revision_id: str | None, *, origin: str, actor: dict,
              reason: str | None = None) -> Revision:
        """Seals the draft as the next accepted revision if its base is still the head and equals `expected`."""
        if origin not in core.ORIGINS or not isinstance(actor, dict) or not actor:
            raise ContractError(tr('knowledge.origin'))
        session = self.session
        try:
            draft = self.draft(draft_id)
            project_id = draft.project_id
            head = self.head(project_id)
            head_id = head.id if head else None
            if draft.base_revision_id != expected_revision_id or head_id != expected_revision_id:
                raise StaleRevision(tr('knowledge.stale', revision=draft_id))
            members, links = self.manifest(draft_id)
            previous = self.manifest_dict(head_id) if head else None
            core.validate_revision(members, links, previous, adoption=True)
            knowledge = core.knowledge_sha256(project_id, members.values(), links)
            if head is not None and knowledge == head.knowledge_sha256:
                raise ContractError(tr('knowledge.empty_adoption'))
            changes = core.change_summary(members, links, previous)
            number = (head.number if head else 0) + 1
            sealed = core.revision_sha256(knowledge, project_id, number,
                                          head.revision_sha256 if head else None, origin, actor, reason, changes)
            result = session.execute(update(KnowledgeRevisionRow).where(
                KnowledgeRevisionRow.id == draft_id, KnowledgeRevisionRow.status == 'DRAFT').values(
                status='ACCEPTED', number=number, knowledge_sha256=knowledge, revision_sha256=sealed,
                origin=origin, actor=actor, reason=reason, changes=changes, closed_at=now()))
            if result.rowcount != 1:
                raise StaleRevision(tr('knowledge.stale', revision=draft_id))
        except IntegrityError as error:
            # A concurrent adoption on the same base won; the database refused the second one.
            raise StaleRevision(tr('knowledge.stale', revision=draft_id)) from error
        session.expire_all()
        return self.revision(project_id, number)

    def manifest(self, revision_id: str):
        rows = self.session.execute(
            select(KnowledgeRevisionMemberRow, KnowledgeItemRow, KnowledgeItemVersionRow)
            .join(KnowledgeItemRow, KnowledgeItemRow.id == KnowledgeRevisionMemberRow.item_id)
            .join(KnowledgeItemVersionRow, KnowledgeItemVersionRow.id == KnowledgeRevisionMemberRow.version_id)
            .where(KnowledgeRevisionMemberRow.revision_id == revision_id)).all()
        members = {item.id: core.Member(item.id, item.kind, item.document, item.code, version.number,
                                        version.content_sha256, version.content, version.provenance, version.source,
                                        member.root_position)
                   for member, item, version in rows}
        links = tuple(core.Link(row.kind, row.source_item_id, row.target_item_id, row.position, row.qualifier)
                      for row in self.session.scalars(select(KnowledgeRevisionLinkRow).where(
                          KnowledgeRevisionLinkRow.revision_id == revision_id)))
        return members, links

    def manifest_dict(self, revision_id: str) -> dict:
        members, links = self.manifest(revision_id)
        return {'members': members, 'links': links}

    def revision(self, project_id: str, number: int | None = None) -> Revision:
        """The accepted revision `number` (default: head), verified with every predecessor back to the root."""
        rows = self.session.scalars(select(KnowledgeRevisionRow).where(
            KnowledgeRevisionRow.project_id == project_id, KnowledgeRevisionRow.status == 'ACCEPTED')
            .order_by(KnowledgeRevisionRow.number)).all()
        if number is not None:
            rows = [row for row in rows if row.number <= number]
        if not rows or number is not None and rows[-1].number != number:
            raise LookupError(tr('knowledge.revision_unknown', number=number))
        previous_row, previous, result = None, None, None
        for expected, row in enumerate(rows, start=1):
            members, links = self.manifest(row.id)
            try:
                _verify(row, members, links, previous_row, previous, expected)
            except ContractError as error:
                raise KnowledgeIntegrityError(tr('knowledge.integrity', number=row.number)) from error
            previous_row, previous = row, {'members': members, 'links': links}
            result = Revision(row.id, row.project_id, row.number, row.base_revision_id, row.knowledge_sha256,
                              row.revision_sha256, row.origin, row.actor, row.reason, row.changes, row.closed_at,
                              members, links)
        return result


def _verify(row, members, links, previous_row, previous, expected: int) -> None:
    if row.number != expected or row.base_revision_id != (previous_row.id if previous_row else None):
        raise ContractError('chain')
    for member in members.values():
        if core.content_sha256(member.kind, member.document, member.code, member.content, member.provenance,
                               member.source) != member.content_sha256:
            raise ContractError('content')
    core.validate_revision(members, links, previous, adoption=True)
    knowledge = core.knowledge_sha256(row.project_id, members.values(), links)
    changes = core.change_summary(members, links, previous)
    sealed = core.revision_sha256(knowledge, row.project_id, row.number,
                                  previous_row.revision_sha256 if previous_row else None, row.origin, row.actor,
                                  row.reason, changes)
    if knowledge != row.knowledge_sha256 or changes != row.changes or sealed != row.revision_sha256:
        raise ContractError('hash')


class KnowledgeRepository:
    """Self-transacting operations (T004); the domain service uses `KnowledgeSession` inside its own transaction."""

    def __init__(self, engine):
        self.engine = engine

    def query_only(self) -> bool:
        with self.engine.connect() as connection:
            return bool(connection.execute(text("PRAGMA query_only")).scalar())

    def _writable(self) -> None:
        if self.query_only():
            raise PermissionError(tr('knowledge.query_only'))

    def _write(self, operation):
        self._writable()
        with Session(self.engine) as session, session.begin():
            return operation(KnowledgeSession(session))

    def project(self, root: str) -> str:
        with Session(self.engine) as session:
            found = KnowledgeSession(session).project_id(root)
        return found or self._write(lambda knowledge: knowledge.create_project(root))

    def head(self, project_id: str) -> KnowledgeRevisionRow | None:
        with Session(self.engine, expire_on_commit=False) as session:
            return KnowledgeSession(session).head(project_id)

    def open_draft(self, project_id: str, base_revision_id: str | None) -> str:
        """A new draft copying the complete manifest of `base_revision_id` (None only for the first revision)."""
        return self._write(lambda knowledge: knowledge.open_draft(project_id, base_revision_id))

    def put(self, draft_id: str, kind: str, code: str, content: dict, **options) -> str:
        """Creates the item if needed and points the draft at a version with exactly this content."""
        return self._write(lambda knowledge: knowledge.put(draft_id, kind, code, content, **options))

    def remove(self, draft_id: str, item_id: str) -> None:
        self._write(lambda knowledge: knowledge.remove(draft_id, item_id))

    def link(self, draft_id: str, kind: str, source: str, target: str, **options) -> None:
        self._write(lambda knowledge: knowledge.link(draft_id, kind, source, target, **options))

    def unlink(self, draft_id: str, kind: str, source: str, target: str) -> None:
        self._write(lambda knowledge: knowledge.unlink(draft_id, kind, source, target))

    def discard(self, draft_id: str) -> None:
        self._write(lambda knowledge: knowledge.discard(draft_id))

    def adopt(self, draft_id: str, expected_revision_id: str | None, *, origin: str, actor: dict,
              reason: str | None = None) -> Revision:
        """Seals the draft as the next accepted revision if its base is still the head and equals `expected`."""
        self._writable()
        if origin not in core.ORIGINS or not isinstance(actor, dict) or not actor:
            raise ContractError(tr('knowledge.origin'))
        try:
            with Session(self.engine) as session, session.begin():
                knowledge = KnowledgeSession(session)
                knowledge.lock()
                draft = knowledge.draft(draft_id)
                project_id = draft.project_id
                revision = knowledge.adopt(draft_id, expected_revision_id, origin=origin, actor=actor, reason=reason)
        except IntegrityError as error:
            raise StaleRevision(tr('knowledge.stale', revision=draft_id)) from error
        return self.revision(project_id, revision.number)

    def revision(self, project_id: str, number: int | None = None) -> Revision:
        """The accepted revision `number` (default: head), verified with every predecessor back to the root."""
        with Session(self.engine) as session:
            return KnowledgeSession(session).revision(project_id, number)

    def history(self, item_id: str) -> list[KnowledgeItemVersionRow]:
        with Session(self.engine, expire_on_commit=False) as session:
            return list(session.scalars(select(KnowledgeItemVersionRow).where(
                KnowledgeItemVersionRow.item_id == item_id).order_by(KnowledgeItemVersionRow.number)))

    # Legacy identities ---------------------------------------------------------------------------------------------

    def map_legacy(self, project_id: str, legacy_kind: str, legacy_ref: str, item_id: str,
                   legacy_sha256: str | None = None) -> None:
        """Records once which item a legacy reference became; the legacy row itself is never touched."""
        self._writable()
        if legacy_kind not in core.LEGACY_KINDS or not legacy_ref:
            raise ContractError(tr('knowledge.legacy', kind=legacy_kind))
        try:
            with Session(self.engine) as session, session.begin():
                session.add(KnowledgeIdentityRow(project_id=project_id, legacy_kind=legacy_kind,
                                                 legacy_ref=legacy_ref, item_id=item_id,
                                                 legacy_sha256=legacy_sha256, created_at=now()))
        except IntegrityError as error:
            raise ValueError(tr('knowledge.legacy_mapped', kind=legacy_kind, reference=legacy_ref)) from error

    def legacy(self, project_id: str, legacy_kind: str, legacy_ref: str) -> str | None:
        with Session(self.engine) as session:
            return session.scalar(select(KnowledgeIdentityRow.item_id).where(
                KnowledgeIdentityRow.project_id == project_id, KnowledgeIdentityRow.legacy_kind == legacy_kind,
                KnowledgeIdentityRow.legacy_ref == legacy_ref))
