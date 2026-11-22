#!/usr/bin/env python3
"""Make a throwaway copy of the PR, merged onto the latest target branch.

full-test runs its checks in this copy, so the human's folder and branch
are never touched, and files git ignores (.env files, old builds,
installed packages) cannot make a check pass by accident.

  setup    make <folder>/pr (the PR merged onto the target branch, plus
           the human's uncommitted changes) and <folder>/base (the target
           branch as it is, to tell new failures from old ones)
  refresh  bring the human's latest uncommitted changes into <folder>/pr
  cleanup  remove both copies and the folder

Exit codes: 0 done, 1 the PR does not merge cleanly (a human decision),
2 could not start.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

STATE_FILE = "full-test.json"
GH_TIMEOUT_SECONDS = 30

# The merge in the copy is a throwaway commit, never pushed. Give it a
# name, and keep the human's signing and hooks out of it.
THROWAWAY_COMMIT_SETTINGS = [
    "-c", "user.name=full-test",
    "-c", "user.email=full-test@localhost",
    "-c", "commit.gpgsign=false",
    "-c", "core.hooksPath=/dev/null",
]


class StartError(Exception):
    """The run cannot start; the message says why."""


class MergeConflict(Exception):
    """The PR does not merge cleanly; the human must decide what to do."""

    def __init__(self, step, files):
        super().__init__(step)
        self.step = step
        self.files = files


def git(args, cwd, check=True):
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise StartError(f"git {' '.join(args)} failed: {message}")
    return result


def git_text(args, cwd):
    output = git(args, cwd).stdout
    return output.decode("utf-8", errors="replace").strip()


def find_repo_root(path):
    folder = Path(path).resolve()
    if not folder.is_dir():
        raise StartError(f"the folder does not exist: {path}")
    result = git(["rev-parse", "--show-toplevel"], folder, check=False)
    if result.returncode != 0:
        raise StartError(f"not inside a git repository: {path}")
    root = Path(result.stdout.decode("utf-8").strip())
    has_commit = git(["rev-parse", "--verify", "--quiet", "HEAD"], root, check=False)
    if has_commit.returncode != 0:
        raise StartError("the repository has no commits yet")
    return root


def target_from_open_pr(repo):
    """The base branch of this branch's open PR, if gh knows one."""
    if shutil.which("gh") is None:
        return None
    try:
        result = subprocess.run(
            ["gh", "pr", "view", "--json", "baseRefName", "--jq", ".baseRefName"],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=GH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    name = result.stdout.decode("utf-8").strip()
    if name == "":
        return None
    return name


def remote_default_branch(repo, remote):
    """The branch the remote's HEAD points to, like main or dev."""
    result = git(
        ["symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD"],
        repo,
        check=False,
    )
    if result.returncode != 0:
        return None
    name = result.stdout.decode("utf-8").strip()
    prefix = f"{remote}/"
    if name.startswith(prefix):
        return name[len(prefix):]
    return None


def detect_target(repo, remote):
    target = target_from_open_pr(repo)
    if target is not None:
        return target
    target = remote_default_branch(repo, remote)
    if target is not None:
        return target
    raise StartError(
        "cannot tell which branch this PR merges into. Pass --target <branch>"
    )


def ref_exists(repo, ref):
    result = git(["rev-parse", "--verify", "--quiet", ref], repo, check=False)
    return result.returncode == 0


def remote_exists(repo, remote):
    result = git(["remote", "get-url", remote], repo, check=False)
    return result.returncode == 0


def resolve_target_ref(repo, remote, target, fetch):
    """Fetch the target branch and return (ref to merge, notes for the human)."""
    notes = []
    if fetch and remote_exists(repo, remote):
        result = git(["fetch", "--quiet", remote, target], repo, check=False)
        if result.returncode != 0:
            notes.append(
                f"could not fetch {remote}/{target}; using the copy this "
                "machine already has, which may be out of date"
            )
    remote_ref = f"{remote}/{target}"
    if ref_exists(repo, f"refs/remotes/{remote_ref}"):
        return remote_ref, notes
    if ref_exists(repo, f"refs/heads/{target}"):
        notes.append(f"no {remote_ref} found; using the local branch {target}")
        return target, notes
    raise StartError(f"branch {target} was not found on {remote} or locally")


def make_folder(requested):
    if requested is None:
        return Path(tempfile.mkdtemp(prefix="full-test-")).resolve()
    folder = Path(requested).resolve()
    if folder.exists() and any(folder.iterdir()):
        raise StartError(f"the folder is not empty: {requested}")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def merge_target(copy, target_ref):
    args = [*THROWAWAY_COMMIT_SETTINGS, "merge", "--no-ff", "--no-edit", target_ref]
    result = git(args, copy, check=False)
    if result.returncode == 0:
        return
    files = conflicted_files(copy)
    if files:
        raise MergeConflict(f"merging {target_ref} into the PR", files)
    message = result.stderr.decode("utf-8", errors="replace").strip()
    raise StartError(f"git merge failed: {message}")


def conflicted_files(copy):
    output = git_text(["diff", "--name-only", "--diff-filter=U"], copy)
    return [name for name in output.splitlines() if name]


def uncommitted_tracked_files(repo):
    output = git_text(["diff", "HEAD", "--name-only", "--no-renames"], repo)
    return [name for name in output.splitlines() if name]


def untracked_files(repo):
    output = git(["ls-files", "--others", "--exclude-standard", "-z"], repo).stdout
    names = output.decode("utf-8", errors="replace").split("\0")
    # A name ending in "/" is a nested git repository; it is not copied.
    return [name for name in names if name and not name.endswith("/")]


def apply_pending(repo, copy):
    """Copy the human's uncommitted changes into the copy. Returns their paths."""
    patch = git(["diff", "HEAD", "--binary"], repo).stdout
    if patch.strip():
        result = subprocess.run(
            ["git", "apply", "--3way", "--whitespace=nowarn"],
            cwd=copy,
            input=patch,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            files = conflicted_files(copy)
            if not files:
                files = uncommitted_tracked_files(repo)
            raise MergeConflict("adding the uncommitted changes", files)

    untracked = untracked_files(repo)
    for name in untracked:
        copy_untracked_file(repo / name, copy / name, name)

    return sorted(uncommitted_tracked_files(repo) + untracked)


def copy_untracked_file(source, destination, name):
    if destination.exists() or destination.is_symlink():
        raise MergeConflict("adding the uncommitted new files", [name])
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination, follow_symlinks=False)


def save_state(folder, state):
    (folder / STATE_FILE).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def load_state(folder_text):
    folder = Path(folder_text).resolve()
    state_path = folder / STATE_FILE
    if not state_path.is_file():
        raise StartError(f"not a full-test folder (no {STATE_FILE}): {folder_text}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["folder"] = folder
    return state


def remove_copies(repo, folder):
    for name in ("pr", "base"):
        path = folder / name
        if path.exists():
            git(["worktree", "remove", "--force", str(path)], repo, check=False)
    if folder.exists():
        shutil.rmtree(folder)
    git(["worktree", "prune"], repo, check=False)


def print_pending(pending):
    if not pending:
        print("pending  none")
        return
    count = len(pending)
    print(f"pending  {count} uncommitted file(s) are in the pr copy; commit them before sending:")
    for name in pending:
        print(f"           {name}")


def print_conflict(error):
    print(f"conflict while {error.step}. The human must decide how to resolve:")
    for name in error.files:
        print(f"  {name}")


def setup(args):
    repo = find_repo_root(args.repo)
    target = args.target
    if target is None:
        target = detect_target(repo, args.remote)
    target_ref, notes = resolve_target_ref(repo, args.remote, target, not args.no_fetch)

    folder = make_folder(args.dir)
    pr = folder / "pr"
    base = folder / "base"
    try:
        git(["worktree", "add", "--quiet", "--detach", str(base), target_ref], repo)
        git(["worktree", "add", "--quiet", "--detach", str(pr), "HEAD"], repo)
        save_state(folder, {"repo": str(repo), "target": target_ref})
        merge_target(pr, target_ref)
        pending = apply_pending(repo, pr)
    except BaseException:
        remove_copies(repo, folder)
        raise

    print(f"target   {target_ref}")
    print(f"folder   {folder}")
    print(f"pr       {pr}  (this PR merged onto {target_ref})")
    print(f"base     {base}  ({target_ref} as it is)")
    print_pending(pending)
    for note in notes:
        print(f"note     {note}")
    return 0


def refresh(args):
    state = load_state(args.folder)
    repo = Path(state["repo"])
    pr = state["folder"] / "pr"
    # Start over from the human's latest commit, so new commits come in,
    # then merge the same target again.
    head = git_text(["rev-parse", "HEAD"], repo)
    git(["reset", "--quiet", "--hard", head], pr)
    # -fd without -x keeps ignored files, such as installed packages.
    git(["clean", "-fdq"], pr)
    merge_target(pr, state["target"])
    pending = apply_pending(repo, pr)
    print(f"pr       {pr}  (refreshed)")
    print_pending(pending)
    return 0


def cleanup(args):
    state = load_state(args.folder)
    remove_copies(Path(state["repo"]), state["folder"])
    print(f"removed  {state['folder']}")
    return 0


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Make a throwaway copy of the PR, merged onto the latest target branch."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    setup_parser = commands.add_parser("setup", help="make the pr and base copies")
    setup_parser.add_argument("--repo", default=".", help="the human's project folder")
    setup_parser.add_argument(
        "--target",
        help="the branch the PR merges into (default: the open PR's base, "
        "else the remote's default branch)",
    )
    setup_parser.add_argument("--remote", default="origin", help="the remote to fetch from")
    setup_parser.add_argument("--dir", help="where to make the copies (default: a new temp folder)")
    setup_parser.add_argument(
        "--no-fetch", action="store_true", help="use the target branch as it is on this machine"
    )

    refresh_parser = commands.add_parser("refresh", help="bring in the latest uncommitted changes")
    refresh_parser.add_argument("folder", help="the folder setup printed")

    cleanup_parser = commands.add_parser("cleanup", help="remove the copies")
    cleanup_parser.add_argument("folder", help="the folder setup printed")

    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    handlers = {"setup": setup, "refresh": refresh, "cleanup": cleanup}
    try:
        return handlers[args.command](args)
    except StartError as error:
        print(f"cannot start: {error}")
        return 2
    except MergeConflict as error:
        print_conflict(error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
