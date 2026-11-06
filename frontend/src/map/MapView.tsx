// SVG work-map view (T021): rough.js outlines in the DOM (no canvas, no editor), theme colours from CSS tokens,
// focusable and labelled nodes, a camera driven by `MapController` and navigation reported to the caller, which
// binds it to the existing router (routes.ts). Product projections are wired by T022; T021 drives it with fixtures.
import { memo, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, MouseEvent, PointerEvent } from "react";
import { useI18n } from "../Language";
import type { Route } from "../router.ts";
import { between, coverage, toScreen, transformOf, zoomAt } from "./camera.ts";
import type { Camera, Viewport } from "./camera.ts";
import { ENTER_COVERAGE, MapController } from "./controller.ts";
import type { ControllerNode } from "./controller.ts";
import { accessibleDescription, accessibleName, statusText, wrapTitle } from "./labels.ts";
import type { MapNodeKind, NodeText } from "./labels.ts";
import { DEFAULT_LAYOUT, gridLayout, layeredLayout } from "./layout.ts";
import type { EdgeKind, Layout, PlacedNode } from "./layout.ts";
import { ease, transitionMs, usePrefersReducedMotion } from "./motion.ts";
import { recallView, rememberView } from "./routes.ts";
import { bubbleShape, cardShape, circleShape, edgeShape, iconShape, raysShape } from "./shapes.ts";
import type { ShapePath } from "./shapes.ts";
import { STATUS_CLASSES, STATUS_ICONS, statusClassOf } from "./status.ts";

export type MapNode = NodeText & { id: string; order?: string; to?: Route };
export type MapEdge = { from: string; to: string; kind: EdgeKind };
export type Arrangement = "layered" | "grid";

export type MapViewProps = {
  /** Identity of the level shown (its path): camera and focus are remembered per key. */
  viewKey: string;
  /** Accessible name of the map. */
  label: string;
  nodes: readonly MapNode[];
  edges?: readonly MapEdge[];
  arrangement: Arrangement;
  hrefOf: (route: Route) => string;
  onEnter: (node: MapNode) => void;
  /** Absent at the top level: Escape and zoom-out then do nothing. */
  onLeave?: () => void;
  /** Overrides the system preference (development fixture only). */
  motion?: "reduce" | "allow";
  /** Access to the controller for the development fixture's measurements. */
  controllerRef?: { current?: MapController };
};

export const CARD_SIZES: Record<MapNodeKind, { width: number; height: number }> = {
  project: { width: 224, height: 124 },
  phase: { width: 208, height: 112 },
  task: { width: 208, height: 112 },
  step: { width: 188, height: 100 },
};
const TITLE_CHARS = 21;
const DEFAULT_VIEWPORT: Viewport = { width: 960, height: 600 };
const EMPTY_EDGES: readonly MapEdge[] = [];

/** Layout of a level: cards sized by kind, layered for graphs and a grid for unrelated cards. */
export function layoutOf(nodes: readonly MapNode[], edges: readonly MapEdge[], arrangement: Arrangement): Layout {
  const size = CARD_SIZES[nodes[0]?.kind ?? "task"];
  const options = { ...DEFAULT_LAYOUT, nodeWidth: size.width, nodeHeight: size.height, rowGap: 56 };
  const items = nodes.map(node => ({ id: node.id, order: node.order ?? node.code }));
  return arrangement === "grid" ? gridLayout(items, options) : layeredLayout(items, [...edges], options);
}

// A keyboard or pointer navigation from one level returns the focus to the map on the next one (module-wide because
// the caller may mount a new view per route). It expires, so a map shown later by an unrelated navigation never takes
// the focus.
const FOCUS_HANDOVER_MS = 2000;
let restoreFocusUntil = 0;
function handOverFocus(root: HTMLElement | null) {
  restoreFocusUntil = root && typeof document !== "undefined" && root.contains(document.activeElement) ? Date.now() + FOCUS_HANDOVER_MS : 0;
}

export function MapView(props: MapViewProps) {
  const { nodes, edges = EMPTY_EDGES, arrangement, viewKey } = props;
  const { t, n } = useI18n();
  const systemReduced = usePrefersReducedMotion();
  const reduced = props.motion ? props.motion === "reduce" : systemReduced;
  const uid = `map${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const layout = useMemo(() => layoutOf(nodes, edges, arrangement), [nodes, edges, arrangement]);
  const byId = useMemo(() => new Map(nodes.map(node => [node.id, node])), [nodes]);
  const placedById = useMemo(() => new Map(layout.nodes.map(node => [node.id, node])), [layout]);
  const targets: ControllerNode[] = useMemo(() => layout.nodes.map(node => ({ id: node.id, rect: node, enterable: !!byId.get(node.id)?.to })), [layout, byId]);
  const relations = useMemo(() => {
    const codes = new Map<string, { dependsOn: string[]; replaces: string[] }>();
    for (const edge of edges) {
      const target = codes.get(edge.to) ?? codes.set(edge.to, { dependsOn: [], replaces: [] }).get(edge.to)!;
      const code = byId.get(edge.from)?.code;
      if (code && edge.kind === "depends_on") target.dependsOn.push(code);
      if (code && edge.kind === "replaces") target.replaces.push(code);
    }
    // Codes in a stable order and without repeats, whatever the order of the edges.
    const unique = (items: string[]) => [...new Set(items)].sort();
    for (const item of codes.values()) { item.dependsOn = unique(item.dependsOn); item.replaces = unique(item.replaces); }
    return codes;
  }, [edges, byId]);

  const rootRef = useRef<HTMLDivElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const worldRef = useRef<SVGGElement | null>(null);
  const nodeRefs = useRef(new Map<string, SVGElement>());
  const latest = useRef({ props, reduced, layout, byId, placedById });
  latest.current = { props, reduced, layout, byId, placedById };
  const viewport = useRef<Viewport>(DEFAULT_VIEWPORT);
  const pointerActive = useRef(false);
  const entering = useRef(false);
  const frame = useRef(0);
  const animation = useRef(0);
  const shownKey = useRef("");
  const recalled = recallView(viewKey);
  const [focused, setFocused] = useState<string | undefined>(() => initialFocus(layout, recalled?.focus));
  const focusedRef = useRef(focused);
  focusedRef.current = focused;
  const [zoom, setZoom] = useState(100);

  const apply = useCallback((camera: Camera) => {
    worldRef.current?.setAttribute("transform", transformOf(camera));
    if (frame.current || typeof requestAnimationFrame === "undefined") return;
    frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      const current = controller.current!.camera;
      setZoom(Math.round(current.k * 100));
      if (!entering.current) rememberView(latest.current.props.viewKey, { camera: current });
    });
  }, []);

  const controller = useRef<MapController | undefined>(undefined);
  if (!controller.current) {
    controller.current = new MapController({
      nodes: targets, bounds: layout.bounds, viewport: DEFAULT_VIEWPORT, canLeave: !!props.onLeave,
      camera: settle(recalled?.camera, recalled?.focus, placedById, DEFAULT_VIEWPORT),
      handlers: {
        camera: camera => apply(camera),
        focus: id => {
          setFocused(id);
          rememberView(latest.current.props.viewKey, { focus: id });
          nodeRefs.current.get(id)?.focus({ preventScroll: true });
        },
        enter: id => enter(id),
        leave: () => {
          handOverFocus(rootRef.current);
          latest.current.props.onLeave?.();
        },
      },
    });
  }
  if (props.controllerRef) props.controllerRef.current = controller.current;
  const initialTransform = useMemo(() => transformOf(controller.current!.camera), []);

  function enter(id: string) {
    const { props: current, reduced: still, byId: known, placedById: placed } = latest.current;
    const node = known.get(id), rect = placed.get(id);
    if (!node || !rect) return;
    handOverFocus(rootRef.current);
    const duration = transitionMs(still);
    if (!duration || typeof requestAnimationFrame === "undefined") { current.onEnter(node); return; }
    // Finish the zoom on the node, then navigate (sketches 02 and 04).
    const { width, height } = viewport.current;
    const k = Math.min(width / rect.width, height / rect.height) * 0.9;
    const to: Camera = { k, x: width / 2 - (rect.x + rect.width / 2) * k, y: height / 2 - (rect.y + rect.height / 2) * k };
    const from = controller.current!.camera;
    const start = performance.now();
    entering.current = true;
    cancelAnimationFrame(animation.current);
    const step = (now: number) => {
      const progress = Math.min(1, (now - start) / duration);
      worldRef.current?.setAttribute("transform", transformOf(between(from, to, ease(progress))));
      if (progress < 1) { animation.current = requestAnimationFrame(step); return; }
      entering.current = false;
      latest.current.props.onEnter(node);
    };
    animation.current = requestAnimationFrame(step);
  }

  // New level or refreshed data: measure, restore or keep the camera and release the navigation lock.
  useLayoutEffect(() => {
    const box = rootRef.current?.querySelector(".map-viewport")?.getBoundingClientRect();
    if (box && box.width && box.height) viewport.current = { width: box.width, height: box.height };
    const sameLevel = shownKey.current === viewKey;
    shownKey.current = viewKey;
    const memory = recallView(viewKey);
    const camera = sameLevel ? controller.current!.camera : settle(memory?.camera, memory?.focus, placedById, viewport.current);
    cancelAnimationFrame(animation.current);
    entering.current = false;
    controller.current!.reset({ nodes: targets, bounds: layout.bounds, viewport: viewport.current, camera, canLeave: !!props.onLeave });
    const keep = sameLevel && focusedRef.current && placedById.has(focusedRef.current) ? focusedRef.current : initialFocus(layout, memory?.focus);
    setFocused(keep);
    if (!sameLevel && Date.now() < restoreFocusUntil) {
      restoreFocusUntil = 0;
      // An empty level keeps the focus on its controls instead of dropping it to the page.
      const target = keep ? nodeRefs.current.get(keep) : rootRef.current?.querySelector<HTMLElement>(".map-toolbar button");
      target?.focus({ preventScroll: true });
    }
  }, [viewKey, layout]);

  useEffect(() => {
    const element = rootRef.current?.querySelector(".map-viewport");
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      if (!width || !height) return;
      viewport.current = { width, height };
      controller.current!.resize(viewport.current);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // Wheel and Safari trackpad gestures need non-passive listeners to keep the page from scrolling or zooming.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const local = (x: number, y: number): [number, number] => { const box = svg.getBoundingClientRect(); return [x - box.left, y - box.top]; };
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const [x, y] = local(event.clientX, event.clientY);
      controller.current!.wheel({ dx: event.deltaX, dy: event.deltaY, x, y, ctrl: event.ctrlKey, shift: event.shiftKey, mode: event.deltaMode as 0 | 1 | 2 });
    };
    let scale = 1;
    const gesture = (event: Event) => {
      const g = event as Event & { scale: number; clientX: number; clientY: number };
      event.preventDefault();
      if (event.type === "gesturestart") { scale = 1; controller.current!.gestureStart(); return; }
      const [x, y] = local(g.clientX, g.clientY);
      controller.current!.gestureZoom(g.scale / scale, [x, y]);
      scale = g.scale;
    };
    svg.addEventListener("wheel", wheel, { passive: false });
    for (const type of ["gesturestart", "gesturechange"]) svg.addEventListener(type, gesture, { passive: false } as AddEventListenerOptions);
    return () => {
      svg.removeEventListener("wheel", wheel);
      for (const type of ["gesturestart", "gesturechange"]) svg.removeEventListener(type, gesture);
    };
  }, []);

  useEffect(() => () => { cancelAnimationFrame(frame.current); cancelAnimationFrame(animation.current); }, []);

  const point = (event: PointerEvent<SVGSVGElement>): [number, number] => {
    const box = event.currentTarget.getBoundingClientRect();
    return [event.clientX - box.left, event.clientY - box.top];
  };
  const pointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    pointerActive.current = true;
    controller.current!.pointerDown(event.pointerId, ...point(event), event.pointerType !== "mouse");
  };
  const pointerMove = (event: PointerEvent<SVGSVGElement>) => {
    controller.current!.pointerMove(event.pointerId, ...point(event));
    // Capture only once a drag starts: capturing on press would retarget the click of a plain press away from its node.
    if (controller.current!.dragging && !event.currentTarget.hasPointerCapture(event.pointerId)) {
      try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* pointer already released */ }
    }
  };
  const pointerUp = (event: PointerEvent<SVGSVGElement>) => {
    controller.current!.pointerUp(event.pointerId);
    pointerActive.current = false;
  };
  const keyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    const handled = controller.current!.key({ key: event.key, shift: event.shiftKey, ctrl: event.ctrlKey, meta: event.metaKey, alt: event.altKey, repeat: event.repeat }, focusedRef.current);
    if (handled) event.preventDefault();
  };
  const activate = useCallback((id: string, event: MouseEvent<SVGElement>) => {
    const keyboard = event.detail === 0;
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      // A modified click opens the real link in the browser, unless it ends a drag.
      if (!controller.current!.takeClick(keyboard)) event.preventDefault();
      return;
    }
    event.preventDefault();
    // Enter on a focused link is a keyboard activation: its auto-repeat must not open the next level's node.
    if (controller.current!.takeClick(keyboard)) controller.current!.enter(id, keyboard ? "key" : undefined);
  }, []);
  const focusNode = useCallback((id: string) => {
    setFocused(id);
    rememberView(latest.current.props.viewKey, { focus: id });
    // Keyboard focus (Tab) reveals the node; a pointer press does not move the camera under the pointer.
    if (!pointerActive.current) controller.current!.focus(id);
  }, []);
  const register = useCallback((id: string, element: SVGElement | null) => {
    if (element) nodeRefs.current.set(id, element); else nodeRefs.current.delete(id);
  }, []);

  const helpId = `${uid}-help`;
  return <div ref={rootRef} className="map" data-motion={reduced ? "reduce" : "allow"}>
    <div className="map-toolbar" role="toolbar" aria-label={t("map.toolbar")}>
      {props.onLeave && <button type="button" className="button-quiet" onClick={() => controller.current!.leave()}>{t("map.up")}</button>}
      <button type="button" className="button-quiet" aria-label={t("map.zoom_out")} title={t("map.zoom_out")}
        onClick={() => controller.current!.zoom(1 / 1.25, [viewport.current.width / 2, viewport.current.height / 2])}>−</button>
      <span className="map-zoom muted">{t("map.zoom_level", { percent: zoom })}</span>
      <button type="button" className="button-quiet" aria-label={t("map.zoom_in")} title={t("map.zoom_in")}
        onClick={() => controller.current!.zoom(1.25, [viewport.current.width / 2, viewport.current.height / 2])}>+</button>
      <button type="button" className="button-quiet" onClick={() => controller.current!.fit()}>{t("map.fit")}</button>
    </div>
    <p id={helpId} className="map-help muted">{t("map.help")}</p>
    <div className="map-viewport">
      {!nodes.length && <p className="map-empty muted">{t("map.empty")}</p>}
      <svg ref={svgRef} className="map-canvas" role="group" aria-label={props.label} aria-describedby={helpId}
        onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={pointerUp}
        onKeyDown={keyDown} onDragStart={event => event.preventDefault()}>
        <defs>
          {STATUS_CLASSES.map(cls => <symbol key={cls} id={`${uid}-icon-${cls}`} viewBox="0 0 20 20" overflow="visible">
            <Paths paths={iconShape(cls, STATUS_ICONS[cls])} className="map-icon-stroke" />
          </symbol>)}
        </defs>
        <g ref={worldRef} transform={initialTransform}>
          <g className="map-edges" aria-hidden="true">
            {layout.edges.map(edge => <EdgeView key={edge.id} id={edge.id} kind={edge.kind} points={edge.points} />)}
          </g>
          <g className="map-nodes" key={viewKey}>
            {layout.nodes.map(placed => {
              const node = byId.get(placed.id)!;
              return <NodeView key={placed.id} node={node} placed={placed} focused={placed.id === focused} icon={`#${uid}-icon-${statusClassOf(node.statusClass)}`}
                href={node.to ? props.hrefOf(node.to) : undefined} name={accessibleName(node, t, n)} status={statusText(node, t)}
                description={accessibleDescription(node, relations.get(node.id) ?? { dependsOn: [], replaces: [] }, !!node.to, t)}
                register={register} onActivate={activate} onFocusNode={focusNode} />;
            })}
          </g>
        </g>
      </svg>
    </div>
  </div>;
}

/** Focus on entry: the remembered node, else the first node in reading order. */
function initialFocus(layout: Layout, remembered?: string): string | undefined {
  if (remembered && layout.nodes.some(node => node.id === remembered)) return remembered;
  return [...layout.nodes].sort((a, b) => a.y - b.y || a.x - b.x)[0]?.id;
}

/**
 * A remembered camera, made safe to reuse: if it is zoomed so far into the focused node that one more zoom step would
 * enter it again, it is pulled back around that node.
 */
function settle(camera: Camera | undefined, focus: string | undefined, placed: Map<string, PlacedNode>, viewport: Viewport): Camera | undefined {
  const rect = focus ? placed.get(focus) : undefined;
  if (!camera || !rect) return camera;
  const share = coverage(camera, rect, viewport);
  if (share < ENTER_COVERAGE * 0.7) return camera;
  const centre = toScreen(camera, [rect.x + rect.width / 2, rect.y + rect.height / 2]);
  return zoomAt(camera, (ENTER_COVERAGE * 0.5) / share, centre, { min: 0, max: Infinity });
}

function Paths({ paths, className }: { paths: ShapePath[]; className: string }) {
  return <>{paths.map((path, i) => <path key={i} d={path.d} className={path.fill ? `${className}-fill` : className} />)}</>;
}

const EdgeView = memo(function EdgeView({ id, kind, points }: { id: string; kind: EdgeKind; points: [number, number][] }) {
  const { line, head } = edgeShape(id, points);
  return <g className={`map-edge map-edge-${kind}`}>
    <Paths paths={line} className="map-edge-line" />
    <Paths paths={head} className="map-edge-head" />
  </g>;
});

type NodeViewProps = {
  node: MapNode; placed: PlacedNode; focused: boolean; icon: string; href?: string; name: string; status: string;
  description: string;
  register: (id: string, element: SVGElement | null) => void;
  onActivate: (id: string, event: MouseEvent<SVGElement>) => void;
  onFocusNode: (id: string) => void;
};

const NodeView = memo(function NodeView(props: NodeViewProps) {
  const { node, placed, focused, href } = props;
  const { width, height } = placed;
  const cls = statusClassOf(node.statusClass);
  const title = wrapTitle(node.title, TITLE_CHARS, 2);
  const common = {
    ref: (element: SVGElement | null) => props.register(node.id, element),
    className: `map-node map-status-${cls}`,
    transform: `translate(${placed.x} ${placed.y})`,
    tabIndex: focused ? 0 : -1,
    "aria-label": props.name,
    "aria-description": props.description,
    "data-node": node.id,
    onFocus: () => props.onFocusNode(node.id),
    onClick: (event: MouseEvent<SVGElement>) => props.onActivate(node.id, event),
  };
  const body = <>
    <Paths paths={cardShape(node.id, width, height)} className="map-card" />
    <use href={props.icon} x={14} y={12} width={20} height={20} className="map-icon" />
    <text className="map-label map-code" x={42} y={28}>{node.code}</text>
    {title.map((line, i) => <text key={i} className="map-label map-title" x={14} y={56 + i * 21}>{line}</text>)}
    <text className="map-label map-status-text" x={14} y={height - 13}>{props.status}</text>
    {(node.actors ?? []).map((actor, i) => {
      const cx = 18 + i * 30, cy = -18;
      return <g key={actor.role} className={`map-actor${actor.active ? " map-actor-active" : ""}`}>
        {actor.active && <g className="map-rays"><Paths paths={raysShape(`${node.id}:${actor.role}`, cx, cy, 12)} className="map-ray" /></g>}
        <Paths paths={circleShape(`${node.id}:${actor.role}`, cx, cy, 24)} className="map-actor-circle" />
        <text className="map-label map-actor-letter" x={cx} y={cy + 5} textAnchor="middle">{actor.role}</text>
      </g>;
    })}
    {!!node.requests && <g className="map-bubble" transform={`translate(${width - 44} -38)`}>
      <Paths paths={bubbleShape(node.id, 38, 24)} className="map-bubble-shape" />
      <text className="map-label map-bubble-count" x={19} y={17} textAnchor="middle">{node.requests > 99 ? "99+" : node.requests}</text>
    </g>}
    <rect className="map-focus-ring" x={-7} y={-7} width={width + 14} height={height + 14} rx={20} />
  </>;
  // Enterable nodes are real SVG links (open in a new tab, copy); the others are focusable, labelled images.
  // React types every `<a>` as HTML, so the SVG anchor is written through the `<g>` typing it shares attributes with.
  const Tag = (href ? "a" : "g") as "g";
  return <Tag {...common} href={href} role={href ? undefined : "img"}>{body}</Tag>;
});
