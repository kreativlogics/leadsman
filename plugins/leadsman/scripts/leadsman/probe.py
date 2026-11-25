"""Look up each reference the ticket names, with file:line evidence.

Searches are fixed-string (`git grep -F`) with the pattern passed after `-e`,
so ticket text can't become a regex, an option or a shell command.
"""

import re
import time

from . import repo, secrets

MAX_HITS = 8
SHOWN = 160
# A line is cut to this before masking: masking a huge line is slow, and a secret this far in is not shown anyway.
MASK_SPAN = 2000


def _shown(text, near=()):
    """The start of a line as shown in the output, with secrets masked before it is shortened.

    near: secret values found in the lines around it, so a value whose name is on another line is hidden too.
    """
    text = text.strip()
    masked = secrets.hide(secrets.mask(text[:MASK_SPAN]), near)
    if len(text) > MASK_SPAN:
        # The word at the cut may be part of a secret its pattern no longer matches; masking can shrink what comes
        # before it into view, so it is dropped.
        masked = re.sub(r"\S*$", "", masked)
    return masked[:SHOWN]


NEAR = 3


def _near_values(lines, number):
    """Secret values in the lines around line number (1-based), each cut as in _shown."""
    window = [text[:MASK_SPAN] for text in lines[max(0, number - 1 - NEAR):number + NEAR]]
    return secrets.found_values("\n".join(window))


def _hit_near(root, name, number, cache):
    """Secret values around a grep hit, or None when the file can't be read (so its line is not shown)."""
    if name not in cache:
        resolved = repo.safe_path(root, name)
        cache[name] = (resolved[0] if resolved else None, repo.read_lines(resolved[0]) if resolved else None)
    real, lines = cache[name]
    if lines is not None:
        return _near_values(lines, number)
    if real is None:
        return None
    # Too large to read whole: read only the lines around the hit.
    window = repo.read_window(real, max(1, number - NEAR), number + NEAR, MASK_SPAN)
    return None if window is None else secrets.found_values("\n".join(window))


UNREAD_LINE = "[hidden: line of a file that could not be checked for secrets]"
_PARAM = re.compile(r"\{[^}/]*\}|:[A-Za-z_]\w*|<[^>/]*>|\*")


def _pathspecs(exclude):
    specs = ["--", "."]
    for pattern in exclude or []:
        if isinstance(pattern, str) and pattern and "\x00" not in pattern:
            specs.append(":(exclude,glob)%s" % pattern.lstrip("/"))
    return specs


def grep(root, needle, exclude=None, limit=MAX_HITS):
    """Fixed-string search of tracked text files. Returns (hits, total); total is None when git failed."""
    if not needle or len(needle) < 2 or "\n" in needle:
        return [], 0
    # -z separates file, line and text with NUL, so a path containing ':' still parses.
    code, out = repo.run_git(["grep", "-z", "-n", "-I", "-F", "--no-color", "--full-name", "-e", needle]
                             + _pathspecs(exclude), cwd=root)
    if code not in (0, 1):
        return [], None
    hits = []
    total = 0
    key_files = None
    files = {}
    for name, number, text in _grep_records(out):
        total += 1
        if len(hits) < limit:
            if key_files is None:
                key_files = _key_files(root)
            if key_files is False or name in key_files:
                shown = KEY_LINE
            else:
                near = _hit_near(root, name, number, files)
                shown = UNREAD_LINE if near is None else _shown(text, near)
            hits.append({"file": name, "line": number, "text": shown})
    return hits, total


KEY_LINE = "[hidden: line of a file holding a private key]"


def _key_files(root):
    """Tracked files holding a private key header, or False when git failed (so every line is hidden)."""
    code, out = repo.run_git(["grep", "-z", "-l", "-I", "-E", "--full-name", "-e", "-----BEGIN [A-Z ]*PRIVATE KEY",
                              "--", "."], cwd=root)
    if code not in (0, 1):
        return False
    return set(x for x in out.split("\x00") if x)


def _grep_records(out):
    """(file, line, text) from `git grep -z -n` output: file NUL line NUL text newline.

    Read field by field: a file name may hold a newline, so the output cannot be split into lines first.
    """
    pos = 0
    while pos < len(out):
        name_end = out.find("\x00", pos)
        number_end = out.find("\x00", name_end + 1) if name_end >= 0 else -1
        if number_end < 0:
            return
        text_end = out.find("\n", number_end + 1)
        if text_end < 0:
            text_end = len(out)
        number = out[name_end + 1:number_end]
        if number.isdigit():
            yield out[pos:name_end], int(number), out[number_end + 1:text_end]
        pos = text_end + 1


def _tracked(root, rel):
    """True or False, or None when git itself failed (so the answer is unknown)."""
    code, out = repo.run_git(["ls-files", "--full-name", "--", ":(literal)" + rel], cwd=root)
    if code != 0:
        return None
    return bool(out.strip())


def _find_by_name(root, name, exclude=None):
    code, out = repo.run_git(["ls-files", "--full-name", "--", ":(glob)**/%s" % _glob_escape(name)]
                             + [":(exclude,glob)%s" % p.lstrip("/") for p in (exclude or []) if p], cwd=root)
    if code != 0:
        return []
    return [x for x in out.split("\n") if x][:MAX_HITS]


def _glob_escape(text):
    return re.sub(r"([*?\[\]])", r"[\1]", text)


def probe_path(root, ref, exclude=None):
    value = ref["value"]
    result = {"found": False, "evidence": [], "note": ""}
    resolved = repo.safe_path(root, value)
    if resolved is None:
        result["note"] = "outside the repository; not checked"
        return result
    real, rel = resolved
    tracked = _tracked(root, rel)
    if tracked is None:
        return {"found": None, "evidence": [], "note": "search failed; unverified"}
    if tracked:
        result["found"] = True
        lines = repo.read_lines(real)
        if lines and secrets.holds_private_key("\n".join(lines)):
            # The body of a key matches no pattern, so no line of such a file is shown.
            result["note"] = "file holds a private key; its lines are not shown"
            return result
        at = ref.get("at_line")
        if at:
            if lines is not None and 1 <= at <= len(lines):
                result["evidence"].append({"file": rel, "line": at, "text": _shown(lines[at - 1], _near_values(lines, at))})
            else:
                if lines is None:
                    result["note"] = "file exists but is too large or unreadable to check line %d" % at
                elif not lines:
                    result["note"] = "file exists but is empty, so it has no line %d" % at
                else:
                    result["note"] = "file exists but has %d lines, not %d" % (len(lines), at)
        else:
            result["evidence"].append({"file": rel, "line": 1, "text": (_shown(lines[0], _near_values(lines, 1)) if lines else "")})
        return result
    if "/" not in value.strip("/"):
        matches = _find_by_name(root, value.strip("/"), exclude)
        if matches:
            result["found"] = True
            result["note"] = "found by name"
            result["evidence"] = [{"file": m, "line": 1, "text": ""} for m in matches]
            return result
    result["note"] = "not a tracked file in this repository"
    return result


def _route_needle(value):
    pieces = [p for p in _PARAM.split(value) if p.strip("/")]
    if not pieces:
        return None
    return max(pieces, key=len).rstrip("/") or None


def probe_text(root, needle, exclude=None):
    hits, total = grep(root, needle, exclude)
    if total is None:
        return {"found": None, "count": 0, "evidence": [], "note": "search failed; unverified"}
    return {"found": total > 0, "count": total, "evidence": hits,
            "note": "" if total else "no match in tracked files"}


def _issue_pattern(value):
    """An extended regex for value as a whole reference: #12 must not match #123, ABC-1 not ABC-10."""
    escaped = re.sub(r"([.\\[\](){}*+?^$|])", r"\\\1", value)
    return "(^|[^0-9A-Za-z_])%s([^0-9A-Za-z_]|$)" % escaped


def probe_issue(root, value):
    code, out = repo.run_git(["log", "--all", "-n", "5", "--format=%h %as %s", "-E",
                              "--grep=%s" % _issue_pattern(value)], cwd=root)
    if code != 0:
        return {"found": None, "commits": [], "note": "search failed; unverified"}
    # Split on "\n" only: splitlines() also breaks on form feeds and other characters a commit subject can hold.
    commits = [secrets.mask(c)[:160] for c in out.split("\n") if c]
    return {"found": bool(commits), "commits": commits,
            "note": "commits mention it" if commits else "no commit mentions it"}


TIME_BUDGET = 60


def probe(root, refs, exclude=None, max_refs=40, budget=TIME_BUDGET):
    """Look up each reference. Without a repository, everything is unverified.

    The lookups share one time budget, so a huge history cannot push the command past the caller's timeout.
    """
    out = []
    deadline = time.monotonic() + budget
    for ref in refs[:max_refs]:
        item = dict(ref)
        if root and time.monotonic() > deadline:
            item.update({"checked": False, "note": "time budget used up; not checked"})
        elif not root:
            item.update({"checked": False, "note": "no git repository; not checked"})
        elif "[hidden:" in ref["value"]:
            item.update({"checked": False, "note": "contains a secret; not searched"})
        elif ref["kind"] == "path":
            item.update(probe_path(root, ref, exclude))
            item["checked"] = True
        elif ref["kind"] in ("symbol", "string"):
            item.update(probe_text(root, ref["value"], exclude))
            if not item["found"] and ref["kind"] == "symbol" and re.search(r"::|->|#|\.", ref["value"]):
                last = re.split(r"::|->|#|\.", ref["value"])[-1]
                if len(last) >= 3:
                    alt = probe_text(root, last, exclude)
                    if alt["found"]:
                        alt["note"] = "only the last part (%s) was found" % last
                        item.update(alt)
            item["checked"] = True
        elif ref["kind"] == "route":
            needle = _route_needle(ref["value"])
            if needle and len(needle) >= 3:
                item.update(probe_text(root, needle, exclude))
                item["searched_for"] = needle
                item["checked"] = True
            else:
                item.update({"checked": False, "note": "too short to search"})
        elif ref["kind"] == "issue":
            item.update(probe_issue(root, ref["value"]))
            item["checked"] = True
        else:
            item.update({"checked": False, "note": "links are not opened"})
        out.append(item)
    return out
