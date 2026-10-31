// D170: presentation labels only; persisted codes and project content are unchanged.
import type { MessageKey, Translate } from "./i18n.ts";

const labels: Record<string, Record<string, MessageKey>> = {
  "kind": {
    "requirement": "knowledge.label.kind.requirement",
    "criterion": "knowledge.label.kind.criterion",
    "phase": "knowledge.label.kind.phase",
    "task": "knowledge.label.kind.task",
    "decision": "knowledge.label.kind.decision",
    "section": "knowledge.label.kind.section"
  },
  "document": {
    "specification": "knowledge.label.document.specification",
    "architecture": "knowledge.label.document.architecture",
    "data_model": "knowledge.label.document.data_model",
    "flows": "knowledge.label.document.flows",
    "instructions": "knowledge.label.document.instructions"
  },
  "relation": {
    "part_of": "knowledge.label.relation.part_of",
    "criterion_of": "knowledge.label.relation.criterion_of",
    "depends_on": "knowledge.label.relation.depends_on",
    "addresses": "knowledge.label.relation.addresses",
    "supersedes": "knowledge.label.relation.supersedes"
  },
  "qualifier": {
    "full": "knowledge.label.qualifier.full",
    "partial": "knowledge.label.qualifier.partial"
  },
  "format": {
    "markdown": "knowledge.label.format.markdown",
    "mermaid": "knowledge.label.format.mermaid"
  },
  "target": {
    "agents": "knowledge.label.target.agents",
    "claude": "knowledge.label.target.claude",
    "gemini": "knowledge.label.target.gemini"
  },
  "status": {
    "active": "knowledge.label.status.active",
    "retired": "knowledge.label.status.retired",
    "planned": "knowledge.label.status.planned",
    "withdrawn": "knowledge.label.status.withdrawn",
    "accepted": "knowledge.label.status.accepted",
    "rejected": "knowledge.label.status.rejected",
    "proposed": "knowledge.label.status.proposed",
    "DRAFT": "knowledge.label.status.DRAFT",
    "ACCEPTED": "knowledge.label.status.ACCEPTED",
    "DISCARDED": "knowledge.label.status.DISCARDED"
  },
  "provenance": {
    "known": "knowledge.label.provenance.known",
    "inferred": "knowledge.label.provenance.inferred",
    "unknown": "knowledge.label.provenance.unknown"
  },
  "origin": {
    "owner_confirmed": "knowledge.label.origin.owner_confirmed",
    "owner_delegated": "knowledge.label.origin.owner_delegated",
    "harness_deterministic": "knowledge.label.origin.harness_deterministic"
  },
  "change": {
    "added": "knowledge.label.change.added",
    "changed": "knowledge.label.change.changed",
    "removed": "knowledge.label.change.removed",
    "reordered": "knowledge.label.change.reordered",
    "linked": "knowledge.label.change.linked",
    "unlinked": "knowledge.label.change.unlinked"
  },
  "class": {
    "owner_only": "knowledge.label.class.owner_only",
    "product": "knowledge.label.class.product",
    "planning": "knowledge.label.class.planning"
  },
  "field": {
    "historical_status": "knowledge.label.field.historical_status",
    "kind": "knowledge.label.field.kind",
    "path": "knowledge.label.field.path",
    "heading": "knowledge.label.field.heading",
    "sha256": "knowledge.label.field.sha256",
    "reference": "knowledge.label.field.reference",
    "principal": "knowledge.label.field.principal",
    "channel": "knowledge.label.field.channel",
    "uid": "knowledge.label.field.uid",
    "user": "knowledge.label.field.user",
    "role": "knowledge.label.field.role",
    "thread_id": "knowledge.label.field.thread_id",
    "invocation_id": "knowledge.label.field.invocation_id",
    "title": "knowledge.field.title",
    "statement": "knowledge.field.statement",
    "objective": "knowledge.field.objective",
    "tag": "knowledge.field.tag",
    "problem": "knowledge.field.problem",
    "expected_result": "knowledge.field.expected_result",
    "evidence": "knowledge.field.evidence",
    "subtasks": "knowledge.field.subtasks",
    "context": "knowledge.field.context",
    "decision": "knowledge.field.decision",
    "alternatives": "knowledge.field.alternatives",
    "consequences": "knowledge.field.consequences",
    "body": "knowledge.field.body"
  }
};

export function knowledgeLabel(t: Translate, group: string, value: unknown): string {
  if (value == null || value === "") return "";
  const key = labels[group]?.[String(value)];
  return key ? t(key) : group === "field" ? t("knowledge.details") : String(value);
}
