// The inspector's bottom sheet and the keyboard focus (P002-T022). On narrow screens a closed sheet hides its body,
// so narrowing the window while the focus is in that body would drop the focus. This keeps it: entering the narrow
// layout with the focus in the body, or just dropped from it, opens the sheet and focuses that control again.

/** Narrow screens show the inspector as a bottom sheet; equal to the `@media` rule of `.map-inspector` in styles.css. */
export const SHEET_MEDIA = "(max-width: 880px)";

type Focusable = {
  isConnected: boolean;
  focus(options?: FocusOptions): void;
  scrollIntoView(options?: ScrollIntoViewOptions): void;
  checkVisibility?(): boolean;
};
type Listener<E> = (event: E) => void;

export type SheetFocusDeps = {
  /** The sheet's media query (`matchMedia(SHEET_MEDIA)`). */
  query: { matches: boolean; addEventListener(type: "change", listener: () => void): void; removeEventListener(type: "change", listener: () => void): void };
  document: {
    activeElement: unknown;
    body: unknown;
    addEventListener(type: "focusin" | "focusout", listener: Listener<FocusEvent>): void;
    removeEventListener(type: "focusin" | "focusout", listener: Listener<FocusEvent>): void;
  };
  /** The sheet's body (may be absent while the view has none). */
  body: () => { contains(node: unknown): boolean; parentElement?: { addEventListener(type: "transitionend", listener: () => void, options: { once: true }): void } | null } | null | undefined;
  open: () => void;
  frame: (callback: () => void) => void;
};

/** Installs the listeners; returns their removal. */
export function keepSheetFocus({ query, document, body, open, frame }: SheetFocusDeps): () => void {
  // The last focused control of the body: the browser may drop that focus before the media change is reported.
  let last: Focusable | null = null;
  const inBody = (node: unknown): node is Focusable => !!node && !!body()?.contains(node);
  let generation = 0;
  const focusIn = (event: FocusEvent) => {
    generation++;
    last = inBody(event.target) ? event.target : null;
  };
  // Leaving a still visible control for nothing (a click on the page) forgets it; being hidden does not.
  const focusOut = (event: FocusEvent) => {
    const current: Focusable | null = last;
    if (current && (event.target as unknown) === current && !event.relatedTarget && current.checkVisibility?.() !== false) last = null;
  };
  const change = () => {
    const pending = ++generation;
    const panel = body();
    const active = document.activeElement;
    const element = inBody(active) ? active : last;
    // Never taken from a control outside the body: only kept in it, or restored when it was dropped.
    if (!query.matches || !panel || !element?.isConnected || !panel.contains(element)
        || (active !== element && active && active !== document.body)) return;
    open();
    const isCurrent = () => query.matches && body() === panel && element.isConnected && panel.contains(element);
    frame(() => {
      if (pending !== generation || !isCurrent()) return;
      const focused = document.activeElement;
      if (focused !== element) {
        if (last !== element || (focused && focused !== document.body) || element.checkVisibility?.() === false) return;
        element.focus({ preventScroll: true });
      }
      const restored = generation;
      const reveal = () => {
        if (restored === generation && isCurrent() && document.activeElement === element
            && element.checkVisibility?.() !== false) element.scrollIntoView({ block: "nearest" });
      };
      reveal();
      // Unless motion is reduced the sheet grows for 160 ms: the control is revealed again once it is open.
      panel.parentElement?.addEventListener("transitionend", reveal, { once: true });
    });
  };
  document.addEventListener("focusin", focusIn);
  document.addEventListener("focusout", focusOut);
  query.addEventListener("change", change);
  return () => {
    generation++;
    document.removeEventListener("focusin", focusIn);
    document.removeEventListener("focusout", focusOut);
    query.removeEventListener("change", change);
  };
}
