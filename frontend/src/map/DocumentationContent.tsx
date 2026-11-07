// Read-only drawer content, loaded only when opened; shared protected Docs renderer and tree.
import { useEffect, useRef } from "react";
import { useI18n } from "../Language";
import { parse } from "../router.ts";
import type { S } from "../managed-api";
import { Alert, Empty, Loading, usePoll } from "../ui";
import { DocumentTree, RichMarkdown } from "../pages/Docs";
import { mapPaths } from "./api.ts";
import { initialDocument } from "./DocsDrawer";
import type { DocContext } from "./DocsDrawer";

export function DrawerContent({ project, archive, context, selected, anchor, choose, linkTo, checkoutProject }: {
  project: string; archive: boolean; context: DocContext; selected?: string; anchor?: string; checkoutProject?: string | null;
  choose: (path?: string, anchor?: string) => void; linkTo: (path?: string) => string;
}) {
  const { t } = useI18n();
  const read = usePoll<S["MapDocumentsRead"]>(mapPaths.documents(project), 0);
  const canonical = read.data?.source === "canonical";
  const checkoutId = checkoutProject === undefined ? project : checkoutProject;
  const legacy = !archive && !!checkoutId && read.data?.source === "checkout";
  const checkoutTree = usePoll<S["DocumentTreeRead"]>(legacy ? `/projects/${encodeURIComponent(checkoutId!)}/documents/tree` : null, 0);
  const tree = canonical ? read.data?.tree : legacy ? checkoutTree.data : undefined;
  const current = selected ?? initialDocument(tree?.files.map(file => file.path) ?? [], context);
  const error = read.error ?? checkoutTree.error;
  function internalHref(url: string) {
    const target = new URL(url, "http://local");
    const route = parse(target.pathname);
    if (route.name !== "docs" || (route.project !== project && route.project !== checkoutId)) return url;
    const href = new URL(linkTo(route.path), "http://local");
    if (target.hash) href.searchParams.set("doc_anchor", target.hash.slice(1));
    return `${href.pathname}${href.search}`;
  }
  function follow(url: string) {
    const target = new URL(url, "http://local");
    const route = parse(target.pathname);
    if (target.searchParams.has("doc")) choose(target.searchParams.get("doc") ?? undefined, target.searchParams.get("doc_anchor") ?? undefined);
    else if (route.name === "docs" && (route.project === project || route.project === checkoutId)) choose(route.path, target.hash.slice(1));
  }
  return <>
    {error && <Alert>{error}</Alert>}
    {read.data?.source === "unavailable" && <Empty title={t("map.docs.unavailable")} />}
    {current && (canonical || legacy) ? <DrawerDocument key={`${project}:${canonical}:${current}`} project={project} path={current} checkoutId={checkoutId ?? undefined}
      canonical={canonical} anchor={anchor} context={context} follow={follow} internalHref={internalHref} /> : !error && read.data?.source !== "unavailable" && <Loading />}
    {tree && <DocumentTree tree={tree} current={current} project={project} onNavigate={choose} linkTo={linkTo} />}
  </>;
}

/** Keyed by path: an earlier document can never appear while a new one is loading. */
function DrawerDocument({ project, path, canonical, anchor, context, follow, checkoutId, internalHref }: {
  project: string; path: string; canonical: boolean; anchor?: string; context: DocContext; follow: (url: string) => void; checkoutId?: string; internalHref: (url: string) => string;
}) {
  const { t } = useI18n();
  const content = usePoll<S["MapDocumentsRead"] | S["DocumentRead"]>(canonical ? mapPaths.documents(project, path)
    : `/projects/${encodeURIComponent(checkoutId!)}/documents/content?path=${encodeURIComponent(path)}`, 0);
  const text = content.data?.content;
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (text == null) return;
    const nodes = [...body.current?.querySelectorAll<HTMLElement>("[id]") ?? []];
    const code = (context.task ?? context.phase)?.toLowerCase();
    const target = anchor ? nodes.find(node => node.id === anchor)
      : code ? nodes.find(node => node.id === `doc-${code}` || node.id.startsWith(`doc-${code}-`)) : body.current;
    target?.scrollIntoView?.({ block: "nearest" });
    // A slow read never takes focus back from a user who has already returned to the map.
    if (body.current?.closest(".map-docs-drawer")?.contains(document.activeElement)) body.current.focus({ preventScroll: true });
  }, [text, anchor, context.task, context.phase]);
  return <div className="map-docs-content" tabIndex={-1} ref={body}>
    <p className="hint">{t(canonical ? "map.docs.canonical" : "map.docs.checkout")} {content.data && "revision_id" in content.data && <code>{content.data.revision_id}</code>}</p>
    <h3><code>{path}</code></h3>
    {content.error && <Alert>{content.error}</Alert>}
    {text != null ? <article className="doc-reader"><RichMarkdown source={text} path={path} project={canonical ? project : checkoutId}
      onNavigate={follow} checkoutImages={!canonical} internalHref={internalHref} /></article> : !content.error && <Loading />}
  </div>;
}
