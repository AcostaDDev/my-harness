// In-house layered layout for the work map (T018 §10, D297: no layout library without measured evidence).
// Left-to-right layers by longest path, dummy points for long edges and barycentric ordering. Every step works on a
// canonical order (sort key, then id), so the same graph gives the same layout whatever the input order.

export type EdgeKind = "depends_on" | "replaces" | "sequence" | "containment" | "parentage" | "causation" | "correlation";

export type LayoutNode = { id: string; order?: string };
/** `from` is the earlier element: the prerequisite of `depends_on`, the replaced task of `replaces`. */
export type LayoutEdge = { from: string; to: string; kind: EdgeKind };

export type Point = [number, number];
export type Bounds = { x: number; y: number; width: number; height: number };
export type PlacedNode = { id: string; x: number; y: number; width: number; height: number; layer: number; row: number };
export type PlacedEdge = { id: string; from: string; to: string; kind: EdgeKind; points: Point[]; reversed: boolean };
export type Layout = { nodes: PlacedNode[]; edges: PlacedEdge[]; bounds: Bounds };

export type LayoutOptions = { nodeWidth: number; nodeHeight: number; layerGap: number; rowGap: number };

export const DEFAULT_LAYOUT: LayoutOptions = { nodeWidth: 200, nodeHeight: 104, layerGap: 96, rowGap: 40 };

const SWEEPS = 6;

function compare(a: string, b: string): number { return a < b ? -1 : a > b ? 1 : 0; }

export function edgeId(edge: LayoutEdge): string { return `${edge.from}->${edge.to}:${edge.kind}`; }

/** Nodes in canonical order without duplicates, and edges between known, distinct nodes without duplicates. */
function canonical(nodes: readonly LayoutNode[], edges: readonly LayoutEdge[]) {
  const byId = new Map<string, LayoutNode>();
  for (const node of [...nodes].sort((a, b) => compare(a.order ?? a.id, b.order ?? b.id) || compare(a.id, b.id))) {
    if (!byId.has(node.id)) byId.set(node.id, node);
  }
  const index = new Map([...byId.keys()].map((id, i) => [id, i]));
  const seen = new Set<string>();
  const kept = edges.filter(edge => {
    const id = edgeId(edge);
    if (edge.from === edge.to || !index.has(edge.from) || !index.has(edge.to) || seen.has(id)) return false;
    seen.add(id);
    return true;
  }).sort((a, b) => index.get(a.from)! - index.get(b.from)! || index.get(a.to)! - index.get(b.to)! || compare(a.kind, b.kind));
  return { ids: [...byId.keys()], index, edges: kept };
}

/** Edges that close a cycle in a depth-first walk in canonical order; they are laid out reversed. */
function backEdges(ids: string[], edges: LayoutEdge[]): Set<LayoutEdge> {
  const out = new Map<string, LayoutEdge[]>(ids.map(id => [id, []]));
  for (const edge of edges) out.get(edge.from)!.push(edge);
  const state = new Map<string, 1 | 2>();
  const back = new Set<LayoutEdge>();
  for (const root of ids) {
    if (state.has(root)) continue;
    // Iterative DFS: deep chains of tasks must not exhaust the call stack.
    const stack: [string, number][] = [[root, 0]];
    state.set(root, 1);
    while (stack.length) {
      const top = stack[stack.length - 1];
      const next = out.get(top[0])![top[1]++];
      if (!next) { state.set(top[0], 2); stack.pop(); continue; }
      const seen = state.get(next.to);
      if (seen === 1) back.add(next);
      else if (!seen) { state.set(next.to, 1); stack.push([next.to, 0]); }
    }
  }
  return back;
}

type Slot = { id: string; dummy: boolean; rank: number };

/** Layered layout of a directed graph, left to right. Nodes without any edge are packed in a grid below it. */
export function layeredLayout(nodes: readonly LayoutNode[], edges: readonly LayoutEdge[], options: LayoutOptions = DEFAULT_LAYOUT): Layout {
  const { ids, index, edges: kept } = canonical(nodes, edges);
  const back = backEdges(ids, kept);
  const directed = kept.map(edge => back.has(edge) ? { edge, u: edge.to, v: edge.from } : { edge, u: edge.from, v: edge.to });
  const connected = new Set(directed.flatMap(({ u, v }) => [u, v]));

  // Longest-path layering over the acyclic orientation (Kahn, canonical tie-break).
  const layer = new Map<string, number>();
  const indegree = new Map<string, number>(ids.map(id => [id, 0]));
  const successors = new Map<string, string[]>(ids.map(id => [id, []]));
  for (const { u, v } of directed) { indegree.set(v, indegree.get(v)! + 1); successors.get(u)!.push(v); }
  const ready = ids.filter(id => connected.has(id) && indegree.get(id) === 0);
  for (const id of ready) layer.set(id, 0);
  while (ready.length) {
    ready.sort((a, b) => index.get(a)! - index.get(b)!);
    const u = ready.shift()!;
    for (const v of successors.get(u)!) {
      layer.set(v, Math.max(layer.get(v) ?? 0, layer.get(u)! + 1));
      indegree.set(v, indegree.get(v)! - 1);
      if (indegree.get(v) === 0) ready.push(v);
    }
  }

  // Layers with real nodes and one dummy slot per intermediate layer of a long edge.
  const layers: Slot[][] = [];
  const put = (slot: Slot, at: number) => { (layers[at] ??= []).push(slot); };
  for (const id of ids) if (connected.has(id)) put({ id, dummy: false, rank: index.get(id)! }, layer.get(id)!);
  const chains: { edge: LayoutEdge; reversed: boolean; path: string[] }[] = [];
  const links: [string, string][] = [];
  for (const { edge, u, v } of directed) {
    const path = [u];
    for (let at = layer.get(u)! + 1; at < layer.get(v)!; at++) {
      const dummy = `${edgeId(edge)}#${at}`;
      put({ id: dummy, dummy: true, rank: index.get(u)! + 0.5 }, at);
      path.push(dummy);
    }
    path.push(v);
    for (let i = 1; i < path.length; i++) links.push([path[i - 1], path[i]]);
    chains.push({ edge, reversed: back.has(edge), path });
  }
  for (const slots of layers) slots?.sort((a, b) => a.rank - b.rank || compare(a.id, b.id));

  // Barycentric ordering sweeps; ties keep the canonical rank, so the result is order-independent.
  const position = new Map<string, number>();
  const left = new Map<string, string[]>(), right = new Map<string, string[]>();
  for (const [a, b] of links) { (right.get(a) ?? right.set(a, []).get(a)!).push(b); (left.get(b) ?? left.set(b, []).get(b)!).push(a); }
  layers.forEach(slots => slots.forEach((slot, i) => position.set(slot.id, i)));
  for (let sweep = 0; sweep < SWEEPS; sweep++) {
    const forward = sweep % 2 === 0;
    const order = forward ? layers.map((_, i) => i).slice(1) : layers.map((_, i) => i).slice(0, -1).reverse();
    for (const at of order) {
      const neighbours = forward ? left : right;
      const weight = new Map(layers[at].map(slot => {
        const near = neighbours.get(slot.id) ?? [];
        return [slot.id, near.length ? near.reduce((sum, id) => sum + position.get(id)!, 0) / near.length : position.get(slot.id)!];
      }));
      layers[at].sort((a, b) => weight.get(a.id)! - weight.get(b.id)! || a.rank - b.rank || compare(a.id, b.id));
      layers[at].forEach((slot, i) => position.set(slot.id, i));
    }
  }

  // Coordinates: columns per layer, rows centred on the tallest layer.
  const { nodeWidth: w, nodeHeight: h, layerGap, rowGap } = options;
  const pitchX = w + layerGap, pitchY = h + rowGap;
  const tallest = Math.max(0, ...layers.map(slots => slots?.length ?? 0));
  const centre = new Map<string, Point>();
  const placed: PlacedNode[] = [];
  layers.forEach((slots, at) => {
    const offset = (tallest - slots.length) * pitchY / 2;
    slots.forEach((slot, row) => {
      const x = at * pitchX, y = offset + row * pitchY;
      centre.set(slot.id, [x + w / 2, y + h / 2]);
      if (!slot.dummy) placed.push({ id: slot.id, x, y, width: w, height: h, layer: at, row });
    });
  });

  // Unconnected nodes: a grid under the graph, in canonical order.
  const loose = ids.filter(id => !connected.has(id));
  if (loose.length) {
    const columns = Math.max(layers.length, Math.ceil(Math.sqrt(loose.length * 1.6)));
    const top = tallest ? tallest * pitchY + rowGap : 0;
    loose.forEach((id, i) => {
      const column = i % columns, row = Math.floor(i / columns);
      placed.push({ id, x: column * pitchX, y: top + row * pitchY, width: w, height: h, layer: column, row: tallest + row });
    });
  }

  const edgesOut: PlacedEdge[] = chains.map(({ edge, reversed, path }) => {
    const points: Point[] = path.map((id, i) => {
      const [cx, cy] = centre.get(id)!;
      if (i === 0) return [cx + w / 2, cy];
      if (i === path.length - 1) return [cx - w / 2, cy];
      return [cx, cy];
    });
    return { id: edgeId(edge), from: edge.from, to: edge.to, kind: edge.kind, points: reversed ? points.reverse() : points, reversed };
  });

  placed.sort((a, b) => index.get(a.id)! - index.get(b.id)!);
  return { nodes: placed, edges: edgesOut, bounds: boundsOf(placed) };
}

/** Cards in rows (L0 projects): canonical order, a near-landscape grid. */
export function gridLayout(nodes: readonly LayoutNode[], options: LayoutOptions = DEFAULT_LAYOUT, columns?: number): Layout {
  const { ids } = canonical(nodes, []);
  const count = columns ?? Math.min(8, Math.max(1, Math.ceil(Math.sqrt(ids.length * 1.6))));
  const placed = ids.map((id, i) => ({
    id, layer: i % count, row: Math.floor(i / count), width: options.nodeWidth, height: options.nodeHeight,
    x: (i % count) * (options.nodeWidth + options.layerGap), y: Math.floor(i / count) * (options.nodeHeight + options.rowGap),
  }));
  return { nodes: placed, edges: [], bounds: boundsOf(placed) };
}

export function boundsOf(nodes: readonly { x: number; y: number; width: number; height: number }[]): Bounds {
  if (!nodes.length) return { x: 0, y: 0, width: 0, height: 0 };
  const x = Math.min(...nodes.map(n => n.x)), y = Math.min(...nodes.map(n => n.y));
  return { x, y, width: Math.max(...nodes.map(n => n.x + n.width)) - x, height: Math.max(...nodes.map(n => n.y + n.height)) - y };
}
