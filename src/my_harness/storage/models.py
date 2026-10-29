from sqlalchemy import (
    Boolean, CheckConstraint, Float, Index, JSON, ForeignKey, ForeignKeyConstraint, Integer, LargeBinary, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SimulationRow(Base):
    __tablename__ = "simulations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    # ISO 8601 keeps UTC; SQLite DateTime does not keep the time zone.
    created_at: Mapped[str] = mapped_column(String(40))
    events: Mapped[list[str]] = mapped_column(JSON)


class LegacySourceRow(Base):
    __tablename__ = "legacy_sources"

    root: Mapped[str] = mapped_column(String, primary_key=True)
    observed_at: Mapped[str] = mapped_column(String(40))
    watch_enabled: Mapped[bool] = mapped_column(Boolean, server_default="0")
    diagnostic: Mapped[str | None] = mapped_column(Text, nullable=True)


class LegacyRunRow(Base):
    __tablename__ = "legacy_runs"

    root: Mapped[str] = mapped_column(ForeignKey("legacy_sources.root", ondelete="CASCADE"), primary_key=True)
    path: Mapped[str] = mapped_column(String, primary_key=True)
    identity: Mapped[str] = mapped_column(String)


class LegacyArtifactRow(Base):
    __tablename__ = "legacy_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(["root", "run_path"], ["legacy_runs.root", "legacy_runs.path"]),
    )

    root: Mapped[str] = mapped_column(ForeignKey("legacy_sources.root", ondelete="CASCADE"), primary_key=True)
    path: Mapped[str] = mapped_column(String, primary_key=True)
    run_path: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String(40))
    format: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20))
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[object] = mapped_column(JSON(none_as_null=True), nullable=True)
    diagnostic: Mapped[str | None] = mapped_column(Text, nullable=True)


class LegacyEventRow(Base):
    __tablename__ = "legacy_events"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    root: Mapped[str] = mapped_column(ForeignKey("legacy_sources.root", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    observed_at: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)


class ManagedRunRow(Base):
    __tablename__ = "managed_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    root: Mapped[str] = mapped_column(String)
    task_id: Mapped[str] = mapped_column(String)
    phase_id: Mapped[str] = mapped_column(String)
    context_json: Mapped[str] = mapped_column(Text)
    versions_json: Mapped[str] = mapped_column(Text)
    history_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40))
    stage: Mapped[str] = mapped_column(String(40))
    revisions: Mapped[int] = mapped_column(Integer)
    revision_limit: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
    # H3.3: 'task', or a phase operation without a task contract ('phase_check', 'phase_close').
    purpose: Mapped[str] = mapped_column(String(20), server_default='task')


_LIVE_ACTIVATION = text("status IN ('PREPARING', 'ACTIVE', 'REVERTING')")


class ManagedActivationRow(Base):
    """Managed mode of a legacy H2.5 checkout: mode authority and provenance of the history."""

    __tablename__ = "managed_activations"
    __table_args__ = (
        Index("uq_managed_activations_live_root", "root", unique=True, sqlite_where=_LIVE_ACTIVATION),
        Index("uq_managed_activations_live_repository", "repository_key", unique=True,
              sqlite_where=_LIVE_ACTIVATION),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    root: Mapped[str] = mapped_column(String)
    repository_key: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    preview_sha256: Mapped[str] = mapped_column(String(64))
    legacy_stopped: Mapped[str] = mapped_column(Text)
    rules_json: Mapped[str] = mapped_column(Text)
    marker: Mapped[str] = mapped_column(Text)
    marker_sha256: Mapped[str] = mapped_column(String(64))
    snapshot_root: Mapped[str] = mapped_column(String)
    manifest_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40))
    activated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    diagnostic: Mapped[str | None] = mapped_column(Text, nullable=True)
    revert_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    export_path: Mapped[str | None] = mapped_column(String, nullable=True)
    export_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ManagedJobRow(Base):
    __tablename__ = "managed_jobs"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("managed_runs.id"))
    request_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40))
    owner_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    heartbeat_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lease_until: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    diagnostic: Mapped[str | None] = mapped_column(Text, nullable=True)
    process_owner: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    owner_closed: Mapped[bool] = mapped_column(Boolean, server_default="0")
    # H2.5 activation under which the job was admitted; null in checkouts without legacy state.
    activation_id: Mapped[str | None] = mapped_column(ForeignKey("managed_activations.id"), nullable=True)
    # 0024: language frozen at admission: `ui-language-1` (visual only, 0024) or `language-context-1` (visual and
    # work, 0025); null in earlier jobs, never inferred.
    language_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class CheckoutLockRow(Base):
    __tablename__ = "checkout_locks"
    __table_args__ = (CheckConstraint('(job_id IS NOT NULL) != (preparation_id IS NOT NULL)',
                                    name='ck_checkout_lock_owner'),)

    root: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("managed_jobs.id"), unique=True, nullable=True)
    preparation_id: Mapped[str | None] = mapped_column(ForeignKey('project_preparation_operations.id'),
                                                     unique=True, nullable=True)


class ManagedAttemptRow(Base):
    __tablename__ = "managed_attempts"
    __table_args__ = (UniqueConstraint("run_id", "number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("managed_runs.id"))
    number: Mapped[int] = mapped_column(Integer)
    request_json: Mapped[str] = mapped_column(Text)
    versions_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40))
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # 0025: language pair of the job copied when the attempt starts (`language-context-1`); null before.
    language_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ManagedEventRow(Base):
    __tablename__ = "managed_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence"), {"sqlite_autoincrement": True})

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("managed_runs.id"))
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    recorded_at: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)


class ManagedProcessRow(Base):
    __tablename__ = "managed_processes"
    __table_args__ = (CheckConstraint(
        '(job_id IS NOT NULL AND attempt_id IS NOT NULL AND preparation_id IS NULL) OR '
        '(job_id IS NULL AND attempt_id IS NULL AND preparation_id IS NOT NULL)', name='ck_managed_process_owner'),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                  default=lambda ctx: ctx.get_current_parameters()['attempt_id'])
    attempt_id: Mapped[str | None] = mapped_column(ForeignKey("managed_attempts.id"), unique=True, nullable=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("managed_jobs.id"), nullable=True)
    preparation_id: Mapped[str | None] = mapped_column(ForeignKey('project_preparation_operations.id'), nullable=True)
    spec: Mapped[dict] = mapped_column(JSON)
    identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(40))
    capture: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ManagedCommitRow(Base):
    """Intent and result of the accepted commit; source of the H2.4 reconciliation."""

    __tablename__ = "managed_commits"
    __table_args__ = (Index("uq_managed_commits_live", "run_id", unique=True,
                            sqlite_where=text("status IN ('INTENT', 'COMMITTED')")),)

    operation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("managed_runs.id"))
    job_id: Mapped[int] = mapped_column(ForeignKey("managed_jobs.id"))
    status: Mapped[str] = mapped_column(String(40))
    base_revision: Mapped[str] = mapped_column(String(64))
    reviewed_fingerprint: Mapped[str] = mapped_column(String(64))
    expected_tree: Mapped[str] = mapped_column(String(64))
    expected_commit: Mapped[str] = mapped_column(String(64))
    intent_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class RunProjectionRow(Base):
    """P010-T003 (D142): derived `run-projection-1` projection of `history_json`, which remains the authority.

    Written in the same transaction as the history; the views only read these tables. JSON columns in frozen
    text (`freeze`) or the exact history text, to compare by equality in the backup."""

    __tablename__ = 'run_projections'

    run_id: Mapped[str] = mapped_column(ForeignKey('managed_runs.id'), primary_key=True)
    projection: Mapped[str] = mapped_column(String(20))
    history_sha256: Mapped[str] = mapped_column(String(64))
    history_status: Mapped[str] = mapped_column(String(40))
    task_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer)
    executor_attempts: Mapped[int] = mapped_column(Integer)
    cycle_count: Mapped[int] = mapped_column(Integer)
    stop_count: Mapped[int] = mapped_column(Integer)
    stop_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    acceptance_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class RunProjectionStopRow(Base):
    __tablename__ = 'run_projection_stops'

    run_id: Mapped[str] = mapped_column(ForeignKey('managed_runs.id'), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)


class RunProjectionCycleRow(Base):
    """Cycle without the diff text or the JUnit cases; `validation_json` is the validation view of the detail."""

    __tablename__ = 'run_projection_cycles'

    run_id: Mapped[str] = mapped_column(ForeignKey('managed_runs.id'), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    fingerprint: Mapped[str] = mapped_column(Text)
    changed_paths_json: Mapped[str] = mapped_column(Text)
    diff_sha256: Mapped[str] = mapped_column(String(64))
    diff_bytes: Mapped[int] = mapped_column(Integer)
    provenance_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    formatting_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_json: Mapped[str] = mapped_column(Text)
    validation_evidence_json: Mapped[str] = mapped_column(Text)
    validation_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_source_attempt_id: Mapped[str | None] = mapped_column(Text, nullable=True)


class RunProjectionDiffChunkRow(Base):
    """Reviewed diff in fixed spans of UTF-8 bytes: a page only reads the spans it covers."""

    __tablename__ = 'run_projection_diff_chunks'

    run_id: Mapped[str] = mapped_column(ForeignKey('managed_runs.id'), primary_key=True)
    cycle: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)


class RunProjectionReportRow(Base):
    __tablename__ = 'run_projection_reports'

    run_id: Mapped[str] = mapped_column(ForeignKey('managed_runs.id'), primary_key=True)
    cycle: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry: Mapped[int] = mapped_column(Integer, primary_key=True)
    report: Mapped[int] = mapped_column(Integer, primary_key=True)
    command_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[str] = mapped_column(Text)
    original_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    case_count: Mapped[int] = mapped_column(Integer)


class RunProjectionCaseRow(Base):
    __tablename__ = 'run_projection_cases'

    run_id: Mapped[str] = mapped_column(ForeignKey('managed_runs.id'), primary_key=True)
    cycle: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry: Mapped[int] = mapped_column(Integer, primary_key=True)
    report: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_json: Mapped[str] = mapped_column(Text)


class PromptHeadRow(Base):
    __tablename__ = 'prompt_heads'
    scope: Mapped[str] = mapped_column(String, primary_key=True)
    owner: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, primary_key=True)
    generation: Mapped[int] = mapped_column(Integer)
    active_id: Mapped[str | None] = mapped_column(String, nullable=True)


class PromptVersionRow(Base):
    __tablename__ = 'prompt_versions'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    scope: Mapped[str] = mapped_column(String)
    owner: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    template: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class PromptActivationRow(Base):
    __tablename__ = 'prompt_activations'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    scope: Mapped[str] = mapped_column(String)
    owner: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    previous_id: Mapped[str | None] = mapped_column(String, nullable=True)
    version_id: Mapped[str] = mapped_column(ForeignKey('prompt_versions.id'))
    generation: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class PermissionRequestRow(Base):
    __tablename__ = 'permission_requests'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('managed_runs.id'))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40))
    request: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40))
    decision: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    consumed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    supersedes: Mapped[str | None] = mapped_column(ForeignKey('permission_requests.id'), nullable=True)


class PhaseRow(Base):
    """H3.3 authority of a phase: frozen definition, adopted documentary base and state."""
    __tablename__ = 'managed_phases'
    __table_args__ = (UniqueConstraint('root', 'code'),
                      Index('uq_managed_phases_open_root', 'root', unique=True,
                            sqlite_where=text("status NOT IN ('CLOSED', 'ABANDONED')")))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    root: Mapped[str] = mapped_column(String)
    code: Mapped[str] = mapped_column(String(120))
    definition: Mapped[dict] = mapped_column(JSON)
    definition_sha256: Mapped[str] = mapped_column(String(64))
    documents: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
    definition_number: Mapped[int] = mapped_column(Integer, server_default='1')


class PhaseDefinitionRow(Base):
    """H3.4: each definition version is kept; an amendment never rewrites the previous one."""
    __tablename__ = 'phase_definitions'
    __table_args__ = (UniqueConstraint('phase_id', 'number'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phase_id: Mapped[str] = mapped_column(ForeignKey('managed_phases.id'))
    number: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict] = mapped_column(JSON)
    definition_sha256: Mapped[str] = mapped_column(String(64))
    documents: Mapped[dict] = mapped_column(JSON)
    # created | amended | migrated (row before H3.4: no reason or identity recorded).
    origin: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))


class PhaseQuestionRow(Base):
    __tablename__ = 'phase_questions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phase_id: Mapped[str] = mapped_column(ForeignKey('managed_phases.id'))
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20))
    answer: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40))


class PhaseOperationRow(Base):
    """Check, closure or reconciliation; an earlier result is never overwritten."""
    __tablename__ = 'phase_operations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phase_id: Mapped[str] = mapped_column(ForeignKey('managed_phases.id'))
    kind: Mapped[str] = mapped_column(String(20))
    run_id: Mapped[str | None] = mapped_column(ForeignKey('managed_runs.id'), nullable=True)
    status: Mapped[str] = mapped_column(String(40))
    previous_status: Mapped[str] = mapped_column(String(40))
    request: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class PhaseAuthorizationRow(Base):
    """Batch or closure authorization: distinct, explicit and audited."""
    __tablename__ = 'phase_authorizations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phase_id: Mapped[str] = mapped_column(ForeignKey('managed_phases.id'))
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    scope: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    actor: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40))
    closed: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer)


class PhaseEventRow(Base):
    __tablename__ = 'phase_events'
    __table_args__ = (UniqueConstraint('phase_id', 'sequence'), {'sqlite_autoincrement': True})
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phase_id: Mapped[str] = mapped_column(ForeignKey('managed_phases.id'))
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    recorded_at: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)


class ChatConversationRow(Base):
    """H4.1: conversation separate from the execution flow; optionally linked to a phase."""
    __tablename__ = 'chat_conversations'
    __table_args__ = (Index('uq_chat_conversations_key', 'idempotency_key', unique=True),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    root: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String(200))
    phase_id: Mapped[str | None] = mapped_column(ForeignKey('managed_phases.id'), nullable=True)
    task_run_id: Mapped[str | None] = mapped_column(ForeignKey('managed_runs.id'), nullable=True)
    actor: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
    # 0018: the same key and the same request return the same conversation; null in earlier or internal registrations.
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ChatTurnRow(Base):
    """Frozen request (message and explicit context) before queuing; one pending turn per conversation."""
    __tablename__ = 'chat_turns'
    __table_args__ = (UniqueConstraint('conversation_id', 'number'),
                      Index('uq_chat_turns_pending', 'conversation_id', unique=True,
                            sqlite_where=text("status = 'QUEUED'")))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey('chat_conversations.id'))
    number: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str] = mapped_column(ForeignKey('managed_runs.id'), unique=True)
    # QUEUED | ANSWERED | FAILED | UNKNOWN (confirmed crash, no retry) | REFUSED
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    request: Mapped[dict] = mapped_column(JSON)
    request_sha256: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    actor: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class ChatProposalRow(Base):
    """Structured proposal of a turn; only an explicit confirmation creates its linked task."""
    __tablename__ = 'chat_proposals'
    __table_args__ = (UniqueConstraint('conversation_id', 'number'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey('chat_conversations.id'))
    turn_id: Mapped[str] = mapped_column(ForeignKey('chat_turns.id'))
    number: Mapped[int] = mapped_column(Integer)
    # PROPOSED | ACCEPTED | DISMISSED
    status: Mapped[str] = mapped_column(String(20))
    proposal: Mapped[dict] = mapped_column(JSON)
    proposal_sha256: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str | None] = mapped_column(ForeignKey('managed_runs.id'), nullable=True, unique=True)
    decision: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40))


class PlanningConversationRow(Base):
    """H6.5: definition conversation (new project) or planning of the next phase; P008-T011:
    import of a project from an earlier harness (Flow A)."""
    __tablename__ = 'planning_conversations'
    __table_args__ = (Index('uq_planning_definition', 'root', unique=True, sqlite_where=text("kind = 'definition'")),
                      Index('uq_planning_conversations_key', 'idempotency_key', unique=True))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    root: Mapped[str] = mapped_column(String)
    # definition | phase_planning | project_import | onboarding
    kind: Mapped[str] = mapped_column(String(20))
    phase_id: Mapped[str | None] = mapped_column(ForeignKey('managed_phases.id'), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    # Frozen Markdown brief with its hash (definition); null in planning.
    brief: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Hashes of drafts the harness knows (last answered turn or applied proposal); the rest belongs to the user.
    known: Mapped[dict] = mapped_column(JSON)
    # Blocking questions explicitly deferred, by question id.
    deferred: Mapped[dict] = mapped_column(JSON)
    # Draft writes by the harness (applied proposals) and edits through the API, with hashes.
    log: Mapped[list] = mapped_column(JSON)
    actor: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
    # 0018: as in the chat.
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 0019: frozen origin: import inventory/map or onboarding inventory/HEAD (T014); null otherwise.
    source: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class PlanningTurnRow(Base):
    """Frozen request (message, context and what was observed) before queuing; one pending turn per conversation."""
    __tablename__ = 'planning_turns'
    __table_args__ = (UniqueConstraint('conversation_id', 'number'),
                      Index('uq_planning_turns_pending', 'conversation_id', unique=True,
                            sqlite_where=text("status = 'QUEUED'")))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey('planning_conversations.id'))
    number: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str] = mapped_column(ForeignKey('managed_runs.id'), unique=True)
    # QUEUED | ANSWERED | FAILED | UNKNOWN (confirmed crash, no retry) | REFUSED
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    request: Mapped[dict] = mapped_column(JSON)
    request_sha256: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    actor: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class PlanningProposalRow(Base):
    """Draft of a document (definition) or plan of the next phase; never applied without confirmation."""
    __tablename__ = 'planning_proposals'
    __table_args__ = (UniqueConstraint('conversation_id', 'number'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey('planning_conversations.id'))
    turn_id: Mapped[str] = mapped_column(ForeignKey('planning_turns.id'))
    number: Mapped[int] = mapped_column(Integer)
    # draft | plan | profile (canonical JSON; documentary intake only)
    kind: Mapped[str] = mapped_column(String(20))
    path: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    # CAS: hash of the draft the turn read (null: absent). Drafts only.
    base_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proposal_sha256: Mapped[str] = mapped_column(String(64))
    # PROPOSED | APPLIED (draft written) | ACCEPTED (plan used in a transition) | DISMISSED | SUPERSEDED
    status: Mapped[str] = mapped_column(String(20))
    decision: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40))


class ProjectBootstrapRow(Base):
    """H4.2: one bootstrap per authorized target; bytes and intent kept before writing."""
    __tablename__ = 'project_bootstraps'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    root: Mapped[str] = mapped_column(String, unique=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('managed_runs.id'), unique=True)
    phase_id: Mapped[str | None] = mapped_column(ForeignKey('managed_phases.id'), nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    preview: Mapped[dict] = mapped_column(JSON)
    intent: Mapped[dict] = mapped_column(JSON)
    decision: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)



class ProjectImportRow(Base):
    """P008-T012/T015: one onboarding (Flow A or B) per checkout; immutable intent and bytes."""
    __tablename__ = 'project_imports'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    root: Mapped[str] = mapped_column(String, unique=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey('planning_conversations.id'), unique=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('managed_runs.id'), unique=True)
    phase_id: Mapped[str | None] = mapped_column(ForeignKey('managed_phases.id'), nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    preview: Mapped[dict] = mapped_column(JSON)
    intent: Mapped[str] = mapped_column(Text)
    decision: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class AttemptMetricRow(Base):
    """H6.4: metrics of a resolved attempt, materialized with its result; per-field provenance.

    Null is absence, never zero. They survive stream retention (H5.3): they do not depend on artifacts."""
    __tablename__ = 'attempt_metrics'
    __table_args__ = (Index('ix_attempt_metrics_scope', 'root', 'phase_code', 'task_id'),
                      Index('ix_attempt_metrics_run', 'run_id', 'number', unique=True))
    attempt_id: Mapped[str] = mapped_column(ForeignKey('managed_attempts.id'), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('managed_runs.id'))
    number: Mapped[int] = mapped_column(Integer)
    root: Mapped[str] = mapped_column(String)
    phase_code: Mapped[str] = mapped_column(String)
    task_id: Mapped[str] = mapped_column(String)
    purpose: Mapped[str] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    adapter_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cli_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    requested_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    requested_effort: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reported_models: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reported_effort: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(40))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Executions of the run up to this attempt: 0 planning, n execution n and its review.
    executor_round: Mapped[int] = mapped_column(Integer)
    accounting: Mapped[str | None] = mapped_column(String(20), nullable=True)
    input_semantics: Mapped[str | None] = mapped_column(String(30), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uncached_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Derived without double counting (see `storage/metrics._total`); null if the semantics are not safe.
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tools: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    permission_denials: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wall_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    api_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    day: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(20))
    normalization: Mapped[str | None] = mapped_column(String(20), nullable=True)
    catalog: Mapped[str] = mapped_column(String(20))
    provenance: Mapped[dict] = mapped_column(JSON)
    diagnostics: Mapped[list] = mapped_column(JSON)
    recorded_at: Mapped[str] = mapped_column(String(40))


class AttemptModelMetricRow(Base):
    """H6.4: consumption reported per model within an attempt (Claude `modelUsage`)."""
    __tablename__ = 'attempt_model_metrics'
    attempt_id: Mapped[str] = mapped_column(ForeignKey('attempt_metrics.attempt_id'), primary_key=True)
    model: Mapped[str] = mapped_column(String(200), primary_key=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)


class RegisteredProjectRow(Base):
    """H6.2 E2 (D054/D076): project registered from the UI; optimistic version and logical retirement.

    Non-executable data only: named composition, or null for a documentary intake (D224)."""
    __tablename__ = 'registered_projects'
    __table_args__ = (Index('uq_registered_projects_active_root', 'root', unique=True,
                            sqlite_where=text("status = 'ACTIVE'")),
                      Index('uq_registered_creation', 'creation_id', unique=True))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    creation_id: Mapped[str | None] = mapped_column(ForeignKey('project_creation_operations.id'), nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    root: Mapped[str] = mapped_column(String)
    composition: Mapped[str | None] = mapped_column(String(64), nullable=True)
    profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Complete canonical row (what is composed) and its hash; trust is confirmed separately.
    row: Mapped[dict] = mapped_column(JSON)
    row_sha256: Mapped[str] = mapped_column(String(64))
    trust: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class RegisteredProjectEventRow(Base):
    """Registry audit: one row per version, never rewritten (who, when, before and after)."""
    __tablename__ = 'registered_project_events'
    __table_args__ = (UniqueConstraint('project_id', 'version'), {'sqlite_autoincrement': True})
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('registered_projects.id'))
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))
    row: Mapped[dict] = mapped_column(JSON)
    row_sha256: Mapped[str] = mapped_column(String(64))
    previous_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preview_sha256: Mapped[str] = mapped_column(String(64))
    actor: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[str] = mapped_column(String(40))


class ProjectCreationRootRow(Base):
    __tablename__ = 'project_creation_root'
    __table_args__ = (CheckConstraint('id = 1', name='ck_creation_root_singleton'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    path: Mapped[str | None] = mapped_column(String, nullable=True)
    identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    row_sha256: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[str] = mapped_column(String(40))


class ProjectCreationRootEventRow(Base):
    __tablename__ = 'project_creation_root_events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    request_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)


class ProjectCreationOperationRow(Base):
    __tablename__ = 'project_creation_operations'
    __table_args__ = (
        Index('uq_creation_reserved_id', 'project_id', unique=True, sqlite_where=text('reserved = 1')),
        Index('uq_creation_reserved_target', 'target', unique=True, sqlite_where=text('reserved = 1')),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    request_sha256: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    project_id: Mapped[str] = mapped_column(String(64))
    directory_name: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String)
    reserved: Mapped[bool] = mapped_column(Boolean)
    authority: Mapped[dict] = mapped_column(JSON)
    intent: Mapped[dict] = mapped_column(JSON)
    intent_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    child_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    diagnostic: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class ProjectCreationOperationEventRow(Base):
    __tablename__ = 'project_creation_operation_events'
    __table_args__ = (UniqueConstraint('operation_id', 'version'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey('project_creation_operations.id'))
    version: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    request_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)


class ProjectPreparationOperationRow(Base):
    __tablename__ = 'project_preparation_operations'
    __table_args__ = (Index('uq_preparation_reserved', 'root', unique=True,
                           sqlite_where=text('reserved = 1')),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('registered_projects.id'))
    root: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    request_sha256: Mapped[str] = mapped_column(String(64))
    previous_id: Mapped[str | None] = mapped_column(ForeignKey('project_preparation_operations.id'), nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    reserved: Mapped[bool] = mapped_column(Boolean)
    plan: Mapped[dict] = mapped_column(JSON)
    plan_sha256: Mapped[str] = mapped_column(String(64))
    owner_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[str | None] = mapped_column(String(40), nullable=True)
    process_owner: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    owner_closed: Mapped[bool] = mapped_column(Boolean, server_default='0')
    cancel_requested: Mapped[bool] = mapped_column(Boolean, server_default='0')
    commit_intent: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    receipt: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    diagnostic: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class ProjectPreparationStepRow(Base):
    __tablename__ = 'project_preparation_steps'
    __table_args__ = (UniqueConstraint('operation_id', 'number'),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey('project_preparation_operations.id'))
    number: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24))
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ProjectPreparationEventRow(Base):
    __tablename__ = 'project_preparation_events'
    __table_args__ = (UniqueConstraint('operation_id', 'version'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey('project_preparation_operations.id'))
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    recorded_at: Mapped[str] = mapped_column(String(40))


class ProductPreferencesRow(Base):
    """P011-T007: global language preferences of this installation; a single row, CAS by version."""
    __tablename__ = 'product_preferences'
    __table_args__ = (CheckConstraint('id = 1', name='ck_product_preferences_singleton'),
                      CheckConstraint("ui_language IN ('en', 'es')", name='ck_product_preferences_ui_language'),
                      CheckConstraint("default_work_language IN ('en', 'es')",
                                      name='ck_product_preferences_work_language'))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    format: Mapped[str] = mapped_column(String(40))
    ui_language: Mapped[str] = mapped_column(String(2))
    default_work_language: Mapped[str] = mapped_column(String(2))
    version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[str] = mapped_column(String(40))


class ProductPreferenceEventRow(Base):
    """Audited change of the preferences; the idempotency key replays its result."""
    __tablename__ = 'product_preference_events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    request_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)


class ProjectWorkLanguageRow(Base):
    """P011-T008: work language confirmed once per canonical root; written once, never updated or deleted."""
    __tablename__ = 'project_work_languages'
    __table_args__ = (CheckConstraint("work_language IN ('en', 'es')", name='ck_project_work_languages_language'),
                      CheckConstraint("source IN ('registration', 'creation', 'toml', 'migration')",
                                      name='ck_project_work_languages_source'))
    root: Mapped[str] = mapped_column(String, primary_key=True)
    format: Mapped[str] = mapped_column(String(40))
    project_id: Mapped[str] = mapped_column(String(64))
    work_language: Mapped[str] = mapped_column(String(2))
    source: Mapped[str] = mapped_column(String(20))
    confirmation: Mapped[dict] = mapped_column(JSON)
    sha256: Mapped[str] = mapped_column(String(64))
    confirmed_at: Mapped[str] = mapped_column(String(40))


class ConfigurationScopeRow(Base):
    """Mutable references only; content authority lives in immutable TOML files (D217)."""
    __tablename__ = 'configuration_scopes'
    scope: Mapped[str] = mapped_column(String(80), primary_key=True)
    directory: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    saved_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pending_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pending_operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    working_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[str] = mapped_column(String(40))


class ConfigurationRevisionRow(Base):
    __tablename__ = 'configuration_revisions'
    __table_args__ = (CheckConstraint("status IN ('DRAFT', 'VALIDATED')", name='ck_configuration_revision_status'),)
    scope: Mapped[str] = mapped_column(ForeignKey('configuration_scopes.scope'), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    operation_id: Mapped[str] = mapped_column(ForeignKey('configuration_operations.id'))
    created_at: Mapped[str] = mapped_column(String(40))


class ConfigurationOperationRow(Base):
    """Intent/candidates are a recovery journal, never a second executable configuration."""
    __tablename__ = 'configuration_operations'
    __table_args__ = (CheckConstraint("status IN ('INTENDED', 'FILES_WRITTEN', 'SAVED', 'RECOVERY_REQUIRED', 'CONFLICT', 'APPLIED')",
                                      name='ck_configuration_operation_status'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    format: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    request_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


# --- P001-T003 (D254–D257, D259): additive invocation accounting -------------------------------------


class UsageInvocationRow(Base):
    """One logical model invocation per native source; no synthetic run/attempt for other sources.

    The lifecycle columns advance under the native source owner; captures and valuations are append-only."""
    __tablename__ = 'usage_invocations'
    __table_args__ = (
        UniqueConstraint('source_kind', 'source_id'),
        CheckConstraint("source_kind IN ('managed_attempt', 'preparation_step', 'configuration_assistance')",
                        name='ck_usage_invocation_source'),
        CheckConstraint("launch IN ('pending', 'not_invoked', 'observed', 'unknown_execution')",
                        name='ck_usage_invocation_launch'),
        CheckConstraint("(source_kind = 'managed_attempt' AND attempt_id = source_id AND run_id IS NOT NULL "
                        "AND preparation_step_id IS NULL AND operation_id IS NULL) OR "
                        "(source_kind = 'preparation_step' AND preparation_step_id = source_id "
                        "AND preparation_id IS NOT NULL AND attempt_id IS NULL AND operation_id IS NULL) OR "
                        "(source_kind = 'configuration_assistance' AND operation_id = source_id "
                        "AND attempt_id IS NULL AND preparation_step_id IS NULL)", name='ck_usage_invocation_link'),
        Index('ix_usage_invocations_scope', 'root', 'phase_code', 'task_id'),
        Index('ix_usage_invocations_started', 'started_at'))
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str] = mapped_column(String(36))
    attempt_id: Mapped[str | None] = mapped_column(ForeignKey('managed_attempts.id'), nullable=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey('managed_runs.id'), nullable=True)
    preparation_id: Mapped[str | None] = mapped_column(ForeignKey('project_preparation_operations.id'), nullable=True)
    preparation_step_id: Mapped[str | None] = mapped_column(ForeignKey('project_preparation_steps.id'), nullable=True)
    operation_id: Mapped[str | None] = mapped_column(ForeignKey('configuration_operations.id'), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    root: Mapped[str | None] = mapped_column(String, nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    phase_code: Mapped[str | None] = mapped_column(String, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    purpose: Mapped[str] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(40))
    agent: Mapped[str | None] = mapped_column(String(20), nullable=True)
    requested_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    requested_effort: Mapped[str | None] = mapped_column(String(40), nullable=True)
    versions: Mapped[dict] = mapped_column(JSON)
    binding: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    binding_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    launch: Mapped[str] = mapped_column(String(20))
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    started_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    recorded_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class UsageCaptureRow(Base):
    """Append-only allowlisted evidence; identical replays are no-ops, changed evidence is another row."""
    __tablename__ = 'usage_captures'
    __table_args__ = (UniqueConstraint('invocation_id', 'version', 'digest'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invocation_id: Mapped[str] = mapped_column(ForeignKey('usage_invocations.id'))
    version: Mapped[str] = mapped_column(String(40))
    digest: Mapped[str] = mapped_column(String(64))
    document: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(20))
    recorded_at: Mapped[str] = mapped_column(String(40))


class UsageComponentRow(Base):
    """Alternative views of one capture (terminal, model, request); inclusive views are never added."""
    __tablename__ = 'usage_components'
    capture_id: Mapped[int] = mapped_column(ForeignKey('usage_captures.id'), primary_key=True)
    key: Mapped[str] = mapped_column(String(250), primary_key=True)
    grain: Mapped[str] = mapped_column(String(20))
    parent_key: Mapped[str | None] = mapped_column(String(250), nullable=True)
    inclusion: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reported_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    semantics: Mapped[str | None] = mapped_column(String(40), nullable=True)
    coverage: Mapped[str] = mapped_column(String(20))
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    write_5m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    write_1h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasons: Mapped[list] = mapped_column(JSON)


class MetricsReferenceRow(Base):
    """Content-addressed immutable identity/tariff documents and bundle envelopes (canonical UTF-8 JSON)."""
    __tablename__ = 'metrics_references'
    __table_args__ = (CheckConstraint("kind IN ('model_identity', 'tariff', 'bundle')", name='ck_metrics_reference_kind'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    format: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    product: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    observed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    recorded_at: Mapped[str] = mapped_column(String(40))


class UsageValuationRow(Base):
    """Immutable valuation; another interpretation is another row, optionally superseding an earlier one."""
    __tablename__ = 'usage_valuations'
    __table_args__ = (UniqueConstraint('invocation_id', 'capture_id', 'normalization', 'calculator', 'profile_digest',
                                       'reference_set_digest', 'basis', 'scenario_digest'),
                      CheckConstraint("status IN ('complete', 'incomplete', 'unsupported')", name='ck_usage_valuation_status'),
                      CheckConstraint("origin IN ('admission', 'backfill', 'repricing')", name='ck_usage_valuation_origin'))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    invocation_id: Mapped[str] = mapped_column(ForeignKey('usage_invocations.id'))
    capture_id: Mapped[int] = mapped_column(ForeignKey('usage_captures.id'))
    origin: Mapped[str] = mapped_column(String(20))
    normalization: Mapped[str] = mapped_column(String(40))
    calculator: Mapped[str] = mapped_column(String(40))
    profile_digest: Mapped[str] = mapped_column(String(64))
    reference_set_digest: Mapped[str] = mapped_column(ForeignKey('metrics_references.id'))
    basis: Mapped[str] = mapped_column(String(40))
    scenario_digest: Mapped[str] = mapped_column(String(64))
    evidence_digest: Mapped[str] = mapped_column(String(64))
    scenario: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20))
    unit: Mapped[str] = mapped_column(String(80))
    scheme: Mapped[str] = mapped_column(String(80))
    amount: Mapped[str | None] = mapped_column(String(200), nullable=True)
    known_subtotal: Mapped[str | None] = mapped_column(String(200), nullable=True)
    exact_sum: Mapped[str | None] = mapped_column(Text, nullable=True)
    rounding_adjustment: Mapped[str | None] = mapped_column(Text, nullable=True)
    counterfactual: Mapped[bool] = mapped_column(Boolean)
    retrospective: Mapped[bool] = mapped_column(Boolean)
    reasons: Mapped[list] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON)
    selected_components: Mapped[list] = mapped_column(JSON)
    discrepancy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    supersedes: Mapped[str | None] = mapped_column(ForeignKey('usage_valuations.id'), nullable=True)
    recorded_at: Mapped[str] = mapped_column(String(40))


class UsageValuationLineRow(Base):
    """Exact decimal-string line amounts; never SQLite REAL."""
    __tablename__ = 'usage_valuation_lines'
    valuation_id: Mapped[str] = mapped_column(ForeignKey('usage_valuations.id'), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_key: Mapped[str] = mapped_column(String(250))
    category: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[int] = mapped_column(Integer)
    rate: Mapped[dict] = mapped_column(JSON)
    factors: Mapped[list] = mapped_column(JSON)
    included_adjustments: Mapped[list] = mapped_column(JSON)
    tariff_reference: Mapped[str] = mapped_column(ForeignKey('metrics_references.id'))
    identity_reference: Mapped[str | None] = mapped_column(ForeignKey('metrics_references.id'), nullable=True)
    rate_case: Mapped[str] = mapped_column(String(200))
    exact_amount: Mapped[str] = mapped_column(Text)


class ValuationCohortRow(Base):
    """Explicit backfill/repricing selection; closed cohorts freeze their membership."""
    __tablename__ = 'valuation_cohorts'
    __table_args__ = (CheckConstraint("kind IN ('backfill', 'repricing')", name='ck_valuation_cohort_kind'),
                      CheckConstraint("status IN ('BUILDING', 'CLOSED')", name='ck_valuation_cohort_status'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    request_sha256: Mapped[str] = mapped_column(String(64))
    selection: Mapped[dict] = mapped_column(JSON)
    selection_digest: Mapped[str] = mapped_column(String(64))
    scenario: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    scenario_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_set_digest: Mapped[str | None] = mapped_column(ForeignKey('metrics_references.id'), nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    expected: Mapped[int] = mapped_column(Integer)
    built: Mapped[int] = mapped_column(Integer)
    cursor: Mapped[str | None] = mapped_column(String(80), nullable=True)
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    closed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class ValuationCohortMemberRow(Base):
    """One member per (cohort, invocation, basis): a selected immutable valuation or an explicit reason."""
    __tablename__ = 'valuation_cohort_members'
    __table_args__ = (CheckConstraint('(valuation_id IS NULL) <> (reason IS NULL)', name='ck_valuation_cohort_member'),)
    cohort_id: Mapped[str] = mapped_column(ForeignKey('valuation_cohorts.id'), primary_key=True)
    invocation_id: Mapped[str] = mapped_column(ForeignKey('usage_invocations.id'), primary_key=True)
    basis: Mapped[str] = mapped_column(String(40), primary_key=True)
    valuation_id: Mapped[str | None] = mapped_column(ForeignKey('usage_valuations.id'), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    recorded_at: Mapped[str] = mapped_column(String(40))


GRAPH_THREAD_STATUSES = ('RUNNING', 'WAITING', 'COMPLETED', 'CANCELLED', 'REVOKED', 'QUARANTINED',
                         'RECOVERY_REQUIRED', 'FAILED')


class GraphThreadRow(Base):
    """P002-T003 (D282, D283): one LangGraph continuation stamped with its graph identity, version and fingerprint.

    Routing progress only; the domain journal stays the authority. `reason` is a code, never a localized text."""
    __tablename__ = 'graph_threads'
    __table_args__ = (CheckConstraint(f"status IN {GRAPH_THREAD_STATUSES}", name='ck_graph_thread_status'),
                      Index('ix_graph_threads_status', 'status'))
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    graph_id: Mapped[str] = mapped_column(String(120))
    graph_version: Mapped[str] = mapped_column(String(40))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30))
    segments: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class GraphCheckpointRow(Base):
    """An immutable serialized checkpoint (strict serializer); a second put of the same id must carry the same bytes."""
    __tablename__ = 'graph_checkpoints'
    thread_id: Mapped[str] = mapped_column(ForeignKey('graph_threads.id'), primary_key=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(200), primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checkpoint_type: Mapped[str] = mapped_column(String(40))
    checkpoint: Mapped[bytes] = mapped_column(LargeBinary)
    metadata_type: Mapped[str] = mapped_column(String(40))
    metadata_value: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[str] = mapped_column(String(40))


class GraphCheckpointWriteRow(Base):
    """A pending write of one task against a checkpoint; LangGraph's special channels replace their own row."""
    __tablename__ = 'graph_checkpoint_writes'
    thread_id: Mapped[str] = mapped_column(ForeignKey('graph_threads.id'), primary_key=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(200), primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(200))
    value_type: Mapped[str] = mapped_column(String(40))
    value: Mapped[bytes] = mapped_column(LargeBinary)
    task_path: Mapped[str] = mapped_column(String(400))
