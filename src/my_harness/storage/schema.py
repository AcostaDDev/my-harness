import hashlib

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from my_harness.i18n import tr


SCHEMA_REVISION = "0030_structured_knowledge"
# P002-T004 (D284): the knowledge protection triggers of 0030, by name and whitespace-normalized SQL. A database,
# backup or restored copy whose triggers are missing or altered is refused.
SCHEMA_TRIGGERS_SHA256 = "8e9bf4a4414b0326f429b30977ac0ba28250b05548e7ca725bd154909834d123"


def trigger_digest(rows) -> str:
    """`rows` are (name, sql) pairs from sqlite_master; the order of rows and whitespace inside SQL are irrelevant."""
    lines = (f'{name}\t{" ".join(sql.split())}' for name, sql in sorted(tuple(row) for row in rows))
    return hashlib.sha256('\n'.join(lines).encode('utf-8')).hexdigest()


def triggers_intact(rows) -> bool:
    return trigger_digest(rows) == SCHEMA_TRIGGERS_SHA256


def require_schema(engine: Engine) -> None:
    try:
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != SCHEMA_REVISION:
                raise RuntimeError(tr('database.schema'))
            for table in ("simulations", "legacy_sources", "legacy_runs", "legacy_artifacts", "legacy_events",
                          "managed_runs", "managed_jobs", "managed_attempts", "managed_events", "checkout_locks", "managed_processes",
                          "managed_commits", "managed_activations", "prompt_heads", "prompt_versions", "prompt_activations", "permission_requests",
                          "managed_phases", "phase_questions", "phase_operations", "phase_authorizations", "phase_events",
                          "phase_definitions", "chat_conversations", "chat_turns", "chat_proposals", "project_bootstraps",
                          "attempt_metrics", "attempt_model_metrics", "planning_conversations", "planning_turns",
                          "planning_proposals", "registered_projects", "registered_project_events", "project_imports",
                          "project_creation_root", "project_creation_root_events", "project_creation_operations",
                          "project_creation_operation_events", "project_preparation_operations",
                          "project_preparation_steps", "project_preparation_events", "run_projections",
                          "run_projection_stops", "run_projection_cycles", "run_projection_diff_chunks",
                          "run_projection_reports", "run_projection_cases", "product_preferences",
                          "product_preference_events", "project_work_languages", "configuration_scopes",
                          "configuration_revisions", "configuration_operations", "usage_invocations", "usage_captures",
                          "usage_components", "metrics_references", "usage_valuations", "usage_valuation_lines",
                          "valuation_cohorts", "valuation_cohort_members", "graph_threads", "graph_checkpoints",
                          "graph_checkpoint_writes", "knowledge_projects", "knowledge_items",
                          "knowledge_item_versions", "knowledge_revisions", "knowledge_revision_members",
                          "knowledge_revision_links", "knowledge_identity_map"):
                connection.execute(text(f"SELECT * FROM {table} LIMIT 0"))
            rows = connection.execute(text("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'")).all()
            if not triggers_intact(rows):
                raise RuntimeError(tr('database.triggers'))
    except SQLAlchemyError as error:
        raise RuntimeError(tr('database.not_prepared')) from error
