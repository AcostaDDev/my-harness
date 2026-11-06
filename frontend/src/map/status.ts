// Status classes of the work map (T018 §5.1, D304). The class comes from the read projection (T020); the engine never
// maps persisted statuses itself. Colour is never the only signal: every class also has an icon and a text label.
import type { MessageKey } from "../i18n.ts";

export const STATUS_CLASSES = ["done", "progress", "waiting", "failed", "pending", "inactive", "unknown"] as const;
export type StatusClass = typeof STATUS_CLASSES[number];

export function isStatusClass(value: unknown): value is StatusClass {
  return typeof value === "string" && (STATUS_CLASSES as readonly string[]).includes(value);
}

/** Class to draw; anything outside the contract is drawn as `unknown`, never guessed. */
export function statusClassOf(value: unknown): StatusClass {
  return isStatusClass(value) ? value : "unknown";
}

export const STATUS_LABELS: Record<StatusClass, MessageKey> = {
  done: "map.status.done",
  progress: "map.status.progress",
  waiting: "map.status.waiting",
  failed: "map.status.failed",
  pending: "map.status.pending",
  inactive: "map.status.inactive",
  unknown: "map.status.unknown",
};

/**
 * Icon outlines per class in a 20×20 box (§5.1): check, static arrow, hand, cross, empty circle, dash, question mark.
 * Paths are traced by rough.js with a seed per class, so the same class always looks the same.
 */
export const STATUS_ICONS: Record<StatusClass, { kind: "path" | "circle"; d?: string }> = {
  done: { kind: "path", d: "M3 10.5 L8 15.5 L17 4.5" },
  progress: { kind: "path", d: "M3 10 L16 10 M11 5 L16 10 L11 15" },
  waiting: { kind: "path", d: "M6 18 L6 8 M6 9 L6 3.5 M9 9 L9 2.5 M12 9 L12 3 M15 10 L15 5 M6 18 L14 18 L16 12 L15 10" },
  failed: { kind: "path", d: "M4 4 L16 16 M16 4 L4 16" },
  pending: { kind: "circle" },
  inactive: { kind: "path", d: "M4 10 L16 10" },
  unknown: { kind: "path", d: "M6 7 C6 2 15 2 14 7.5 C13.5 10 10 10 10 13 M10 16.5 L10 17.5" },
};
