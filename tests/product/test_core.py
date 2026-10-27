import ast
from pathlib import Path
import subprocess
import sys

import pytest

from my_harness.adapters.fake import FakeSimulationAdapter
from my_harness.core.simulation import SimulationService


class MemoryRepository:
    def __init__(self):
        self.saved = []

    def save(self, simulation):
        self.saved.append(simulation)


def test_core_imports_with_standard_library_only():
    source = Path(__file__).resolve().parents[2] / "src"
    result = subprocess.run([
        sys.executable, "-S", "-c",
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from my_harness.core.simulation import SimulationService; "
        "from my_harness.core.engine.workflow import OfflineEngine",
        str(source),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    for path in (source / "my_harness/core").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            # P011-T021 (D171): the message catalogs are the only outer leaf allowed; they use the stdlib only.
            assert all(module.split(".")[0] in sys.stdlib_module_names or module == "my_harness.i18n"
                       or module.startswith("my_harness.core") for module in modules)


def test_fake_result_is_local_and_does_not_launch_processes(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("The simulation must not launch processes.")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    repository = MemoryRepository()
    service = SimulationService(repository, FakeSimulationAdapter())
    result = service.create("  Datos sintéticos  ")
    assert result.title == "Datos sintéticos"
    assert result.created_at.utcoffset().total_seconds() == 0
    assert len(result.events) == 3
    assert repository.saved == [result]


def test_adapter_error_is_not_saved_or_retried():
    class FailingAdapter:
        calls = 0

        def execute(self):
            self.calls += 1
            raise RuntimeError("Synthetic failure")

    repository = MemoryRepository()
    adapter = FailingAdapter()
    service = SimulationService(repository, adapter)
    with pytest.raises(RuntimeError, match="Synthetic failure"):
        service.create("Datos sintéticos")
    assert adapter.calls == 1
    assert repository.saved == []


def test_core_rejects_blank_titles_before_execution():
    repository = MemoryRepository()
    with pytest.raises(ValueError):
        SimulationService(repository, FakeSimulationAdapter()).create("  ")
    assert repository.saved == []
