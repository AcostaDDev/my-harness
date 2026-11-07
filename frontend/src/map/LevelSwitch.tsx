// Map/list toggle on every map level (T018 §4, D304; P002-T022). The same path renders the map or its list: in
// ordinary mode the list is the existing page with all its controls; in archives it is the table over the same
// SQLite projection, because the operational list pages stay blocked there.
import type { ReactNode } from "react";
import { useI18n } from "../Language";
import { useServiceMode } from "../ServiceMode";
import { useViewMode } from "./view-mode.ts";
import type { ViewMode } from "./view-mode.ts";
import { WorkMap } from "./WorkMap";
import type { MapRoute } from "./WorkMap";

export function ViewToggle({ mode, choose }: { mode: ViewMode; choose: (mode: ViewMode) => void }) {
  const { t } = useI18n();
  return <div className="map-view-toggle" role="group" aria-label={t("map.view.label")}>
    {(["map", "list"] as const).map(option => <button key={option} type="button" className="button-quiet" aria-pressed={mode === option}
      onClick={() => { if (mode !== option) choose(option); }}>
      <span aria-hidden="true" className={`map-view-mark map-view-${option}`} />{t(`map.view.${option}`)}</button>)}
  </div>;
}

export function MapLevelSwitch({ route, list, base }: { route: MapRoute; list?: ReactNode; base?: string }) {
  const { mode, choose } = useViewMode();
  const service = useServiceMode();
  const archive = service?.read_only_archive === true;
  const canRespond = !archive && (!service?.configuration_mode || service.configuration_mode === "READY");
  return <>
    <ViewToggle mode={mode} choose={choose} />
    {/* One map across levels of a project, as the engine expects (camera and focus memory per path). */}
    {mode === "map" ? <WorkMap key="map" route={route} archive={archive} canRespond={canRespond} base={base} />
      : archive || !list ? <WorkMap key="table" route={route} archive={archive} canRespond={false} display="table" base={base} /> : list}
  </>;
}
