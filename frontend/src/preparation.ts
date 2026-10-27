import type { MessageKey, Translate } from "./i18n.ts";

export function pendingPreparationStep(steps: { number: number; status: string }[]): number | undefined {
  return steps.find(step => step.status !== 'DONE')?.number ?? steps.at(-1)?.number;
}
/** P010-T002 (D142): what each packaged recipe prepares, by its frozen `project_recipe` (v2: P011-T020, D168). */
export function recipeLabel(recipe: string | null | undefined): string | null {
  return ({ 'django-recipe-1': 'Django', 'typescript-web-recipe-1': 'TypeScript web', 'django-recipe-2': 'Django',
    'typescript-web-recipe-2': 'TypeScript web' } as Record<string, string>)[recipe ?? ''] ?? null;
}
export function isTypeScriptRecipe(recipe: string | null | undefined): boolean {
  return recipe === 'typescript-web-recipe-1' || recipe === 'typescript-web-recipe-2';
}
export function recipeModes(recipe: string | null | undefined, t: Translate): { offline: string; network: string; hint: string } {
  if (!recipeLabel(recipe)) return { offline: t('preparation.mode.generic.offline'),
    network: t('preparation.mode.generic.network'), hint: t('preparation.mode.generic.hint') };
  return isTypeScriptRecipe(recipe)
    ? { offline: t('preparation.mode.typescript.offline'), network: t('preparation.mode.typescript.network'),
        hint: t('preparation.mode.typescript.hint') }
    : { offline: t('preparation.mode.django.offline'), network: t('preparation.mode.django.network'),
        hint: t('preparation.mode.django.hint') };
}
/** Recipe text with its name, or the generic sentence when the recipe is unknown (no fragment is inserted). */
export function recipeText(recipe: string | null | undefined, t: Translate, named: MessageKey, generic: MessageKey): string {
  const label = recipeLabel(recipe);
  return label ? t(named, { recipe: label }) : t(generic);
}
export function preparationStatus(status: string, recipe: string | null | undefined, t: Translate): string {
  if (status === 'ACTIVE') return recipeText(recipe, t, 'preparation.status.active', 'preparation.status.active_generic');
  if (status === 'COMPLETED') return recipeText(recipe, t, 'preparation.status.completed', 'preparation.status.completed_generic');
  const keys: Record<string, MessageKey> = { QUEUED: 'preparation.status.queued', FAILED: 'preparation.status.failed',
    RECOVERY_REQUIRED: 'preparation.status.recovery_required', CANCELLED: 'preparation.status.cancelled' };
  return keys[status] ? t(keys[status]) : status;
}

// P011-T020 (D168): v2 steps carry a stable `id` and are named in the visual language; the label frozen in the plan
// is not rewritten. v1 plans have no id and keep their frozen label.
const STEP_KEYS: Record<string, MessageKey> = {
  'python-version': 'preparation.step.python_version', 'installer-version': 'preparation.step.installer_version',
  'create-environment': 'preparation.step.create_environment', 'check-dependencies': 'preparation.step.check_dependencies',
  'installed-versions': 'preparation.step.installed_versions', 'generate-project': 'preparation.step.generate_project',
  'generate-app': 'preparation.step.generate_app', publish: 'preparation.step.publish', migrate: 'preparation.step.migrate',
  'node-version': 'preparation.step.node_version', 'npm-version': 'preparation.step.npm_version',
  commit: 'preparation.step.commit',
};
const RECIPE_STEP_KEYS: Record<string, Record<string, MessageKey>> = {
  'django-recipe-2': { files: 'preparation.step.files.django', install: 'preparation.step.install.django' },
  'typescript-web-recipe-2': { files: 'preparation.step.files.typescript', install: 'preparation.step.install.typescript' },
};
/** Generic profiles nest their exact command; packaged recipe steps carry it directly. */
export function preparationCommand(step: Record<string, unknown>): Record<string, unknown> {
  return step.command && typeof step.command === 'object' && !Array.isArray(step.command)
    ? step.command as Record<string, unknown> : step;
}
export function preparationStepLabel(recipe: string | null | undefined, step: Record<string, unknown>, t: Translate): string {
  const id = step.id, frozen = String(step.label ?? '');
  if (recipe == null && !frozen) {
    if (step.kind === 'directories') return t('preparation.step.directories');
    if (step.kind === 'executor') return t('preparation.step.executor');
    if (step.kind === 'commit') return t('preparation.step.commit');
    const command = preparationCommand(step);
    if (step.kind === 'command' && Array.isArray(command.argv)) {
      return t(step.stage === 'validation' ? 'preparation.step.validate' : 'preparation.step.prepare',
        { command: command.argv.map(String).join(' ') });
    }
    return t('preparation.step.unknown', { kind: String(step.kind ?? step.id ?? t('common.not_recorded_null')) });
  }
  if (typeof id !== 'string') return frozen;
  if (/^validate-[0-9]+$/.test(id) && Array.isArray(step.argv) && step.argv.length) {
    // The profile command as the recipe declares it: its tool name, not the absolute executable path.
    const [tool, ...args] = step.argv.map(String);
    return t('preparation.step.validate', { command: [tool.split('/').at(-1), ...args].join(' ') });
  }
  const key = RECIPE_STEP_KEYS[recipe ?? '']?.[id] ?? STEP_KEYS[id];
  return key ? t(key) : frozen;
}
