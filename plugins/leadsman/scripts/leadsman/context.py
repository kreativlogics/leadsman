"""What the checks can rely on here: git, the base branch and how fresh it is, and gh.

Nothing is fetched. Staleness is read from local refs and the age of FETCH_HEAD,
and a fetch command is suggested for the user to run.
"""

import os
import re
import shutil
import time

from . import repo

_GITHUB_REMOTE = re.compile(r"^(?:https://(?:[^@/\s]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)"
                            r"([\w.\-]+)/([\w.\-]+?)(?:\.git)?/?$")


def github_slug(remote_url):
    """owner/repo when the remote is on github.com, else None."""
    m = _GITHUB_REMOTE.match((remote_url or "").strip())
    return "%s/%s" % (m.group(1), m.group(2)) if m else None


# Branch names end up in a command shown to the user, so only plain names are used.
_PLAIN_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,200}$")


def _default_branch(root):
    code, out = repo.run_git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], cwd=root)
    if code == 0 and out.strip().startswith("origin/"):
        name = out.strip().split("/", 1)[1]
        if _PLAIN_BRANCH.match(name):
            return name
    # An odd or missing origin/HEAD falls back to the usual names, so the stale check still runs.
    for name in ("main", "master", "trunk", "develop"):
        code, _ = repo.run_git(["rev-parse", "--verify", "--quiet", "refs/remotes/origin/%s" % name], cwd=root)
        if code == 0:
            return name
    return None


def _git_file_mtime(root, name):
    code, out = repo.run_git(["rev-parse", "--git-path", name], cwd=root)
    if code != 0 or not out.strip():
        return None
    path = out.strip()
    if not os.path.isabs(path):
        path = os.path.join(root, path)
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _last_remote_update(root, default):
    """When the remote refs were last written: FETCH_HEAD after a fetch, the ref files after a clone.

    `git clone` writes no FETCH_HEAD, so a fresh clone is dated by its remote-tracking ref instead.
    """
    times = [t for t in (_git_file_mtime(root, "FETCH_HEAD"),
                         _git_file_mtime(root, "refs/remotes/origin/%s" % default) if default else None)
             if t is not None]
    if times:
        return max(times)
    return _git_file_mtime(root, "packed-refs") if default else None


def gather(project_dir, stale_days=7, now=None):
    now = now or time.time()
    info = {
        "git": repo.git_available(),
        "repo_root": None,
        "branch": None,
        "head": None,
        "default_branch": None,
        "behind": None,
        "fetch_age_days": None,
        "stale": False,
        "stale_reason": None,
        "fetch_command": None,
        "gh": shutil.which("gh") is not None,
        "github_repo": None,
        "overlap_possible": False,
        "overlap_reason": None,
    }
    root = repo.repo_root(project_dir) if info["git"] else None
    info["repo_root"] = root
    if not root:
        info["overlap_reason"] = "no git repository here"
        return info
    code, out = repo.run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    info["branch"] = out.strip() if code == 0 else None
    code, out = repo.run_git(["rev-parse", "--short", "HEAD"], cwd=root)
    info["head"] = out.strip() if code == 0 else None
    default = _default_branch(root)
    info["default_branch"] = default
    if default and info["head"]:
        code, out = repo.run_git(["rev-list", "--count", "HEAD..refs/remotes/origin/%s" % default], cwd=root)
        if code == 0 and out.strip().isdigit():
            info["behind"] = int(out.strip())
    last_update = _last_remote_update(root, default)
    if last_update is not None:
        info["fetch_age_days"] = round((now - last_update) / 86400.0, 1)
    reasons = []
    if info["behind"]:
        reasons.append("HEAD is %d commit(s) behind origin/%s" % (info["behind"], default))
    if default and info["fetch_age_days"] is None:
        reasons.append("this clone has never been fetched")
    elif info["fetch_age_days"] is not None and info["fetch_age_days"] > stale_days:
        reasons.append("last fetch was %.0f days ago" % info["fetch_age_days"])
    if reasons:
        info["stale"] = True
        info["stale_reason"] = "; ".join(reasons)
        info["fetch_command"] = "git fetch origin %s" % default if default else "git fetch"
    code, out = repo.run_git(["remote", "get-url", "origin"], cwd=root)
    slug = github_slug(out) if code == 0 else None
    info["github_repo"] = slug
    if not info["gh"]:
        info["overlap_reason"] = "gh is not installed"
    elif not slug:
        info["overlap_reason"] = "the origin remote is not on github.com"
    else:
        info["overlap_possible"] = True
    return info
