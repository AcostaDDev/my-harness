"""Projection of the D088 contract for the viewer, without altering snapshots or the adopted base."""

import stat

from my_harness.core.engine.documents import require_layout


def document_kind(target, path):
    if target.archived(path):
        return 'archive'
    if path in target.instructions:
        return 'instructions'
    if path == target.ddbb_diagram:
        return 'diagram'
    if path.startswith(target.flows_dir + '/'):
        return 'flow'
    if path.startswith(target.phase_dir + '/'):
        return 'phase_work'
    if path in target.phase_documents:
        return 'phase'
    return 'product' if path in target.product_documents else 'other'


def document_status(repository, context, git):
    target = require_layout(context)
    result = repository.status(context, git)
    # The instructions are not part of the phase's adopted hashes.
    for path in target.instructions:
        entry = dict(path=path, exists=False, sha256=None, adopted_sha256=None,
                     drift=False, blocks=[], error=None)
        try:
            document = repository.read(context, path)
            entry.update(exists=True, sha256=document['sha256'], blocks=document['blocks'])
        except LookupError:
            pass
        except (ValueError, OSError, UnicodeError) as error:
            entry['error'] = str(error)
        result['documents'].append(entry)
    for entry in result['documents']:
        entry['kind'] = document_kind(target, entry['path'])
    return result


def document_tree(repository, context):
    target = require_layout(context)
    result = repository.tree(context)
    for path in target.instructions:
        try:
            info = (context.root / path).lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode):
            result['skipped'].append(path)
        else:
            result['files'].append(dict(path=path, bytes=info.st_size, editable=True, archived=False))
    for entry in result['files']:
        entry['kind'] = document_kind(target, entry['path'])
    result['files'].sort(key=lambda entry: entry['path'])
    result['skipped'].sort()
    return result
