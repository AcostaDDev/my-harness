"""H0.2 contract probe: synthetic JSONL, without processes or product integration."""

from dataclasses import dataclass
import json


KNOWN = {
    "codex": {"thread.started", "turn.started", "turn.completed", "turn.failed",
              "item.started", "item.updated", "item.completed", "error"},
    "claude": {"system", "assistant", "user", "stream_event", "result"},
}


@dataclass
class ProbeReport:
    status: str
    events: list[dict]
    raw_records: list[bytes]
    diagnostics: list[dict]
    unknown_events: list[dict]
    tail: bytes
    telemetry: dict


def reject_constant(value):
    raise ValueError(f"Non-JSON constant: {value}")


class StreamProbe:
    """Reads incremental bytes; only a known terminal can certify the end.

    It does not validate the task contract or implement start/cancel/respond_approval.
    finish requires the observed process code, supplied by the fixture.
    """

    def __init__(self, provider):
        if provider not in KNOWN:
            raise ValueError("Unsupported provider")
        self.provider = provider
        self.buffer = b""
        self.events = []
        self.raw_records = []
        self.diagnostics = []
        self.unknown_events = []
        self.terminals = []
        self.failed = False
        self.telemetry = {}
        self.finished = False

    def feed(self, chunk):
        if self.finished:
            raise RuntimeError("Stream already finished")
        self.buffer += chunk
        while b"\n" in self.buffer:
            record, self.buffer = self.buffer.split(b"\n", 1)
            self._record(record + b"\n")

    def _diagnostic(self, code):
        self.diagnostics.append({"record": len(self.raw_records), "code": code})

    def _record(self, raw, *, eof=False):
        self.raw_records.append(raw)
        if not raw.strip():
            return True
        try:
            event = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
        except (UnicodeDecodeError, ValueError):
            self._diagnostic("unfinished_tail" if eof else "invalid_json_or_utf8")
            return False
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            self._diagnostic("invalid_envelope")
            return True
        self.events.append(event)  # Includes the original unknown and null fields.
        kind = event["type"]
        if kind not in KNOWN[self.provider]:
            self.unknown_events.append(event)
            return True
        if self.provider == "codex":
            if kind in {"error", "turn.failed"}:
                self.failed = True
            if kind in {"turn.completed", "turn.failed"}:
                self.terminals.append(event)
        elif kind == "result":
            self.terminals.append(event)
            if not isinstance(event.get("is_error"), bool):
                self._diagnostic("invalid_result")
            elif event["is_error"] or str(event.get("subtype", "")).startswith("error_"):
                self.failed = True
            elif event.get("subtype") != "success":
                self._diagnostic("unknown_result_subtype")
        if self.terminals and self.terminals[-1] is event:
            self.telemetry = {key: event[key] for key in
                              ("usage", "modelUsage", "duration_ms", "total_cost_usd")
                              if key in event}
        return True

    def finish(self, exit_code):
        if self.finished:
            raise RuntimeError("Stream already finished")
        self.finished = True
        tail = self.buffer
        if tail and self._record(tail, eof=True):
            tail = b""
        if len(self.terminals) > 1:
            self._diagnostic("multiple_terminals")
        invalid = any(d["code"] != "unfinished_tail" for d in self.diagnostics)
        if invalid:
            status = "invalid"
        elif self.failed or exit_code != 0:
            status = "failed"
        elif tail or not self.terminals:
            status = "incomplete"
        else:
            status = "complete"
        return ProbeReport(status, self.events, self.raw_records, self.diagnostics,
                           self.unknown_events, tail, self.telemetry)
