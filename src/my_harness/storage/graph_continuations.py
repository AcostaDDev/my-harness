"""P002-T003 (D282, D283): graph thread stamps and status transitions, without importing LangGraph.

Every transition is a compare-and-set on the current status, so two owners never advance the same thread.
"""
from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from my_harness.i18n import tr
from my_harness.storage.models import GraphThreadRow


def now() -> str:
    return datetime.now(UTC).isoformat()


class GraphContinuationRepository:
    def __init__(self, engine):
        self.engine = engine

    def query_only(self) -> bool:
        with self.engine.connect() as connection:
            return bool(connection.execute(text("PRAGMA query_only")).scalar())

    def create(self, thread_id: str, graph_id: str, version: str, fingerprint: str) -> GraphThreadRow:
        stamp = now()
        row = GraphThreadRow(id=thread_id, graph_id=graph_id, graph_version=version, fingerprint=fingerprint,
                             status='RUNNING', segments=0, created_at=stamp, updated_at=stamp)
        try:
            with Session(self.engine, expire_on_commit=False) as session, session.begin():
                session.add(row)
        except IntegrityError as error:
            raise ValueError(tr('orchestration.thread_exists', thread=thread_id)) from error
        return row

    def get(self, thread_id: str) -> GraphThreadRow:
        with Session(self.engine, expire_on_commit=False) as session:
            row = session.scalar(select(GraphThreadRow).where(GraphThreadRow.id == thread_id))
        if row is None:
            raise LookupError(tr('orchestration.thread_unknown', thread=thread_id))
        return row

    def transition(self, thread_id: str, expected: tuple[str, ...], status: str, *, reason=None, detail=None,
                   segments: int = 0) -> GraphThreadRow:
        """Moves the thread from one of `expected` to `status`; any other current status is refused unchanged."""
        with Session(self.engine) as session, session.begin():
            result = session.execute(
                update(GraphThreadRow)
                .where(GraphThreadRow.id == thread_id, GraphThreadRow.status.in_(expected))
                .values(status=status, reason=reason, detail=detail, segments=GraphThreadRow.segments + segments,
                        updated_at=now()))
        if result.rowcount != 1:
            current = self.get(thread_id)
            raise ValueError(tr('orchestration.thread_state', thread=thread_id, status=current.status,
                                expected=', '.join(expected)))
        return self.get(thread_id)

    def add_segment(self, thread_id: str) -> None:
        with Session(self.engine) as session, session.begin():
            session.execute(update(GraphThreadRow).where(GraphThreadRow.id == thread_id, GraphThreadRow.status == 'RUNNING')
                            .values(segments=GraphThreadRow.segments + 1, updated_at=now()))
