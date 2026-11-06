// Development fixture of the work-map engine (P002-T021, D312). It drives the real `MapView`, controller, router
// (`parse`/`href`/`trail`) and history (`navigate`, Back/Forward) with synthetic data under the `/__map-fixture` base,
// so the owner can review look, navigation and interaction in the browser. It needs no API and no session.
import { useEffect, useMemo, useRef, useState } from "react";
import { I18nProvider, useI18n } from "../../Language";
import type { Language } from "../../i18n.ts";
import { Link } from "../../navigation";
import { trail } from "../../router.ts";
import type { MapController } from "../controller.ts";
import { layoutOf, MapView } from "../MapView";
import { forgetViews, mapPath, useMapNavigation } from "../routes.ts";
import { clearShapes } from "../shapes.ts";
import { STATUS_CLASSES, STATUS_LABELS } from "../status.ts";
import { fixtureLevel, SCENARIOS } from "./data.ts";
import type { Scenario } from "./data.ts";
import { panZoomBenchmark, visibleNodes } from "./measure.ts";
import type { BenchmarkResult } from "./measure.ts";
import { fixtureText } from "./text.ts";
import type { FixtureKey } from "./text.ts";

export const FIXTURE_BASE = "/__map-fixture";
const STORAGE = "harness-map-fixture";

type Theme = "system" | "light" | "dark";
type Motion = "system" | "reduce" | "allow";
type Settings = { scenario: Scenario; language: Language; theme: Theme; motion: Motion };
const DEFAULTS: Settings = { scenario: "normal", language: "en", theme: "system", motion: "system" };

// Per-tab convenience only: losing it just shows the defaults.
function stored(): Settings {
  try { return { ...DEFAULTS, ...JSON.parse(sessionStorage.getItem(STORAGE) ?? "{}") as Partial<Settings> }; }
  catch { return DEFAULTS; }
}

declare global {
  interface Window { __mapFixtureResults?: { render?: { scenario: Scenario; path: string; nodes: number; ms: number }[]; bench?: (BenchmarkResult & { scenario: Scenario; path: string })[] } }
}

export function FixtureRoot() {
  const [settings, setSettings] = useState<Settings>(stored);
  useEffect(() => {
    try { sessionStorage.setItem(STORAGE, JSON.stringify(settings)); } catch { /* defaults next time */ }
    if (settings.theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", settings.theme);
  }, [settings]);
  return <I18nProvider fixed={settings.language}>
    <FixtureApp settings={settings} change={patch => setSettings(current => ({ ...current, ...patch }))} />
  </I18nProvider>;
}

function FixtureApp({ settings, change }: { settings: Settings; change: (patch: Partial<Settings>) => void }) {
  const { t } = useI18n();
  const f = (key: FixtureKey, params?: Record<string, string | number>) => fixtureText(settings.language, key, params);
  const navigation = useMapNavigation(FIXTURE_BASE);
  const { route, path } = navigation;
  // The route is derived from the path, so the path identifies the level.
  const level = useMemo(() => fixtureLevel(settings.scenario, route), [settings.scenario, path]);
  const controller = useRef<MapController | undefined>(undefined);
  const [generation, setGeneration] = useState(0);
  const [render, setRender] = useState<{ nodes: number; ms: number }>();
  const [bench, setBench] = useState<BenchmarkResult | "running">();

  // First-render timing: from the render that starts a new level to the second animation frame after its commit.
  const key = `${settings.scenario}|${path}|${generation}`;
  const started = useRef({ key: "", at: 0 });
  if (started.current.key !== key) started.current = { key, at: performance.now() };
  useEffect(() => {
    if (!level) return;
    const at = started.current.at;
    let second = 0;
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => {
        const result = { nodes: level.nodes.length, ms: Math.round((performance.now() - at) * 10) / 10 };
        setRender(result);
        ((window.__mapFixtureResults ??= {}).render ??= []).push({ scenario: settings.scenario, path, ...result });
      });
    });
    return () => { cancelAnimationFrame(first); cancelAnimationFrame(second); };
  }, [key]);

  const runBenchmark = async () => {
    const current = controller.current;
    const box = document.querySelector(".map-viewport")?.getBoundingClientRect();
    if (!current || !level || !box) return;
    setBench("running");
    const rects = layoutOf(level.nodes, level.edges, level.arrangement).nodes;
    current.fit();
    const result = await panZoomBenchmark(current, visibleNodes(current, rects, box.width, box.height));
    setBench(result);
    ((window.__mapFixtureResults ??= {}).bench ??= []).push({ scenario: settings.scenario, path, ...result });
  };

  const levelLabel = level && ({
    projects: t("map.level.projects"),
    phases: t("map.level.phases", { project: level.scope }),
    tasks: t("map.level.tasks", { phase: level.scope }),
    steps: t("map.level.steps", { task: level.scope }),
  })[level.level];

  return <main className="map-fixture">
    <header className="map-fixture-header">
      <h1>{f("fixture.title")}</h1>
      <p className="muted">{f("fixture.synthetic")}</p>
      <div className="map-fixture-controls">
        <label>{f("fixture.scenario")} <select value={settings.scenario} onChange={event => { forgetViews(); change({ scenario: event.target.value as Scenario }); }}>
          {SCENARIOS.map(item => <option key={item} value={item}>{f(`fixture.scenario.${item}`)}</option>)}
        </select></label>
        <label>{f("fixture.language")} <select value={settings.language} onChange={event => change({ language: event.target.value as Language })}>
          <option value="en">English</option><option value="es">Español</option>
        </select></label>
        <label>{f("fixture.theme")} <select value={settings.theme} onChange={event => change({ theme: event.target.value as Theme })}>
          {(["system", "light", "dark"] as const).map(item => <option key={item} value={item}>{f(`fixture.theme.${item}`)}</option>)}
        </select></label>
        <label>{f("fixture.motion")} <select value={settings.motion} onChange={event => change({ motion: event.target.value as Motion })}>
          {(["system", "reduce", "allow"] as const).map(item => <option key={item} value={item}>{f(`fixture.motion.${item}`)}</option>)}
        </select></label>
        <button type="button" className="button-quiet" onClick={() => { clearShapes(); setGeneration(value => value + 1); }}>{f("fixture.measure.cold")}</button>
        <button type="button" className="button-quiet" disabled={bench === "running"} onClick={() => void runBenchmark()}>{f("fixture.measure.bench")}</button>
      </div>
      <nav aria-label="breadcrumb" className="map-fixture-trail">
        {trail(route, t).map((item, i, all) => <span key={i}>{i > 0 && " › "}
          {i === all.length - 1 ? <span aria-current="page">{item.label}</span> : <Link to={mapPath(item.to, FIXTURE_BASE)}>{item.label}</Link>}
        </span>)}
      </nav>
      <p className="map-fixture-results" aria-live="polite">
        {render && f("fixture.result.render", { count: render.nodes, ms: render.ms })}{" "}
        {bench === "running" ? f("fixture.result.running") : bench && f("fixture.result.bench", {
          frames: bench.frames, fps: bench.meanFps, low: bench.lowFps, worst: bench.worstMs, visible: bench.visible })}
      </p>
    </header>
    {level
      ? <MapView key={`${settings.scenario}:${generation}`} viewKey={path} label={t("map.label", { level: levelLabel! })} nodes={level.nodes} edges={level.edges}
        arrangement={level.arrangement} hrefOf={to => mapPath(to, FIXTURE_BASE)} controllerRef={controller}
        motion={settings.motion === "system" ? undefined : settings.motion}
        onEnter={node => node.to && navigation.enter(node.to, node.id)} onLeave={navigation.parent ? navigation.leave : undefined} />
      : <p>{f("fixture.not_map")} <Link to={mapPath({ name: "home" }, FIXTURE_BASE)}>{f("fixture.back")}</Link></p>}
    <section className="map-fixture-legend" aria-label={f("fixture.legend")}>
      <h2>{f("fixture.legend")}</h2>
      <ul>
        {STATUS_CLASSES.map(cls => <li key={cls} className={`map-status-${cls}`}><span className="map-fixture-swatch" aria-hidden="true" />{t(STATUS_LABELS[cls])}</li>)}
        <li><span className="map-fixture-line" aria-hidden="true" />{f("fixture.legend.depends_on")}</li>
        <li><span className="map-fixture-line map-fixture-dashed" aria-hidden="true" />{f("fixture.legend.replaces")}</li>
        <li><span className="map-fixture-line" aria-hidden="true" />{f("fixture.legend.sequence")}</li>
      </ul>
    </section>
  </main>;
}
