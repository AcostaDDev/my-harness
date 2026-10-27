# Synthetic streams — H0.2

Eight samples made up from the documented envelopes; none comes from a real
call. The [manifest](manifest.json) gives the provider, simulated exit code,
expected status and number of complete events. They are independent of the
H0.1 legacy fixtures and do not test what the user's accounts emit today.

Per provider: success with unknown fields and event, truncated stream,
synthetic authentication error and output without a terminal. The success
samples deliberately omit telemetry. The truncated ones end mid-JSON, without
a newline.

The [probe](../../stream_probe.py) receives incremental bytes and keeps the
original records, the partial tail and unknown fields. `complete` only
certifies a known end of stream with exit code zero: it does not mean
acceptance, commit or validation of the response contract. Codex requires
`turn.completed`; Claude, `result` with `subtype: success` and
`is_error: false`. An agent message or a future event called «completed» does
not replace those terminals.

A malformed finished record invalidates the output without erasing later
events. An undecodable tail at EOF is kept as incomplete; without a newline a
cut cannot be told apart from malformed JSON with certainty. EOF with valid
JSON is processed. A duplicate terminal is invalid. An error or a non-zero exit
code prevents success; the format diagnostic takes priority when both fail.
The reader opens no processes or network and does not retry or choose models.

The checks also cover split/cut UTF-8, non-object JSON, the NaN constant, an
end without newline, a terminal followed by an error/cut, an unknown Claude
terminal, observed absence/null/zero and chunks of 1, 7 or all bytes.

Limits: a finite in-memory probe under `tests/`, not a production adapter, a
complete JSON Schema validator, an App Server/SDK parser or a bounded log
reader. Task result validation, tool denials and stdout/stderr isolation will
be resolved when the adapters are implemented; these data grant no
permissions. Run from the root with the unittest command of the README.
