from datetime import datetime

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from my_harness.core.simulation import Simulation
from my_harness.storage.models import SimulationRow


def to_domain(row: SimulationRow) -> Simulation:
    return Simulation(row.id, row.title, datetime.fromisoformat(row.created_at), tuple(row.events))


class SQLiteSimulationRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def save(self, simulation: Simulation) -> None:
        with Session(self.engine) as session, session.begin():
            session.add(SimulationRow(
                id=simulation.id,
                title=simulation.title,
                created_at=simulation.created_at.isoformat(),
                events=list(simulation.events),
            ))

    def list(self) -> list[Simulation]:
        with Session(self.engine) as session:
            rows = session.scalars(select(SimulationRow).order_by(
                SimulationRow.created_at.desc(), SimulationRow.id.desc(),
            ))
            return [to_domain(row) for row in rows]

    def get(self, simulation_id: str) -> Simulation | None:
        with Session(self.engine) as session:
            row = session.get(SimulationRow, simulation_id)
            return to_domain(row) if row else None
