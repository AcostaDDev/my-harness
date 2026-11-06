// Texts of the development fixture only (T021). They are kept out of the product catalogues, which ship in every
// build, but follow the same rules: English and Spanish with the same keys and fields (tested).
import { translate } from "../../i18n.ts";
import type { Language, Params } from "../../i18n.ts";

const en = {
  "fixture.title": "Work map fixture",
  "fixture.synthetic": "Synthetic data for the development review of P002-T021. Nothing here reads or changes real projects.",
  "fixture.scenario": "Scenario",
  "fixture.scenario.normal": "Normal review",
  "fixture.scenario.budget": "Budget: D309 maxima (80 tasks)",
  "fixture.scenario.stress": "Stress: 200 tasks",
  "fixture.language": "Language",
  "fixture.theme": "Theme",
  "fixture.theme.system": "System",
  "fixture.theme.light": "Light",
  "fixture.theme.dark": "Dark",
  "fixture.motion": "Motion",
  "fixture.motion.system": "System preference",
  "fixture.motion.reduce": "Reduced",
  "fixture.motion.allow": "Allowed",
  "fixture.measure.cold": "Redraw with an empty shape cache",
  "fixture.measure.bench": "Run the pan and zoom benchmark (4 s)",
  "fixture.result.render": "{count} nodes drawn in {ms} ms (route change to the second animation frame).",
  "fixture.result.bench": "{frames} frames: mean {fps} fps, 5th percentile {low} fps, longest frame {worst} ms, {visible} nodes in view.",
  "fixture.result.running": "Measuring…",
  "fixture.legend": "Legend",
  "fixture.legend.depends_on": "depends_on: solid arrow",
  "fixture.legend.replaces": "replaces: dashed arrow",
  "fixture.legend.sequence": "order of phases and steps: solid arrow",
  "fixture.not_map": "This route is not a map level in the fixture.",
  "fixture.back": "Back to projects",
} as const;

export type FixtureKey = keyof typeof en;

const es: Record<FixtureKey, string> = {
  "fixture.title": "Fixture del mapa de trabajo",
  "fixture.synthetic": "Datos sintéticos para la revisión de desarrollo de P002-T021. Nada aquí lee ni cambia proyectos reales.",
  "fixture.scenario": "Escenario",
  "fixture.scenario.normal": "Revisión normal",
  "fixture.scenario.budget": "Presupuesto: máximos de D309 (80 tareas)",
  "fixture.scenario.stress": "Estrés: 200 tareas",
  "fixture.language": "Idioma",
  "fixture.theme": "Tema",
  "fixture.theme.system": "Sistema",
  "fixture.theme.light": "Claro",
  "fixture.theme.dark": "Oscuro",
  "fixture.motion": "Movimiento",
  "fixture.motion.system": "Preferencia del sistema",
  "fixture.motion.reduce": "Reducido",
  "fixture.motion.allow": "Permitido",
  "fixture.measure.cold": "Volver a dibujar con la caché de formas vacía",
  "fixture.measure.bench": "Medir desplazamiento y zoom (4 s)",
  "fixture.result.render": "{count} nodos dibujados en {ms} ms (del cambio de ruta al segundo fotograma).",
  "fixture.result.bench": "{frames} fotogramas: media {fps} fps, percentil 5 {low} fps, fotograma más largo {worst} ms, {visible} nodos a la vista.",
  "fixture.result.running": "Midiendo…",
  "fixture.legend": "Leyenda",
  "fixture.legend.depends_on": "depends_on: flecha continua",
  "fixture.legend.replaces": "replaces: flecha discontinua",
  "fixture.legend.sequence": "orden de fases y pasos: flecha continua",
  "fixture.not_map": "Esta ruta no es un nivel del mapa en la fixture.",
  "fixture.back": "Volver a proyectos",
};

export const FIXTURE_TEXT: Record<Language, Readonly<Record<FixtureKey, string>>> = { en, es };

export function fixtureText(language: Language, key: FixtureKey, params?: Params): string {
  return translate(FIXTURE_TEXT, language, key, params);
}
