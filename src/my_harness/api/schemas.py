from datetime import datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class SimulationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=120)


class SimulationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    created_at: datetime
    events: tuple[str, ...]
    kind: Literal["simulation"] = "simulation"
    status: Literal["completed"] = "completed"


class HealthRead(BaseModel):
    status: Literal["ok"] = "ok"
    mode: Literal["simulation"] = "simulation"


Item = TypeVar("Item")


class Page(BaseModel, Generic[Item]):
    items: list[Item]
    offset: int
    next_offset: int | None


class ProblemRead(BaseModel):
    code: str
    diagnostic: str


class ProblemResponse(BaseModel):
    detail: ProblemRead


class SupervisorRead(BaseModel):
    read_only_archive: bool
    enabled: bool
    alive: bool
    last_error: str | None
    ports_configured: bool
    commit_writer_configured: bool
    configuration_mode: str | None = None


class ReviewerAgentRead(BaseModel):
    """D052: the reviewer plans, reviews, evaluates phases, converses and proposes the bootstrap (read-only)."""
    provider: str | None  # null outside a local-config-2 CLI composition (demo or injected adapter)
    model: str
    effort: str


class SelectionRead(BaseModel):
    model: str
    effort: str


class ExecutorAgentRead(BaseModel):
    """Sole writer; the reviewer fixes its model and effort in each task and review."""
    provider: str | None
    selection_mode: Literal["catalog", "open"]
    models: list[str]
    efforts: list[str]
    effort_vocabulary: list[str]


class ProjectAgentsRead(BaseModel):
    planning_mode: Literal["auto", "agent", "deterministic"]
    reviewer: ReviewerAgentRead
    planner: SelectionRead
    executor: ExecutorAgentRead


class WorkLanguageRead(BaseModel):
    """P011-T008: work language confirmed once for the project's canonical root; it never changes (D167)."""
    format: Literal["work-language-1"]
    work_language: Literal["en", "es"]
    source: Literal["registration", "creation", "toml", "migration"]
    project_id: str = Field(description="Project that confirmed it; a later registration of the same root keeps it.")
    confirmation: dict[str, Any]
    sha256: str
    confirmed_at: str


class ManagedProjectRead(BaseModel):
    id: str
    root: str
    profile: str | None
    configuration_state: Literal['PROFILE_REQUIRED', 'PROFILE_PROPOSED', 'DOCUMENTS_COMMITTED', 'PREPARATION_REQUIRED', 'READY_TO_ACTIVATE', 'ACTIVE'] = 'ACTIVE'
    versions: dict[str, str | None]
    tag_kind: Literal["lightweight", "annotated"]
    agents: ProjectAgentsRead
    documents: Literal["v2"] | None = Field(default=None, description="Unified D088 documentary contract; null only when reading earlier projects.")
    source: Literal["operator", "registry"] = Field(
        default="operator", description="D076: declared in the operator TOML or registered from the UI.")
    registry_version: int | None = Field(default=None, description="Registry version frozen in its jobs.")
    bootstrap_enabled: bool = False
    work_language: WorkLanguageRead | None = Field(
        default=None, description="Null until confirmed: new work is refused with 409 `work_language_required`.")


class ModeRead(BaseModel):
    project_id: str
    root: str
    refusal: str | None


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    task_id: str = Field(min_length=1, max_length=120)
    phase_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=200_000)
    source_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')] | None = Field(default=None, description=(
        'Hash of the section chosen in `/projects/{id}/task-sources` (P009-T020). The server reads the '
        'document again and responds 409 if the task is gone or its text changed. Without it, the text is used as is.'))
    notes: str | None = Field(default=None, max_length=4000, description=(
        'Additional notes for the agent. They are frozen in the contract (`additional_notes`) and reach the planner, '
        'the executor and the reviewer; they never widen paths, commands or permissions. Empty equals absent.'))


class TaskSourceRead(BaseModel):
    task_id: str
    phase_id: str
    title: str
    text: str = Field(description='Literal section of the task, preceded by the shared constraints if there are any.')
    sha256: str


class TaskSourcesRead(BaseModel):
    path: str
    sha256: str | None = Field(description='Hash of the document read; null if it does not exist.')
    items: list[TaskSourceRead]
    diagnostics: list[str] = Field(description='Repeated tasks or missing document: not offered for queuing.')


class RunActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["revalidate", "retry_executor", "commit"]
    expected_version: int = Field(ge=0)


class ConfirmStoppedCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    owner_token: str = Field(min_length=1, max_length=64)
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=2000)


Language = Literal["en", "es"]


class UiLanguageContextRead(BaseModel):
    """P011-T007: visual language frozen when the job was admitted; null in jobs earlier than 0024."""
    format: Literal["ui-language-1"]
    ui_language: Language
    preferences_version: int


class LanguageContextRead(BaseModel):
    """P011-T008: language pair frozen when the job was admitted (D167); continuations keep the first job's value."""
    format: Literal["language-context-1"]
    ui_language: Language
    preferences_version: int
    work_language: Language
    work_language_source: Literal["registration", "creation", "toml", "migration"]
    work_language_sha256: str


class PreferencesRead(BaseModel):
    """Global preferences of this installation; `invalid` reads as English and blocks new admissions."""
    format: Literal["product-preferences-1"]
    version: int
    ui_language: Language
    default_work_language: Language
    updated_at: str | None
    status: Literal["stored", "default", "invalid"]


class PreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=0)
    ui_language: Language
    default_work_language: Language


class PreferencesUpdateRead(PreferencesRead):
    replayed: bool


class ManagedJobRead(BaseModel):
    id: int
    run_id: str
    action: str
    status: str
    idempotency_key: str
    owner_token: str | None
    lease_until: str | None
    created_at: str
    finished_at: str | None
    diagnostic: str | None
    activation_id: str | None
    owner_closed: bool
    language_context: LanguageContextRead | UiLanguageContextRead | None = Field(
        description="`ui-language-1` in jobs admitted under 0024, `language-context-1` afterwards; null before.")


class ManagedRunSummaryRead(BaseModel):
    id: str
    project_id: str | None
    root: str
    task_id: str
    phase_id: str
    status: str
    stage: str
    version: int
    revisions: int
    revision_limit: int
    created_at: str
    updated_at: str
    purpose: Literal['task', 'phase_check', 'phase_close', 'chat', 'document_export', 'bootstrap', 'bootstrap_discovery',
                     'definition', 'phase_planning', 'project_import', 'onboarding', 'import_commit',
                     'document_edit', 'phase_transition']



class PhaseTaskRead(BaseModel):
    """Summary of a phase task for its `PNNN-TNNN` URL (D076); without runs, `latest` is null."""
    task_id: str
    planned: bool = Field(description='The task appears in the current definition of the phase.')
    runs: int = Field(description='Runs with the task purpose recorded for this task.')
    latest: ManagedRunSummaryRead | None


class StopRead(BaseModel):
    stage: str
    reason: str


class JUnitCaseRead(BaseModel):
    id: str
    reported_id: str | None
    name: str | None
    classname: str | None
    suite: list[str | None]
    result: Literal['passed', 'failed', 'error', 'skipped', 'unknown']
    duration_seconds: float | None
    message: str | None
    error_type: str | None
    error: str | None


class JUnitReportRead(BaseModel):
    path: str
    coverage: str
    status: Literal['complete', 'partial', 'invalid', 'missing', 'unreadable', 'limit', 'stale']
    diagnostics: list[str]
    sha256: str | None
    size_bytes: int | None
    freshness: Literal['unknown', 'created', 'changed', 'unchanged']
    case_count: int
    original_available: bool


class ValidationEntryRead(BaseModel):
    command: dict[str, Any] | None
    requested: str
    result: dict[str, Any]
    command_id: str | None
    reports: list[JUnitReportRead]


class ValidationRead(BaseModel):
    evidence: dict[str, Any]
    entries: list[ValidationEntryRead]
    run_id: str | None
    source_attempt_id: str | None


class JUnitCasesRead(BaseModel):
    report: JUnitReportRead
    run_id: str | None
    source_attempt_id: str | None
    command_id: str | None
    evidence: dict[str, Any]
    items: list[JUnitCaseRead]
    offset: int
    next_offset: int | None


class CycleRead(BaseModel):
    diff_sha256: str = Field(description='SHA-256 of the reviewed cycle diff (stored UTF-8 text); its content is read '
                                         'paginated at `/runs/{id}/cycles/{n}/diff`.')
    diff_bytes: int = Field(description='Size in UTF-8 bytes of the reviewed diff of the cycle.')
    provenance: dict[str, Any] | None
    validation: ValidationRead
    review: dict[str, Any] | None
    formatting: dict[str, Any] | None = Field(default=None, description='Profile formatting after the executor '
                                              'attempt (command, paths, result); null if there was none (D133).')
    number: int
    verdict: str | None
    fingerprint: str
    changed_paths: list[str]


class CycleDiffRead(BaseModel):
    run_id: str
    cycle: int
    sha256: str
    size_bytes: int
    offset: int
    next_offset: int | None = Field(description='Offset of the next page; null on the last one. Pages end at '
                                                'a line end except for a line longer than the limit, cut at a UTF-8 boundary.')
    text: str


class AcceptanceRead(BaseModel):
    eligible: bool
    reasons: list[str]
    base_revision: str
    fingerprint: str
    changed_paths: list[str]


class ManagedHistoryRead(BaseModel):
    status: str
    task: dict[str, Any] | None
    stop: StopRead | None
    stops: list[StopRead]
    attempts: int
    cycle_count: int = Field(description='Review cycles of the run; read by pages at `/runs/{id}/cycles`.')
    latest_cycle: CycleRead | None = Field(description='Last review cycle; null if the run has no cycles yet.')
    acceptance: AcceptanceRead | None


class ManagedCommitRead(BaseModel):
    operation_id: str
    job_id: int
    status: Literal["INTENT", "COMMITTED", "INVALIDATED"]
    base_revision: str
    reviewed_fingerprint: str
    expected_tree: str
    expected_commit: str
    commit: str | None
    result: dict[str, Any] | None
    created_at: str
    finished_at: str | None


class ManagedRunRead(ManagedRunSummaryRead):
    actions: list[Literal['revalidate', 'retry_executor', 'commit', 'permissions']]
    versions: dict[str, str | None]
    history: ManagedHistoryRead
    commit: ManagedCommitRead | None
    locked_by_job: int | None
    active_job: int | None = Field(description='Job of the run queued, running or pending recovery; null if the run '
                                               'does not advance without a new action.')


class ManagedAttemptRead(BaseModel):
    prompt: str
    permission_snapshot: dict[str, Any] | None = None
    prompt_snapshot: dict[str, Any] | None
    id: str
    number: int
    role: str
    selection: dict[str, Any]
    fresh_session: bool
    status: str
    versions: dict[str, str | None]
    result: dict[str, Any] | None
    started_at: str
    finished_at: str | None
    language_context: LanguageContextRead | UiLanguageContextRead | None = Field(
        default=None, description="Language pair of the job, copied when the attempt started; null before 0025.")


class ManagedEventRead(BaseModel):
    id: int
    sequence: int
    kind: str
    recorded_at: str
    payload: dict[str, Any]


class ManagedLogRead(BaseModel):
    stream: str
    source: str
    sha256: str
    size_bytes: int
    state: Literal['retained', 'purged', 'pending', 'missing', 'unverified']
    diagnostic: str | None
    authorization: dict[str, Any] | None


class ManagedEventsRead(BaseModel):
    items: list[ManagedEventRead]
    cursor: int
    has_more: bool


PromptScope = Literal['core', 'profile', 'project']


class PromptVersionRead(BaseModel):
    name: str
    id: str
    scope: str
    owner: str
    template: str
    sha256: str
    source: str


class PromptActivationRead(BaseModel):
    previous_id: str | None
    version_id: str
    reason: str
    generation: int
    created_at: str


class PromptDetailRead(BaseModel):
    name: str
    scope: PromptScope
    owner: str
    generation: int
    active_id: str | None
    effective: PromptVersionRead
    variables: list[str]
    versions: list[PromptVersionRead]
    activations: list[PromptActivationRead]


class PromptDraftCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=0)
    template: str | None = Field(default=None, max_length=100000)
    from_version: str | None = Field(default=None, max_length=200)


class PromptActivateCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=0)
    version_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    confirmed: Literal[True]


class PromptValidateCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    template: str = Field(max_length=100000)


class PromptValidationRead(BaseModel):
    variables: list[str]


class PromptDiffRead(BaseModel):
    diff: str


PermissionKind = Literal['files', 'tools', 'network', 'product', 'acceptance']


class PermissionCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_version: int = Field(ge=0)
    kind: PermissionKind
    target: str = Field(min_length=1, max_length=2000)
    operation: str = Field(min_length=1, max_length=120)
    arguments: list[str] = Field(max_length=100)
    requested_by: str = Field(min_length=1, max_length=120)
    source_attempt_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=1, max_length=2000)
    ttl_seconds: int = Field(ge=1, le=86400)
    supersedes: str | None = None


class PermissionDecisionCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_version: int = Field(ge=0)
    expected_request_version: int = Field(ge=1)
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    decision: Literal['grant', 'deny']
    scope: Literal['once', 'task']
    reason: str = Field(min_length=1, max_length=2000)
    confirmed: Literal[True]


class PermissionRequestRead(BaseModel):
    id: str
    run_id: str
    version: int
    status: str
    effective_status: str
    request: dict[str, Any]
    fingerprint: str
    expires_at: str
    decision: dict[str, Any] | None
    consumed_by: str | None
    supersedes: str | None


PhaseStatus = Literal['ACTIVE', 'CHECKING', 'READY_TO_CLOSE', 'NEEDS_RECONCILIATION', 'BLOCKED', 'CLOSING', 'CLOSED',
                      'ABANDONED']
PhaseAction = Literal['check', 'reconcile', 'reconcile_task', 'close', 'question', 'authorize_batch', 'batch_next',
                      'amend', 'abandon']


class PhaseCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    code: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=4000)
    exit_criteria: list[str] = Field(min_length=1, max_length=100)
    tasks: list[str] = Field(max_length=200)
    documents: list[str] | None = Field(default=None, max_length=50,
                                        description='Checkout paths; by default the project STATE and NEXT_STEPS.')
    tag: str | None = Field(default=None, max_length=100)


class PhaseSummaryRead(BaseModel):
    id: str
    code: str
    objective: str
    status: PhaseStatus
    version: int
    created_at: str
    updated_at: str


class PhaseDocumentsRead(BaseModel):
    baseline: dict[str, str | None]
    current: dict[str, str | None] | None
    drift: list[str] | None
    current_sha256: str | None


class PhaseQuestionRead(BaseModel):
    id: str
    text: str
    source: dict[str, Any]
    status: Literal['OPEN', 'ANSWERED']
    answer: dict[str, Any] | None
    version: int
    created_at: str


class PhaseOperationRead(BaseModel):
    id: str
    kind: Literal['check', 'close', 'reconcile', 'reconcile_task', 'amend', 'abandon', 'document_export',
                  'transition', 'document_edit']
    run_id: str | None
    status: str
    previous_status: str
    request: dict[str, Any]
    result: dict[str, Any] | None
    created_at: str
    finished_at: str | None


class PhaseAuthorizationRead(BaseModel):
    id: str
    kind: Literal['batch', 'close']
    status: str
    effective_status: str
    scope: dict[str, Any]
    fingerprint: str
    actor: dict[str, Any]
    reason: str
    expires_at: str
    created_at: str
    closed: dict[str, Any] | None
    version: int


class PhaseReadyRead(BaseModel):
    operation_id: str
    binding: dict[str, Any]
    binding_sha256: str
    stale_reasons: list[str]


class PhaseClosureCheckRead(BaseModel):
    operation_id: str
    verdict: str
    finished_at: str | None
    summary: str | None
    exit_criteria_results: list[dict[str, Any]]


class PhaseClosureRead(BaseModel):
    """P010-T005: historical evidence of a CLOSED or ABANDONED phase; never recomputed with the current state."""
    operation_id: str
    status: Literal['CLOSED', 'ABANDONED']
    finished_at: str | None
    actor: dict[str, Any] | None
    reason: str | None
    commit: str | None
    tag: dict[str, Any] | None = Field(description='Result of the tag created on closing; null without a tag.')
    archive: str | None
    check: PhaseClosureCheckRead | None = Field(description='READY check that authorized closing; null if abandoned.')
    binding: dict[str, Any] = Field(description='Historical base: head, evidence hash and documents of the READY.')
    documents: dict[str, str | None] = Field(
        description='Expected hashes: adopted base, closure renewal and later confirmed edits.')
    renewed: list[str] = Field(description='Expected differences from the adopted base.')
    changed: list[str] | None = Field(
        description='Live documents unlike the expected ones; null with a successor or if unreadable.')
    archive_files: list[str]
    archive_altered: list[str] | None = Field(
        description='Archive files that no longer have the closure bytes; null if they could not be read.')


class PhaseDefinitionRead(BaseModel):
    number: int
    definition: dict[str, Any]
    definition_sha256: str
    documents: dict[str, str | None]
    origin: Literal['created', 'amended', 'migrated']
    reason: str | None
    actor: dict[str, Any] | None
    created_at: str


class PhaseRead(BaseModel):
    id: str
    project_id: str | None
    root: str
    code: str
    definition: dict[str, Any]
    definition_sha256: str
    definition_number: int
    definitions: list[PhaseDefinitionRead]
    tag_kind: Literal['lightweight', 'annotated'] | None = Field(
        description='Tag kind the closure will set according to the registered project; null if it is not registered.')
    status: PhaseStatus
    version: int
    created_at: str
    updated_at: str
    documents: PhaseDocumentsRead
    tasks: dict[str, dict[str, str] | None]
    questions: list[PhaseQuestionRead]
    operations: list[PhaseOperationRead]
    authorizations: list[PhaseAuthorizationRead]
    ready: PhaseReadyRead | None
    closure: PhaseClosureRead | None = Field(description='Recorded closure or abandonment; null while the phase is open.')
    actions: list[PhaseAction]
    successor: str | None = Field(description='Code of the next phase of the checkout; null if this is the last. Only the '
                                              'last one exports its state and decides on its documents.')


class PhaseVersioned(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=0)


class PhaseCheckCreate(PhaseVersioned):
    action: Literal['check']


class PhaseCloseCreate(PhaseVersioned):
    action: Literal['close']
    binding_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    reason: str = Field(min_length=1, max_length=2000)
    ttl_seconds: int = Field(default=3600, ge=1, le=86400)
    confirmed: Literal[True]


class PhaseReconcileCreate(PhaseVersioned):
    documents_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    reason: str = Field(min_length=1, max_length=2000)
    confirmed: Literal[True]


class PhaseQuestionCreate(PhaseVersioned):
    text: str = Field(min_length=1, max_length=4000)


class PhaseAnswerCreate(PhaseVersioned):
    expected_question_version: int = Field(ge=1)
    answer: str = Field(min_length=1, max_length=4000)
    confirmed: Literal[True]


class PhaseBatchCreate(PhaseVersioned):
    tasks: list[str] = Field(min_length=1, max_length=200)
    ttl_seconds: int = Field(ge=1, le=86400)
    reason: str = Field(min_length=1, max_length=2000)
    confirmed: Literal[True]
    chain_commits: bool = Field(default=False, description=(
        'Explicit scope «chain tasks and confirm commits»: the supervisor queues each task, the commit of '
        'each eligible acceptance and the next task; it stops at the first blocker. It never checks or closes.'))
    text: str | None = Field(default=None, min_length=1, max_length=200_000,
                             description='Frozen plan text; required only with chain_commits.')


class PhaseAmendCreate(PhaseVersioned):
    objective: str = Field(min_length=1, max_length=4000)
    exit_criteria: list[str] = Field(min_length=1, max_length=100)
    tasks: list[str] = Field(max_length=200)
    documents: list[str] = Field(min_length=1, max_length=50)
    tag: str | None = Field(default=None, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)
    confirmed: Literal[True]


class PhaseAbandonCreate(PhaseVersioned):
    reason: str = Field(min_length=1, max_length=2000)
    confirmed: Literal[True]


class PhaseReconcileTaskCreate(PhaseVersioned):
    pass


class DocumentExportPreviewRead(BaseModel):
    expected_version: int
    resume_operation_id: str | None
    preview_sha256: str
    snapshot: dict[str, Any]
    baseline: dict[str, str | None]
    head: str
    fingerprint: str
    tree: str
    index_tree: str
    documents: list[dict[str, Any]]
    mechanical: list[dict[str, str]]
    diff: str


class DocumentExportCreate(PhaseVersioned):
    preview_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    resume_operation_id: str | None = Field(default=None, max_length=36)
    reason: str = Field(min_length=1, max_length=2000)
    confirmed: Literal[True]


# --- D072/H6.3: per-phase documentary contract ---------------------------------------------------


DocumentKind = Literal['phase', 'product', 'instructions', 'diagram', 'flow', 'phase_work', 'archive', 'other']


class DocumentStateRead(BaseModel):
    path: str
    kind: DocumentKind
    exists: bool
    sha256: str | None
    adopted_sha256: str | None
    drift: bool
    blocks: list[str]
    error: str | None


class DocumentFolderRead(BaseModel):
    path: str
    exists: bool


class DocumentChangeRead(BaseModel):
    path: str
    editable: bool


class DecisionEntryRead(BaseModel):
    id: str
    title: str
    status: str | None


class ArchivedPhaseRead(BaseModel):
    path: str
    files: list[str]


class DocumentsStatusRead(BaseModel):
    layout: Literal['v2']
    phase: dict[str, Any] | None
    documents: list[DocumentStateRead]
    folders: list[DocumentFolderRead]
    uncommitted: list[DocumentChangeRead] | None = Field(
        description='Local changes of the checkout; null if no Git writer is configured.')
    warnings: list[str]
    decisions: list[DecisionEntryRead]
    archive: list[ArchivedPhaseRead]
    unresolved_intent: bool
    git_error: str | None


class DocumentRead(BaseModel):
    path: str
    content: str
    sha256: str
    editable: bool
    archived: bool
    blocks: list[str]


class DocumentChange(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=512 * 1024)
    base_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')] | None = Field(default=None, description=(
        'Hash of the document when opened in the editor (CAS); null: must not exist. Without it, no comparison.'))


class DocumentEditInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    source: Literal['content', 'worktree'] = Field(
        description='content: documents submitted over a clean checkout; worktree: local changes of the editor.')
    changes: list[DocumentChange] | None = Field(default=None, max_length=50)
    regenerate_blocks: bool = Field(default=False, description=(
        'Worktree only: replaces the managed blocks edited locally with those of the base (H6.2 E3).'))


class DocumentPreviewEntry(BaseModel):
    path: str
    before_sha256: str | None
    after_sha256: str
    content: str
    disk_sha256: str | None = Field(default=None, description='Local bytes that are replaced (regenerated blocks).')


class RegeneratedDocumentRead(BaseModel):
    path: str
    local_sha256: str
    diff: str = Field(description='What is discarded from the local bytes when regenerating the blocks.')


class DocumentTreeEntryRead(BaseModel):
    path: str
    kind: DocumentKind
    editable: bool
    archived: bool
    bytes: int


class DocumentTreeRead(BaseModel):
    docs: str
    files: list[DocumentTreeEntryRead]
    truncated: bool
    skipped: list[str] = Field(description='Symbolic links or non-regular objects that are not listed.')


class DocumentOperationPreview(BaseModel):
    resume_operation_id: str | None
    preview_sha256: str
    operation: Literal['document_edit']
    head: str
    fingerprint: str
    tree: str
    index_tree: str
    documents: list[DocumentPreviewEntry]
    mechanical: list[dict[str, str]]
    diff: str


class DocumentEditPreviewRead(DocumentOperationPreview):
    source: Literal['content', 'worktree']
    regenerated: list[RegeneratedDocumentRead] = []


class DocumentEditCreate(DocumentEditInput):
    preview_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    resume_operation_id: str | None = Field(default=None, max_length=36)
    reason: str = Field(min_length=1, max_length=2000)
    confirmed: Literal[True]


class PhasePlanInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    next_steps: str | None = Field(default=None, max_length=512 * 1024)
    plan_proposal: 'PlanProposalRef | None' = None


class PhasePlanCreate(PhasePlanInput):
    preview_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    resume_operation_id: str | None = Field(default=None, max_length=36)
    reason: str = Field(min_length=1, max_length=2000)
    confirmed: Literal[True]


class PhasePlanPreviewRead(DocumentEditPreviewRead):
    phase_plan: dict[str, Any]


class PhaseRevokeCreate(PhaseVersioned):
    reason: str = Field(min_length=1, max_length=2000)


class PhaseBatchNextCreate(PhaseVersioned):
    authorization_id: str = Field(min_length=1, max_length=36)
    text: str = Field(min_length=1, max_length=200_000)


# --- H4.1: contextual chat -------------------------------------------------------------------

ChatTurnStatus = Literal['QUEUED', 'ANSWERED', 'FAILED', 'UNKNOWN', 'REFUSED']


class ChatConversationCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    task_run_id: str | None = Field(default=None, max_length=36)
    title: str = Field(min_length=1, max_length=200)
    phase_id: str | None = Field(default=None, max_length=36,
                                 description='Managed phase of this project whose context is offered by default.')


class ChatConversationSummaryRead(BaseModel):
    id: str
    title: str
    phase_id: str | None
    phase_code: str | None
    task_run_id: str | None
    turns: int
    version: int
    created_at: str
    updated_at: str


class ChatDocumentRead(BaseModel):
    path: str
    sha256: str | None = Field(description='null: the document did not exist when the turn was frozen.')
    size: int | None
    truncated: bool


class ChatTurnRead(BaseModel):
    id: str
    number: int
    status: ChatTurnStatus
    run_id: str
    run_status: str
    message: str
    documents: list[ChatDocumentRead]
    run_ids: list[str]
    phase_code: str | None
    head: str | None
    command: dict[str, str] | None
    previous_turns: int
    context_sha256: str
    request_sha256: str
    result: dict[str, Any] | None
    actor: dict[str, Any]
    created_at: str
    finished_at: str | None


class ChatProposalRunRead(BaseModel):
    task_id: str
    phase_id: str
    status: str
    commit: str | None


class ChatProposalRead(BaseModel):
    id: str
    number: int
    turn_id: str
    turn_number: int
    status: Literal['PROPOSED', 'ACCEPTED', 'DISMISSED']
    proposal: dict[str, Any]
    proposal_sha256: str
    run_id: str | None
    run: ChatProposalRunRead | None
    decision: dict[str, Any] | None
    version: int
    created_at: str
    actions: list[Literal['accept', 'dismiss']]


class ChatPhaseRead(BaseModel):
    id: str
    code: str
    status: str


class ChatConversationRead(BaseModel):
    id: str
    project_id: str | None
    root: str
    title: str
    phase: ChatPhaseRead | None
    task_run_id: str | None
    actor: dict[str, Any]
    version: int
    created_at: str
    updated_at: str
    turns: list[ChatTurnRead]
    proposals: list[ChatProposalRead]
    actions: list[Literal['message']]


class ChatMessageCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=20_000)
    documents: list[str] | None = Field(default=None, max_length=8, description=(
        'Checkout documents frozen as context; null: those of the phase or STATE and NEXT_STEPS.'))
    run_ids: list[str] = Field(default_factory=list, max_length=10,
                               description='Runs of this checkout whose evidence is frozen as context.')


class ChatProposalAcceptCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=0)
    proposal_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    task_id: str = Field(min_length=1, max_length=120)
    phase_id: str = Field(min_length=1, max_length=120)
    confirmed: Literal[True]


class ChatProposalDismissCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=2000)


class ChatCommandCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=20_000)


class ChatCommandRead(BaseModel):
    name: Literal['estado', 'tests', 'siguiente', 'lote', 'check', 'cerrar', 'exportar', 'abrir-fase', 'tarea']
    argument: str
    conversation_version: int
    phase_code: str | None
    phase_version: int | None
    run_id: str | None
    run_version: int | None
    preview_sha256: str


# --- H6.5: conversational creation and planning ----------------------------------------------------

PlanningKind = Literal['definition', 'phase_planning', 'onboarding']
SHA256 = r'^[0-9a-f]{64}$'


class DefinitionDocumentRead(BaseModel):
    path: str
    content: str
    sha256: str
    before_sha256: str | None = Field(description='Hash of the replaced draft on disk; null if it did not exist.')
    origin: Literal['draft', 'draft+blocks', 'template', 'archive']


class DefinitionPreviewRead(BaseModel):
    """Acceptance of the v2 definition: blockers or the complete files of the root commit (D037 bootstrap)."""
    template: dict[str, str]
    input: dict[str, str]
    definition: dict[str, Any]
    context_sha256: str
    profile_proposal_sha256: str | None = None
    documents: list[DefinitionDocumentRead]
    phase: dict[str, Any] | None
    first_task: dict[str, Any] | None
    task_text: str | None
    blockers: list[str]
    warnings: list[str]
    preparation: list[dict[str, Any]]
    validations: list[dict[str, Any]]
    policy: dict[str, Any]
    profile: str
    versions: dict[str, str | None]
    target: dict[str, Any]
    author: dict[str, str]
    git: dict[str, str]
    ready: bool
    preview_sha256: str
    resume_operation_id: str | None = None
    expected_version: int | None = None


class DefinitionOperationRead(BaseModel):
    id: str
    root: str
    run_id: str
    phase_id: str | None
    status: Literal['QUEUED', 'COMPLETED', 'INTERRUPTED']
    preview: DefinitionPreviewRead
    intent: dict[str, Any]
    decision: dict[str, Any]
    result: dict[str, Any] | None
    created_at: str
    finished_at: str | None
    expected_version: int
    run_status: str
    first_task_run: dict[str, str] | None


class DefinitionAcceptCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    preview_sha256: str = Field(pattern=SHA256)
    confirmed: Literal[True]
    reason: str = Field(min_length=1, max_length=2000)
    resume_operation_id: str | None = Field(default=None, max_length=36)
    expected_version: int | None = Field(default=None, ge=0)


class PlanningConversationCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: PlanningKind
    title: str = Field(min_length=1, max_length=200)
    brief: str | None = Field(default=None, min_length=1, max_length=256 * 1024, description=(
        'Markdown brief (UTF-8, at most 256 KiB) of a definition; null in planning and import.'))
    phase_id: str | None = Field(default=None, max_length=36,
                                 description='ACTIVE phase without tasks that is planned; earlier historical conversations are kept.')


class PlanningConversationSummaryRead(BaseModel):
    id: str
    kind: PlanningKind
    title: str
    phase_id: str | None
    phase_code: str | None
    turns: int
    version: int
    created_at: str
    updated_at: str


class PlanningTurnRead(BaseModel):
    id: str
    number: int
    status: ChatTurnStatus
    run_id: str
    run_status: str
    message: str
    context_sha256: str
    request_sha256: str
    drafts: list[dict[str, Any]] = Field(description='Frozen drafts (path, hash, size); definition and import.')
    user_edits: list[dict[str, Any]] = Field(description='User edits detected by hash when freezing.')
    documents: list[dict[str, Any]] = Field(description='Frozen documents; phase planning only.')
    result: dict[str, Any] | None
    actor: dict[str, Any]
    created_at: str
    finished_at: str | None


class PlanningProposalRead(BaseModel):
    id: str
    number: int
    turn_id: str
    turn_number: int
    kind: Literal['draft', 'plan', 'profile']
    path: str | None
    content: str
    reason: str
    content_sha256: str
    base_sha256: str | None = Field(description='CAS: hash of the draft the turn read; null if it did not exist.')
    proposal_sha256: str
    status: Literal['PROPOSED', 'APPLIED', 'ACCEPTED', 'DISMISSED', 'SUPERSEDED']
    decision: dict[str, Any] | None
    version: int
    created_at: str
    actions: list[Literal['apply', 'dismiss']]


class PlanningQuestionRead(BaseModel):
    id: str
    text: str
    blocking: bool
    deferred: dict[str, Any] | None


class PlanningConversationRead(BaseModel):
    id: str
    project_id: str | None
    root: str
    kind: PlanningKind
    title: str
    phase: ChatPhaseRead | None
    brief: dict[str, Any] | None
    source: dict[str, Any] | None = Field(default=None, description=(
        'Onboarding: frozen HEAD, tree and inventory fingerprint; null for other conversation kinds.'))
    known: dict[str, str | None]
    log: list[dict[str, Any]]
    questions: list[PlanningQuestionRead]
    pending: list[str]
    actor: dict[str, Any]
    version: int
    created_at: str
    updated_at: str
    created: bool = Field(description='Definition or import already confirmed; its drafts are closed.')
    turns: list[PlanningTurnRead]
    proposals: list[PlanningProposalRead]
    actions: list[Literal['message', 'edit_draft', 'defer_question', 'accept']]
    operation: DefinitionOperationRead | None = None


class PlanningMessageCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=20_000)


class PlanningApplyCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=0)
    proposal_sha256: str = Field(pattern=SHA256)
    confirmed: Literal[True]


class PlanningDismissCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=2000)


class PlanningDeferCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=0)
    question_id: str = Field(pattern=SHA256)
    reason: str = Field(min_length=1, max_length=2000)


class PlanningDraftEdit(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=0)
    path: str = Field(min_length=1, max_length=500)
    content: str | None = Field(max_length=512 * 1024, description='Complete content; null deletes the draft.')
    base_sha256: str | None = Field(pattern=SHA256, description='CAS: current hash on disk; null if it does not exist.')


class PlanningDraftStateRead(BaseModel):
    path: str
    sha256: str | None
    known_sha256: str | None
    user_edited: bool


class PlanningDraftsRead(BaseModel):
    created: bool
    allowed: dict[str, list[str]]
    drafts: list[PlanningDraftStateRead]
    foreign: list[str]
    foreign_truncated: bool
    invalid: list[str]
    import_required: bool


class PlanningDraftContentRead(BaseModel):
    path: str
    content: str
    sha256: str = Field(description='Hash on disk: the CAS base for editing it.')
    known_sha256: str | None = Field(description='Hash the harness knows (last answered turn or applied proposal).')


class PlanningBriefRead(BaseModel):
    content: str
    sha256: str
    size: int


class PlanProposalRef(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    conversation_id: str = Field(min_length=1, max_length=36)
    proposal_id: str = Field(min_length=1, max_length=36)
    proposal_sha256: str = Field(pattern=SHA256)


class BootstrapStatusRead(BaseModel):
    enabled: bool
    import_required: bool
    diagnostic: str | None
    definition_operation: DefinitionOperationRead | None = Field(default=None, description=(
        'Creation confirmed from the definition conversation, with the root commit and P001.'))


# --- H6.4: per-attempt metrics and aggregates (D072 §9) -----------------------------------------------

class MetricSumRead(BaseModel):
    sum: int | None = Field(description='Sum over the attempts that contribute the field; null if none does (not zero).')
    attempts: int = Field(description='Attempts that contribute a value to the field.')


class MetricAmountRead(BaseModel):
    sum: float | None
    attempts: int
    basis: Literal['api_equivalent_reported'] = Field(
        description='API-equivalent cost reported by the provider; it is neither an invoice nor a quota.')


class MetricAccountingRead(BaseModel):
    terminal: int = Field(description='Attempts with the accumulated terminal total (reported).')
    messages: int = Field(description='Attempts without terminal, deduplicated per-message usage (derived, partial).')
    absent: int


class ConsumptionRead(BaseModel):
    attempts: int
    accounting: MetricAccountingRead
    tokens: dict[str, MetricSumRead] = Field(description='uncached_input/cache_read/cache_write/output/reasoning '
                                                         '(⊆ output)/total, each summed separately. Raw '
                                                         'input is not summed: its meaning depends on the provider.')
    cost_usd: MetricAmountRead
    turns_reported: MetricSumRead = Field(description='Claude num_turns.')
    turns_derived: MetricSumRead = Field(description='Completed items of the Codex stream.')
    tool_calls: MetricSumRead
    permission_denials: MetricSumRead
    attempt_wall_ms: MetricSumRead = Field(description='Sum of durations per attempt: agent time, not elapsed time.')
    reported_duration_ms: MetricSumRead
    api_duration_ms: MetricSumRead


class ModelUsageRead(BaseModel):
    model: str
    input_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    cost_usd: float | None


class AttemptMetricRead(BaseModel):
    attempt_id: str
    run_id: str
    number: int
    root: str
    phase_code: str
    task_id: str
    purpose: str
    role: str
    provider: str | None
    adapter_version: str | None
    cli_version: str | None
    requested_model: str | None
    requested_effort: str | None
    reported_models: list[str] | None
    reported_effort: str | None
    status: str
    error: str | None
    verdict: str | None
    executor_round: int
    accounting: Literal['terminal', 'messages'] | None
    input_semantics: Literal['excludes_cache', 'includes_cache_read'] | None
    input_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    uncached_input_tokens: int | None
    total_tokens: int | None
    turns: int | None
    tool_calls: int | None
    tools: dict[str, int] | None
    permission_denials: int | None
    wall_ms: int | None
    duration_ms: int | None
    api_duration_ms: int | None
    cost_usd: float | None
    started_at: str
    finished_at: str | None
    day: str
    source: Literal['capture', 'backfill']
    normalization: str | None
    catalog: str
    provenance: dict[str, str] = Field(description='requested | reported | derived | measured | absent, per field.')
    diagnostics: list[str]
    recorded_at: str
    models: list[ModelUsageRead]


MetricDimension = Literal['role', 'provider', 'requested_model', 'requested_effort', 'day', 'phase', 'task', 'status',
                          'purpose', 'root']
MetricOrder = Literal['attempts', 'tokens', 'key']


class MetricGroupRead(ConsumptionRead):
    key: str | None


class MetricGroupsRead(BaseModel):
    dimension: MetricDimension
    order: MetricOrder
    role: str | None
    items: list[MetricGroupRead]
    offset: int
    next_offset: int | None


class ModelMetricGroupRead(BaseModel):
    key: str
    attempts: int
    tokens: dict[str, MetricSumRead]
    cost_usd: MetricAmountRead


class ModelMetricGroupsRead(BaseModel):
    dimension: Literal['reported_model']
    order: MetricOrder
    role: str | None
    items: list[ModelMetricGroupRead]
    offset: int
    next_offset: int | None


class TaskAgentRead(BaseModel):
    role: str
    provider: str | None
    requested_model: str | None
    requested_effort: str | None
    attempts: int


class ValidationCountsRead(BaseModel):
    commands_passed: int
    commands_failed: int
    cases: dict[str, int] | None = Field(description='JUnit: passed, failed, error, skipped; null if no readable report.')


class StopRead(BaseModel):
    stage: str
    reason: str


class TaskMetricsRead(BaseModel):
    root: str
    phase_code: str
    task_id: str
    runs: int
    status: str | None
    agents: list[TaskAgentRead]
    attempts_by_role: dict[str, int]
    executions: int
    corrections: int | None
    first_verdict: str | None
    accepted_first_time: bool | None
    started_at: str | None
    accepted_at: str | None
    committed_at: str | None
    seconds_to_accept: float | None
    seconds_to_commit: float | None
    tests: ValidationCountsRead | None = Field(description='Last validation of the task.')
    stops: list[StopRead]
    consumption: ConsumptionRead


class MetricsScopeRead(BaseModel):
    root: str | None
    phase: str | None
    task: str | None


class CountSumRead(BaseModel):
    sum: int
    tasks: int


class DurationSumRead(BaseModel):
    sum: float
    tasks: int
    max: float


class TaskQualityRead(BaseModel):
    count: int
    reviewed: int
    accepted_first_time: int
    committed: int
    corrections: CountSumRead | None
    seconds_to_commit: DurationSumRead | None


class ValidationTotalsRead(BaseModel):
    tasks_with_validation: int
    commands_passed: int
    commands_failed: int
    cases: dict[str, int] | None


class StopCountRead(BaseModel):
    purpose: str
    stage: str
    reason: str
    count: int


class StopsRead(BaseModel):
    distinct: int
    items: list[StopCountRead]


ValidationDimension = Literal['phase', 'task', 'root']


class ValidationGroupRead(BaseModel):
    key: str = Field(description='Phase, task or root. Cycles do not store their time: there is no grouping by day.')
    validations: int = Field(description='Task validation cycles, revalidations included.')
    passed: int = Field(description='Validations with every command passing and no new JUnit failures.')
    failed: int
    commands_passed: int
    commands_failed: int
    cases: dict[str, int] | None = Field(description='JUnit: passed, failed, error, skipped; null if no readable report.')
    validations_with_cases: int


class ValidationGroupsRead(BaseModel):
    dimension: ValidationDimension
    items: list[ValidationGroupRead]
    offset: int
    next_offset: int | None


class MetricsSummaryRead(BaseModel):
    scope: MetricsScopeRead
    catalog: str
    consumption: ConsumptionRead
    attempts_without_metrics: int = Field(description='Resolved attempts without a row: explicit backfill pending.')
    tasks: TaskQualityRead
    tests: ValidationTotalsRead
    stops: StopsRead


# --- P001-T004 (D262): invocation accounting, read-only `accounting-aggregate-1` ---------------

AccountingWork = Literal['task_first_pass', 'task_rework', 'phase', 'conversation', 'setup', 'other']
AccountingDimension = Literal['provider', 'effective_model', 'requested_model', 'role', 'purpose', 'work',
                              'source_kind', 'root', 'phase', 'task', 'day', 'outcome', 'launch']
AccountingOrder = Literal['invocations', 'key']
AccountingSource = Literal['managed_attempt', 'preparation_step', 'configuration_assistance']
AccountingLaunch = Literal['pending', 'not_invoked', 'observed', 'unknown_execution']
AccountingModelKind = Literal['reported', 'mixed', 'unknown']
DecimalText = Annotated[str, Field(description='Exact decimal string; never a binary float.')]


class AccountingFiltersRead(BaseModel):
    root: str | None = None
    phase: str | None = None
    task: str | None = None
    provider: str | None = None
    role: str | None = None
    purpose: str | None = None
    source_kind: AccountingSource | None = None
    outcome: str | None = None
    launch: AccountingLaunch | None = None
    requested_model: str | None = None
    effective_model: str | None = None
    effective_model_kind: AccountingModelKind | None = None
    work: list[AccountingWork] | None = Field(default=None, description='With a phase and no explicit work, '
                                              'the phase-work default: conversations and setup are excluded.')
    started_from: str | None = Field(default=None, description='UTC invocation start, inclusive.')
    started_before: str | None = Field(default=None, description='UTC invocation start, exclusive.')


class AccountingCohortRead(BaseModel):
    id: str
    name: str
    kind: Literal['backfill', 'repricing']
    status: Literal['BUILDING', 'CLOSED']
    expected: int
    built: int
    selection_digest: str
    scenario_digest: str | None
    reference_set_digest: str | None
    basis: str | None
    retrospective: bool | None
    created_at: str
    closed_at: str | None


class AccountingSelectionRead(BaseModel):
    policy: Literal['admission', 'cohort'] = Field(description='Original admission-bound valuation per invocation, '
                                                   'or the frozen membership of one named cohort.')
    cohort: AccountingCohortRead | None
    complete: bool = Field(description='False while the cohort is BUILDING: no full amount is available.')


class AccountingLaunchCountsRead(BaseModel):
    pending: int
    not_invoked: int
    observed: int
    unknown_execution: int


class AccountingUsageCountsRead(BaseModel):
    complete: int
    partial: int
    absent: int


class AccountingValuationCountsRead(BaseModel):
    complete: int
    incomplete: int
    unsupported: int
    unpriced: int


class AccountingCoverageRead(BaseModel):
    invocations: int = Field(description='Invocation rows in scope and selection, not-invoked included.')
    expected: int = Field(description='Invocations except not-invoked: the denominator of usage and spend.')
    launch: AccountingLaunchCountsRead
    captured: int
    usage: AccountingUsageCountsRead
    valuation: AccountingValuationCountsRead
    unpriced_reasons: dict[str, int]
    outside_selection: int | None = Field(description='Cohort policy: invocations in the filters but not members.')
    full_scope_priced: bool


class AccountingTokenSumRead(BaseModel):
    sum: int | None = Field(description='Null when no invocation contributes: absence, not zero.')
    invocations: int
    partial: int = Field(description='Contributing invocations whose usage is a partial subtotal.')


class AccountingCacheHitRead(BaseModel):
    cache_read_tokens: int
    input_tokens: int = Field(description='Uncached input + cache reads + known cache writes.')
    invocations: int = Field(description='Complete usage with every input category known.')
    excluded: int
    ratio: float | None


class AccountingThroughputRead(BaseModel):
    output_tokens: int
    wall_ms: int
    invocations: int = Field(description='Complete usage with output and a positive measured wall duration.')
    excluded: int
    output_tokens_per_wall_second: float | None = Field(description='Wall throughput, not generation speed.')


class AccountingAmountRead(BaseModel):
    unit: str
    platform: str | None
    product: str | None
    scheme: str
    basis: str
    counterfactual: bool
    retrospective: bool
    invocations: int
    complete: int
    incomplete: int
    unsupported: int
    denominator: int = Field(description='Expected invocations of the scope or group.')
    amount: DecimalText | None = Field(description='Null unless every valuation of this bucket is complete, no '
                                       'expected invocation is unpriced and the selection is complete.')
    known_subtotal: DecimalText | None = Field(description='Complete amounts plus incomplete known subtotals.')
    reasons: dict[str, int]
    discrepancies: dict[str, int]


class AccountingTotalsRead(BaseModel):
    coverage: AccountingCoverageRead
    tokens: dict[str, AccountingTokenSumRead]
    cache_hit: AccountingCacheHitRead
    wall_throughput: AccountingThroughputRead
    amounts: list[AccountingAmountRead] = Field(description='Only identical unit/platform/product/scheme/basis/'
                                                'counterfactual/retrospective valuations are added.')


class AccountingSummaryRead(AccountingTotalsRead):
    format: Literal['accounting-aggregate-1']
    filters: AccountingFiltersRead
    selection: AccountingSelectionRead


class AccountingGroupRead(AccountingTotalsRead):
    key: str | None
    key_kind: Literal['value', 'unknown', 'reported', 'mixed']
    root: str | None = Field(description='Phase and task groups are keyed within their root (and phase).')
    phase_code: str | None


class AccountingGroupsRead(BaseModel):
    format: Literal['accounting-aggregate-1']
    dimension: AccountingDimension
    order: AccountingOrder
    filters: AccountingFiltersRead
    selection: AccountingSelectionRead
    items: list[AccountingGroupRead]
    offset: int
    next_offset: int | None


class AccountingTaskCountsRead(BaseModel):
    attempted: int
    committed: int = Field(description='Attempted tasks with a verified COMMITTED acceptance.')
    acceptance_unknown: int
    not_committed: int


class AccountingAmountPairRead(BaseModel):
    amount: DecimalText | None
    known_subtotal: DecimalText | None


class AccountingIndicatorRead(BaseModel):
    unit: str
    platform: str | None
    product: str | None
    scheme: str
    basis: str
    counterfactual: bool
    retrospective: bool
    total: AccountingAmountPairRead = Field(description='All attempted task work: revisions, reviews, retries.')
    committed_work: AccountingAmountPairRead = Field(description='Work of committed tasks only.')
    per_committed_task: DecimalText | None = Field(description='Total / committed tasks, half-even to 12 places.')
    per_attempted_task: DecimalText | None
    committed_work_per_committed_task: DecimalText | None


class AccountingTasksRead(BaseModel):
    format: Literal['accounting-aggregate-1']
    filters: AccountingFiltersRead
    selection: AccountingSelectionRead
    tasks: AccountingTaskCountsRead
    coverage: AccountingCoverageRead
    committed_coverage: AccountingCoverageRead
    indicators: list[AccountingIndicatorRead]


class AccountingValuationBriefRead(BaseModel):
    id: str
    origin: Literal['admission', 'backfill', 'repricing']
    status: Literal['complete', 'incomplete', 'unsupported']
    unit: str
    platform: str | None
    product: str | None
    scheme: str
    basis: str
    counterfactual: bool
    retrospective: bool
    amount: DecimalText | None
    known_subtotal: DecimalText | None
    reasons: list[str]
    warnings: list[str]
    discrepancy: str | None = Field(description='Comparison status against the client-reported estimate.')


class AccountingCaptureRefRead(BaseModel):
    id: int
    version: str
    source: str
    recorded_at: str


class AccountingInvocationUsageRead(BaseModel):
    coverage: Literal['complete', 'partial', 'absent'] | None = Field(description='Null when not invoked.')
    partition: str | None
    delegation: str | None
    charges_complete: bool | None
    reasons: list[str]
    tokens: dict[str, int | None]


class AccountingInvocationRead(BaseModel):
    id: str
    source_kind: AccountingSource
    source_id: str
    run_id: str | None
    attempt_id: str | None
    preparation_id: str | None
    preparation_step_id: str | None
    operation_id: str | None
    request_id: str | None
    root: str | None
    project_id: str | None
    phase_code: str | None
    task_id: str | None
    purpose: str
    work: AccountingWork
    role: str
    agent: str | None
    provider: str | None
    requested_model: str | None
    requested_effort: str | None
    effective_model: str | None
    effective_model_kind: AccountingModelKind
    launch: AccountingLaunch
    outcome: str | None
    started_at: str
    finished_at: str | None
    wall_ms: int | None
    capture: AccountingCaptureRefRead | None = Field(description='Latest append-only capture.')
    usage: AccountingInvocationUsageRead
    in_selection: bool
    valuations: list[AccountingValuationBriefRead] = Field(description='Valuations chosen by the selection policy.')
    unpriced_reason: str | None


class AccountingInvocationsRead(BaseModel):
    format: Literal['accounting-aggregate-1']
    filters: AccountingFiltersRead
    selection: AccountingSelectionRead
    items: list[AccountingInvocationRead]
    offset: int
    next_offset: int | None


class AccountingComponentRead(BaseModel):
    key: str
    grain: str
    parent_key: str | None
    inclusion: str | None
    reported_model: str | None
    model_source: str | None
    semantics: str | None
    coverage: str
    input_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    write_5m: int | None
    write_1h: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    reasons: list[str]


class AccountingCaptureDocumentRead(BaseModel):
    digest: str
    document: dict[str, Any] = Field(description='Allowlisted capture: no prompts, argv, environment or paths.')
    evidence: dict[str, Any] | None
    evidence_digest: str | None


class AccountingInvocationDetailRead(AccountingInvocationRead):
    selection: AccountingSelectionRead
    versions: dict[str, Any]
    binding: dict[str, Any] | None
    binding_sha256: str | None
    captures: int
    capture_document: AccountingCaptureDocumentRead | None
    components: list[AccountingComponentRead] = Field(description='Alternative views; never added together.')


class AccountingReferenceRead(BaseModel):
    id: str
    kind: str
    format: str
    source: str
    provider: str | None
    product: str | None
    model: str | None
    observed_at: str | None


class AccountingLineRead(BaseModel):
    number: int
    component_key: str
    category: str
    quantity: int
    rate: dict[str, Any]
    factors: list[Any]
    included_adjustments: list[Any]
    tariff_reference: str
    identity_reference: str | None
    rate_case: str
    exact_amount: DecimalText


class AccountingCohortRefRead(BaseModel):
    id: str
    name: str


class AccountingValuationRead(AccountingValuationBriefRead):
    capture_id: int
    normalization: str
    calculator: str
    profile_digest: str
    reference_set_digest: str
    scenario_digest: str
    evidence_digest: str
    scenario: dict[str, Any]
    exact_sum: DecimalText | None
    rounding_adjustment: DecimalText | None
    selected_components: list[Any]
    discrepancy_detail: dict[str, Any] | None
    supersedes: str | None
    recorded_at: str
    cohorts: list[AccountingCohortRefRead]
    lines: list[AccountingLineRead]
    references: list[AccountingReferenceRead]


# --- H6.2 E2: project registry (D054/D076) -----------------------------------------------

PermissionLayer = Literal['global', 'project', 'contract', 'provider']
PermissionKind = Literal['files', 'tools', 'network', 'product', 'acceptance']
ShortText = Annotated[str, Field(min_length=1, max_length=200)]


class RegistryPolicyInput(BaseModel):
    """Project D052 policy: selections, never executables or environments."""
    model_config = ConfigDict(extra='forbid', strict=True)
    planning_mode: Literal['agent', 'deterministic']
    executor_mode: Literal['catalog', 'open']
    executor_models: list[ShortText] = Field(min_length=1, max_length=20)
    executor_efforts: list[ShortText] = Field(min_length=1, max_length=10)
    max_revision_cycles: int | None = Field(default=None, ge=0, le=20)


class ReviewerSelectionInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    preset_id: str = Field(min_length=1, max_length=64)
    model: ShortText
    effort: ShortText


class ExecutorSelectionInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    preset_id: str = Field(min_length=1, max_length=64)


class AgentSelectionInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    reviewer: ReviewerSelectionInput
    executor: ExecutorSelectionInput


class AgentPresetRead(BaseModel):
    id: str
    provider: Literal['codex', 'claude']
    roles: list[Literal['reviewer', 'executor']]
    models: list[str]
    efforts: list[str]
    allow_open_executor: bool


class RegistryChangeInput(BaseModel):
    """Register (`register`), change (`update`) or logical retirement (`retire`); the composition is named."""
    model_config = ConfigDict(extra='forbid', strict=True)
    action: Literal['register', 'update', 'retire']
    project_id: str = Field(min_length=1, max_length=64)
    expected_version: int = Field(ge=0, le=2**31, description='0 to register; the version read to change or retire.')
    root: str | None = Field(default=None, max_length=4096, description='Registration only; immutable afterwards.')
    composition: str | None = Field(default=None, max_length=64)
    policy: RegistryPolicyInput | None = None
    agent_selection: AgentSelectionInput | None = None
    tag_kind: Literal['lightweight', 'annotated'] = 'lightweight'
    documents: Literal['v2'] | None = 'v2'
    bootstrap_enabled: bool = False
    permission_authority: dict[PermissionLayer, dict[PermissionKind, list[ShortText]]] | None = Field(
        default=None, description='Permission ceiling per layer; null: no explicit ceiling.')
    work_language: Language | None = Field(
        default=None, description='Required to register; immutable afterwards, so update/retire refuse it (409).')


class RegistryApplyCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    change: RegistryChangeInput
    preview_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    trust_root: str | None = Field(default=None, max_length=4096,
                                   description='Separate confirmation of trust: the exact canonical root.')
    reason: str | None = Field(default=None, max_length=2000)


class RegistryCompositionRead(BaseModel):
    name: str
    profile: str
    executables: list[str] = Field(description='Names only; the paths stay in the TOML.')
    environment_keys: list[str] = Field(description='Keys only; the values never leave the TOML.')
    authorize_profile_commands: bool
    extra_commands: list[list[str]]


class RegisteredProjectSummaryRead(BaseModel):
    id: str
    creation_id: str | None = None
    version: int
    status: Literal['ACTIVE', 'RETIRED']
    root: str
    composition: str | None
    profile: str | None
    row_sha256: str
    created_at: str
    updated_at: str
    available: bool
    diagnostic: str | None = Field(description='Why an active row does not compose with the current TOML.')
    work_language: WorkLanguageRead | None = None


class RegistryRead(BaseModel):
    available: bool
    creation_available: bool = False
    format: str | None
    roots: list[str]
    bootstrap_enabled: bool
    compositions: list[RegistryCompositionRead]
    executor_provider: str | None
    reviewer_provider: str | None
    executor_effort_vocabulary: list[str]
    agent_presets: list[AgentPresetRead] = Field(default_factory=list)
    reserved_ids: list[str]
    operator_projects: list[str]
    projects: list[RegisteredProjectSummaryRead]
    trust_statement: str


class RegistryEventRead(BaseModel):
    version: int
    action: Literal['register', 'update', 'retire']
    row: dict[str, Any]
    row_sha256: str
    previous_sha256: str | None
    preview_sha256: str
    actor: dict[str, Any]
    reason: str | None
    recorded_at: str


class RegisteredProjectRead(RegisteredProjectSummaryRead):
    row: dict[str, Any]
    trust: dict[str, Any]
    unfinished_jobs: list[int]
    configuration_blockers: list[str] = Field(default_factory=list)
    history: list[RegistryEventRead]


class RegistryFieldChangeRead(BaseModel):
    field: str
    before: Any
    after: Any


class WorkLanguagePreviewRead(BaseModel):
    """The work language a confirmation will associate with the root; the default is shown, never applied silently."""
    work_language: Language
    source: Literal['registration', 'creation', 'migration']
    default_work_language: Language = Field(description='Global default read for this preview (provenance only).')
    preferences_version: int
    existing: WorkLanguageRead | None = Field(
        description='Association the root already has (same value required); null when the confirmation creates it.')


class RegistryPreviewRead(BaseModel):
    action: Literal['register', 'update', 'retire']
    project_id: str
    expected_version: int
    version: int
    status: Literal['ACTIVE', 'RETIRED']
    row: dict[str, Any]
    row_sha256: str
    changes: list[RegistryFieldChangeRead]
    versions: dict[str, str | None] | None = Field(description='Versions its jobs will freeze; null on retirement.')
    profile: str | None
    trust_required: bool
    trust_statement: str | None
    unfinished_jobs: list[int] = Field(description='Unfinished jobs of the checkout: they block the confirmation.')
    configuration_blockers: list[str] = Field(default_factory=list)
    work_language: WorkLanguagePreviewRead | None = Field(
        default=None, description='Registration only: the chosen value, sealed in the preview hash.')
    preview_sha256: str


class RegistryApplyRead(BaseModel):
    project: RegisteredProjectSummaryRead
    replayed: bool = Field(description='The same confirmation was already applied; there is no other version.')


class ImportPreviewRead(BaseModel):
    preview_sha256: str
    operation: Literal['import_commit']
    proposed_tree: str
    head: str
    fingerprint: str
    tree: str
    index_tree: str
    documents: list[dict[str, Any]]
    mechanical: list[dict[str, Any]]
    diff: str
    phase: dict[str, Any]
    baseline: dict[str, str]
    origin: dict[str, Any]
    source: dict[str, Any]
    moves: list[dict[str, Any]]
    preserved: list[dict[str, Any]]
    foreign: list[dict[str, Any]]
    result_tree: list[dict[str, Any]]
    warnings: list[str]
    author: dict[str, str]
    message: str
    versions: dict[str, Any]
    context: str
    resume_operation_id: str | None = None
    expected_version: int | None = None
    already_imported: bool = False
    flow: Literal['onboarding']
    profile: dict[str, Any] | None = None
    profile_sha256: str | None = None
    profile_proposal: dict[str, Any] | None = None
    profile_proposal_sha256: str | None = None


class OnboardingConfirmCreate(DefinitionAcceptCreate):
    profile_sha256: str = Field(pattern=SHA256)


class ImportOperationRead(BaseModel):
    id: str
    root: str
    conversation_id: str
    run_id: str
    phase_id: str | None
    status: Literal['QUEUED', 'COMPLETED', 'INTERRUPTED']
    preview: ImportPreviewRead
    decision: dict[str, Any]
    result: dict[str, Any] | None
    expected_version: int
    run_status: str
    created_at: str
    finished_at: str | None


class ImportEntryRead(BaseModel):
    refusal: str | None
    operation: ImportOperationRead | None


class CreationRootChangeInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: Literal['select', 'retire']
    expected_version: int = Field(ge=0)
    path: str | None = Field(default=None, max_length=4096)


class CreationRootApplyInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    change: CreationRootChangeInput
    preview_sha256: str = Field(pattern=SHA256)
    confirm_path: str | None = Field(default=None, max_length=4096)
    reason: str | None = Field(default=None, max_length=2000)


class CreationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    project_id: str = Field(min_length=1, max_length=64)
    directory_name: str = Field(min_length=1, max_length=64)
    root_version: int = Field(ge=1)
    composition: str | None = Field(default=None, min_length=1, max_length=64)
    policy: RegistryPolicyInput
    agent_selection: AgentSelectionInput | None = None
    tag_kind: Literal['lightweight', 'annotated'] = 'lightweight'
    documents: Literal['v2'] = 'v2'
    permission_authority: dict[PermissionLayer, dict[PermissionKind, list[ShortText]]] | None = None
    work_language: Language = Field(description='Work language of the new project, immutable once it is registered.')


class CreationConfirmInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    change: CreationInput
    preview_sha256: str = Field(pattern=SHA256)
    trust_root: str = Field(min_length=1, max_length=4096)
    reason: str | None = Field(default=None, max_length=2000)


class CreationRootSnapshotRead(BaseModel):
    version: int
    status: Literal['ABSENT', 'ACTIVE', 'REVOKED']
    path: str | None
    identity: dict[str, int] | None
    row_sha256: str | None = None
    updated_at: str | None = None


class CreationOperationRead(BaseModel):
    id: str
    version: int
    project_id: str
    directory_name: str
    target: str
    reserved: bool
    authority: dict[str, Any]
    intent: dict[str, Any]
    intent_sha256: str
    status: Literal['INTENDED', 'DIRECTORY_CREATED', 'REGISTERED', 'BLOCKED', 'RECOVERY_REQUIRED', 'CANCELLED']
    child_identity: dict[str, int] | None
    result: dict[str, Any] | None
    diagnostic: str | None
    created_at: str
    updated_at: str
    history: list[dict[str, Any]] = Field(default_factory=list)


class CreationRootRead(CreationRootSnapshotRead):
    available: bool
    diagnostic: str | None
    bootstrap_enabled: bool
    permission_statement: str
    history: list[dict[str, Any]]
    operations: list[CreationOperationRead]


class CreationRootPreviewRead(BaseModel):
    action: Literal['select', 'retire']
    expected_version: int
    root: CreationRootSnapshotRead
    permission_statement: str
    preview_sha256: str
    replayed: bool = False


class CreationPreviewRead(BaseModel):
    contract: str
    authority: dict[str, Any]
    row: dict[str, Any]
    target: str
    directory_name: str
    versions: dict[str, str | None]
    profile: str | None
    profile_details: dict[str, Any]
    agents: ProjectAgentsRead
    composition: RegistryCompositionRead | None
    trust_statement: str
    permission_statement: str
    work_language: WorkLanguagePreviewRead
    preview_sha256: str


class CreationResumeInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=1)
    root_version: int = Field(ge=1)


class CreationResumePreviewRead(BaseModel):
    operation_id: str
    expected_version: int
    authority: dict[str, Any]
    intent_sha256: str
    target: str
    preview_sha256: str


class CreationResumeConfirmInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    change: CreationResumeInput
    preview_sha256: str = Field(pattern=SHA256)
    reason: str | None = Field(default=None, max_length=2000)


class CreationCancelInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=1)
    intent_sha256: str = Field(pattern=SHA256)
    reason: str | None = Field(default=None, max_length=2000)


class PreparationChangeInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=1)
    mode: Literal['offline', 'network']
    previous_id: str | None = Field(default=None, min_length=1, max_length=36)
    retry_step: int | None = Field(default=None, ge=0, le=100)


class PreparationConfirmInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    change: PreparationChangeInput
    preview_sha256: str = Field(pattern=SHA256)
    reason: str | None = Field(default=None, max_length=2000)


class ProfilePreparationChangeInput(PreparationChangeInput):
    contract: Literal['project-profile-preparation-1']
    configuration_revision: int = Field(ge=1)
    configuration_sha256: str = Field(pattern=SHA256)
    proposal_id: str = Field(min_length=1, max_length=36)
    proposal_sha256: str = Field(pattern=SHA256)


class ProfilePreparationConfirmInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    change: ProfilePreparationChangeInput
    preview_sha256: str = Field(pattern=SHA256)
    confirmed: Literal[True]
    reason: str = Field(min_length=1, max_length=2000)


class PreparationControlInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=1)
    plan_sha256: str = Field(pattern=SHA256)
    reason: str | None = Field(default=None, max_length=2000)


class PreparationPlanRead(BaseModel):
    model_config = ConfigDict(extra='allow')
    contract: str
    recipe: str | None
    project_id: str
    root: str
    preview_sha256: str
    files: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    mode: Literal['offline', 'network']
    work_language: Language | None = Field(
        default=None, description="v2 recipes: the project's confirmed work language this plan prepares with.")
    recipe_sha256: str | None = Field(
        default=None, pattern=SHA256, description='v2 recipes: fingerprint of the recipe for that work language.')


class PreparationOperationRead(BaseModel):
    id: str
    project_id: str
    version: int
    status: Literal['QUEUED', 'ACTIVE', 'FAILED', 'RECOVERY_REQUIRED', 'CANCELLED', 'COMPLETED']
    plan: dict[str, Any]
    plan_sha256: str
    previous_id: str | None
    receipt: dict[str, Any] | None
    diagnostic: str | None
    cancel_requested: bool
    owner_closed: bool
    created_at: str
    updated_at: str
    steps: list[dict[str, Any]]
    events: list[dict[str, Any]]


class PreparationRead(BaseModel):
    available: bool
    prepared: bool
    diagnostic: str | None
    recipe: str | None
    project_version: int
    operation: PreparationOperationRead | None


class WorkLanguageMigrationInput(BaseModel):
    """Explicit confirmation for a project without a work language (absent → en/es); nothing is inferred."""
    model_config = ConfigDict(extra='forbid', strict=True)
    work_language: Language


class WorkLanguageMigrationPreviewRead(BaseModel):
    project_id: str
    root: str
    work_language: WorkLanguagePreviewRead
    files_preserved: bool = Field(description='Existing files are kept as they are: nothing is translated or renamed.')
    unfinished_jobs: list[int] = Field(description='Unfinished jobs of the checkout: they block the confirmation.')
    configuration_blockers: list[str]
    preview_sha256: str


class WorkLanguageMigrationApplyCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    change: WorkLanguageMigrationInput
    preview_sha256: str = Field(pattern=SHA256)
    reason: str = Field(min_length=1, max_length=2000)


class WorkLanguageMigrationApplyRead(BaseModel):
    project: ManagedProjectRead
    replayed: bool


class ProfileProposalPreviewCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    proposal_id: str = Field(min_length=1, max_length=36)
    expected_version: int = Field(ge=0)
    proposal_sha256: str = Field(pattern=SHA256)


class ProfileProposalConfirmCreate(ProfileProposalPreviewCreate):
    preview_sha256: str = Field(pattern=SHA256)
    confirmed: Literal[True]
    reason: str = Field(min_length=1, max_length=2000)


class ProfileProposalPreviewRead(BaseModel):
    conversation_id: str
    proposal_id: str
    expected_version: int
    proposal_sha256: str
    profile: dict[str, Any]
    blockers: list[str] = Field(description='Adoption blockers, including missing or changed applied documents and '
                               'unresolved nondeferred blocking questions. Informational pending items do not block.')
    ready: bool = Field(description='True only when the exact document base, candidate and frozen context pass '
                        'adoption guards. This does not qualify preparation or activate configuration.')
    configuration_state: Literal['PROFILE_REQUIRED', 'PROFILE_PROPOSED']
    preview_sha256: str


class ProfileProposalAdoptedRead(BaseModel):
    conversation_id: str
    proposal_id: str
    configuration_state: Literal['PROFILE_PROPOSED']
    version: int
    proposal_sha256: str
