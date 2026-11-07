// Owner requests over the map (T018 §§4, 5.3, D297, D302; P002-T022, TM13). A bubble carries T017 item identities
// only; this panel opens T017's own `InboxConversation`, which re-reads the item and applies nothing stale: its
// controls are the guarded T017 commands with their fresh confirmations, and a resolved or changed item shows its
// current state instead. When the projection lists no identities (L0 aggregates) or only the first ones
// (`items_truncated`), the element's items are read from T020's request list with the element's exact scope (phase,
// task, run, attempt) and, for a circle's own bubble, that circle, on every page: the count and the items shown are
// the same set, and attribution is T020's, never guessed from the kind of request. Executor and judge get no free
// composer: only T017's typed responses exist.
import { useEffect, useId, useRef, useState } from "react";
import { InboxConversation } from "../Inbox";
import { useI18n } from "../Language";
import type { MessageKey } from "../i18n.ts";
import type { S } from "../managed-api";
import { Link } from "../navigation";
import { Loading, message, Stale } from "../ui";
import { mapPaths } from "./api.ts";
import type { BubbleFilter, MapBubblesPage } from "./api.ts";
import type { ActorRole } from "./labels.ts";
import { useLevel } from "./use-level.ts";

type Bubbles = S["MapBubbles"];
type BubbleItem = S["MapBubbleItem"];

export type RequestsTarget = {
  /** T017 project identity of the element (the map's project key). */
  project: string;
  /** Code or name of the element, for the heading. */
  label: string;
  bubbles: Bubbles;
  /** Only this circle's requests (a circle's own bubble). */
  role?: ActorRole;
  /** Exact element scope of the request list (L0 aggregates: the whole project; a step: its run and attempt). */
  scope?: Omit<BubbleFilter, "circle">;
};

/** The listed identities, and whether they are complete (otherwise the element's list is read: absent or truncated). */
export function listedItems(bubbles: Bubbles, role?: ActorRole): { items: BubbleItem[]; complete: boolean } {
  const items = (bubbles.items ?? []).filter(item => item.kind !== "notification" && (!role || item.circle === role));
  const complete = Array.isArray(bubbles.items) && !bubbles.items_truncated;
  return { items, complete };
}

export function RequestsPanel({ target, canRespond, onClose, onChange }: {
  target: RequestsTarget; canRespond: boolean; onClose: () => void; onChange: () => void;
}) {
  const { t, n } = useI18n();
  const heading = useId();
  const { items, complete } = listedItems(target.bubbles, target.role);
  // A single listed request opens directly; otherwise the owner picks one.
  const [open, setOpen] = useState<string | undefined>(complete && items.length === 1 ? items[0].id : undefined);
  // Opening the panel (from a bubble or the inspector's button) moves the focus to its heading; nothing is trapped.
  const title = useRef<HTMLHeadingElement | null>(null);
  useEffect(() => { title.current?.focus?.({ preventScroll: true }); }, []);
  return <section className="map-requests" aria-labelledby={heading}>
    <div className="map-requests-head">
      <h2 id={heading} tabIndex={-1} ref={title}>{t("map.requests.title", { element: target.label })}</h2>
      <button type="button" className="button-quiet" onClick={open && !(complete && items.length === 1) ? () => setOpen(undefined) : onClose}>
        {open && !(complete && items.length === 1) ? t("map.requests.back") : t("map.requests.close")}</button>
    </div>
    {!canRespond && <p className="hint">{t("map.requests.read_only")}</p>}
    {open && <InboxConversation project={target.project} item={open} canRespond={canRespond} onChange={onChange} />}
    {/* The list stays mounted under an open conversation, so going back keeps its pages without reading them again. */}
    <div hidden={!!open}>
      <p>{n("map.node.requests", target.role ? target.bubbles.by_circle[target.role] ?? items.length : target.bubbles.total)}</p>
      {complete && items.length > 0 && <ul className="map-request-list">{items.map(item => <li key={item.id}>
        <button type="button" className="map-request-open" onClick={() => setOpen(item.id)}>{t(`inbox.topic.${item.topic}` as MessageKey)}</button>
        <Attribution item={item} />
      </li>)}</ul>}
      {!complete && <ElementRequests target={target} onOpen={setOpen} />}
      <p><Link to={{ name: "project-inbox", project: target.project }}>{t("map.requests.inbox")}</Link></p>
    </div>
  </section>;
}

function Attribution({ item }: { item: Pick<BubbleItem, "circle" | "attributed"> }) {
  const { t } = useI18n();
  return <>{" · "}<span className="map-circle-chip" aria-hidden="true">{item.circle}</span> {t(`map.actor.${item.circle}`)}
    {!item.attributed && <> · <span className="muted">{t("map.requests.not_attributed")}</span></>}</>;
}

/**
 * The element's open requests from T020's request list (50 per page, by item id), exact scope and circle on every
 * page; further pages on demand within the loader's window, and a superseded list rereads its first page.
 */
function ElementRequests({ target, onOpen }: { target: RequestsTarget; onOpen: (id: string) => void }) {
  const { t, n } = useI18n();
  const list = useLevel<MapBubblesPage>(mapPaths.bubbles(target.project, { ...target.scope, circle: target.role }));
  const { pages, error, loading, recovered, skipped } = list.state;
  if (!pages.length) return error ? <><Stale error={message(error)} />
    <button type="button" className="button-quiet" disabled={loading} onClick={list.reload}>{t("map.retry")}</button></> : <Loading />;
  const items = pages.flatMap(page => page.items);
  return <>
    {error !== undefined && <Stale error={message(error)} />}
    {recovered && <p role="status" className="state state-stale">{t("map.recovered")}</p>}
    {skipped > 0 && <p className="hint">{n("map.window.skipped", skipped)}{" "}
      <button type="button" className="button-quiet" disabled={loading} onClick={list.reload}>{t("map.window.start")}</button></p>}
    {items.length ? <ul className="map-request-list">{items.map(item => <li key={item.id}>
      <button type="button" className="map-request-open" onClick={() => onOpen(item.id)}>{t(`inbox.topic.${item.topic}` as MessageKey)}</button>
      <Attribution item={item} />{item.phase && <> · <code>{item.phase}</code></>}{item.task && <> · <code>{item.task}</code></>}
    </li>)}</ul> : <p className="muted">{t("map.requests.none_listed")}</p>}
    {list.canLoadMore && <button type="button" className="button-quiet" disabled={loading} onClick={list.loadMore}>{t("map.load_more")}</button>}
  </>;
}
