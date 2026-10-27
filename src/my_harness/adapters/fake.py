"""Deterministic adapter: uses no network, processes, CLI or checkouts."""
from my_harness.i18n import tr


class FakeSimulationAdapter:
    def execute(self) -> tuple[str, ...]:
        return tr('simulation.prepared'), tr('simulation.result'), tr('simulation.finished')
