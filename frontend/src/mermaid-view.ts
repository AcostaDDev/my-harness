// Mermaid diagrams of the viewer (H6.2 E3, D076): lazy loading, `securityLevel: "strict"` and isolated output.
// The generated SVG is shown as an <img> from a Blob: an image runs no scripts and loads no external resources,
// so neither an `%%{init}%%` directive nor a label with HTML can act on the page.
import { LocalizedError } from "./i18n.ts";

export const MERMAID_CONFIG = {
  startOnLoad: false,
  securityLevel: "strict",
  // Text SVG labels: no foreignObject or HTML inside the diagram.
  htmlLabels: false,
  flowchart: { htmlLabels: false },
  suppressErrorRendering: true,
  maxTextSize: 50_000,
  fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
  // Keys a document directive cannot change (the Mermaid ones and HTML labels).
  secure: ["secure", "securityLevel", "startOnLoad", "maxTextSize", "suppressErrorRendering", "maxEdges", "htmlLabels", "flowchart", "fontFamily"],
} as const;

type Mermaid = typeof import("mermaid")["default"];
let loader: Promise<Mermaid> | undefined;
let counter = 0;
// Mermaid shares global state: one diagram at a time.
let queue: Promise<unknown> = Promise.resolve();

export function prefersDark(): boolean {
  const theme = document.documentElement.getAttribute("data-theme");
  if (theme) return theme === "dark";
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

/** `blob:` URL of an SVG image of the diagram; the caller revokes it when it stops showing it. */
export function renderDiagram(source: string, dark: boolean): Promise<string> {
  const job = queue.then(async () => {
    const mermaid = await (loader ??= import("mermaid").then(module => module.default));
    mermaid.initialize({ ...MERMAID_CONFIG, theme: dark ? "dark" : "neutral", secure: [...MERMAID_CONFIG.secure] });
    const { svg } = await mermaid.render(`doc-mermaid-${++counter}`, source);
    // Intrinsic size from the viewBox: as an image, a 100 % width does not set the size.
    const parsed = new DOMParser().parseFromString(svg, "image/svg+xml");
    const root = parsed.documentElement;
    if (root.nodeName !== "svg") throw new LocalizedError("docs.mermaid.no_svg");
    const box = (root.getAttribute("viewBox") ?? "").split(/[\s,]+/).map(Number);
    if (box.length === 4 && box.every(Number.isFinite)) {
      root.setAttribute("width", String(Math.ceil(box[2])));
      root.setAttribute("height", String(Math.ceil(box[3])));
      root.removeAttribute("style");
    }
    const text = new XMLSerializer().serializeToString(root);
    return URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }));
  });
  queue = job.catch(() => undefined);
  return job;
}
