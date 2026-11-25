"""Read-only GitHub access through the gh CLI.

Only three subcommands are ever run: `issue view`, `issue list` and `pr list`.
Anything else is refused here, before a process starts. Arguments are a list,
never a shell string, and search text is reduced to plain words.
"""

import json
import re
import shutil
import subprocess

from . import repo, secrets

ALLOWED = (("issue", "view"), ("issue", "list"), ("pr", "list"))
GH_TIMEOUT = 30
_ISSUE_URL = re.compile(r"^https://github\.com/([\w.\-]+/[\w.\-]+)/issues/(\d{1,9})/?(?:[#?].*)?$")
# gh's own sign-in and host settings; nothing else from the environment reaches gh.
GH_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "GH_HOST", "GH_CONFIG_DIR", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY")
_SLUG = re.compile(r"^[\w.\-]+/[\w.\-]+$")


class GhError(Exception):
    pass


def available():
    return shutil.which("gh") is not None


def run(args, timeout=GH_TIMEOUT):
    """Run an allow-listed, read-only gh command and parse its JSON output."""
    if tuple(args[:2]) not in ALLOWED:
        raise GhError("leadsman only reads from GitHub; 'gh %s' is not allowed." % " ".join(args[:2]))
    if any(a in ("--web", "-w") for a in args):
        raise GhError("leadsman does not open a browser.")
    if not available():
        raise GhError("gh is not installed.")
    try:
        res = subprocess.run(["gh"] + list(args), env=repo.child_env(GH_ENV, GH_PROMPT_DISABLED="1",
                                                                     GH_NO_UPDATE_NOTIFIER="1", NO_COLOR="1"),
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True, timeout=timeout, errors="replace")
    except subprocess.TimeoutExpired:
        raise GhError("gh timed out.")
    except OSError as exc:
        raise GhError("gh could not start (%s)." % exc)
    if res.returncode != 0:
        raise GhError("gh failed: %s" % (res.stderr.strip().splitlines() or ["no message"])[-1][:300])
    try:
        return json.loads(res.stdout or "null")
    except ValueError:
        raise GhError("gh returned something that is not JSON.")


def parse_issue(ref, default_repo=None):
    """(repo or None, number) from '123', '#123', 'owner/repo#123' or an issue URL."""
    ref = (ref or "").strip()
    m = _ISSUE_URL.match(ref)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"^(?:([\w.\-]+/[\w.\-]+)#|#)?(\d{1,9})$", ref)
    if m:
        return m.group(1) or default_repo, m.group(2)
    raise GhError("Not a GitHub issue number or link: %r." % ref[:80])


def issue_view(ref, default_repo=None):
    slug, number = parse_issue(ref, default_repo)
    args = ["issue", "view", number, "--json", "number,title,body,state,stateReason,labels,url,comments,closedAt"]
    if slug:
        args += ["--repo", slug]
    return run(args)


def _key_like(word):
    """Long words, and words mixing letters and digits, may be keys or passwords; they never go into a search."""
    return len(word) > 40 or (len(word) >= 8 and re.search(r"[A-Za-z]", word) and re.search(r"[0-9]", word))


def search_words(text, limit=8):
    """Plain search words from free text: letters, digits, _ and -, no leading dash."""
    words = []
    # Judge whole tokens first: a key split at "/" or "+" would pass as harmless pieces.
    tokens = [t for t in (text or "").split() if not _key_like(t) and not (re.search(r"[/+=]", t)
                                                                           and re.search(r"[0-9]", t))]
    for w in re.findall(r"[A-Za-z0-9_\-]+", " ".join(tokens)):
        w = w.lstrip("-")
        if len(w) < 3 or _key_like(w):
            continue
        if w.lower() not in words:
            words.append(w.lower())
        if len(words) >= limit:
            break
    return " ".join(words)


def title_words(ticket_text, limit=8):
    """Search words from the ticket's title: its first non-empty line, without a leading '#'."""
    found = secrets.found_values(ticket_text)
    secrets.remember(secrets.found_values(ticket_text, everywhere=True))
    for line in (ticket_text or "").split("\n"):
        if line.strip():
            # Every value found anywhere in the ticket stays out of the search, short ones too.
            title = secrets.mask(secrets.hide(line.strip().lstrip("#"), found))
            title = re.sub(r"\[hidden: [^\]]*\]", " ", title)
            return search_words(title, limit=limit)
    return ""


def overlap(ticket_text, slug, limit=10):
    """Open and recently closed issues and PRs that match words from the ticket's title.

    The words come from the saved ticket file, so ticket text never passes through a shell command.
    """
    if not _SLUG.match(slug or ""):
        raise GhError("Not a GitHub repository: %r." % (slug or "")[:80])
    words = title_words(ticket_text)
    if not words:
        raise GhError("No search words left after cleaning the query.")
    issues = run(["issue", "list", "--repo", slug, "--state", "all", "--limit", str(limit),
                  "--search=%s" % words, "--json", "number,title,state,url,updatedAt"])
    prs = run(["pr", "list", "--repo", slug, "--state", "all", "--limit", str(limit),
               "--search=%s" % words, "--json", "number,title,state,url,updatedAt,isDraft"])
    return {"query": words, "issues": issues or [], "pull_requests": prs or []}
