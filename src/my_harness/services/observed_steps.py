"""P002-T019 (D305, D310): background projector of observed steps, beside the supervisor lanes.

The repository wakes it after each settlement commit (the ordinary path); its first pass and each idle pass project
every pending marker, which is also the recovery path after a restart or a failed projection. It never runs on
restored `query_only` archives (the runtime composes no supervisor there) and holds no lease or checkout lock.
"""
import logging
from threading import Event, Thread

from my_harness.storage.observed_steps import ObservedStepProjector

logger = logging.getLogger(__name__)


class ObservedStepWorker:
    def __init__(self, engine, *, idle_seconds: float = 10.0):
        self.projector = ObservedStepProjector(engine)
        self.idle_seconds = idle_seconds
        self.wake, self.stopping = Event(), Event()
        self.thread: Thread | None = None

    def start(self) -> None:
        self.thread = Thread(target=self._loop, name='observed-steps', daemon=True)
        self.thread.start()

    def notify(self, _invocation_ids=()) -> None:
        self.wake.set()

    def _loop(self) -> None:
        while not self.stopping.is_set():
            self.wake.clear()
            try:
                # One pass over every owed marker in order, past persistent failures, stopping between invocations.
                self.projector.run_pending(limit=20, stop=self.stopping.is_set)
            except Exception:  # markers stay pending; retention keeps their streams
                logger.exception('Observed-step projection pass failed.')
            self.wake.wait(self.idle_seconds)

    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def stop(self, timeout: float) -> None:
        self.stopping.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join(timeout)
