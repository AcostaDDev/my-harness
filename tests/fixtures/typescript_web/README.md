# TypeScript web fixture — H4.3

Synthetic static website: a task field computes an estimate of thirty minutes
per task. No backend, Docker, credentials or providers.

Node 24.15.0, npm 11.12.1 and TypeScript 5.9.3 (the only dependency, pinned in the lock).
`check` verifies types without emitting; `test` compiles and runs three tests with Node;
`build` compiles and copies modules and HTML to `dist/`. There is no bundler or framework.
The interaction test uses a minimal test DOM; it does not certify a browser.
Since H5.1, `test` keeps TAP on stdout and keeps the original XML of the Node JUnit
reporter in `.local/junit.xml`, declared by the profile; it does not measure code coverage.

The Python tests copy this folder to a temporary checkout; a 45-minute
regression is introduced only in that copy to verify execution, review and
commit. The versioned fixture passes its tests unmodified. `node_modules/`,
`.build/`, `dist/` and `.local/` are ignored and do not enter the Git evidence.

The visible text of the application (`lang="es"`, labels and messages) is fixture data checked by its tests,
not documentation; it stays in Spanish.

Full journey, from the repository root:

```sh
UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline pytest -q tests/product/test_typescript_profile.py
```

Requires the `.local/npm-cache` cache populated by the documented frontend
installation (it shares the TypeScript 5.9.3 pin). An empty cache causes an
`ENOTCACHED` stop; the tests do not download packages. The profile is described in
[ARCHITECTURE](../../../docs/ARCHITECTURE.md).
