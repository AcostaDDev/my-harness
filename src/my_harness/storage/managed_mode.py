"""Read-only authority for activations persisted by older my_harness releases."""
from dataclasses import dataclass
import json

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from my_harness.core.managed_mode import (LIVE_STATUSES, ActivationView, CheckoutFacts, MigrationError, digest, mode_refusal)
from my_harness.storage.models import ManagedActivationRow as Activation
from my_harness.i18n import tr

class ModeConflict(MigrationError):
    pass


@dataclass(frozen=True)
class ActivationRecord:
    id: str
    root: str
    repository_key: str | None
    status: str
    preview_sha256: str
    marker: bytes
    marker_sha256: str
    snapshot_root: str
    manifest_json: str | None
    manifest_sha256: str | None
    owner_token: str | None
    version: int
    diagnostic: str | None
    export_path: str | None
    export_sha256: str | None

    def view(self) -> ActivationView:
        return ActivationView(self.id, self.root, self.repository_key, self.status, self.marker_sha256,
                              json.loads(self.manifest_json) if self.manifest_json else None, self.version)


def _record(row: Activation) -> ActivationRecord:
    return ActivationRecord(row.id, row.root, row.repository_key, row.status, row.preview_sha256,
                            row.marker.encode("utf-8"), row.marker_sha256, row.snapshot_root, row.manifest_json,
                            row.manifest_sha256, row.owner_token, row.version, row.diagnostic,
                            row.export_path, row.export_sha256)


def _live(session, root: str, repository_key: str | None):
    clause = Activation.root == root
    if repository_key is not None:
        clause = or_(clause, Activation.repository_key == repository_key)
    rows = session.scalars(select(Activation).where(clause, Activation.status.in_(LIVE_STATUSES))).all()
    if len(rows) > 1:
        # Root of one activation and repository of another: ambiguity, one is never chosen.
        raise ModeConflict(tr('mode.ambiguous'))
    return rows[0] if rows else None


@dataclass(frozen=True)
class Assessment:
    facts: CheckoutFacts | None
    activation: ActivationRecord | None
    refusal: str | None


class ModeGuard:
    """Legacy/managed exclusion: disk read outside the transaction, verification inside."""

    def __init__(self, engine, probe=None, drift=None):
        from my_harness.adapters import managed_mode as filesystem
        self.engine = engine
        self.probe = probe or filesystem.probe
        self.drift = drift or filesystem.legacy_drift

    def assess(self, root) -> Assessment:
        try:
            facts = self.probe(root)
            with Session(self.engine) as session:
                row = _live(session, facts.root, facts.repository_key)
                activation = _record(row) if row else None
            source, drift = None, None
            if activation is not None and activation.status == "ACTIVE":
                source = facts if activation.root == facts.root else self.probe(activation.root)
                manifest = json.loads(activation.manifest_json)
                if digest(activation.marker) != activation.marker_sha256 or digest(activation.manifest_json) != activation.manifest_sha256:
                    raise ValueError('Existing activation marker or manifest integrity mismatch')
                if (manifest['activation_id'] != activation.id or manifest['origin_root'] != activation.root
                        or manifest['snapshot_root'] != activation.snapshot_root
                        or manifest.get('repository_key') != activation.repository_key):
                    raise ValueError('Existing activation manifest belongs to another authority')
                from pathlib import Path
                from my_harness.adapters.safe_files import read_raw
                for artifact in manifest['artifacts']:
                    if artifact['copied']:
                        path = artifact['path']
                        if Path(path).is_absolute() or '..' in Path(path).parts or '\\' in path:
                            raise ValueError('Unsafe existing activation snapshot path')
                        raw = read_raw(Path(activation.snapshot_root), path)
                        if len(raw) != artifact['size_bytes'] or digest(raw) != artifact['sha256']:
                            raise ValueError('Existing activation snapshot integrity mismatch')
                drift = self.drift(activation.root, manifest)
            refusal = mode_refusal(facts, activation.view() if activation else None, source, drift)
            return Assessment(facts, activation, refusal)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return Assessment(None, None, tr('mode.unchecked', root=root, error=exc))

    @staticmethod
    def enforce(session, assessment: Assessment) -> str | None:
        """Inside the writing transaction: the mode has not changed since the evaluation."""
        if assessment.refusal is not None:
            raise ModeConflict(assessment.refusal)
        row = _live(session, assessment.facts.root, assessment.facts.repository_key)
        expected = assessment.activation
        if (row is None) != (expected is None) or (row is not None and (
                row.id != expected.id or row.status != expected.status or row.version != expected.version)):
            raise ModeConflict(tr('mode.changed_check'))
        return row.id if row else None


def import_marker(guard, root):
    """D099: only the marker of an own ACTIVE activation without drift can be excluded from Git."""
    assessment = guard.assess(root)
    live = assessment.activation
    if (assessment.refusal is None and live is not None and live.status == 'ACTIVE'
            and live.root == str(root)):
        return live.marker_sha256
    return None


def bind_git_mode(writer, guard):
    """Injects the mode authority without coupling the Git adapter to SQLite."""
    from my_harness.adapters.git import GitWorkspace
    if isinstance(writer, GitWorkspace):
        writer.marker_reader = lambda root: import_marker(guard, root)
    return writer
