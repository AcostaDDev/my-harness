"""Opt-in profile for a static TypeScript website; nothing runs on import."""

from my_harness.core.engine.context import Command, JUnitDeclaration, ProjectProfile


def typescript_web_profile() -> ProjectProfile:
    return ProjectProfile(
        name="typescript-web",
        preparation=(
            Command(("node", "--version"), timeout_seconds=30),
            Command(("npm", "--version"), timeout_seconds=30),
            Command(("npm", "ci", "--offline", "--ignore-scripts", "--no-audit", "--no-fund"),
                    environment=(("npm_config_engine_strict", "true"),), timeout_seconds=120),
        ),
        validations=tuple(Command(("npm", "run", script), timeout_seconds=120)
                          for script in ("check", "test", "build")),
        allowed_command_prefixes=(("npm", "run", "check"), ("npm", "run", "test"),
                                  ("npm", "run", "build")),
        junit_reports=(JUnitDeclaration(Command(('npm', 'run', 'test'), timeout_seconds=120),
                                        '.local/junit.xml', 'Tests Node de tests/*.test.mjs; no cobertura de código'),),
        # D088 point 6 (P008-T003): the executor may maintain product documentation, diagrams,
        # `docs/flows/` and `docs/phase/` if its contract includes them; control documents belong to the harness.
        protected_paths=("docs/STATE.md", "docs/NEXT_STEPS.md", "docs/ROADMAP.md", "docs/DECISIONS.md",
                         "docs/archive/**", "AGENTS.md", "CLAUDE.md", "GEMINI.md",
                         ".harness/**", ".codex/**", ".claude/**", "package.json", "package-lock.json",
                         "tsconfig.json", "scripts/**", "tests/**", ".gitignore"),
        sensitive_paths=(".env", ".env.*", "**/.env", "**/.env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*"),
        sensitive_allowlist=(".env.example",),
        executor_instructions=(
            "Implement the static TypeScript web application within the frozen task paths. "
            "Use the existing npm run check, npm run test and npm run build scripts. "
            "Do not weaken tests, compiler settings, scripts or the dependency lock. "
            "Keep node_modules, .build, dist and the npm cache ignored. "
            "Preparation uses an already populated, explicitly configured npm cache offline; "
            "a cache miss stops the task. Dependency downloads, configuration changes and "
            "network access require separate authorization. Command prefixes do not grant "
            "agent tools or provide a sandbox."
        ),
    )
