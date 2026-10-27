"""Facts read from a Git tree; no filesystem or provider access."""
from dataclasses import dataclass

class ImportInventoryError(ValueError):
    """The local Git tree cannot be inspected safely."""


@dataclass(frozen=True)
class TreeEntry:
    """HEAD tree entry within the document scope. `data` is None if it was not read."""

    path: str
    mode: str
    size: int | None
    data: bytes | None = None
    diagnostic: str | None = None
