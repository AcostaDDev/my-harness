import { managed, ManagedError } from "./managed-api";
import type { S } from "./managed-api";
import { LocalizedError } from "./i18n";

type Conversation = S["PlanningConversationRead"];
type Proposal = S["PlanningProposalRead"];
type Draft = S["PlanningDraftContentRead"];
export type DocumentReview = { proposal: Proposal; before: Draft | null; conflict: boolean };
export type ProposalBatchReview = { conversation: string; version: number; documents: DocumentReview[] };
export type ProposalBatchResult = { applied: string[]; remaining: string[]; unconfirmed?: string; error?: unknown };

export function applicableDocuments(conversation: Conversation): Proposal[] {
  if (conversation.created || !["definition", "onboarding"].includes(conversation.kind)
      || !conversation.actions.includes("edit_draft") || conversation.turns.some(t => t.status === "QUEUED")) return [];
  return conversation.proposals.filter(p => p.kind === "draft" && p.status === "PROPOSED" && p.path && p.actions.includes("apply"));
}

function checkConversation(current: Conversation, review: ProposalBatchReview) {
  const available = applicableDocuments(current);
  if (current.id !== review.conversation || current.version !== review.version || !review.documents.length
      || new Set(review.documents.map(d => d.proposal.id)).size !== review.documents.length
      || review.documents.some(({ proposal }) => !available.some(p => p.id === proposal.id
        && p.path === proposal.path && p.proposal_sha256 === proposal.proposal_sha256
        && p.content_sha256 === proposal.content_sha256 && p.content === proposal.content
        && p.base_sha256 === proposal.base_sha256))) throw new LocalizedError("planning.batch.stale");
}

async function readDraft(base: string, path: string): Promise<Draft | null> {
  try { return await managed<Draft>(`${base}/drafts/content?path=${encodeURIComponent(path)}`); }
  catch (error) { if (error instanceof ManagedError && error.status === 404) return null; throw error; }
}

/** Read-only review. Proposal identities and document bytes stay bound to this conversation version. */
export async function reviewDocumentProposals(base: string, conversation: Conversation): Promise<ProposalBatchReview> {
  const proposals = structuredClone(applicableDocuments(conversation));
  const review: ProposalBatchReview = { conversation: conversation.id, version: conversation.version,
    documents: proposals.map(proposal => ({ proposal, before: null, conflict: false })) };
  checkConversation(await managed<Conversation>(base), review);
  review.documents = await Promise.all(proposals.map(async proposal => {
    const before = await readDraft(base, proposal.path!);
    const hash = before?.sha256 ?? null;
    return { proposal, before, conflict: hash !== proposal.base_sha256 && hash !== proposal.content_sha256 };
  }));
  return review;
}

/** Existing per-document CAS calls, in order. No rollback, automatic replay or concurrent-version rebase. */
export async function applyReviewedDocuments(base: string, review: ProposalBatchReview,
  progress: (applied: string[]) => void = () => {}): Promise<ProposalBatchResult> {
  const applied: string[] = [];
  const paths = review.documents.map(d => d.proposal.path!);
  try {
    checkConversation(await managed<Conversation>(base), review);
    const current = await Promise.all(paths.map(path => readDraft(base, path)));
    if (review.documents.some((d, i) => d.conflict || (current[i]?.sha256 ?? null) !== (d.before?.sha256 ?? null)))
      throw new LocalizedError("planning.batch.stale");
  } catch (error) { return { applied, remaining: paths, error }; }
  let expected = review.version;
  for (let index = 0; index < review.documents.length; index++) {
    const { proposal } = review.documents[index];
    let current: Conversation;
    try {
      current = await managed<Conversation>(`${base}/proposals/${encodeURIComponent(proposal.id)}/apply`, {
        expected_version: expected, proposal_sha256: proposal.proposal_sha256, confirmed: true,
      } satisfies S["PlanningApplyCreate"]);
    } catch (error) { return { applied, remaining: paths.slice(index + 1), unconfirmed: proposal.path!, error }; }
    applied.push(proposal.path!);
    progress([...applied]);
    expected += 1;
    // A concurrent change may land between the write and the returned conversation read.
    if (current.version !== expected) return { applied, remaining: paths.slice(index + 1),
      error: new LocalizedError("planning.batch.stale") };
  }
  return { applied, remaining: [] };
}
