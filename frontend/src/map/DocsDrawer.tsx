// P002-T023 / Q4: read-only documentation beside the live map. URL-owned selection survives Back/Forward.
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useI18n } from "../Language";
import { navigate, usePath, useSearch } from "../navigation";
import { Alert, Loading, message } from "../ui";

export type DocContext = { level: number; phase?: string | null; task?: string | null };
/** Exact canonical paths first, then a stable lexical fallback. No inference from a checkout or agent text. */
export function initialDocument(paths: readonly string[], context: DocContext): string | undefined {
  const available = new Set(paths);
  const choices = context.task ? ["docs/NEXT_STEPS.md", "docs/ROADMAP.md"]
    : context.phase || context.level === 1 ? ["docs/ROADMAP.md", "docs/STATE.md"] : ["docs/SPECIFICATION.md"];
  return [...choices, "docs/SPECIFICATION.md", ...[...paths].sort()].find(path => available.has(path));
}
export function drawerHref(path: string, search: string, doc?: string, anchor?: string): string {
  const params = new URLSearchParams(search);
  if (doc === undefined) { params.delete("doc"); params.delete("doc_anchor"); }
  else { params.set("doc", doc); if (anchor) params.set("doc_anchor", anchor); else params.delete("doc_anchor"); }
  return `${path}${params.size ? `?${params}` : ""}`;
}

// Keep the existing documentation/Markdown chunk lazy: merely visiting a map does not download it.
let Documentation: typeof import("./DocumentationContent").DrawerContent | undefined;
export async function loadDocumentation() {
  const module = await import("./DocumentationContent");
  Documentation = module.DrawerContent;
  return Documentation;
}

export function MapWithDocs({ project, archive, context, children, checkoutProject }: {
  project: string; archive: boolean; context: DocContext; children: ReactNode; checkoutProject?: string | null;
}) {
  const { t } = useI18n();
  const path = usePath(), search = useSearch();
  const params = new URLSearchParams(search), selected = params.get("doc");
  const open = selected !== null;
  const [ready, setReady] = useState(() => !!Documentation);
  const [loadError, setLoadError] = useState<string>();
  useEffect(() => {
    if (!open) return;
    if (Documentation) { setReady(true); return; }
    setLoadError(undefined);
    let active = true;
    loadDocumentation().then(() => { if (active) setReady(true); }, error => { if (active) setLoadError(message(error)); });
    return () => { active = false; };
  }, [open]);
  const trigger = useRef<HTMLButtonElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open && !wasOpen.current) close.current?.focus();
    if (!open && wasOpen.current) trigger.current?.focus();
    wasOpen.current = open;
  }, [open]);
  const dismiss = () => navigate(drawerHref(path, search));
  return <div className={`map-docs-layout${open ? " map-docs-open" : ""}`}>
    <div className="map-docs-map">
      <button ref={trigger} type="button" className="button-quiet map-docs-trigger" aria-expanded={open}
        onClick={() => open ? dismiss() : navigate(drawerHref(path, search, ""))}>{t("map.docs.open")}</button>
      {children}
    </div>
    {open && <section className="map-docs-drawer" aria-label={t("map.docs.title")} onKeyDown={event => {
      if (event.key === "Escape") { event.stopPropagation(); dismiss(); }
    }}>
      <header className="map-docs-head"><h2>{t("map.docs.title")}</h2>
        <button ref={close} type="button" className="button-quiet" onClick={dismiss}>{t("common.close")}</button></header>
      {loadError && <Alert>{loadError}</Alert>}
      {ready && Documentation ? <Documentation key={project} project={project} archive={archive} context={context} checkoutProject={checkoutProject} selected={selected || undefined}
        anchor={params.get("doc_anchor") ?? undefined} choose={(doc, anchor) => navigate(drawerHref(path, search, doc ?? "", anchor))}
        linkTo={doc => drawerHref(path, search, doc ?? "")} /> : !loadError && <Loading />}
    </section>}
  </div>;
}
