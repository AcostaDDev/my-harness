import json
from pathlib import Path
from uuid import uuid4

from alembic import command
from session_client import TestClient
from sqlalchemy import inspect, text
import pytest

from my_harness.api.app import create_app
from my_harness.storage.database import make_engine


LOCAL = {"base_url": "http://127.0.0.1:8013", "headers": {"X-My-Harness": "1"}}  # D033 local guard


def test_migration_wal_and_round_trip(migrated_database):
    url, config = migrated_database
    engine = make_engine(url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA journal_mode")) == "wal"
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0032_operation_journal"
        command.check(config)
        command.downgrade(config, "base")
        assert "simulations" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
        assert "simulations" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_simulation_survives_application_restart(migrated_database, tmp_path):
    url, _ = migrated_database
    with TestClient(create_app(url, tmp_path), **LOCAL) as client:
        assert client.get("/api/health").json() == {"status": "ok", "mode": "simulation"}
        assert client.get("/api/simulations").json() == []
        response = client.post("/api/simulations", json={"title": "  Recorrido sintético  "})
        assert response.status_code == 201
        created = response.json()
        assert created["kind"] == "simulation"
        assert created["status"] == "completed"
        assert created["title"] == "Recorrido sintético"
        assert len(created["events"]) == 3
        assert "tokens" not in created and "cost" not in created and "model" not in created
    with TestClient(create_app(url, tmp_path), **LOCAL) as restarted:
        assert restarted.get(f"/api/simulations/{created['id']}").json() == created
        assert restarted.get("/api/simulations").json() == [created]


@pytest.mark.parametrize("payload", [
    {"title": " "}, {"title": "x" * 121}, {},
    {"title": "Sintético", "model": "real"}, {"title": 17},
])
def test_invalid_requests_do_not_create_rows(migrated_database, tmp_path, payload):
    url, _ = migrated_database
    with TestClient(create_app(url, tmp_path), **LOCAL) as client:
        assert client.post("/api/simulations", json=payload).status_code == 422
        assert client.get("/api/simulations").json() == []
        assert client.get(f"/api/simulations/{uuid4()}").status_code == 404
        assert client.get("/api/simulations/not-a-uuid").status_code == 422


def test_startup_requires_explicit_migration(tmp_path):
    url = f"sqlite:///{tmp_path / 'unmigrated.sqlite3'}"
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        with TestClient(create_app(url, tmp_path), **LOCAL):
            pass
    engine = make_engine(url)
    try:
        assert "simulations" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_exported_openapi_matches_runtime_without_database_side_effects(tmp_path):
    exported = Path(__file__).resolve().parents[2] / "frontend/openapi.json"
    db = tmp_path / "not-created.sqlite3"
    app = create_app(f"sqlite:///{db}", tmp_path)
    assert json.loads(exported.read_text()) == app.openapi()
    assert not db.exists()


def test_serves_local_ui_without_masking_api_routes(migrated_database, tmp_path):
    url, _ = migrated_database
    (tmp_path / "index.html").write_text("<!doctype html><title>UI sintética</title>")
    with TestClient(create_app(url, tmp_path), **LOCAL) as client:
        assert "UI sintética" in client.get("/").text
        assert client.get("/api/simulations").json() == []
        assert client.get("/api/nonexistent").status_code == 404
