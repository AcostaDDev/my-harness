"""P002-T005 (D286): pure capability policy of typed domain operations.

- `classify` gives every change between a draft and its base, including relationship and order changes, a class
  (`owner_only`, `product`, `planning`) and a sensitivity, independent of the hashed D284 change summary.
- `evaluate` decides the capability requirements of one call: owner authority, or for agents exact unrevoked grants
  of the frozen snapshot within every ceiling layer (the four 0.1.9 `permission_authority` layers, frozen and current
  copies intersected, plus the role ceiling) and outside the owner-only exclusions. Prompts and arguments are never
  policy (TM01).
"""
from dataclasses import dataclass, field
from typing import Mapping

from my_harness.core.engine.domain_catalogue import digest
from my_harness.core.engine.permissions import LAYERS

POLICY_VERSION = 'domain-policy-1'
PREVIEW_FORMAT = 'knowledge-adoption-preview-1'
CLASSES = ('owner_only', 'product', 'planning')
ROLE_LAYER = 'role'
# Targets no grant, delegation tier or ruling can satisfy; later tasks add their owner-only targets (D273).
EXCLUDED = frozenset({('product', 'knowledge.adopt:owner_only')})
AGENT_PROVENANCES = ('inferred', 'unknown')


def group(kind: str, document: str | None) -> str:
    return f'section:{document}' if kind == 'section' else kind


def _label(member) -> str:
    return f'{member.document}/{member.code}' if member.kind == 'section' else member.code


def _owner(item_id: str, links) -> str | None:
    return next((l.target for l in links if l.kind == 'criterion_of' and l.source == item_id), None)


def classify(members: Mapping, links, previous: Mapping | None) -> list[dict]:
    """One entry per changed item or link, sorted; `previous` is the base's {'members', 'links'} or None."""
    old_members = previous['members'] if previous else {}
    old_links = previous['links'] if previous else ()
    new_items = set(members) - set(old_members)

    def with_new_task(criterion_id: str, owner: str | None) -> bool:
        return (criterion_id in new_items and owner is not None and owner in new_items
                and members[owner].kind == 'task')

    def item_class(member, criterion_owner=None) -> tuple[str, bool]:
        kind, document = member.kind, member.document
        if kind == 'requirement' or kind == 'phase' or kind == 'section' and document == 'instructions':
            return 'owner_only', True
        if kind == 'criterion':
            return ('planning', True) if with_new_task(member.item_id, criterion_owner) else ('owner_only', True)
        if kind == 'decision':
            return 'product', True
        if kind == 'section':
            return 'product', False
        return 'planning', False

    def link_class(link, endpoints) -> tuple[str, bool]:
        source, target = endpoints[link.source], endpoints[link.target]
        if link.kind == 'supersedes':
            return 'owner_only', True
        if link.kind == 'criterion_of':
            return ('planning', True) if with_new_task(link.source, link.target) else ('owner_only', True)
        if link.kind == 'addresses':
            return ('owner_only', True) if source.kind == 'phase' else ('planning', False)
        if link.kind == 'part_of' and source.kind == 'section':
            return ('owner_only', True) if source.document == 'instructions' else ('product', False)
        return 'planning', False

    entries = []

    def note(target_group, code, change, cls):
        entries.append({'group': target_group, 'code': code, 'change': change, 'class': cls[0],
                        'sensitive': cls[1]})
    for item_id, member in members.items():
        old = old_members.get(item_id)
        change = ('added' if old is None else 'changed' if old.version != member.version
                  else 'reordered' if old.root_position != member.root_position else None)
        if change:
            note(group(member.kind, member.document), _label(member), change,
                 item_class(member, _owner(item_id, links)))
    for item_id, old in old_members.items():
        if item_id not in members:
            note(group(old.kind, old.document), _label(old), 'removed', item_class(old, _owner(item_id, old_links)))
    current = {(l.kind, l.source, l.target): l for l in links}
    before = {(l.kind, l.source, l.target): l for l in old_links}
    endpoints = {**old_members, **members}
    for key, link in current.items():
        old = before.get(key)
        change = ('linked' if old is None else 'reordered' if old.position != link.position
                  else 'changed' if old.qualifier != link.qualifier else None)
        if change:
            note(f'link:{link.kind}', f'{_label(endpoints[link.source])}->{_label(endpoints[link.target])}', change,
                 link_class(link, endpoints))
    for key, link in before.items():
        if key not in current:
            note(f'link:{link.kind}', f'{_label(endpoints[link.source])}->{_label(endpoints[link.target])}',
                 'unlinked', link_class(link, endpoints))
    return sorted(entries, key=lambda e: (e['group'], e['code'], e['change']))


def classes(classification) -> list[str]:
    return sorted({entry['class'] for entry in classification})


def reason_required(classification) -> bool:
    return any(entry['sensitive'] for entry in classification)


def preview_sha256(project_id: str, draft_id: str, base_revision_id: str | None, base_sha256: str | None,
                   draft_sha256: str, changes: dict, classification: list) -> str:
    return digest({'format': PREVIEW_FORMAT, 'project': project_id, 'draft': draft_id, 'base': base_revision_id,
                   'base_sha256': base_sha256, 'draft_sha256': draft_sha256, 'changes': changes,
                   'classification': classification})


def request_sha256(entry, arguments: Mapping, origin: str | None) -> str:
    return digest({'operation': entry.id, 'version': entry.version, 'schema': entry.schema_sha256,
                   'arguments': arguments, 'origin': origin})


def provenance_allowed(principal: str, provenance: str, source) -> bool:
    """Agents cannot assert that content is known from a document (D284: no invented provenance)."""
    if principal != 'agent':
        return True
    return provenance in AGENT_PROVENANCES and (source is None or source.get('kind') == 'observation')


@dataclass(frozen=True)
class PermissionState:
    snapshot_sha256: str
    grants: tuple[tuple[str, str, str], ...]  # (grant_id, dimension, target) of the frozen snapshot
    unavailable: frozenset[str]  # grant ids revoked or expired now
    frozen_authority: Mapping[str, Mapping]  # permission_authority frozen with the invocation
    current_authority: Mapping[str, Mapping]  # the project's current permission_authority
    role_ceiling: Mapping[str, frozenset]  # dimension -> targets for the caller's role
    policy_version: str = POLICY_VERSION
    ceilings_sha256: str = field(init=False)

    def __post_init__(self):
        def plain(authority):
            return {layer: {kind: sorted(targets) for kind, targets in values.items()}
                    for layer, values in (authority or {}).items()}
        object.__setattr__(self, 'ceilings_sha256', digest({
            'frozen': plain(self.frozen_authority), 'current': plain(self.current_authority),
            'role': {kind: sorted(targets) for kind, targets in (self.role_ceiling or {}).items()}}))


@dataclass(frozen=True)
class Decision:
    allowed: bool
    code: str | None = None
    layer: str | None = None
    basis: Mapping = field(default_factory=dict)


def _contains(authority, layer: str, dimension: str, target: str) -> bool:
    return target in (authority or {}).get(layer, {}).get(dimension, ())


def evaluate(requirements, state: PermissionState | None) -> Decision:
    """Agent authority: every requirement outside the exclusions, granted exactly, and inside every layer."""
    if state is None:
        return Decision(False, 'capability_unavailable')
    used = []
    for dimension, target in requirements:
        if (dimension, target) in EXCLUDED:
            return Decision(False, 'owner_only_excluded')
        grant = next((g for g in state.grants if g[1] == dimension and g[2] == target
                      and g[0] not in state.unavailable), None)
        if grant is None:
            return Decision(False, 'capability_denied')
        for layer in LAYERS:
            for copy, authority in (('frozen', state.frozen_authority), ('current', state.current_authority)):
                if not _contains(authority, layer, dimension, target):
                    return Decision(False, 'ceiling_excluded', f'{layer}:{copy}')
        if target not in (state.role_ceiling or {}).get(dimension, ()):
            return Decision(False, 'ceiling_excluded', ROLE_LAYER)
        used.append(grant[0])
    return Decision(True, basis={'authority': 'grants', 'snapshot_sha256': state.snapshot_sha256,
                                 'grants': sorted(set(used)), 'ceilings_sha256': state.ceilings_sha256,
                                 'policy_version': state.policy_version})
