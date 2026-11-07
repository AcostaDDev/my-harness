// SVG work-map view (T021): rough.js outlines in the DOM (no canvas, no editor), theme colours from CSS tokens,
// focusable and labelled nodes, a camera driven by `MapController` and navigation reported to the caller, which
// binds it to the existing router (routes.ts). T022 drives it with T020's projections: card counters, error marks,
// badges and Plan · Check · Close slots are drawn inside the card link, while circles, request bubbles and the
// details control are separate overlay controls, so selecting them never also navigates the card.
import { memo, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, MouseEvent, PointerEvent } from "react";
import { useI18n } from "../Language";
import type { Route } from "../router.ts";
import { between, coverage, toScreen, transformOf, zoomAt } from "./camera.ts";
import type { Camera, Viewport } from "./camera.ts";
import { ENTER_COVERAGE, MapController } from "./controller.ts";
import type { ControllerNode } from "./controller.ts";
import { accessibleDescription, accessibleName, fitLine, lineFits, statusText, wrapTitle } from "./labels.ts";
import type { ActorRole, MapNodeKind, NodeActor, NodeText } from "./labels.ts";
import { DEFAULT_LAYOUT, gridLayout, layeredLayout } from "./layout.ts";
import type { EdgeKind, Layout, PlacedNode } from "./layout.ts";
import { ease, transitionMs, usePrefersReducedMotion } from "./motion.ts";
import { recallView, rememberView } from "./routes.ts";
import { bubbleShape, cardShape, circleShape, edgeShape, iconShape, raysShape } from "./shapes.ts";
import type { ShapePath } from "./shapes.ts";
import { STATUS_CLASSES, STATUS_ICONS, statusClassOf } from "./status.ts";
import { fitsWithin, textWidth, type LineBudget } from "./text-fit.ts";

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
  /** Node shown by the caller's inspector; focusing or clicking a node selects it (T018 §3). */
  selected?: string;
  onSelect?: (node: MapNode) => void;
  /** A circle with a target was chosen: the caller opens its invocation, apart from the card's navigation. */
  onActor?: (node: MapNode, actor: NodeActor) => void;
  /** A request bubble was chosen (optionally one circle's): the caller opens the requests without navigating. */
  onRequests?: (node: MapNode, role?: ActorRole) => void;
};

// Card rows (T018 §3): the code (with the L0 badge), two title lines, the status and the primary counter. Status and
// counter each have their own row, so neither can cover the other in any language or font; every label is fitted to
// its row (text-fit.ts) and its full text stays in the accessible name and the inspector.
export const CARD_SIZES: Record<MapNodeKind, { width: number; height: number }> = {
  project: { width: 224, height: 128 },
  phase: { width: 208, height: 128 },
  task: { width: 208, height: 128 },
  step: { width: 188, height: 128 },
};
/** Font sizes (px) of the card labels; they equal `.map-code`, `.map-title`, … in styles.css (asserted by a test). */
export const CARD_FONT = { code: 15, title: 16, status: 14, counter: 13, badge: 13, slot: 12 } as const;
/** Baselines of the card rows; status and counter are measured from the card's bottom. */
export const CARD_ROWS = { code: 28, title: 56, titleStep: 21, status: 29, counter: 11 } as const;
const PAD = 14, CODE_X = 42, BADGE_GAP = 8;
// The details control (top-right corner) and the error mark (middle of the right edge) overlap the card's border;
// the code row and the title lines stop short of them.
const CORNER = 12, EDGE_MARK = 2;
// Server renders and test hosts have no animation frames; there is then nothing to cancel.
const cancelFrame = (id: number) => { if (id && typeof cancelAnimationFrame !== "undefined") cancelAnimationFrame(id); };
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
    cancelFrame(animation.current);
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
    cancelFrame(animation.current);
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

  useEffect(() => () => { cancelFrame(frame.current); cancelFrame(animation.current); }, []);

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
    const chosen = latest.current.byId.get(id);
    if (chosen) latest.current.props.onSelect?.(chosen);
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
    const node = latest.current.byId.get(id);
    if (node) latest.current.props.onSelect?.(node);
    // Keyboard focus (Tab) reveals the node; a pointer press does not move the camera under the pointer.
    if (!pointerActive.current) controller.current!.focus(id);
  }, []);
  // Overlay controls (circles, bubbles, details): a click that ends a drag is ignored like on cards, and nothing here
  // reaches the card's own link or the controller's enter.
  const overlay = useCallback((event: MouseEvent<SVGElement>, run: () => void) => {
    event.stopPropagation();
    const keyboard = event.detail === 0;
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      if (!controller.current!.takeClick(keyboard)) event.preventDefault();
      return;
    }
    event.preventDefault();
    if (controller.current!.takeClick(keyboard)) run();
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
              return <NodeView key={placed.id} node={node} placed={placed} focused={placed.id === focused} selected={placed.id === props.selected}
                icon={`#${uid}-icon-${statusClassOf(node.statusClass)}`} uid={uid}
                href={node.to ? props.hrefOf(node.to) : undefined} name={accessibleName(node, t, n)} status={statusText(node, t)}
                description={accessibleDescription(node, relations.get(node.id) ?? { dependsOn: [], replaces: [] }, !!node.to, t)}
                register={register} onActivate={activate} onFocusNode={focusNode} />;
            })}
          </g>
          <g className="map-overlays">
            {layout.nodes.map(placed => <NodeOverlay key={placed.id} node={byId.get(placed.id)!} placed={placed} hrefOf={props.hrefOf}
              select={props.onSelect} actor={props.onActor} requests={props.onRequests} overlay={overlay} />)}
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
    {kind !== "correlation" && <Paths paths={head} className="map-edge-head" />}
  </g>;
});

type NodeViewProps = {
  node: MapNode; placed: PlacedNode; focused: boolean; selected: boolean; icon: string; uid: string;
  href?: string; name: string; status: string; description: string;
  register: (id: string, element: SVGElement | null) => void;
  onActivate: (id: string, event: MouseEvent<SVGElement>) => void;
  onFocusNode: (id: string) => void;
};

/**
 * The lines drawn on a card, each fitted to its row: the code beside the badge (the badge keeps at most half the
 * row), two title lines, the visible status and the counter on rows of their own. An unknown status whose
 * "Unknown: CODE" does not fit shows its raw code alone beside the card's question-mark icon (T018 §5.1: the label
 * shows the raw code); the accessible name and the inspector keep the full text.
 */
export function cardText(node: Pick<MapNode, "code" | "title" | "badge" | "counter">, status: string, width: number, rawCode?: string) {
  const inner = width - 2 * PAD;
  const row = width - PAD - CORNER - CODE_X;
  const badge = node.badge ? fitLine(node.badge, fitsWithin(CARD_FONT.badge, row / 2)) : undefined;
  const codeWidth = badge ? row - textWidth(badge, CARD_FONT.badge) - BADGE_GAP : row;
  return {
    code: fitLine(node.code, fitsWithin(CARD_FONT.code, codeWidth)),
    badge,
    title: wrapTitle(node.title, fitsWithin(CARD_FONT.title, inner - EDGE_MARK), 2),
    status: statusLine(status, fitsWithin(CARD_FONT.status, inner), rawCode),
    counter: node.counter ? fitLine(node.counter, fitsWithin(CARD_FONT.counter, inner)) : undefined,
  };
}

function statusLine(status: string, fits: LineBudget, rawCode?: string): string {
  if (lineFits(status, fits) || !rawCode) return fitLine(status, fits);
  return fitLine(rawCode, fits);
}

const NodeView = memo(function NodeView(props: NodeViewProps) {
  const { node, placed, focused, href } = props;
  const { width, height } = placed;
  const cls = statusClassOf(node.statusClass);
  const text = cardText(node, props.status, width, cls === "unknown" ? node.status : undefined);
  const common = {
    ref: (element: SVGElement | null) => props.register(node.id, element),
    className: `map-node map-status-${cls}${props.selected ? " map-selected" : ""}`,
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
    <use href={props.icon} x={PAD} y={12} width={20} height={20} className="map-icon" />
    <text className="map-label map-code" x={CODE_X} y={CARD_ROWS.code}>{text.code}</text>
    {text.badge && <text className="map-label map-badge" x={width - PAD - CORNER} y={CARD_ROWS.code} textAnchor="end">{text.badge}</text>}
    {text.title.map((line, i) => <text key={i} className="map-label map-title" x={PAD} y={CARD_ROWS.title + i * CARD_ROWS.titleStep}>{line}</text>)}
    <text className="map-label map-status-text" x={PAD} y={height - CARD_ROWS.status}>{text.status}</text>
    {text.counter && <text className="map-label map-counter" x={PAD} y={height - CARD_ROWS.counter}>{text.counter}</text>}
    {!!node.errors && <g className="map-error-mark" transform={`translate(${width} ${Math.round(height / 2)})`}>
      <Paths paths={circleShape(`${node.id}:errors`, 0, 0, 24)} className="map-error-circle" />
      <text className="map-label map-error-count" x={0} y={5} textAnchor="middle">{node.errors > 9 ? "9+" : `!${node.errors > 1 ? node.errors : ""}`}</text>
    </g>}
    {(node.slots ?? []).map((slot, i) => {
      const x = i * Math.round(width / 3);
      const indent = slot.statusClass ? 17 : 0, fits = fitsWithin(CARD_FONT.slot, Math.round(width / 3) - indent - 6);
      return <g key={slot.key} className={`map-slot map-status-${statusClassOf(slot.statusClass ?? "pending")}${slot.statusClass ? "" : " map-slot-empty"}`} transform={`translate(${x} ${height + 8})`}>
        {slot.statusClass && <use href={`#${props.uid}-icon-${statusClassOf(slot.statusClass)}`} x={0} y={0} width={14} height={14} className="map-icon" />}
        <text className="map-label map-slot-label" x={indent} y={12}>{fitLine(slot.label, fits)}</text>
        {slot.actors.length > 0 && <text className="map-label map-slot-actors" x={indent} y={28}>{fitLine(slot.actors.join(" "), fits)}</text>}
      </g>;
    })}
    <rect className="map-focus-ring" x={-7} y={-7} width={width + 14} height={height + 14} rx={20} />
  </>;
  // Enterable nodes are real SVG links (open in a new tab, copy); the others are focusable, labelled images.
  // React types every `<a>` as HTML, so the SVG anchor is written through the `<g>` typing it shares attributes with.
  const Tag = (href ? "a" : "g") as "g";
  return <Tag {...common} href={href} role={href ? undefined : "img"}>{body}</Tag>;
});

type NodeOverlayProps = {
  node: MapNode; placed: PlacedNode; hrefOf: (route: Route) => string;
  select?: (node: MapNode) => void;
  actor?: (node: MapNode, actor: NodeActor) => void;
  requests?: (node: MapNode, role?: ActorRole) => void;
  overlay: (event: MouseEvent<SVGElement>, run: () => void) => void;
};

/**
 * Controls drawn over a card but outside its link (T018 §§4–5.3): R/E/J/H circles (a link to the circle's latest
 * invocation, or a labelled inert image), rays on every active circle, the chat-lane label, request bubbles and the
 * details control. They are pointer targets kept out of the tab order; the inspector offers every one of them to
 * the keyboard. A press that becomes a drag pans the map and never activates them.
 */
const NodeOverlay = memo(function NodeOverlay({ node, placed, hrefOf, select, actor, requests, overlay }: NodeOverlayProps) {
  const { t, n } = useI18n();
  const actors = node.actors ?? [];
  const chat = actors.some(item => item.active && item.chat);
  const Anchor = "a" as "g";
  return <g className="map-overlay" transform={`translate(${placed.x} ${placed.y})`} data-overlay={node.id}>
    {actors.map((item, i) => {
      const cx = 18 + i * 30, cy = -18;
      // Concurrent invocations of one circle are separate actors: the second R is `R#2` (its own key and shape seed).
      const repeat = actors.slice(0, i).filter(other => other.role === item.role).length;
      const seed = repeat ? `${node.id}:${item.role}#${repeat + 1}` : `${node.id}:${item.role}`;
      const name = t(`map.actor.${item.role}`);
      const label = item.target ? t(item.chat && item.active ? "map.circle.open_chat" : "map.circle.open", { actor: name })
        : t("map.circle.inert", { actor: name });
      const target = item.target && actor ? hrefOf(item.target) : undefined;
      const shape = <>
        {item.active && <g className="map-rays"><Paths paths={raysShape(seed, cx, cy, 12)} className="map-ray" /></g>}
        <Paths paths={circleShape(seed, cx, cy, 24)} className="map-actor-circle" />
        <text className="map-label map-actor-letter" x={cx} y={cy + 5} textAnchor="middle">{item.role}</text>
      </>;
      const cls = `map-actor${item.active ? " map-actor-active" : ""}${item.chat && item.active ? " map-actor-chat" : ""}${target ? " map-actor-link" : " map-actor-inert"}`;
      return <g key={seed}>
        {target
          ? <Anchor className={cls} href={target} tabIndex={-1} aria-label={label} data-actor={item.role}
            onClick={(event: MouseEvent<SVGElement>) => overlay(event, () => actor!(node, item))}>{shape}</Anchor>
          : <g className={cls} role="img" aria-label={label} data-actor={item.role}>{shape}</g>}
        {!!item.requests && <g className="map-actor-requests" role="button" tabIndex={-1} aria-label={n("map.circle.requests", item.requests, { actor: name })}
          transform={`translate(${cx + 8} ${cy - 26})`} onClick={(event: MouseEvent<SVGElement>) => overlay(event, () => requests?.(node, item.role))}>
          <Paths paths={bubbleShape(`${node.id}:${item.role}:requests`, 22, 16)} className="map-bubble-shape" />
          <text className="map-label map-bubble-count map-bubble-small" x={11} y={12} textAnchor="middle">{item.requests > 9 ? "9+" : item.requests}</text>
        </g>}
      </g>;
    })}
    {chat && <text className="map-label map-chat-label" x={18 + actors.length * 30 - 6} y={-13}>{t("map.circle.chat")}</text>}
    {!!node.requests && <g className="map-bubble" role="button" tabIndex={-1} aria-label={n("map.node.requests", node.requests)}
      transform={`translate(${placed.width - 44} -38)`} onClick={(event: MouseEvent<SVGElement>) => overlay(event, () => requests?.(node))}>
      <Paths paths={bubbleShape(node.id, 38, 24)} className="map-bubble-shape" />
      <text className="map-label map-bubble-count" x={19} y={17} textAnchor="middle">{node.requests > 99 ? "99+" : node.requests}</text>
    </g>}
    {select && node.to && <g className="map-details" role="button" tabIndex={-1} aria-label={t("map.details", { code: node.code })}
      transform={`translate(${placed.width - 11} 11)`} onClick={(event: MouseEvent<SVGElement>) => overlay(event, () => select(node))}>
      <Paths paths={circleShape(`${node.id}:details`, 11, 11, 22)} className="map-details-circle" />
      <text className="map-label map-details-mark" x={11} y={16} textAnchor="middle">i</text>
    </g>}
  </g>;
});
