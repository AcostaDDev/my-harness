from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from my_harness.i18n import tr


SCHEMA_REVISION = "0028_usage_accounting"


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
                          "valuation_cohorts", "valuation_cohort_members"):
                connection.execute(text(f"SELECT * FROM {table} LIMIT 0"))
    except SQLAlchemyError as error:
        raise RuntimeError(tr('database.not_prepared')) from error
