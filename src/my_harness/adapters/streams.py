"""Incremental JSONL envelope parser. Raw bytes live in separate artifacts."""
import json
import hashlib

from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.metrics import TERMINAL_FIELDS, TERMINAL_FIELDS_2, StreamMetrics
from my_harness.i18n import tr


def strict_json(value):
    def reject(value):
        raise ValueError(f"Nonfinite JSON: {value}")
    return json.loads(value, parse_constant=reject)


class AgentStream:
    def __init__(self, provider, emit):
        self.provider, self.emit = provider, emit
        self.tail = b""
        self.invalid = False
        self.failed = False
        self.terminals = []
        self.payload = None
        self.observed = {}
        self.records = 0
        self.offset = 0
        # H6.4: counters derived from the same read (terminal-2 normalization).
        self.metrics = StreamMetrics(provider)

    def feed(self, chunk):
        self.tail += chunk
        # Bounded JSONL record; bytes already preserved even if envelope too large.
        if len(self.tail) > 4 * 1024 * 1024:
            raise ValueError(tr('agents.jsonl_record_exceeds_4'))
        while b"\n" in self.tail:
            record, self.tail = self.tail.split(b"\n", 1)
            self.record(record, newline=True)

    def record(self, raw, *, eof=False, newline=False):
        offset = self.offset
        original_bytes = raw + (b"\n" if newline else b"")
        self.offset += len(original_bytes)
        if not raw.strip():
            return
        self.records += 1
        try:
            event = strict_json(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            if not eof:
                self.invalid = True
            self.emit("stream_diagnostic", {"record": self.records, "code": "partial_tail" if eof else "invalid"})
            return
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            self.invalid = True
            self.emit("stream_diagnostic", {"record": self.records, "code": "invalid_envelope"})
            return
        kind = event["type"]
        if len(original_bytes) <= 16 * 1024:
            self.emit("agent_event", {"record": self.records, "original": event})
        else:
            self.emit("agent_event", {"record": self.records, "type": kind, "original_reference": {
                "stream": "stdout", "offset": offset, "size": len(original_bytes),
                "sha256": hashlib.sha256(original_bytes).hexdigest()}})
        if isinstance(event.get("message"), dict) and "model" in event["message"]:
            models = self.observed.setdefault("message_models", [])
            if event["message"]["model"] not in models:
                models.append(event["message"]["model"])
        # Only fields actually reported; no requested selection copied here.
        for key in ("model", "effort", "session_id", "thread_id"):
            if key in event:
                self.observed[key] = event[key]
        if self.provider == "codex":
            if kind in {"error", "turn.failed"}:
                self.failed = True
            if kind == "item.completed" and isinstance(event.get("item"), dict) and event["item"].get("type") == "agent_message":
                self.payload = event["item"].get("text")
            if kind in {"turn.completed", "turn.failed"}:
                self.terminals.append(event)
        elif kind == "result":
            self.terminals.append(event)
            if type(event.get("is_error")) is not bool or event.get("subtype") not in {
                    "success", "error_during_execution", "error_max_turns", "error_max_budget_usd",
                    "error_max_structured_output_retries"}:
                self.invalid = True
            if event.get("is_error") or event.get("subtype") != "success":
                self.failed = True
            payload = event.get("structured_output", event.get("result"))
            self.payload = freeze(payload) if isinstance(payload, dict) else payload
        terminal = bool(self.terminals) and self.terminals[-1] is event
        if terminal:
            for key in TERMINAL_FIELDS + TERMINAL_FIELDS_2:
                if key in event:
                    self.observed[key] = event[key]
        self.metrics.event(event, terminal=terminal)

    def finish(self, exit_code):
        partial = False
        if self.tail:
            before = self.records
            raw = self.tail
            self.tail = b""
            try:
                strict_json(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                partial = True
            self.record(raw, eof=True)
            assert self.records >= before
        if self.invalid or len(self.terminals) > 1:
            status = "invalid"
        elif self.failed or exit_code != 0:
            status = "failed"
        elif partial or len(self.terminals) != 1:
            status = "partial"
        else:
            status = "complete"
        payload = None
        if status == "complete":
            try:
                data = strict_json(self.payload or "")
                if not isinstance(data, dict):
                    raise ValueError(tr('agents.structured_agent_result_object'))
                payload = freeze(data)
            except (ValueError, TypeError):
                status = "invalid"
        return status, payload
