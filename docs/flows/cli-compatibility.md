# Flow — automatic CLI discovery and compatibility

Agent CLIs are discovered automatically and admitted by minimum version and capabilities
([D173](../DECISIONS.md#d173--automatic-cli-discovery-minimums-and-capability-contract),
[D174](../DECISIONS.md#d174--automatic-clients-and-conditional-compatibility)). No version pin, candidate acceptance
or operator evidence file is required in `local-config-7`/`8`.

```mermaid
flowchart TD
    C["Parse local-config-7/8: explicit environment, provider, optional executable"] --> D["Data-only project composition: versions not yet observed"]
    D --> S["Service startup or effective project composition: resolve selected roles"]
    S --> P["Resolve command on explicit absolute PATH or optional path"]
    P --> V["Bounded version/help probes, closed stdin and temporary cwd"]
    V --> M{"Stable version at or above minimum and required interface present?"}
    M -- no --> X["Install/update/capability diagnostic; no model invocation or fallback"]
    M -- yes --> F["Freeze observed version, launch identity and packaged policy in job"]
    F --> B{"Current composition and launch identity match frozen job?"}
    B -- no --> Q["RECOVERY_REQUIRED; preserve original job and evidence"]
    B -- yes --> A["Fresh version/help observation for this attempt"]
    A --> G{"Capabilities and actual argv preserve required guards?"}
    G -- no --> R["Record refused intent without target launch; job RECOVERY_REQUIRED until confirm-stopped"]
    G -- yes --> I["Durable process intent and process identity; target waits at gate"]
    I --> H{"Launch identity still matches immediately before GO?"}
    H -- no --> K["Stop own gated group; record dead or uncertain state; no target GO; job RECOVERY_REQUIRED"]
    H -- yes --> E["GO: fresh client session under existing controls"]
    E --> T{"One known terminal, valid payload and dead process group?"}
    T -- no --> O["Preserve original stream/failure; existing stop or recovery rules"]
    T -- yes --> N["Continue engine validation and review; every next attempt revalidates"]
```

A refusal at binding or at an attempt raises a journal error: the supervisor quarantines the job without a result,
and confirming the writer stopped marks any unfinished attempt `INTERRUPTED` without retry
([task run](task-run.md#run-states)). Admission of new work already rejects unresolved or below-minimum clients with
`CompatibilityError`, before any run exists.

Minimums are Codex 0.163.0 and Claude Code 2.1.304 for both roles. Historical configurations and evidence remain
readable; a below-minimum client cannot start new work. Only effective provider roles are detected during normal
operation; `check-config --preflight` explicitly diagnoses the defaults and every preset role. No auth, status or
login command, test prompt, network lookup, installation or global configuration change is part of discovery.

Each mutation observes the client again and reuses that project resolution only inside the same request. Each
attempt also observes version and help again. Content-hash caching restats inode, size, mtime and ctime; it is not a
cached compatibility verdict. A fresh job can detect an updated client automatically; a queued job never adopts it.
Explicit capability lists wrapped across help lines stay scoped to their own option; a missing required value
still blocks. Source and profile hashes bind the packaged policy; symlink, script and interpreter hashes bind
explicit local launch files. Hashing does not certify transitive runtime dependencies or prevent adversarial concurrent
replacement. Public reports expose hashes and structured diagnostics, not raw help, environment values or executable
paths.

Later releases matching the known interface are admitted with **conditional compatibility**. The packaged policy
keeps explicit sandbox, trust, memory and configuration controls; it does not claim observation of undocumented
startup persistence or of effective permissions in every new release. Missing or changed local controls block. No
per-release approval or audit is transferred to the user. Provider-internal retries remain unknown; the harness adds
no fallback or retry. Read-only project and history views do not trigger discovery.

## Source

- `adapters/cli_compatibility.py` (minimums, policy, discovery and identity), `adapters/cli_agents.py` (adapter
  `cli-14`, argv and preflight), `adapters/cli_diagnostics.py`, `adapters/process_gate.py`.
- `services/local_config.py` (`local-config-7`/`8`), `services/managed_runtime.py`, `cli.py` (`check-config`,
  `diagnose-cli`).
