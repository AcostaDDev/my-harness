// Answers to the reviewer's questions (OT002): one draft per question, prepared without calling a model and sent
// only by an explicit action as ONE planning message, so one turn. Pure functions without React; the Node tests
// drive them with synthetic conversations. The question set and its blocking rules stay the service's: an answer
// sent here closes nothing by itself (D075/D102).

/** `PlanningMessageCreate.text` limit. The service counts characters (code points), not UTF-16 units. */
export const MESSAGE_LIMIT = 20000;

export type Question = { id: string; text: string; blocking: boolean; deferred?: Record<string, unknown> | null };
export type TurnLike = { number: number; status: string; message: string; result?: Record<string, unknown> | null };

/**
 * A prepared answer, bound to the question it was written for (its text and the answered turn that asked it).
 * `sent` is the text of the last accepted submission that carried it; it is never resent automatically.
 */
export type Draft = { text: string; question: string; blocking: boolean; turn: number; selected: boolean; sent?: string };
export type Drafts = Record<string, Draft>;

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

/** Drafts live in this browser, isolated by project and conversation. */
export const draftsKey = (project: string, conversation: string) => `harness-planning-answers-v1:${project}:${conversation}`;

function isDraft(value: unknown): value is Draft {
  const d = value as Draft;
  return !!d && typeof d === "object" && typeof d.text === "string" && typeof d.question === "string"
    && typeof d.blocking === "boolean" && typeof d.turn === "number" && typeof d.selected === "boolean"
    && (d.sent === undefined || typeof d.sent === "string");
}

export function readDrafts(storage: Store | undefined, key: string): Drafts {
  try {
    const value = JSON.parse(storage?.getItem(key) ?? "null") as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter(([id, draft]) => /^[0-9a-f]{64}$/.test(id) && isDraft(draft)));
  } catch { return {}; }
}

export function writeDrafts(storage: Store | undefined, key: string, drafts: Drafts) {
  try {
    if (Object.keys(drafts).length) storage?.setItem(key, JSON.stringify(drafts));
    else storage?.removeItem(key);
  } catch { /* no storage: the drafts last while the page is open */ }
}

/** Characters as the service counts them. */
export const characters = (value: string) => [...value].length;

/** The answered turn whose questions are the current ones; null before the first answer. */
export function sourceTurn(turns: TurnLike[]): number | null {
  const answered = turns.filter(turn => turn.status === "ANSWERED").map(turn => turn.number);
  return answered.length ? Math.max(...answered) : null;
}

// A composed message names each question by a short, language-neutral marker of its id (hash of its text).
const MARK = /\[q:([0-9a-f]{12})\]/g;
export const mark = (id: string) => `[q:${id.slice(0, 12)}]`;
export const marked = (message: string) => new Set([...message.matchAll(MARK)].map(match => match[1]));

/** Where a current question stands with respect to answers already sent in turns. */
export type Standing = { kind: "open" } | { kind: "awaiting"; turn: number } | { kind: "unreviewed"; turn: number; status: string }
  | { kind: "asked_again"; turn: number };

export function standings(questions: Question[], turns: TurnLike[]): Record<string, Standing> {
  const latest = [...turns].sort((a, b) => b.number - a.number);
  return Object.fromEntries(questions.map(question => {
    const turn = latest.find(item => marked(item.message).has(question.id.slice(0, 12)));
    const value: Standing = !turn ? { kind: "open" }
      : turn.status === "QUEUED" ? { kind: "awaiting", turn: turn.number }
        : turn.status === "ANSWERED" ? { kind: "asked_again", turn: turn.number }
          : { kind: "unreviewed", turn: turn.number, status: turn.status };
    return [question.id, value];
  }));
}

function questionsOf(turn: TurnLike): { id?: unknown; text?: unknown }[] {
  const result = (turn.result as { result?: { questions?: unknown } } | null | undefined)?.result;
  return Array.isArray(result?.questions) ? result.questions as { id?: unknown; text?: unknown }[] : [];
}

/** Questions the reviewer stopped asking after an answered turn that carried an answer to them. Newest first. */
export function resolved(questions: Question[], turns: TurnLike[], limit = 8): { id: string; text: string; turn: number }[] {
  const current = new Set(questions.map(question => question.id.slice(0, 12)));
  const texts = new Map<string, string>();
  for (const turn of turns) for (const item of questionsOf(turn)) {
    if (typeof item.id === "string" && typeof item.text === "string") texts.set(item.id.slice(0, 12), item.text);
  }
  const found: { id: string; text: string; turn: number }[] = [];
  for (const turn of [...turns].sort((a, b) => b.number - a.number)) {
    if (turn.status !== "ANSWERED") continue;
    for (const id of marked(turn.message)) {
      if (!current.has(id) && !found.some(item => item.id === id)) found.push({ id, text: texts.get(id) ?? "", turn: turn.number });
    }
  }
  return found.slice(0, limit);
}

/**
 * Drafts after a conversation change: empty, unselected drafts and resolved answers whose text was sent unchanged
 * are dropped; anything else is kept, so nothing typed is lost because the question set moved.
 */
export function prune(drafts: Drafts, questions: Question[], turns: TurnLike[]): Drafts {
  const current = new Set(questions.map(question => question.id));
  const done = new Set(resolved(questions, turns, Number.MAX_SAFE_INTEGER).map(item => item.id));
  const kept = Object.entries(drafts).filter(([id, draft]) => {
    if (!draft.text.trim()) return current.has(id) && draft.selected;
    return !(done.has(id.slice(0, 12)) && draft.sent === draft.text);
  });
  return kept.length === Object.keys(drafts).length ? drafts : Object.fromEntries(kept);
}

/** Drafts written for questions that are no longer in the current set: shown for an explicit decision. */
export function orphans(drafts: Drafts, questions: Question[]): [string, Draft][] {
  const current = new Set(questions.map(question => question.id));
  return Object.entries(drafts).filter(([id, draft]) => !current.has(id) && !!draft.text.trim());
}

/** A current question's draft, empty when there is none, bound to the current source turn. */
export function draftFor(drafts: Drafts, question: Question, turn: number): Draft {
  return drafts[question.id] ?? { text: "", question: question.text, blocking: question.blocking, turn, selected: false };
}

export type Entry = { id: string; question: string; blocking: boolean; earlier: boolean; answer: string };
export type Labels = { intro: string; blocking: string; informative: string; earlier: string; answer: string; context: string };

/**
 * Entries of a submission, in the order shown: the chosen ids that have text and are not already waiting for
 * review. Earlier (orphan) answers follow the current questions and are labelled as such.
 */
export function entries(ids: string[], drafts: Drafts, questions: Question[], waiting: Set<string>): Entry[] {
  const current = new Map(questions.map(question => [question.id, question]));
  const order = [...questions.map(question => question.id), ...Object.keys(drafts).filter(id => !current.has(id))];
  return order.filter(id => ids.includes(id) && !waiting.has(id) && !!drafts[id]?.text.trim()).map(id => {
    const question = current.get(id);
    const draft = drafts[id];
    return { id, question: question?.text ?? draft.question, blocking: question?.blocking ?? draft.blocking, earlier: !question, answer: draft.text };
  });
}

/** The exact message sent as one turn: each question's marker, kind and text with its answer, then the context. */
export function compose(items: Entry[], context: string, labels: Labels): string {
  const parts = [labels.intro, ...items.map((item, index) => {
    const kind = item.earlier ? labels.earlier : item.blocking ? labels.blocking : labels.informative;
    return `${index + 1}. ${mark(item.id)} ${kind}: ${item.question.trim()}\n${labels.answer}:\n${item.answer.trim()}`;
  })];
  if (context.trim()) parts.push(`${labels.context}:\n${context.trim()}`);
  return parts.join("\n\n");
}

/** After an accepted submission: each carried answer records what was sent and leaves the batch. */
export function markSent(drafts: Drafts, ids: string[]): Drafts {
  return Object.fromEntries(Object.entries(drafts).map(([id, draft]) => [id, ids.includes(id) ? { ...draft, sent: draft.text, selected: false } : draft]));
}
