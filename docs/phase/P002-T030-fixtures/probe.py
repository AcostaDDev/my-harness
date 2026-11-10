"""Disposable, offline D321 component probe for macOS. No harness or native agent."""
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(argv, cwd, env, data=None):
    return subprocess.run(argv, cwd=cwd, env=env, input=data, capture_output=True, check=False)


def git(cwd, env, *args, data=None):
    result = run(("/usr/bin/git", *args), cwd, env, data)
    result.check_returncode()
    return result.stdout.strip().decode()


def write(root, path, body):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)


def probe(area):
    host = area / "host"
    repo = host / "repo"
    guest = area / "projection"
    repo.mkdir(parents=True)
    guest.mkdir()
    env = {
        "PATH": "/usr/bin:/bin", "HOME": str(area), "LC_ALL": "C",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Synthetic", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Synthetic", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_AUTHOR_DATE": "2020-01-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2020-01-01T00:00:00+00:00",
    }
    canary = b"Selected source.\nPrivate synthetic suffix.\n"
    build = b'printf "%s\\n" 7\n'
    test = b'test "$(/bin/sh ./app.sh)" = 7\n'
    write(repo, "docs/original.md", canary)
    write(repo, "nested/AGENTS.md", b"Synthetic nested instruction\n")
    write(repo, "copies/renamed.txt", canary)
    write(repo, "mixed.sh", b"# " + canary)
    write(host, "external.txt", canary)
    write(host, "retained.txt", canary)
    write(repo, "app.sh", build)
    write(repo, "test.sh", test)
    write(repo, "notes.md", b"Public build notes.\n")
    (repo / "alias").symlink_to("docs/original.md")
    os.link(repo / "docs/original.md", repo / "hardcopy")

    git(repo, env, "init", "-q", "-b", "main")
    git(repo, env, "add", "--all")
    git(repo, env, "commit", "-qm", "synthetic base")
    base = git(repo, env, "rev-parse", "HEAD")
    blob = git(repo, env, "rev-parse", "HEAD:docs/original.md")
    # Positive projection from a trusted, fixed inventory, copied as independent regular bytes.
    inputs = {"app.sh": build, "test.sh": test, "notes.md": b"Public build notes.\n"}
    for name, expected in inputs.items():
        path = repo / name
        assert stat.S_ISREG(path.lstat().st_mode) and path.stat().st_nlink == 1
        assert digest(path.read_bytes()) == digest(expected) != digest(canary)
        write(guest, name, expected)
    assert {path.name for path in guest.iterdir()} == set(inputs)
    print("PASS positive projection, including noncanonical Markdown")

    # This path-scoped OS denial tests one local primitive, outside the preferred guest design.
    policy = f'(version 1) (allow default) (deny file-read-data (subpath "{host}"))'
    sandbox = ("/usr/bin/sandbox-exec", "-p", policy)
    assert run(("/bin/cat", str(repo / "docs/original.md")), guest, env).stdout == canary
    for source in (
        repo / "docs/original.md", repo / "copies/renamed.txt", repo / "alias",
        repo / "hardcopy", repo / "mixed.sh", repo / "nested/AGENTS.md",
        host / "external.txt", host / "retained.txt",
    ):
        result = run((*sandbox, "/bin/sh", "-c", '/bin/cat "$1"', "probe", str(source)), guest, env)
        assert result.returncode != 0 and result.stdout == b"" and b"Operation not permitted" in result.stderr
    result = run((*sandbox, "/usr/bin/git", f"--git-dir={repo / '.git'}", "cat-file", "-p", blob),
                 guest, env)
    assert result.returncode != 0 and result.stdout == b""
    result = run(("/usr/bin/git", f"--git-dir={guest / '.git'}", "cat-file", "-p", blob), guest, env)
    assert result.returncode != 0 and result.stdout == b""
    print("PASS eight local direct-read denials and two Git object denials")

    capture = (host / "external.txt").read_bytes()
    start, length = 0, len(b"Selected source.")
    exposure = capture[start:start + length]
    receipt = ("fixture-source", digest(capture), start, length, digest(exposure))
    assert receipt[1] == digest(canary) and receipt[4] == digest(b"Selected source.")
    assert exposure != capture and len(exposure) == length
    print("PASS bounded synthetic source slice and receipt")

    for script in ("./app.sh", "./test.sh"):
        assert run((*sandbox, "/bin/sh", "-n", script), guest, env).returncode == 0
    assert run((*sandbox, "/bin/sh", "./test.sh"), guest, env).returncode == 0
    candidate = build + b"# reviewed code delta\n"
    write(guest, "app.sh", candidate)
    assert run((*sandbox, "/bin/sh", "./test.sh"), guest, env).returncode == 0
    print("PASS admitted syntax check, test and candidate retest")

    mechanical = b"# State\nSynthetic sealed document\n"
    approved = {"app.sh": candidate, "docs/STATE.md": mechanical}
    # Compare Git's worktree reference tree with a host staging path from exact input blobs.
    write(repo, "app.sh", approved["app.sh"])
    write(repo, "docs/STATE.md", mechanical)
    git(repo, env, "add", "--", *approved)
    expected_tree = git(repo, env, "write-tree")
    index_env = {**env, "GIT_INDEX_FILE": str(host / "candidate-index")}
    git(repo, index_env, "read-tree", base)
    for name, data in approved.items():
        oid = git(repo, index_env, "hash-object", "-w", "--stdin", data=data)
        git(repo, index_env, "update-index", "--add", "--cacheinfo", "100644", oid, name)
    tree = git(repo, index_env, "write-tree")
    assert tree == expected_tree
    commit = git(repo, env, "commit-tree", tree, "-p", base, data=b"sealed synthetic effect\n")
    git(repo, env, "update-ref", "refs/heads/main", commit, base)
    stale = run(("/usr/bin/git", "update-ref", "refs/heads/main", base, base), repo, env)
    assert stale.returncode != 0 and git(repo, env, "rev-parse", "HEAD") == commit
    assert git(repo, env, "rev-parse", "HEAD^") == base
    assert git(repo, env, "rev-parse", "HEAD^{tree}") == expected_tree
    assert git(repo, env, "rev-parse", "HEAD:docs/original.md") == blob
    print(f"PASS exact code+document Git tree {tree}; stale ref refused")


if __name__ == "__main__":
    if not Path("/usr/bin/sandbox-exec").is_file():
        raise SystemExit("Requires the local macOS sandbox-exec primitive")
    with tempfile.TemporaryDirectory(prefix="t030-") as tmp:
        probe(Path(tmp).resolve())
