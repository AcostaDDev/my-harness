"""Offline H0.2 checks; synthetic samples and the standard library."""

import json
from pathlib import Path
import unittest

from stream_probe import StreamProbe


FIXTURES = Path(__file__).parent / "fixtures/streams"


class StreamContractTests(unittest.TestCase):
    def parse(self, provider, content, exit_code=0, chunk_size=1):
        parser = StreamProbe(provider)
        for start in range(0, len(content), chunk_size):
            parser.feed(content[start:start + chunk_size])
        return parser.finish(exit_code)

    def test_synthetic_cases_and_byte_preservation(self):
        manifest = json.loads((FIXTURES / "manifest.json").read_text())
        self.assertTrue(manifest["synthetic"])
        self.assertEqual({case["path"] for case in manifest["cases"]},
                         {path.name for path in FIXTURES.glob("*.jsonl")})
        for case in manifest["cases"]:
            content = (FIXTURES / case["path"]).read_bytes()
            for size in (1, 7, len(content)):
                with self.subTest(path=case["path"], size=size):
                    report = self.parse(case["provider"], content, case["exit_code"], size)
                    self.assertEqual(report.status, case["expected_status"])
                    self.assertEqual(len(report.events), case["expected_events"])
                    self.assertEqual(b"".join(report.raw_records), content)

    def test_unknown_fields_events_and_missing_telemetry(self):
        for provider in ("codex", "claude"):
            report = self.parse(provider, (FIXTURES / f"{provider}-success.jsonl").read_bytes())
            self.assertEqual(report.status, "complete")
            self.assertEqual(report.events[0]["future_field"], {"nested": [None, "ñ"]})
            self.assertEqual(report.unknown_events[0]["type"], "future.event")
            self.assertEqual(report.telemetry, {})
        report = self.parse("codex", b'{"type":"future.completed"}\n')
        self.assertEqual(report.status, "incomplete")

    def test_absent_null_and_observed_telemetry_are_distinct(self):
        for usage, expected in ((None, None), ({"input_tokens": 0}, {"input_tokens": 0})):
            content = json.dumps({"type": "turn.completed", "usage": usage}).encode()
            report = self.parse("codex", content)
            self.assertEqual(report.telemetry, {"usage": expected})
            self.assertNotIn("duration_ms", report.telemetry)
            self.assertNotIn("model", report.events[0])

    def test_eof_with_valid_record_and_cut_utf8(self):
        report = self.parse("codex", b'{"type":"turn.completed"}')
        self.assertEqual(report.status, "complete")
        cut = '{"type":"item.updated","text":"ñ'.encode()[:-1]
        report = self.parse("codex", cut)
        self.assertEqual(report.status, "incomplete")
        self.assertEqual(report.tail, cut)
        self.assertEqual(report.diagnostics[0]["code"], "unfinished_tail")

    def test_invalid_record_does_not_discard_later_evidence(self):
        for bad in (b'{broken}\n', b'[]\n', b'{"type":null}\n', b'\xff\n',
                    b'{"type":"future.event","x":NaN}\n'):
            with self.subTest(bad=bad):
                report = self.parse("codex", bad + b'{"type":"turn.completed"}\n')
                self.assertEqual(report.status, "invalid")
                self.assertEqual(report.events[-1]["type"], "turn.completed")
                self.assertTrue(report.diagnostics)

    def test_success_terminal_does_not_hide_error_exit_or_truncation(self):
        terminal = b'{"type":"turn.completed"}\n'
        self.assertEqual(self.parse("codex", terminal, 1).status, "failed")
        self.assertEqual(self.parse("codex", terminal + b'{"type":').status, "incomplete")
        report = self.parse("codex", b'{"type":"error","message":"synthetic"}\n' + terminal)
        self.assertEqual(report.status, "failed")
        self.assertEqual(self.parse("codex", terminal * 2).status, "invalid")

    def test_claude_terminal_requires_known_success_and_boolean(self):
        for fields in ({"subtype": "success"}, {"subtype": "success", "is_error": "false"},
                       {"subtype": "future", "is_error": False}):
            content = json.dumps({"type": "result", **fields}).encode()
            self.assertEqual(self.parse("claude", content).status, "invalid")
        error = b'{"type":"result","subtype":"error_max_turns","is_error":true}\n'
        self.assertEqual(self.parse("claude", error).status, "failed")

    def test_empty_stream_and_partial_activity_never_certify_success(self):
        for provider, kind in (("codex", "item.completed"), ("claude", "assistant")):
            self.assertEqual(self.parse(provider, b'').status, "incomplete")
            content = json.dumps({"type": kind}).encode() + b'\n'
            self.assertEqual(self.parse(provider, content).status, "incomplete")
            self.assertEqual(self.parse(provider, content, 1).status, "failed")


if __name__ == "__main__":
    unittest.main()
