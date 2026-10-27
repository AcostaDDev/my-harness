// OT004: pure helpers for the guided profile, command and agent forms. They mirror the server's strict checks
// (services/local_config.py, core/engine/context.py, adapters/commands.py and cli_agents.py) to point at the
// field to correct; the server stays authoritative and every change still goes through its exact preview.
// Editors replace only the edited key: any value without a control here is carried over unchanged.
import type { MessageKey } from "./i18n.ts";

export type Obj = Record<string, any>;
export type Issues = Record<string, MessageKey>;

export const COMMAND_NAME = /^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$/;
export const ENTRY_NAME = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const SHELLS = new Set(["sh", "bash", "zsh", "dash", "ksh", "mksh", "ash", "fish", "csh", "tcsh", "busybox"]);
const SHELL_TOKENS = new Set([";", "&", "&&", "|", "||", "|&", ">", ">>", "<", "<<", "2>", "2>&1"]);
export const MAX_TIMEOUT = 86400;
export const MAX_OUTPUT = 1048576;
export const MAX_JUNIT = 8;
export const PATH_KEYS = ["protected_paths", "sensitive_paths", "sensitive_allowlist", "data_model_paths"] as const;
export const TOOL_KEYS = ["tools", "allowed_tools", "grantable_tools"] as const;

/** A stable DOM id for an issue key; profile and preset names may contain dots. */
export const domId = (scope: string, key: string) => `${scope}-${key.replace(/[^A-Za-z0-9_-]/g, "-")}`;

export const isObject = (value: unknown): value is Obj => !!value && typeof value === "object" && !Array.isArray(value);
export const texts = (value: unknown): string[] => Array.isArray(value) ? value.map(item => String(item)) : [];
const blank = (value: unknown) => typeof value !== "string" || !value.trim();
const positive = (value: unknown) => typeof value === "number" && Number.isFinite(value) && value > 0;

/** One value per line, exactly as typed (no trimming); a line break cannot be represented, so it is detected. */
export const fromLines = (text: string) => text === "" ? [] : text.split("\n");
export const toLines = (values: string[]) => values.join("\n");
export const multiline = (values: unknown) => texts(values).some(value => value.includes("\n"));
/** Blank lines left while typing are removed once the field loses focus; other values stay exact. */
export const withoutBlank = (values: string[]) => values.filter(value => value !== "");

export function relative(path: string) {
  return !!path && !path.startsWith("/") && !path.includes("\\") && !path.split("/").includes("..");
}

/** Shell-free argv whose first element is a logical executable name (D241), never a path or a shell. */
export function argvIssue(argv: unknown): MessageKey | undefined {
  if (!Array.isArray(argv) || !argv.length) return "editor.argv_required";
  if (argv.some(blank)) return "editor.argv_blank";
  if (!COMMAND_NAME.test(argv[0]) || SHELLS.has(argv[0])) return "editor.argv_name";
  if (argv.some(item => SHELL_TOKENS.has(item) || item.includes("`") || item.includes("$("))) return "editor.argv_shell";
  return undefined;
}

export function environmentIssue(environment: unknown): MessageKey | undefined {
  if (environment === undefined) return undefined;
  if (!isObject(environment)) return "editor.environment_invalid";
  for (const [name, value] of Object.entries(environment))
    if (!name.trim() || name.includes("=") || typeof value !== "string") return "editor.environment_invalid";
  return undefined;
}

export function nameIssue(name: string, used: Iterable<string>, pattern = /^[^=\s][^=]*$/): MessageKey | undefined {
  if (!name.trim()) return "configuration.required";
  if (!pattern.test(name)) return "editor.name_invalid";
  if ([...used].includes(name)) return "editor.name_repeated";
  return undefined;
}

export function commandIssues(command: unknown, prefix: string, issues: Issues, junit = false) {
  if (!isObject(command)) { issues[prefix] = "editor.command_invalid"; return; }
  const argv = argvIssue(command.argv);
  if (argv) issues[`${prefix}.argv`] = argv;
  if (!positive(command.timeout_seconds)) issues[`${prefix}.timeout_seconds`] = "configuration.positive";
  if (command.cwd !== undefined && (typeof command.cwd !== "string" || !relative(command.cwd)))
    issues[`${prefix}.cwd`] = "editor.relative";
  const environment = environmentIssue(command.environment);
  if (environment) issues[`${prefix}.environment`] = environment;
  if (junit && command.junit !== undefined) {
    const report = command.junit;
    const path = isObject(report) && typeof report.path === "string" ? report.path : "";
    if (!relative(path) || path === "." || path.split("/").includes(".git")) issues[`${prefix}.junit.path`] = "editor.junit_path";
    if (!isObject(report) || blank(report.coverage)) issues[`${prefix}.junit.coverage`] = "configuration.required";
  }
}

function patternIssues(value: unknown, key: string, issues: Issues, required: boolean) {
  const list = texts(value);
  if (!Array.isArray(value) || required && !list.length) issues[key] = "editor.paths_required";
  else if (list.some(item => !relative(item))) issues[key] = "editor.relative";
  else if (new Set(list).size !== list.length) issues[key] = "editor.repeated";
}

/** The logical names a profile runs: argv[0] of its commands and formatter, in first-use order. */
export function profileTools(profile: unknown): string[] {
  if (!isObject(profile)) return [];
  const commands = [...(Array.isArray(profile.preparation) ? profile.preparation : []),
    ...(Array.isArray(profile.validations) ? profile.validations : [])];
  const names = commands.map(command => isObject(command) && Array.isArray(command.argv) ? command.argv[0] : undefined);
  if (Array.isArray(profile.formatter_argv)) names.push(profile.formatter_argv[0]);
  return [...new Set(names.filter((name): name is string => typeof name === "string" && !!name))];
}

export function profileIssues(profile: unknown, prefix: string): Issues {
  const issues: Issues = {};
  if (!isObject(profile)) return { [prefix]: "editor.profile_invalid" };
  if (blank(profile.executor_instructions)) issues[`${prefix}.executor_instructions`] = "configuration.required";
  if (!Array.isArray(profile.preparation)) issues[`${prefix}.preparation`] = "editor.command_invalid";
  if (!Array.isArray(profile.validations) || !profile.validations.length) issues[`${prefix}.validations`] = "editor.validations_required";
  for (const key of ["preparation", "validations"] as const)
    (Array.isArray(profile[key]) ? profile[key] : []).forEach((command: unknown, index: number) =>
      commandIssues(command, `${prefix}.${key}.${index}`, issues, key === "validations"));
  const reports = (Array.isArray(profile.validations) ? profile.validations : [])
    .filter((command: unknown) => isObject(command) && command.junit !== undefined)
    .map((command: Obj) => isObject(command.junit) ? command.junit.path : undefined);
  if (reports.length > MAX_JUNIT) issues[`${prefix}.validations`] = "editor.junit_limit";
  else if (new Set(reports).size !== reports.length) issues[`${prefix}.validations`] = "editor.junit_repeated";
  if (!Array.isArray(profile.allowed_command_prefixes)) issues[`${prefix}.allowed_command_prefixes`] = "editor.command_invalid";
  else profile.allowed_command_prefixes.forEach((argv: unknown, index: number) => {
    const problem = argvIssue(argv);
    if (problem) issues[`${prefix}.allowed_command_prefixes.${index}`] = problem;
  });
  patternIssues(profile.protected_paths, `${prefix}.protected_paths`, issues, true);
  patternIssues(profile.sensitive_paths, `${prefix}.sensitive_paths`, issues, true);
  patternIssues(profile.data_model_paths, `${prefix}.data_model_paths`, issues, false);
  if (profile.sensitive_allowlist !== undefined) patternIssues(profile.sensitive_allowlist, `${prefix}.sensitive_allowlist`, issues, false);
  if (profile.formatter_argv !== undefined || profile.formatter_paths !== undefined) {
    const argv = profile.formatter_argv;
    const problem = argvIssue(argv);
    if (problem) issues[`${prefix}.formatter_argv`] = problem;
    else if (argv.length < 2 || argv.at(-1) !== "--") issues[`${prefix}.formatter_argv`] = "editor.formatter_end";
    patternIssues(profile.formatter_paths, `${prefix}.formatter_paths`, issues, true);
  }
  return issues;
}

const sameCommand = (a: Obj, b: Obj) => JSON.stringify([a.argv, a.cwd ?? ".", a.environment ?? {}, a.timeout_seconds])
  === JSON.stringify([b.argv, b.cwd ?? ".", b.environment ?? {}, b.timeout_seconds]);

/** Logical names used by the profile, its extra authorizations or formatter without an installed path. */
export function unmappedTools(profile: unknown, commands: unknown): string[] {
  const executables = isObject(commands) && isObject(commands.executables) ? commands.executables : {};
  const extra = isObject(commands) && Array.isArray(commands.authorized) ? commands.authorized : [];
  const names = [...profileTools(profile), ...extra.map((command: Obj) => isObject(command) && Array.isArray(command.argv) ? command.argv[0] : undefined)];
  return [...new Set(names.filter((name): name is string => typeof name === "string" && !!name && !(name in executables)))];
}

export function commandsIssues(commands: unknown, prefix: string, profile?: unknown): Issues {
  const issues: Issues = {};
  if (!isObject(commands)) return { [prefix]: "editor.command_invalid" };
  const executables = commands.executables;
  if (!isObject(executables) || !Object.keys(executables).length) issues[`${prefix}.executables`] = "editor.executables_required";
  else for (const [name, path] of Object.entries(executables)) {
    const key = `${prefix}.executables.${name}`;
    if (!COMMAND_NAME.test(name) || SHELLS.has(name)) issues[key] = "editor.argv_name";
    else if (typeof path !== "string" || !path.trim()) issues[key] = "configuration.required";
    else if (!path.startsWith("/")) issues[key] = "configuration.absolute";
  }
  const environment = environmentIssue(commands.environment ?? {});
  if (environment || !isObject(commands.environment)) issues[`${prefix}.environment`] = environment ?? "editor.environment_invalid";
  if (typeof commands.authorize_profile_commands !== "boolean") issues[`${prefix}.authorize_profile_commands`] = "configuration.required";
  const extra = Array.isArray(commands.authorized) ? commands.authorized : [];
  if (commands.authorized !== undefined && !Array.isArray(commands.authorized)) issues[`${prefix}.authorized`] = "editor.command_invalid";
  extra.forEach((command: unknown, index: number) => commandIssues(command, `${prefix}.authorized.${index}`, issues));
  if (commands.max_timeout_seconds !== undefined && !(positive(commands.max_timeout_seconds) && commands.max_timeout_seconds <= MAX_TIMEOUT))
    issues[`${prefix}.max_timeout_seconds`] = "editor.max_timeout";
  if (commands.max_output_bytes !== undefined && !(Number.isInteger(commands.max_output_bytes)
      && commands.max_output_bytes >= 1 && commands.max_output_bytes <= MAX_OUTPUT))
    issues[`${prefix}.max_output_bytes`] = "editor.max_output";
  if (isObject(profile)) {
    const required = [...(Array.isArray(profile.preparation) ? profile.preparation : []),
      ...(Array.isArray(profile.validations) ? profile.validations : [])].filter(isObject);
    if (commands.authorize_profile_commands === false && required.some(command => !extra.some((item: unknown) => isObject(item) && sameCommand(item, command))))
      issues[`${prefix}.authorize_profile_commands`] = "editor.authorize_all";
    else if (commands.authorize_profile_commands === false && profile.formatter_argv !== undefined)
      issues[`${prefix}.authorize_profile_commands`] = "editor.formatter_authorize";
    if (isObject(executables) && Object.keys(executables).length && unmappedTools(profile, commands).length)
      issues[`${prefix}.executables`] ??= "editor.unmapped";
  }
  return issues;
}

/** Tool lists are explicit Claude Code permissions for the executor only; never a file/network sandbox switch. */
export const toolsSupported = (provider: unknown, roles: string[]) => provider === "claude" && !roles.includes("reviewer");
export const hasTools = (agent: unknown) => isObject(agent) && TOOL_KEYS.some(key => texts(agent[key]).length > 0);

export function agentIssues(agent: unknown, prefix: string, roles: string[], efforts: Record<string, string[]>): Issues {
  const issues: Issues = {};
  if (!isObject(agent)) return { [prefix]: "configuration.required" };
  if (!efforts[String(agent.provider)]) issues[`${prefix}.provider`] = "configuration.required";
  if (!positive(agent.timeout_seconds)) issues[`${prefix}.timeout_seconds`] = "configuration.positive";
  const environment = environmentIssue(agent.environment);
  if (environment || !isObject(agent.environment)) issues[`${prefix}.environment`] = environment ?? "configuration.required";
  else if (!("USER" in agent.environment)) issues[`${prefix}.environment`] = "editor.user_required";
  else if (blank(agent.environment.USER)) issues[`${prefix}.environment.USER`] = "configuration.required";
  else if (agent.provider === "claude" && (agent.environment.CLAUDE_CODE_DISABLE_AUTO_MEMORY ?? "1") !== "1")
    issues[`${prefix}.environment`] = "editor.memory";
  const argv = agent.executable;
  if (argv !== undefined && (!Array.isArray(argv) || !argv.length || !String(argv[0]).startsWith("/")))
    issues[`${prefix}.executable`] = "configuration.absolute";
  if (agent.cli_version !== undefined && !/^(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})$/.test(String(agent.cli_version)))
    issues[`${prefix}.cli_version`] = "editor.version";
  if (hasTools(agent) && !toolsSupported(agent.provider, roles)) issues[`${prefix}.tools`] = "editor.tools_unsupported";
  else for (const key of TOOL_KEYS) if (texts(agent[key]).some(tool => !tool.trim() || tool.startsWith("-")))
    issues[`${prefix}.${key}`] = "editor.tool_invalid";
  return issues;
}

export function emptyProfile(): Obj {
  return { executor_instructions: "", preparation: [], validations: [], allowed_command_prefixes: [],
    protected_paths: [], sensitive_paths: [], data_model_paths: [] };
}
export function emptyCommands(): Obj {
  return { executables: {}, environment: {}, authorize_profile_commands: true };
}

/** Move one item without changing any other entry. */
export function moved<T>(items: T[], index: number, offset: number): T[] {
  const target = index + offset;
  if (target < 0 || target >= items.length) return items;
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}
/** Rename an object key in place, keeping the order and every other value. */
export function renamed(value: Obj, from: string, to: string): Obj {
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key === from ? to : key, item]));
}
export function without(value: Obj, key: string): Obj {
  return Object.fromEntries(Object.entries(value).filter(([name]) => name !== key));
}
