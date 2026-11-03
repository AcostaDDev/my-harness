"""Correction budgets across all runs of a task and its owner-adopted replacement family."""
from sqlalchemy import select, func
from my_harness.storage.models import (
    KnowledgeProjectRow, KnowledgeRevisionRow, KnowledgeRevisionLinkRow, KnowledgeItemRow,
    ManagedRunRow, ManagedAttemptRow,
)


def family(session, root, task):
    project = session.scalar(select(KnowledgeProjectRow.id).where(KnowledgeProjectRow.root == root))
    if project is None:
        return [task]
    items = {row.id: row.code for row in session.scalars(select(KnowledgeItemRow).where(
        KnowledgeItemRow.project_id == project, KnowledgeItemRow.kind == 'task'))}
    edges = session.execute(select(KnowledgeRevisionLinkRow.source_item_id,
                                  KnowledgeRevisionLinkRow.target_item_id).join(
        KnowledgeRevisionRow, KnowledgeRevisionLinkRow.revision_id == KnowledgeRevisionRow.id).where(
        KnowledgeRevisionRow.project_id == project, KnowledgeRevisionRow.status == 'ACCEPTED',
        KnowledgeRevisionLinkRow.kind == 'replaces')).all()
    neighbours = {}
    for source, target in edges:
        neighbours.setdefault(items[source], set()).add(items[target])
        neighbours.setdefault(items[target], set()).add(items[source])
    found, pending = {task}, [task]
    while pending:
        for code in neighbours.get(pending.pop(), ()):
            if code not in found:
                found.add(code)
                pending.append(code)
    return sorted(found)


def budget(session, root, task, limit):
    # A task identity is a family even before the owner adopts a replacement link.
    codes = family(session, root, task)
    runs = list(session.scalars(select(ManagedRunRow).where(
        ManagedRunRow.root == root, ManagedRunRow.purpose == 'task', ManagedRunRow.task_id.in_(codes))))
    ceiling = min([limit, *[run.revision_limit for run in runs]])
    executions = session.scalar(select(func.count()).select_from(ManagedAttemptRow).where(
        ManagedAttemptRow.run_id.in_([run.id for run in runs]),
        func.json_extract(ManagedAttemptRow.request_json, '$.role') == 'executor'))
    return {'tasks': codes, 'executions': executions, 'revision_limit': ceiling}

