# Synthetic CLI capability fixtures

Independently authored flag lists, not copied CLI output. `test_cli_baseline.py` uses them for positive and
per-flag negative preflight checks. They prove harness behavior, not vendor semantics, authentication or inference.
The tests read no real CLI help output.
