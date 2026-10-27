"""Git adapters H2.4: complete capture, per-task worktrees and idempotent commit.

Every command uses an explicit, minimal environment: no global/system
configuration, no hooks, no fsmonitor or automatic maintenance. Capture works
on temporary copies of the index and does not modify HEAD, the real index or files.
Only Git objects (blobs/trees) are written. There are no filters defined outside the
repository and no sandbox: a worktree separates work, it does not isolate security.
"""

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from my_harness.core.engine.commit import (
    CommitError, CommitIntent, CommitOutcome, CommitPlan, CommitUncertain, GIT_FORMAT, GitIdentity, _OBJECT_ID,
)
from my_harness.core.engine.context import ProjectContext
from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.evidence import ContentEvidence
from my_harness.i18n import tr

MAX_DIFF_BYTES = 4 * 1024 * 1024
_CONFIG = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.ignorecase=false", "-c", "core.quotePath=false",
           "-c", "core.excludesFile=/dev/null", "-c", "gc.auto=0", "-c", "maintenance.auto=false",
           "-c", "advice.detachedHead=false")


class GitError(RuntimeError):
    def __init__(self, message: str, *, argv: tuple[str, ...] = (), returncode: int | None = None,
                 stderr: str = ""):
        super().__init__(message)
        self.argv, self.returncode, self.stderr = argv, returncode, stderr


class EvidenceCaptureError(RuntimeError):
    """The content cannot be captured completely; the engine stops without judging."""


class Git:
    """Invokes the Git executable with a controlled environment; never uses a shell."""

    def __init__(self, cwd: Path, *, executable: str = "git", timeout: float = 120.0):
        self.cwd = Path(cwd)
        self.executable = executable
        self.timeout = timeout

    def _environment(self, extra: dict[str, str] | None) -> dict[str, str]:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ATTR_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
               "GIT_OPTIONAL_LOCKS": "0"}
        if os.environ.get("DEVELOPER_DIR"):
            env["DEVELOPER_DIR"] = os.environ["DEVELOPER_DIR"]
        env.update(extra or {})
        return env

    def _completed(self, args: tuple[str, ...], input: bytes | None,
                   env: dict[str, str] | None) -> tuple[tuple[str, ...], subprocess.CompletedProcess]:
        """Runs Git and captures its output; a launch failure or the timeout are GitError.

        D125: with an absolute path, `-C` instead of cwd and without closing descriptors, subprocess uses
        posix_spawn instead of fork (several times cheaper from a large process). Python
        descriptors are not inheritable (PEP 446) and SQLite opens with O_CLOEXEC, so the
        child receives the same as with close_fds. An inaccessible directory fails before launching Git,
        like subprocess's chdir: it never becomes a Git exit code.
        """
        argv = (self.executable, *_CONFIG, *args)
        environment = self._environment(env)
        executable = self.executable
        if not os.path.isabs(executable) and os.sep not in executable:
            executable = shutil.which(executable, path=environment["PATH"]) or executable
        try:
            if os.path.isabs(executable):
                if not (os.path.isdir(self.cwd) and os.access(self.cwd, os.X_OK)):
                    raise NotADirectoryError(f"cannot change to {self.cwd}")
                completed = subprocess.run((executable, "-C", str(self.cwd), *argv[1:]), input=input,
                                           capture_output=True, env=environment, close_fds=False,
                                           timeout=self.timeout, check=False)
            else:
                completed = subprocess.run(argv, cwd=self.cwd, input=input, capture_output=True,
                                           env=environment, timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitError(tr('git.git_could_not_run', command=args[0] if args else '', exc=exc), argv=argv) from exc
        return argv, completed

    def run(self, *args: str, input: bytes | None = None, env: dict[str, str] | None = None,
            ok: tuple[int, ...] = (0,)) -> bytes:
        argv, completed = self._completed(args, input, env)
        if completed.returncode not in ok:
            stderr = completed.stderr.decode("utf-8", "replace").strip()
            raise GitError(tr('git.git_failed_exit', command=args[0] if args else '', returncode=completed.returncode,
                              stderr=stderr[:500]),
                           argv=argv, returncode=completed.returncode, stderr=stderr)
        return completed.stdout

    def code(self, *args: str, env: dict[str, str] | None = None) -> int:
        """Uninterpreted exit code; allows boolean questions (is-ancestor)."""
        return self._completed(args, None, env)[1].returncode

    def text(self, *args: str, input: bytes | None = None, env: dict[str, str] | None = None) -> str:
        try:
            return self.run(*args, input=input, env=env).decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise GitError(tr('git.git_produced_non_utf', command=args[0] if args else '')) from exc


def _split0(data: bytes) -> list[str]:
    try:
        return [item.decode("utf-8") for item in data.split(b"\0") if item]
    except UnicodeDecodeError as exc:
        raise EvidenceCaptureError(tr('git.non_utf_8_paths')) from exc


def _raw_entries(data: bytes) -> list[tuple[str, str, str, str]]:
    """`diff-tree --raw -z` without renames: (status, old mode, new mode, path)."""
    tokens = data.split(b"\0")
    entries, index = [], 0
    while index < len(tokens) and tokens[index]:
        meta = tokens[index].decode("ascii").lstrip(":").split(" ")
        try:
            path = tokens[index + 1].decode("utf-8")
        except (IndexError, UnicodeDecodeError) as exc:
            raise EvidenceCaptureError(tr('git.non_utf_8_malformed')) from exc
        entries.append((meta[4][0], meta[0], meta[1], path))
        index += 2
    return entries


def _exact_path(root: Path, path: str) -> bool:
    """The spelling of a Git path is exact, also on case-insensitive file systems."""
    parent = root
    for part in path.split('/'):
        if not parent.is_dir() or part not in {item.name for item in parent.iterdir()}:
            return False
        parent = parent / part
    return True


class GitWorkspace:
    """Complete Git capture and commit writer; can replace SyntheticWorkspace."""

    def __init__(self, identity: GitIdentity, *, max_diff_bytes: int = MAX_DIFF_BYTES,
                 executable: str = "git", timeout: float = 120.0):
        if not isinstance(identity, GitIdentity) or max_diff_bytes <= 0:
            raise ValueError("Explicit GitIdentity and positive diff limit required")
        self.identity = identity
        self.max_diff_bytes = max_diff_bytes
        self.executable = executable
        self.timeout = timeout
        self.marker_reader = None
        self.local_objects_only = False

    def _git(self, root: Path) -> Git:
        git_class = Git
        if self.local_objects_only:
            from my_harness.adapters.local_git import LocalGit
            git_class = LocalGit
        return git_class(root, executable=self.executable, timeout=self.timeout)

    def _require_root(self, git: Git, root: Path) -> None:
        try:
            top = Path(git.text("rev-parse", "--show-toplevel")).resolve()
        except GitError as exc:
            raise EvidenceCaptureError(tr('git.not_git_checkout', exc=exc)) from exc
        if top != root:
            raise EvidenceCaptureError(tr('git.project_root_top_level'))

    def _index_path(self, git: Git) -> Path:
        return Path(git.text("rev-parse", "--path-format=absolute", "--git-path", "index"))

    def _scratch_index(self, git: Git, target: Path, real: Path | None = None) -> dict[str, str]:
        """Copy of the real index; the user's index is never written."""
        real = real or self._index_path(git)
        env = {"GIT_INDEX_FILE": str(target)}
        if real.is_file():
            shutil.copy2(real, target)
        else:
            git.run("read-tree", "--empty", env=env)
        return env

    def _index_tree(self, git: Git) -> str:
        with tempfile.TemporaryDirectory(prefix="harness-git-") as scratch:
            env = self._scratch_index(git, Path(scratch) / "index")
            return git.text("write-tree", env=env)

    def capture(self, context: ProjectContext) -> ContentEvidence:
        root = context.root
        git = self._git(root)
        self._require_root(git, root)
        try:
            head = git.text("rev-parse", "--verify", "HEAD^{commit}")
            base_tree = git.text("rev-parse", "--verify", f"{head}^{{tree}}")
            ref = git.run("symbolic-ref", "-q", "HEAD", ok=(0, 1)).decode("utf-8").strip() or None
            with tempfile.TemporaryDirectory(prefix="harness-git-") as scratch:
                real_index = self._index_path(git)
                staged_env = self._scratch_index(git, Path(scratch) / "staged", real_index)
                work_env = self._scratch_index(git, Path(scratch) / "work", real_index)
                # An index with conflicts fails here: it is never resolved implicitly.
                index_tree = git.text("write-tree", env=staged_env)
                untracked = sorted(_split0(git.run("ls-files", "--others", "--exclude-standard", "-z",
                                                   env=staged_env)))
                paths = ["."]
                # D099: exclusion only while SQLite and the filesystem agree on a live activation.
                if self.marker_reader is not None:
                    from my_harness.core.managed_mode import MARKER_PATH
                    if self.marker_reader(root) is not None:
                        if git.run("ls-files", "--", MARKER_PATH).strip():
                            raise EvidenceCaptureError(tr('git.managed_marker_remain_untracked'))
                        if MARKER_PATH in untracked:
                            paths.append(":(exclude,literal)" + MARKER_PATH)
                            untracked.remove(MARKER_PATH)
                if untracked:
                    tracked = _split0(git.run('ls-files', '-z', env=work_env))
                    spellings = {path.lower() for path in untracked}
                    for path in tracked:
                        if path.lower() in spellings and path not in untracked and not _exact_path(root, path):
                            git.run('update-index', '--force-remove', '--', path, env=work_env)
                git.run("add", "-A", "--", *paths, env=work_env)
                worktree_tree = git.text("write-tree", env=work_env)
            diff_args = ("diff-tree", "-r", "--no-renames", "--no-ext-diff", "--no-textconv", "--no-color")
            raw = _raw_entries(git.run(*diff_args, "-z", "--raw", "--full-index", base_tree, worktree_tree))
            staged = _raw_entries(git.run(*diff_args, "-z", "--raw", "--full-index", base_tree, index_tree))
            patch = git.run(*diff_args, "-p", "--binary", "--full-index", base_tree, worktree_tree)
        except GitError as exc:
            raise EvidenceCaptureError(tr('git.git_evidence_could_not', exc=exc)) from exc
        if any("160000" in (old, new) for _, old, new, _ in raw + staged):
            raise EvidenceCaptureError(tr('git.submodule_gitlink_changes_not'))
        if len(patch) > self.max_diff_bytes:
            raise EvidenceCaptureError(tr('git.diff_exceeds_byte_review', max_diff_bytes=self.max_diff_bytes))
        changed = tuple(sorted({path for _, _, _, path in raw}))
        provenance = freeze({
            "format": GIT_FORMAT, "head_ref": ref, "base_tree": base_tree, "worktree_tree": worktree_tree,
            "index_tree": index_tree, "staged_paths": sorted({path for _, _, _, path in staged}),
            "untracked_paths": untracked, "deleted_paths": sorted(path for status, _, _, path in raw if status == "D"),
            "diff_sha256": hashlib.sha256(patch).hexdigest(), "diff_bytes": len(patch),
            "git_version": git.text("--version"),
        })
        fingerprint = hashlib.sha256(freeze({
            "format": GIT_FORMAT, "base_revision": head, "worktree_tree": worktree_tree,
            "index_tree": index_tree}).encode("utf-8")).hexdigest()
        return ContentEvidence(head, fingerprint, changed, patch.decode("utf-8", "replace"), provenance)

    # --- commit -----------------------------------------------------------------

    @staticmethod
    def _commit_text(tree: str, base: str, message: str, name: str, email: str, timestamp: int) -> bytes:
        who = f"{name} <{email}> {timestamp} +0000"
        return (f"tree {tree}\nparent {base}\nauthor {who}\ncommitter {who}\n\n{message}").encode("utf-8")

    def _tree_with(self, git: Git, tree: str, plan_updates) -> str:
        updates = sorted(plan_updates, key=lambda item: item.path)
        # A single tree listing (exact paths, no pathspec) for all modes.
        modes = {}
        for record in git.run("ls-tree", "-r", "-t", "-z", "--full-tree", tree).split(b"\0"):
            if record:
                header, _, path = record.partition(b"\t")
                modes[path.decode("utf-8", "surrogateescape")] = header.split(b" ", 1)[0].decode()
        for update in updates:
            if update.content is not None and modes.get(update.path, "100644") not in {"100644", "100755"}:
                raise CommitError(tr('git.mechanical_update_target_not'))
        with tempfile.TemporaryDirectory(prefix="harness-git-") as scratch:
            env = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
            git.run("read-tree", tree, env=env)
            # hash-object is still per path: `--path` applies each target's attributes.
            # Consecutive additions share one update-index (each --cacheinfo is applied in order
            # and fails as it would separately); deletions keep their position in the order.
            additions = []
            for update in updates:
                if update.content is None:
                    if additions:
                        git.run("update-index", "--add", *additions, env=env)
                        additions = []
                    git.run('update-index', '--force-remove', '--', update.path, env=env)
                    continue
                blob = git.text("hash-object", "-w", f"--path={update.path}", "--stdin",
                                input=update.bytes())
                additions += ["--cacheinfo", f"{modes.get(update.path, '100644')},{blob},{update.path}"]
            if additions:
                git.run("update-index", "--add", *additions, env=env)
            return git.text("write-tree", env=env)

    def seal(self, context: ProjectContext, plan: CommitPlan) -> tuple[str, str]:
        git = self._git(context.root)
        try:
            tree = self._tree_with(git, plan.reviewed_tree, plan.mechanical) if plan.mechanical else plan.reviewed_tree
            git.run("cat-file", "-e", f"{tree}^{{tree}}")
            text = self._commit_text(tree, plan.base_revision, plan.message, plan.author_name,
                                     plan.author_email, plan.committed_at)
            # Without -w: only computes the deterministic commit identifier.
            commit = git.text("hash-object", "-t", "commit", "--stdin", input=text)
        except GitError as exc:
            raise CommitError(tr('git.commit_could_not_sealed', exc=exc)) from exc
        return tree, commit

    def check_tree_diff(self, context, before, after):
        """Rejects a preview that the capture could not verify after writing it."""
        patch = self._git(context.root).run('diff-tree', '-r', '-p', '--binary', '--full-index',
            '--no-ext-diff', '--no-textconv', '--no-color', before, after)
        if len(patch) > self.max_diff_bytes:
            raise EvidenceCaptureError(tr('git.import_diff_exceeds_byte', max_diff_bytes=self.max_diff_bytes))

    def _write_mechanical(self, context: ProjectContext, intent: CommitIntent) -> None:
        # All targets are validated before writing any: no partial own state.
        targets = []
        for update in intent.mechanical:
            target = context.path(update.path)
            if target.exists() and (target.is_symlink() or not target.is_file()):
                raise CommitError(tr('git.mechanical_update_target_not'))
            targets.append((update, target))
        for update, target in targets:
            if update.content is None:
                target.unlink(missing_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            mode = target.stat().st_mode & 0o777 if target.exists() else 0o644
            temporary = target.with_name(f".{target.name}.{intent.operation_id}.tmp")
            temporary.write_bytes(update.bytes())
            os.chmod(temporary, mode)
            os.replace(temporary, target)

    def _reachable(self, git: Git, intent: CommitIntent, head: str) -> bool:
        if head == intent.expected_commit:
            return True
        if git.code("cat-file", "-e", f"{intent.expected_commit}^{{commit}}") != 0:
            return False
        code = git.code("merge-base", "--is-ancestor", intent.expected_commit, head)
        if code not in (0, 1):
            raise CommitUncertain(tr('git.ancestry_expected_commit_could'))
        return code == 0

    def _refresh_index(self, git: Git, intent: CommitIntent) -> str:
        current = self._index_tree(git)
        if current == intent.expected_tree:
            return "already_current"
        if current != intent.reviewed_index_tree:
            return "left_untouched"  # content staged after the review: not discarded
        git.run("read-tree", intent.expected_tree)
        git.run("update-index", "-q", "--refresh", ok=(0, 1))
        return "refreshed"

    def _reconciled(self, git: Git, intent: CommitIntent, head: str, *, status: str) -> CommitOutcome:
        expected = self._commit_text(intent.expected_tree, intent.base_revision, intent.message,
                                     intent.author_name, intent.author_email, intent.committed_at)
        if git.run("cat-file", "commit", intent.expected_commit) != expected:
            raise CommitUncertain(tr('git.commit_object_expected_id'))
        return CommitOutcome(status, intent.operation_id, commit=intent.expected_commit,
                             tree=intent.expected_tree, head=head, index=self._refresh_index(git, intent))

    def inspect_bootstrap(self, context):
        from my_harness.adapters.bootstrap import inspect_target
        try:
            self._git(context.root).text('version')  # Git environment checked on read
            return inspect_target(context, self._git(context.root))
        except GitError as exc:
            raise ValueError(tr('git.bootstrap_git_environment_unavailable', exc=exc)) from exc

    def inspect_definition(self, context, *, texts=False):
        """H6.5: drafts, foreign and invalid files at the target of a v2 definition."""
        from my_harness.adapters.bootstrap import inspect_drafts
        try:
            self._git(context.root).text('version')
            return inspect_drafts(context, self._git(context.root), texts=texts)
        except GitError as exc:
            raise ValueError(tr('git.bootstrap_git_environment_unavailable', exc=exc)) from exc

    def write_draft(self, context, path, content, base_sha256):
        from my_harness.adapters.bootstrap import write_draft
        return write_draft(self, context, path, content, base_sha256)

    def seal_bootstrap(self, shown, operation_id, committed_at):
        from my_harness.adapters.bootstrap import seal
        return seal(self, shown, operation_id, committed_at)

    def execute_bootstrap(self, context, shown, intent):
        from my_harness.adapters.bootstrap import execute
        return execute(self, context, shown, intent)

    def execute(self, context: ProjectContext, intent: CommitIntent) -> CommitOutcome:
        git = self._git(context.root)
        self._require_root(git, context.root)
        text = self._commit_text(intent.expected_tree, intent.base_revision, intent.message,
                                 intent.author_name, intent.author_email, intent.committed_at)
        try:
            if git.text("hash-object", "-t", "commit", "--stdin", input=text) != intent.expected_commit:
                raise CommitError("Persisted commit intent is internally inconsistent")
            head = git.text("rev-parse", "--verify", "HEAD^{commit}")
            if self._reachable(git, intent, head):
                return self._reconciled(git, intent, head, status="reconciled")
            if head != intent.base_revision:
                if git.code("cat-file", "-e", f"{intent.expected_commit}^{{commit}}") == 0:
                    raise CommitUncertain(
                        tr('git.head_moved_expected_commit', base_revision=intent.base_revision, head=head))
                return CommitOutcome(
                    "invalidated", intent.operation_id, head=head,
                    diagnostic=tr('git.head_moved_no_commit', base=intent.base_revision, head=head,
                                  operation=intent.operation_id))
            observed = self.capture(context)
            tree = json.loads(observed.provenance_json)
            if observed.fingerprint != intent.reviewed_fingerprint:
                already = (intent.mechanical and tree["worktree_tree"] == intent.expected_tree
                           and tree["index_tree"] == intent.reviewed_index_tree)
                if not already:
                    return CommitOutcome(
                        "invalidated", intent.operation_id, head=head,
                        observed_fingerprint=observed.fingerprint,
                        diagnostic=tr('git.content_changed_review', reviewed=intent.reviewed_fingerprint,
                                      observed=observed.fingerprint))
            elif intent.mechanical:
                self._write_mechanical(context, intent)
                observed = self.capture(context)
                tree = json.loads(observed.provenance_json)
                if tree["worktree_tree"] != intent.expected_tree or tree["index_tree"] != intent.reviewed_index_tree:
                    return CommitOutcome(
                        "invalidated", intent.operation_id, head=head, observed_fingerprint=observed.fingerprint,
                        diagnostic=tr('git.mechanical_not_sealed'))
            if tree["worktree_tree"] != intent.expected_tree:
                raise CommitError(tr('git.verified_content_does_not'))
            written = git.text("hash-object", "-t", "commit", "-w", "--stdin", input=text)
            if written != intent.expected_commit:
                raise CommitError(tr('git.written_commit_id_differs'))
            update = ("update-ref", "-m", f"harness: commit {intent.operation_id}", "HEAD",
                      intent.expected_commit, intent.base_revision)
            try:
                git.run(*update)
            except GitError:
                # A failed CAS does not by itself prove what happened: observe again.
                head = git.text("rev-parse", "--verify", "HEAD^{commit}")
                if self._reachable(git, intent, head):
                    return self._reconciled(git, intent, head, status="reconciled")
                if head != intent.base_revision:
                    return CommitOutcome(
                        "invalidated", intent.operation_id, head=head,
                        diagnostic=tr('git.head_moved_before_record', head=head))
                raise
            return self._reconciled(git, intent, intent.expected_commit, status="committed")
        except GitError as exc:
            raise CommitUncertain(tr('git.git_state_could_not', exc=exc)) from exc

    def read_blob(self, context: ProjectContext, revision: str, path: str) -> bytes | None:
        """Bytes of a file at an exact revision; None if absent there. Reads only."""
        from my_harness.core.engine.context import relative_path
        relative_path(path)
        if not _OBJECT_ID.fullmatch(revision):
            raise ValueError("Expected a full Git object id")
        git = self._git(context.root)
        self._require_root(git, context.root)
        spec = f"{revision}:{path}"
        if git.code("cat-file", "-e", spec) != 0:
            return None
        if git.text("cat-file", "-t", spec) != "blob":
            raise ValueError(tr('git.not_regular_file', path=path, revision=revision))
        return git.run("cat-file", "blob", spec)

    def execute_documents(self, context: ProjectContext, intent: CommitIntent, documents: list[dict]) -> CommitOutcome:
        """H2.4 with recovery of a partial document write by old/new hashes.

        Never adopts external bytes. Even after a crash, the tree when completing the
        documents must be exactly the sealed tree and the index must remain intact.
        D072: a new document (phase file) has a null previous hash and must remain absent
        or already contain its sealed bytes.
        """
        git = self._git(context.root)
        head = git.text("rev-parse", "--verify", "HEAD^{commit}")
        if self._reachable(git, intent, head):
            return self.execute(context, intent)
        if head != intent.base_revision:
            return self.execute(context, intent)
        for doc in documents:
            sha = self._document_sha(context, doc)
            if sha is False:
                return CommitOutcome('invalidated', intent.operation_id, diagnostic=tr('git.export_not_regular'))
            # `disk_sha256`: local bytes that the confirmed preview replaces (regenerated blocks, H6.2 E3).
            allowed = {doc['before_sha256'], doc['after_sha256']}
            if doc.get('disk_sha256') is not None:
                allowed.add(doc['disk_sha256'])
            if sha not in allowed:
                return CommitOutcome('invalidated', intent.operation_id,
                                     diagnostic=tr('git.export_changed_externally', path=doc['path']))
        observed = self.capture(context)
        provenance = json.loads(observed.provenance_json)
        plan = CommitPlan(intent.base_revision, provenance['worktree_tree'], intent.mechanical, intent.message,
                          intent.author_name, intent.author_email, intent.committed_at)
        tree, commit = self.seal(context, plan)
        if (tree != intent.expected_tree or commit != intent.expected_commit
                or provenance['index_tree'] != intent.reviewed_index_tree):
            return CommitOutcome('invalidated', intent.operation_id, diagnostic=tr('git.export_outside_blocks'))
        # Each replacement is atomic. After a crash between documents, only original or sealed
        # hashes are accepted; no other commit intent/identity is generated.
        for update in intent.mechanical:
            doc = next(d for d in documents if d['path'] == update.path)
            sha = self._document_sha(context, doc)
            if sha == doc['after_sha256']:
                continue
            allowed = {doc['before_sha256']}
            if doc.get('disk_sha256') is not None:
                allowed.add(doc['disk_sha256'])
            if sha is False or sha not in allowed:
                return CommitOutcome('invalidated', intent.operation_id, diagnostic=tr('git.export_document_changed'))
            self._write_mechanical(context, replace(intent, mechanical=(update,)))
        return self.execute(context, intent)

    execute_export = execute_documents  # D036: name kept

    @staticmethod
    def _document_sha(context: ProjectContext, doc: dict):
        """Hash of the document; None if missing (the CAS decides whether that is admitted); False if not regular."""
        target = context.path(doc['path'])
        if doc.get('exact_path') and not _exact_path(context.root, doc['path']):
            return None
        if not target.exists() and not target.is_symlink():
            return None
        if not target.is_file() or target.is_symlink():
            return False
        return hashlib.sha256(target.read_bytes()).hexdigest()

    # --- H3.3: phase gates and tag ------------------------------------------------

    def contains(self, context: ProjectContext, commit: str) -> bool:
        """Is the accepted commit reachable from HEAD? Reads only."""
        if not isinstance(commit, str) or not _OBJECT_ID.fullmatch(commit):
            raise ValueError("Expected a full Git object id")
        git = self._git(context.root)
        self._require_root(git, context.root)
        if git.code("cat-file", "-e", f"{commit}^{{commit}}") != 0:
            return False
        code = git.code("merge-base", "--is-ancestor", commit, "HEAD")
        if code not in (0, 1):
            raise EvidenceCaptureError(tr('git.ancestry_accepted_task_commit'))
        return code == 0

    @staticmethod
    def _tag_text(intent: dict) -> bytes:
        """Annotated tag object: message, identity and date fixed in the intent → deterministic id."""
        GitIdentity(intent["tagger_name"], intent["tagger_email"])  # no markup or line breaks
        if type(intent["tagged_at"]) is not int or not isinstance(intent["message"], str) or "\0" in intent["message"]:
            raise ValueError("Annotated tag intent requires an integer date and a NUL-free message")
        name = intent["ref"][len("refs/tags/"):]
        who = f"{intent['tagger_name']} <{intent['tagger_email']}> {intent['tagged_at']} +0000"
        return (f"object {intent['target']}\ntype commit\ntag {name}\ntagger {who}\n\n{intent['message']}").encode("utf-8")

    def _tag_git(self, context: ProjectContext, intent: dict) -> Git:
        ref, target = intent["ref"], intent["target"]
        if not ref.startswith("refs/tags/") or not _OBJECT_ID.fullmatch(target):
            raise ValueError("Phase tag intent must name refs/tags/<name> and a full commit id")
        if intent.get("kind", "lightweight") not in ("lightweight", "annotated"):
            raise ValueError("Unknown tag kind")
        git = self._git(context.root)
        self._require_root(git, context.root)
        if git.code("check-ref-format", ref) != 0:
            raise ValueError(tr('git.invalid_tag_name'))
        return git

    def seal_tag(self, context: ProjectContext, intent: dict) -> str:
        """Only computes the id of the annotated object (without -w); no effect before the intent."""
        git = self._tag_git(context, intent)
        try:
            git.run("cat-file", "-e", f"{intent['target']}^{{commit}}")
            return git.text("hash-object", "-t", "tag", "--stdin", input=self._tag_text(intent))
        except GitError as exc:
            raise CommitError(tr('git.phase_tag_could_not', exc=exc)) from exc

    def tag(self, context: ProjectContext, intent: dict) -> dict:
        """Deterministic lightweight or annotated tag: create only if absent (CAS); never move or overwrite."""
        git = self._tag_git(context, intent)
        ref, target = intent["ref"], intent["target"]
        annotated = intent.get("kind", "lightweight") == "annotated"
        # Expected value of the reference: the commit (lightweight) or the sealed tag object (annotated).
        expected = intent["object"] if annotated else target
        if annotated and not _OBJECT_ID.fullmatch(expected or ""):
            raise ValueError("Annotated tag intent requires its sealed object id")

        def observed():
            return git.run("rev-parse", "-q", "--verify", ref, ok=(0, 1)).decode("utf-8").strip() or None

        def outcome(status, **extra):
            return {"status": status, "ref": ref, "target": target, **extra}

        try:
            existing = observed()
            if existing == expected:
                return outcome("reconciled", **({"object": expected} if annotated else {}))
            if existing is not None:
                return outcome("conflict", observed=existing, diagnostic=(
                    tr('git.tag_points_elsewhere_annotated', ref=ref, existing=existing, expected=expected,
                       target=target) if annotated
                    else tr('git.tag_points_elsewhere', ref=ref, existing=existing, target=target)))
            if annotated:
                written = git.text("hash-object", "-t", "tag", "-w", "--stdin", input=self._tag_text(intent))
                if written != expected:
                    raise CommitError(tr('git.annotated_tag_object_differs'))
            try:
                git.run("update-ref", "-m", f"harness: close phase {intent['operation_id']}", ref, expected,
                        "0" * len(expected))
            except GitError:
                # A failed CAS does not prove what happened: observe again.
                if observed() == expected:
                    return outcome("reconciled", **({"object": expected} if annotated else {}))
                raise
            return outcome("created", **({"object": expected} if annotated else {}))
        except GitError as exc:
            raise CommitUncertain(tr('git.phase_tag_state_could', exc=exc)) from exc


@dataclass(frozen=True)
class WorktreeInfo:
    path: Path
    branch: str
    base_revision: str
    head: str
    created: bool


class GitWorktrees:
    """One worktree per task, kept between reviews; never cleaned or removed."""

    def __init__(self, *, executable: str = "git", timeout: float = 120.0):
        self.executable = executable
        self.timeout = timeout

    def _registered(self, git: Git) -> dict[Path, dict[str, str]]:
        found: dict[Path, dict[str, str]] = {}
        current: dict[str, str] | None = None
        for line in git.run("worktree", "list", "--porcelain", "-z").decode("utf-8").split("\0"):
            key, _, value = line.partition(" ")
            if key == "worktree":
                current = {}
                found[Path(value).resolve()] = current
            elif current is not None and key:
                current[key] = value
        return found

    def prepare(self, repository: Path, destination: Path, *, branch: str, base: str = "HEAD") -> WorktreeInfo:
        repository, destination = Path(repository).resolve(strict=True), Path(destination)
        git = Git(repository, executable=self.executable, timeout=self.timeout)
        if not destination.is_absolute() or not destination.parent.is_dir():
            raise GitError(tr('git.worktree_destination_absolute_existing'))
        destination = destination.parent.resolve() / destination.name
        if destination == repository or destination.is_relative_to(repository):
            raise GitError(tr('git.worktree_live_outside_checkout'))
        if branch.startswith("-") or base.startswith("-"):
            raise GitError(tr('git.branch_base_revision_not'))
        git.run("check-ref-format", "--branch", branch)
        base_sha = git.text("rev-parse", "--verify", f"{base}^{{commit}}")
        existing = self._registered(git).get(destination)
        if existing is not None:
            if existing.get("branch") != f"refs/heads/{branch}":
                raise GitError(tr('git.different_branch_already_checked'))
            head = existing["HEAD"]
            if git.code("merge-base", "--is-ancestor", base_sha, head) != 0:
                raise GitError(tr('git.existing_task_worktree_does'))
            return WorktreeInfo(destination, branch, base_sha, head, created=False)
        if destination.exists() or destination.is_symlink():
            raise GitError(tr('git.worktree_path_exists_not'))
        if git.code("show-ref", "--verify", "--quiet", f"refs/heads/{branch}") == 0:
            raise GitError(tr('git.task_branch_already_exists'))
        try:
            git.run("worktree", "add", "--quiet", "-b", branch, str(destination), base_sha)
        except GitError:
            # A race with another identical preparation is idempotent; any other failure propagates.
            raced = self._registered(git).get(destination)
            if raced is not None and raced.get("branch") == f"refs/heads/{branch}":
                return WorktreeInfo(destination, branch, base_sha, raced["HEAD"], created=False)
            raise
        return WorktreeInfo(destination, branch, base_sha, base_sha, created=True)
