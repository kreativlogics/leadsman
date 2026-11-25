"""Repository access: safe paths and read-only git calls.

Every git call is an argument list (never a shell string), runs with a timeout,
and only reads. Paths that come from a ticket or from the model are resolved
with safe_path, which refuses anything outside the repository root, including
symlinks that point out of it.
"""

import os
import shutil
import subprocess

GIT_TIMEOUT = 10

# Child processes get only what they need to find their tools, config and locale; nothing else is passed on.
PASS_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "USER", "XDG_CONFIG_HOME")


def child_env(extra_names=(), **fixed):
    """A small environment for git and gh: the named keys that are set, plus fixed values."""
    env = {}
    for name in tuple(PASS_ENV) + tuple(extra_names):
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
    env.update(fixed)
    return env


def git_available():
    return shutil.which("git") is not None


def run_git(args, cwd, timeout=GIT_TIMEOUT):
    """Run a read-only git command. Returns (returncode, stdout). Never raises for git errors."""
    if not git_available():
        return 127, ""
    env = child_env(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    try:
        res = subprocess.run(["git", "--no-pager"] + list(args), cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True,
                             timeout=timeout, errors="replace")
    except (OSError, ValueError, subprocess.SubprocessError):
        return 128, ""
    return res.returncode, res.stdout


def repo_root(path):
    """The top folder of the git work tree that holds path, or None."""
    if not path or not os.path.isdir(path):
        return None
    code, out = run_git(["rev-parse", "--show-toplevel"], cwd=path)
    if code != 0 or not out.strip():
        return None
    return os.path.realpath(out.strip())


def encodable(text):
    """False for text a file system path cannot hold, such as a lone surrogate from JSON."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def safe_path(root, rel):
    """Resolve rel inside root. Returns (real_path, repo_relative) or None if it escapes or is unusable."""
    if not root or not isinstance(rel, str) or not rel or "\x00" in rel or len(rel) > 1024 or not encodable(rel):
        return None
    root_real = os.path.realpath(root)
    cleaned = rel.strip().replace("\\", "/")
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if os.path.isabs(cleaned):
        candidate = cleaned
    else:
        candidate = os.path.join(root_real, cleaned)
    real = os.path.realpath(candidate)
    if real != root_real and not real.startswith(root_real + os.sep):
        return None
    return real, os.path.relpath(real, root_real).replace(os.sep, "/")


def is_tracked(root, rel):
    """True when rel is a file git tracks in root (so not ignored, untracked or inside .git)."""
    if not rel or rel == ".git" or rel.startswith(".git/"):
        return False
    code, out = run_git(["ls-files", "--full-name", "-z", "--", ":(literal)" + rel], cwd=root)
    return code == 0 and rel in out.split("\x00")


def read_lines(real_path, max_bytes=2000000):
    """The file's lines (without newlines), or None if it can't be read as text."""
    try:
        if not os.path.isfile(real_path) or os.path.getsize(real_path) > max_bytes:
            return None
        # Split on "\n" only, as git and editors count lines; splitlines() also breaks on form feeds.
        with open(real_path, "r", encoding="utf-8", errors="replace", newline="") as fh:
            text = fh.read()
    except OSError:
        return None
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [ln[:-1] if ln.endswith("\r") else ln for ln in lines]


def unchanged_since_head(root, rel):
    """True when the file in the working tree matches HEAD, so a citation describes committed code."""
    code, _ = run_git(["diff", "--quiet", "HEAD", "--", ":(literal)" + rel], cwd=root)
    return code == 0


def read_window(real_path, first, last, keep, chunk=65536):
    """Lines first..last (1-based) of a file of any size, each cut to keep characters, read in chunks.

    Returns None if the file can't be read. Memory stays bounded by the window, however long the file or its lines.
    """
    lines, part, number = [], [], 1
    try:
        with open(real_path, "r", encoding="utf-8", errors="replace", newline="") as fh:
            while number <= last:
                block = fh.read(chunk)
                if not block:
                    if any(part) and first <= number:
                        lines.append("".join(part))
                    break
                pieces = block.split("\n")
                for i, piece in enumerate(pieces):
                    if first <= number <= last:
                        room = keep - sum(len(x) for x in part)
                        if room > 0:
                            part.append(piece[:room])
                    if i < len(pieces) - 1:
                        if first <= number <= last:
                            lines.append("".join(part))
                        part = []
                        number += 1
                        if number > last:
                            break
    except OSError:
        return None
    return lines
