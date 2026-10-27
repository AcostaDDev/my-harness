"""H0.3 walkthrough; it is neither the attempt engine nor a task acceptance."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from my_harness.i18n import tr


@dataclass(frozen=True)
class Simulation:
    id: str
    title: str
    created_at: datetime
    events: tuple[str, ...]


class SimulationAdapter(Protocol):
    def execute(self) -> tuple[str, ...]: ...


class SimulationRepository(Protocol):
    def save(self, simulation: Simulation) -> None: ...
    def list(self) -> list[Simulation]: ...
    def get(self, simulation_id: str) -> Simulation | None: ...


class SimulationService:
    def __init__(self, repository: SimulationRepository, adapter: SimulationAdapter):
        self.repository = repository
        self.adapter = adapter

    def create(self, title: str) -> Simulation:
        title = title.strip()
        if not 1 <= len(title) <= 120:
            raise ValueError(tr('simulation.title'))
        # Run outside a transaction; only store a complete result.
        events = self.adapter.execute()
        simulation = Simulation(str(uuid4()), title, datetime.now(timezone.utc), events)
        self.repository.save(simulation)
        return simulation

    def list(self) -> list[Simulation]:
        return self.repository.list()

    def get(self, simulation_id: str) -> Simulation | None:
        return self.repository.get(simulation_id)
