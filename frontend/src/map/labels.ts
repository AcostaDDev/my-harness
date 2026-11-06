// Text of map nodes: accessible names (T018 §11: kind, code, title, status text, active actors, request count),
// accessible descriptions (raw status code and relations) and the wrapped title drawn on the card.
import type { Plural, Translate } from "../i18n.ts";
import { STATUS_LABELS, statusClassOf } from "./status.ts";

export type ActorRole = "R" | "E" | "J" | "H";
export type MapNodeKind = "project" | "phase" | "task" | "step";

export type NodeText = {
  kind: MapNodeKind;
  code: string;
  title: string;
  statusClass: string;
  status: string;
  actors?: readonly { role: ActorRole; active: boolean }[];
  requests?: number;
};

/** Visible status text: the translated class, or the raw code for a value outside the contract (§5.1). */
export function statusText(node: Pick<NodeText, "statusClass" | "status">, t: Translate): string {
  const cls = statusClassOf(node.statusClass);
  return cls === "unknown" ? t("map.status.unknown_code", { code: node.status }) : t(STATUS_LABELS[cls]);
}

export function accessibleName(node: NodeText, t: Translate, n: Plural): string {
  const parts = [t("map.node.name", { kind: t(`map.kind.${node.kind}`), code: node.code, title: node.title, status: statusText(node, t) })];
  const active = (node.actors ?? []).filter(actor => actor.active).map(actor => t(`map.actor.${actor.role}`));
  if (active.length) parts.push(t("map.node.active", { actors: active.join(", ") }));
  if (node.requests) parts.push(n("map.node.requests", node.requests));
  return parts.join(" ");
}

export function accessibleDescription(node: NodeText, relations: { dependsOn: string[]; replaces: string[] }, enterable: boolean, t: Translate): string {
  const parts = [t("map.node.raw_status", { code: node.status })];
  if (relations.dependsOn.length) parts.push(t("map.node.depends_on", { codes: relations.dependsOn.join(", ") }));
  if (relations.replaces.length) parts.push(t("map.node.replaces", { codes: relations.replaces.join(", ") }));
  if (!enterable) parts.push(t("map.node.not_enterable"));
  return parts.join(" ");
}

/** Up to `lines` lines of at most `width` characters, breaking at spaces; the last line ends in "…" when cut. */
export function wrapTitle(title: string, width: number, lines: number): string[] {
  const words = title.trim().split(/\s+/).filter(Boolean).map(word => word.length > width ? `${word.slice(0, width - 1)}…` : word);
  const out: string[] = [];
  let current = "";
  let i = 0;
  for (; i < words.length; i++) {
    const next = current ? `${current} ${words[i]}` : words[i];
    if (next.length <= width) { current = next; continue; }
    if (out.length === lines - 1) break;
    out.push(current);
    current = words[i];
  }
  if (current) out.push(current);
  if (i < words.length) {
    const last = out[out.length - 1];
    out[out.length - 1] = last.endsWith("…") ? last : `${last.length >= width ? last.slice(0, width - 1) : last}…`;
  }
  return out;
}
