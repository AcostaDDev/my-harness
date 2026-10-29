"""D280 option B / D282: LangGraph checkpoint saver over the Alembic-managed harness tables.

Synchronous only; the async variants keep LangGraph's NotImplementedError, as do pruning, copying and per-run
deletion, which the harness never performs: a checkpoint is never edited or rewritten. The serializer is strict
(no msgpack module allowlist) and graph state is limited to primitives, identities and revision references (D269).
A checkpoint can only be stored for a thread the runner has stamped (foreign key to `graph_threads`).
"""
from collections.abc import Iterator, Sequence
from threading import Lock
from typing import Any

from langgraph.checkpoint.base import (
    WRITES_IDX_MAP, BaseCheckpointSaver, ChannelVersions, Checkpoint, CheckpointMetadata, CheckpointTuple,
    get_checkpoint_id, get_checkpoint_metadata, writes_sort_key,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from my_harness.i18n import tr
from my_harness.storage.graph_continuations import now
from my_harness.storage.models import GraphCheckpointRow, GraphCheckpointWriteRow

PRIMITIVES = (str, int, float, bool, type(None))


def strict_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=None)


def require_primitive(value: Any, where: str) -> None:
    """Graph state is not a copy of tasks, grants or policy: nested primitives with string keys only."""
    if isinstance(value, PRIMITIVES):
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            require_primitive(item, where)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            require_primitive(item, where)
        return
    raise TypeError(tr('orchestration.state_not_primitive', channel=where, kind=type(value).__name__))


def _config(thread_id: str, namespace: str, checkpoint_id: str | None):
    if checkpoint_id is None:
        return None
    return {'configurable': {'thread_id': thread_id, 'checkpoint_ns': namespace, 'checkpoint_id': checkpoint_id}}


class HarnessCheckpointSaver(BaseCheckpointSaver[int]):
    def __init__(self, engine):
        super().__init__(serde=strict_serializer())
        self.engine = engine
        # LangGraph calls put and put_writes from its background executor; a SQLite read-then-write transaction
        # whose snapshot another writer advanced fails at once instead of waiting, so this saver writes one at a time.
        self._write = Lock()

    def _tuple(self, session: Session, row: GraphCheckpointRow) -> CheckpointTuple:
        writes = session.scalars(select(GraphCheckpointWriteRow).where(
            GraphCheckpointWriteRow.thread_id == row.thread_id,
            GraphCheckpointWriteRow.checkpoint_ns == row.checkpoint_ns,
            GraphCheckpointWriteRow.checkpoint_id == row.checkpoint_id)).all()
        writes = sorted(writes, key=lambda write: writes_sort_key(write.task_path, write.task_id, write.idx))
        return CheckpointTuple(
            config=_config(row.thread_id, row.checkpoint_ns, row.checkpoint_id),
            checkpoint=self.serde.loads_typed((row.checkpoint_type, row.checkpoint)),
            metadata=self.serde.loads_typed((row.metadata_type, row.metadata_value)),
            parent_config=_config(row.thread_id, row.checkpoint_ns, row.parent_checkpoint_id),
            pending_writes=[(write.task_id, write.channel, self.serde.loads_typed((write.value_type, write.value)))
                            for write in writes])

    def get_tuple(self, config) -> CheckpointTuple | None:
        configurable = config['configurable']
        query = select(GraphCheckpointRow).where(
            GraphCheckpointRow.thread_id == configurable['thread_id'],
            GraphCheckpointRow.checkpoint_ns == configurable.get('checkpoint_ns', ''))
        if checkpoint_id := get_checkpoint_id(config):
            query = query.where(GraphCheckpointRow.checkpoint_id == checkpoint_id)
        else:
            query = query.order_by(GraphCheckpointRow.checkpoint_id.desc()).limit(1)
        with Session(self.engine) as session:
            row = session.scalar(query)
            return self._tuple(session, row) if row is not None else None

    def list(self, config, *, filter: dict[str, Any] | None = None, before=None,
             limit: int | None = None) -> Iterator[CheckpointTuple]:
        query = select(GraphCheckpointRow).order_by(GraphCheckpointRow.thread_id,
                                                    GraphCheckpointRow.checkpoint_id.desc())
        if config is not None:
            configurable = config['configurable']
            query = query.where(GraphCheckpointRow.thread_id == configurable['thread_id'])
            if configurable.get('checkpoint_ns') is not None:
                query = query.where(GraphCheckpointRow.checkpoint_ns == configurable['checkpoint_ns'])
            if checkpoint_id := get_checkpoint_id(config):
                query = query.where(GraphCheckpointRow.checkpoint_id == checkpoint_id)
        if before is not None and (before_id := get_checkpoint_id(before)):
            query = query.where(GraphCheckpointRow.checkpoint_id < before_id)
        with Session(self.engine) as session:
            found = []
            for row in session.scalars(query):
                item = self._tuple(session, row)
                if filter and not all(item.metadata.get(key) == value for key, value in filter.items()):
                    continue
                if limit is not None and len(found) >= limit:
                    break
                found.append(item)
        yield from found

    def put(self, config, checkpoint: Checkpoint, metadata: CheckpointMetadata,
            new_versions: ChannelVersions) -> dict:
        configurable = config['configurable']
        thread_id, namespace = configurable['thread_id'], configurable.get('checkpoint_ns', '')
        for channel, value in checkpoint['channel_values'].items():
            require_primitive(value, channel)
        checkpoint_type, checkpoint_bytes = self.serde.dumps_typed(checkpoint)
        metadata_type, metadata_bytes = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
        with self._write, Session(self.engine) as session, session.begin():
            existing = session.get(GraphCheckpointRow, (thread_id, namespace, checkpoint['id']))
            if existing is None:
                session.add(GraphCheckpointRow(
                    thread_id=thread_id, checkpoint_ns=namespace, checkpoint_id=checkpoint['id'],
                    parent_checkpoint_id=configurable.get('checkpoint_id'), checkpoint_type=checkpoint_type,
                    checkpoint=checkpoint_bytes, metadata_type=metadata_type, metadata_value=metadata_bytes,
                    created_at=now()))
            elif (existing.checkpoint_type, existing.checkpoint) != (checkpoint_type, checkpoint_bytes):
                raise ValueError(tr('orchestration.checkpoint_rewrite', thread=thread_id, checkpoint=checkpoint['id']))
        return _config(thread_id, namespace, checkpoint['id'])

    def put_writes(self, config, writes: Sequence[tuple[str, Any]], task_id: str, task_path: str = '') -> None:
        configurable = config['configurable']
        key = (configurable['thread_id'], configurable.get('checkpoint_ns', ''), configurable['checkpoint_id'])
        with self._write, Session(self.engine) as session, session.begin():
            for position, (channel, value) in enumerate(writes):
                special = channel in WRITES_IDX_MAP
                if not special:
                    require_primitive(value, channel)
                idx = WRITES_IDX_MAP.get(channel, position)
                existing = session.get(GraphCheckpointWriteRow, (*key, task_id, idx))
                if existing is not None and not special:
                    continue
                value_type, value_bytes = self.serde.dumps_typed(value)
                if existing is None:
                    session.add(GraphCheckpointWriteRow(
                        thread_id=key[0], checkpoint_ns=key[1], checkpoint_id=key[2], task_id=task_id, idx=idx,
                        channel=channel, value_type=value_type, value=value_bytes, task_path=task_path))
                else:
                    existing.channel, existing.value_type, existing.value = channel, value_type, value_bytes
                    existing.task_path = task_path

    def delete_thread(self, thread_id: str) -> None:
        with self._write, Session(self.engine) as session, session.begin():
            session.execute(delete(GraphCheckpointWriteRow).where(GraphCheckpointWriteRow.thread_id == thread_id))
            session.execute(delete(GraphCheckpointRow).where(GraphCheckpointRow.thread_id == thread_id))
