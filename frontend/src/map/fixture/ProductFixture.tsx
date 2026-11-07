// Development fixture of the product map (P002-T022, D312): the real `MapLevelSwitch`, `WorkMap`, inspector, run
// selector, requests panel (T017's `InboxConversation`) and invocation header, under `/__map-fixture`, with every
// `/api/managed/…` read answered in this page from synthetic T020 projections (`projections.ts`). Every mutation is
// refused, so nothing is applied. Served by the Vite development server only; never built or packaged.
import { useEffect, useMemo, useState } from "react";
import { useI18n } from "../../Language";
import type { Language } from "../../i18n.ts";
import type { S } from "../../managed-api";
import { Link, RouteBase } from "../../navigation";
import { trail } from "../../router.ts";
import { ServiceModeContext } from "../../ServiceMode";
import { InvocationPage } from "../InvocationPage";
import { MapLevelSwitch } from "../LevelSwitch";
import { forgetViews, mapPath, useMapNavigation } from "../routes.ts";
import { isMapRoute } from "../WorkMap";
import { FIXTURE_BASE } from "./FixtureApp";
import type { Settings, Source } from "./FixtureApp";
import { PROJECTION_SCENARIOS, respond, syntheticMap } from "./projections.ts";
import type { ProjectionScenario, SyntheticMap } from "./projections.ts";
import { fixtureText } from "./text.ts";
import type { FixtureKey } from "./text.ts";

let current: SyntheticMap | undefined;
let original: typeof fetch | undefined;

/** Routes `/api/managed/…` to the synthetic map (reads) or a refusal (mutations); anything else is the real fetch. */
function install(map: SyntheticMap, refused: string) {
  current = map;
  if (original) return;
  original = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (!current || !url.startsWith("/api/managed/")) return original!(input, init);
    await new Promise(resolve => setTimeout(resolve, 60));
    if (init?.method && init.method !== "GET") return Response.json({ detail: { code: "synthetic_fixture", diagnostic: refused } }, { status: 409 });
    const answer = respond(current, url);
    return Response.json(answer.body, { status: answer.status });
  };
}

export function ProductFixture({ settings, change }: { settings: Settings; change: (patch: Partial<Settings>) => void }) {
  const { t } = useI18n();
  const f = (key: FixtureKey, params?: Record<string, string | number>) => fixtureText(settings.language, key, params);
  const navigation = useMapNavigation(FIXTURE_BASE);
  const { route } = navigation;
  const [reviewer, setReviewer] = useState(false);
  const map = useMemo(() => syntheticMap(settings.product, { archive: settings.archive, reviewer }), [settings.product, settings.archive, reviewer]);
  // Installed while rendering: the map's own effects read before a parent effect would run.
  useMemo(() => install(map, f("fixture.refused")), [map, settings.language]);
  useEffect(() => () => { current = undefined; }, []);
  const [version, setVersion] = useState(map.version);
  useEffect(() => setVersion(map.version), [map]);
  const mode = { read_only_archive: settings.archive, configuration_mode: null, enabled: !settings.archive, alive: !settings.archive,
    last_error: null, ports_configured: !settings.archive, commit_writer_configured: false } as unknown as S["SupervisorRead"];
  return <main className="map-fixture">
    <header className="map-fixture-header">
      <h1>{f("fixture.title")}</h1>
      <p className="muted">{f("fixture.product.note")}</p>
      <div className="map-fixture-controls">
        <label>{f("fixture.source")} <select value={settings.source} onChange={event => { forgetViews(); change({ source: event.target.value as Source }); }}>
          {(["engine", "product"] as const).map(item => <option key={item} value={item}>{f(`fixture.source.${item}`)}</option>)}
        </select></label>
        <label>{f("fixture.scenario")} <select value={settings.product} onChange={event => { forgetViews(); change({ product: event.target.value as ProjectionScenario }); }}>
          {PROJECTION_SCENARIOS.map(item => <option key={item} value={item}>{f(`fixture.product.scenario.${item}`)}</option>)}
        </select></label>
        <label>{f("fixture.archive")} <select value={settings.archive ? "on" : "off"} onChange={event => { forgetViews(); change({ archive: event.target.value === "on" }); }}>
          <option value="off">{f("fixture.archive.off")}</option><option value="on">{f("fixture.archive.on")}</option>
        </select></label>
        <label>{f("fixture.language")} <select value={settings.language} onChange={event => change({ language: event.target.value as Language })}>
          <option value="en">English</option><option value="es">Español</option>
        </select></label>
        <label>{f("fixture.theme")} <select value={settings.theme} onChange={event => change({ theme: event.target.value as Settings["theme"] })}>
          {(["system", "light", "dark"] as const).map(item => <option key={item} value={item}>{f(`fixture.theme.${item}`)}</option>)}
        </select></label>
        <button type="button" className="button-quiet" onClick={() => { map.bump(); setVersion(map.version); }}>{f("fixture.simulate")}</button>
        <button type="button" className="button-quiet" onClick={() => { map.bump({ finish: true }); setVersion(map.version); }}>{f("fixture.finish")}</button>
        <button type="button" className="button-quiet" onClick={() => { map.startRun("P002-T004"); setVersion(map.version); }}>{f("fixture.first_run")}</button>
        <label>{f("fixture.reviewer")} <select value={reviewer ? "on" : "off"} onChange={event => { forgetViews(); setReviewer(event.target.value === "on"); }}>
          <option value="off">{f("fixture.reviewer.off")}</option><option value="on">{f("fixture.reviewer.on")}</option>
        </select></label>
        <span className="muted">{f("fixture.version", { version })}</span>
      </div>
      <nav aria-label="breadcrumb" className="map-fixture-trail">
        {trail(route, t).map((item, i, all) => <span key={i}>{i > 0 && " › "}
          {i === all.length - 1 ? <span aria-current="page">{item.label}</span> : <Link to={mapPath(item.to, FIXTURE_BASE)}>{item.label}</Link>}
        </span>)}
      </nav>
    </header>
    <ServiceModeContext.Provider value={mode}>
      <RouteBase.Provider value={FIXTURE_BASE}>
        {isMapRoute(route) ? <MapLevelSwitch key={`${settings.product}:${settings.archive}:${reviewer}`} route={route} base={FIXTURE_BASE} />
          : route.name === "invocation" ? <InvocationPage key={route.invocation} project={route.project} invocation={route.invocation} archive={settings.archive} base={FIXTURE_BASE} />
          : <p>{f("fixture.not_map")} <Link to={mapPath({ name: "home" }, FIXTURE_BASE)}>{f("fixture.back")}</Link></p>}
      </RouteBase.Provider>
    </ServiceModeContext.Provider>
  </main>;
}
