// Text of map nodes: accessible names (T018 §11: kind, code, title, status text, active actors, request count),
// accessible descriptions (raw status code and relations) and the wrapped title drawn on the card.
import type { Plural, Translate } from "../i18n.ts";
import type { Route } from "../router.ts";
import { STATUS_LABELS, statusClassOf } from "./status.ts";

import type { LineBudget } from "./text-fit.ts";

export type ActorRole = "R" | "E" | "J" | "H";
export type MapNodeKind = "project" | "phase" | "task" | "step";

/**
 * One actor circle on a node (T018 §5.3). `active` lights its rays; `chat` labels the conversation lane beside the
 * task lane; `requests` counts the owner requests attributed to it; `target` is the invocation it opens: its own for
 * an active actor (concurrent invocations of one circle are separate actors), else the circle's latest in the element
 * (absent: the circle is labelled and inert). Product levels fill these from T020 as projected.
 */
export type NodeActor = { role: ActorRole; active: boolean; chat?: boolean; requests?: number; target?: Route };

/** One Plan · Check · Close slot of a phase card with the actors that actually took part (T018 §3). */
export type NodeSlot = { key: string; label: string; statusClass?: string; actors: readonly ActorRole[] };

export type NodeText = {
  kind: MapNodeKind;
  code: string;
  title: string;
  statusClass: string;
  status: string;
  /** Explicit event/outcome text when a trace node is not a lifecycle status. */
  statusLabel?: string;
  actors?: readonly NodeActor[];
  requests?: number;
  /** Primary counter, already formatted with its meaning ("Phases 2/5", "not observed"). */
  counter?: string;
  /** Number of error marks of the element (T020 `errors`). */
  errors?: number;
  /** Short badge drawn on the card (the L0 mode). */
  badge?: string;
  slots?: readonly NodeSlot[];
};

/** Visible status text: the translated class, or the raw code for a value outside the contract (§5.1). */
export function statusText(node: Pick<NodeText, "statusClass" | "status" | "statusLabel">, t: Translate): string {
  if (node.statusLabel) return node.statusLabel;
  const cls = statusClassOf(node.statusClass);
  return cls === "unknown" ? t("map.status.unknown_code", { code: node.status }) : t(STATUS_LABELS[cls]);
}

export function accessibleName(node: NodeText, t: Translate, n: Plural): string {
  const parts = [t("map.node.name", { kind: t(`map.kind.${node.kind}`), code: node.code, title: node.title, status: statusText(node, t) })];
  const active = (node.actors ?? []).filter(actor => actor.active)
    .map(actor => actor.chat ? t("map.node.actor_chat", { actor: t(`map.actor.${actor.role}`) }) : t(`map.actor.${actor.role}`));
  if (active.length) parts.push(t("map.node.active", { actors: active.join(", ") }));
  if (node.requests) parts.push(n("map.node.requests", node.requests));
  if (node.counter) parts.push(`${node.counter}.`);
  if (node.errors) parts.push(n("map.node.errors", node.errors));
  return parts.join(" ");
}

export function accessibleDescription(node: NodeText, relations: { dependsOn: string[]; replaces: string[] }, enterable: boolean, t: Translate): string {
  const parts = [t("map.node.raw_status", { code: node.status })];
  if (relations.dependsOn.length) parts.push(t("map.node.depends_on", { codes: relations.dependsOn.join(", ") }));
  if (relations.replaces.length) parts.push(t("map.node.replaces", { codes: relations.replaces.join(", ") }));
  if (!enterable) parts.push(t("map.node.not_enterable"));
  return parts.join(" ");
}

export type LineFit = number | LineBudget;
const budgetOf = (width: LineFit): LineBudget =>
  typeof width === "number" ? { limit: width, advance: character => character.length } : width;

function prefixEnd(text: string, limit: number, advance: LineBudget["advance"]): number {
  let end = 0;
  for (const character of text) {
    limit -= advance(character);
    if (limit < 0) break;
    end += character.length;
  }
  return end;
}

function remainingWidth(text: string, limit: number, advance: LineBudget["advance"]): number {
  for (const character of text) {
    limit -= advance(character);
    if (limit < 0) break;
  }
  return limit;
}

export function lineFits(text: string, { limit, advance }: LineBudget): boolean {
  return !text || remainingWidth(text, limit, advance) >= 0;
}

const graphemes = new Intl.Segmenter(undefined, { granularity: "grapheme" });

/** The longest whole-character prefix that fits with a trailing ellipsis. */
function cut(text: string, { limit, advance }: LineBudget): string {
  const end = prefixEnd(text, limit - advance("…"), advance);
  const boundary = graphemes.segment(text).containing(end)?.index ?? end;
  return `${text.slice(0, boundary).trimEnd()}…`;
}

/** One line: `text` unchanged when it fits, else shortened with an ellipsis. */
export function fitLine(text: string, width: LineFit): string {
  const budget = budgetOf(width);
  return lineFits(text, budget) ? text : cut(text, budget);
}

/** Up to `lines` lines that fit `width`, breaking at spaces; the last line ends in "…" when cut. */
export function wrapTitle(title: string, width: LineFit, lines: number): string[] {
  if (lines <= 0) return [];
  const budget = budgetOf(width);
  const { limit, advance } = budget;
  const space = advance(" ");
  const out: string[] = [];
  let current: string[] = [];
  let remaining = limit;
  for (const [word] of title.matchAll(/\S+/g)) {
    const available = current.length ? remaining - space : remaining;
    const after = remainingWidth(word, available, advance);
    if (after >= 0) {
      current.push(word);
      remaining = after;
      continue;
    }
    if (current.length && out.length === lines - 1) {
      const last = current.join(" ");
      out.push(last.endsWith("…") ? last : fitLine(`${last}…`, budget));
      return out;
    }
    if (current.length) out.push(current.join(" "));
    const fitted = fitLine(word, budget);
    current = [fitted];
    remaining = remainingWidth(fitted, limit, advance);
  }
  if (current.length) out.push(current.join(" "));
  return out;
}
