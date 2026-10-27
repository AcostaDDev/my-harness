"""Flow B: HEAD snapshot without running code or filters or querying the worktree.

Only rev-parse, ls-tree and cat-file without filters. Does not use status: it may launch the project's clean filters.
The inventory describes the given commit, even if the disk has changes; the confirmed onboarding must
check its base again. Does not read ignored local files, links, submodules or installed dependencies.
"""

from pathlib import Path

from my_harness.adapters.git import GitError
from my_harness.adapters.local_git import LocalGit as _InventoryGit, object_size
from my_harness.adapters.import_git import _blobs
from my_harness.core.tree import ImportInventoryError, TreeEntry
from my_harness.core.project_onboarding import (
    MAX_ENTRIES, MAX_ENTRY_BYTES, MAX_TOTAL_BYTES, OnboardingInventoryError, build_inventory, in_scope,
)
from my_harness.i18n import tr


def read_inventory(root: Path, *, executable: str = 'git') -> dict:
    root = Path(root).resolve()
    git = _InventoryGit(root, executable=executable)
    try:
        if Path(git.text('rev-parse', '--show-toplevel')).resolve() != root:
            raise OnboardingInventoryError(tr('onboarding.project_root_top_level'))
        head = git.text('rev-parse', '--verify', '--quiet', 'HEAD^{commit}')
        tree = git.text('rev-parse', '--verify', f'{head}^{{tree}}')
        # Use the sealed id, not HEAD again: a concurrent move of the reference does not mix commits.
        output = git.run('ls-tree', '-r', '-z', '-l', '--full-tree', tree)
        rows = []
        records = [record for record in output.split(b'\0') if record]
        if not records:
            raise OnboardingInventoryError(tr('onboarding.head_has_no_files'))
        if len(records) > MAX_ENTRIES:
            raise OnboardingInventoryError(tr('onboarding.more_tree_entries_inventory', max_entries=MAX_ENTRIES))
        for record in records:
            header, raw_path = record.split(b'\t', 1)
            mode, kind, obj, size = header.decode('ascii').split()
            path = raw_path.decode('utf-8')
            if in_scope(path):
                rows.append((mode, obj, object_size(size, kind, obj, path), path))
        readable = [row for row in rows if row[0] in ('100644', '100755')
                    and row[2] is not None and row[2] <= MAX_ENTRY_BYTES]
        if sum(row[2] for row in readable) > MAX_TOTAL_BYTES:
            raise OnboardingInventoryError(tr('onboarding.sources_exceed_bytes_inventory',
                                              max_total_bytes=MAX_TOTAL_BYTES))
        blobs = _blobs(git, sorted({row[1] for row in readable}))
        entries = []
        for mode, obj, size, path in rows:
            diagnostic = None
            if mode not in ('100644', '100755'):
                diagnostic = 'Symbolic link or submodule: not followed or read.'
            elif size is None or size > MAX_ENTRY_BYTES:
                diagnostic = f'Entry over {MAX_ENTRY_BYTES} bytes: not read.'
            entries.append(TreeEntry(path, mode, size, None if diagnostic else blobs[obj], diagnostic))
        return build_inventory(tuple(entries), head=head, tree=tree)
    except (GitError, ImportInventoryError, UnicodeError) as exc:
        raise OnboardingInventoryError(tr('onboarding.cannot_read_non_empty', exc=exc)) from exc
