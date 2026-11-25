"""Map tracker status names to six categories, with a confidence for each guess.

Input is a list of {"name": ..., "native": ...}, where native is the tracker's
own category when it has one (Jira statusCategory key, Linear state type,
GitHub open/closed). High-confidence guesses can be applied silently, medium
ones are shown, and low ones are asked.
"""

import re

NATIVE = {
    # Jira statusCategory keys
    "new": ("backlog", "ready"),
    "indeterminate": ("in_progress", "review", "testing"),
    "done": ("done",),
    # Linear state types
    "triage": ("backlog",),
    "backlog": ("backlog",),
    "unstarted": ("ready", "backlog"),
    "started": ("in_progress", "review", "testing"),
    "completed": ("done",),
    "canceled": ("done",),
    "cancelled": ("done",),
    # GitHub issues
    "open": ("backlog", "ready", "in_progress", "review", "testing"),
    "closed": ("done",),
}

LEXICON = {
    "backlog": ("backlog", "icebox", "triage", "new", "open", "idea", "proposed", "inbox", "later"),
    "ready": ("ready", "to do", "todo", "selected", "selected for development", "next", "up next", "planned",
              "ready for dev", "ready for development", "groomed", "refined", "committed"),
    "in_progress": ("in progress", "doing", "in development", "development", "started", "working", "wip",
                    "active", "implementing", "building"),
    "review": ("review", "code review", "in review", "pr", "peer review", "awaiting review", "pull request"),
    "testing": ("testing", "qa", "in qa", "test", "verification", "verify", "validation", "uat", "acceptance",
                "ready for qa", "staging"),
    "done": ("done", "closed", "complete", "completed", "resolved", "released", "shipped", "deployed", "fixed",
             "won't do", "wont do", "won't fix", "wontfix", "cancelled", "canceled", "duplicate", "rejected",
             "archived"),
}


def _norm(name):
    if not isinstance(name, str):
        return ""
    return re.sub(r"[\s_\-]+", " ", name.strip().lower())


def _lexicon(name):
    """(exact category or None, substring categories)."""
    n = _norm(name)
    exact = None
    partial = []
    for cat, words in LEXICON.items():
        if n in words:
            exact = exact or cat
        elif any(re.search(r"\b%s\b" % re.escape(w), n) for w in words):
            partial.append(cat)
    return exact, partial


def guess(name, native=None):
    """{"name", "category", "confidence", "why"}."""
    native_cats = NATIVE.get(_norm(native)) if native else None
    exact, partial = _lexicon(name)
    lex = [exact] if exact else partial
    if native_cats and len(native_cats) == 1:
        cat = native_cats[0]
        conf = "high" if (not lex or cat in lex) else "medium"
        return {"name": name, "category": cat, "confidence": conf, "why": "tracker category %s" % native}
    if native_cats and lex:
        both = [c for c in lex if c in native_cats]
        if both:
            return {"name": name, "category": both[0], "confidence": "high",
                    "why": "tracker category %s and the name" % native}
    if exact:
        return {"name": name, "category": exact, "confidence": "high" if not native_cats else "medium",
                "why": "the name"}
    if len(partial) == 1:
        return {"name": name, "category": partial[0], "confidence": "medium", "why": "part of the name"}
    if native_cats:
        return {"name": name, "category": native_cats[0], "confidence": "low",
                "why": "tracker category %s only" % native}
    return {"name": name, "category": partial[0] if partial else "backlog", "confidence": "low",
            "why": "no clear match"}


def map_statuses(items):
    out = []
    for item in items:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            continue
        out.append(guess(item["name"].strip(), item.get("native")))
    return out
