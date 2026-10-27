# Contributing to My Harness

My Harness is preparing its first public release. Support and compatibility
claims belong to the documentation shipped with that release.

Use this repository's GitHub issues for bugs, feature requests and questions.
For a bug, include the package version, operating system, Python/Node versions,
CLI versions if relevant, expected behavior and a minimal synthetic reproduction.
Remove credentials, personal paths, project code and operational data from reports.
Follow [SECURITY.md](SECURITY.md) for suspected vulnerabilities.

Before making a substantial change, describe the problem in an issue. Branch from
`develop` with a `<kind>/<topic>` name (`feat`, `fix`, `docs`, `chore` or `test`)
and open the pull request against `develop`: `main` is protected and only receives
release pull requests from `develop`, merged as merge commits
([D235](docs/DECISIONS.md#d235--release-branch-integration-branch-and-topic-branches)).
Keep pull requests focused, explain the resulting behavior and report the checks
performed and any omissions. Read the repository's agent instructions and current project
documentation before editing. Keep model/schema documentation and flow diagrams
consistent with changes. Preserve frozen histories, snapshots and fixtures.

The development setup and the checks are in the README's
[Development](README.md#development) section. Record durable decisions in
`docs/DECISIONS.md` and keep `docs/STATE.md`, `docs/ONE_OFF_TASKS.md` and
`docs/NEXT_STEPS.md` current with the change. Read the normally empty one-off queue
before phase work: bounded fixes/improvements there take precedence. Once a task
meets its acceptance, preserve evidence in `docs/phase/OTNNN-<topic>.md` and remove
its queue section. Do not turn the queue into a completed-task catalog or a second
roadmap; resume the existing phase plan when it is empty.

Use synthetic projects and fake agents for tests. Real providers, paid calls,
network access and operations on someone else's projects require their explicit
authorization. Include only content you have the right to contribute, preserve
third-party notices, and contribute under the project's [MIT license](LICENSE).

Maintainers review contributions as time permits. There is no guaranteed response
time, support contract or acceptance of a proposed change.
