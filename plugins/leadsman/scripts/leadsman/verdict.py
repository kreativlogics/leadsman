"""Check the model's findings against the repository and decide what stands.

The model writes findings.json. This module:
- confirms every file:line it cites (inside the repo, file exists, line in
  range, quote on or near that line) and drops what it can't confirm;
- turns a code check without confirmed evidence into `unverified`;
- applies the decision rules (Duplicate and Close need a failed disproof);
- renders the report with secret values masked.
"""

import os
import re

from . import probe, repo
from . import secrets

CHECKS = ("valid", "reachable", "references", "clear", "testable", "safe", "size_overlap")
CODE_CHECKS = ("valid", "reachable", "references")
TEXT_CHECKS = ("clear", "testable", "safe")
STATUSES = ("pass", "warn", "fail", "unverified")
DECISIONS = ("ready", "fix", "ask", "duplicate", "close", "park")
DISPROOF = ("stands", "disproved", "not_run")
LABELS = {
    "ready": "Ready",
    "fix": "Fix then ready",
    "ask": "Ask",
    "duplicate": "Duplicate",
    "close": "Close",
    "park": "Park",
}
CHECK_TITLES = {
    "valid": "Still valid",
    "reachable": "Reachable",
    "references": "References true",
    "clear": "Clear",
    "testable": "Testable",
    "safe": "Safe",
    "size_overlap": "Size and overlap",
}
QUOTE_WINDOW = 2
MIN_QUOTE = 3
# A quote must be this long, or cover most of the line it is on, so a fragment such as "ret" proves nothing.
LONG_QUOTE = 12
LINE_SHARE = 0.6
READY_BLOCKERS = ("valid", "reachable", "references", "clear", "testable")
MAX_TEXT = 6000


class FindingsError(Exception):
    """The findings break a rule the model must fix (exit 3)."""

    def __init__(self, problems):
        Exception.__init__(self, "; ".join(problems))
        self.problems = problems


def _norm_space(text):
    return re.sub(r"\s+", " ", text or "").strip()


def confirm_evidence(root, item):
    """(confirmed item, None) or (None, reason)."""
    if not isinstance(item, dict):
        return None, "evidence is not an object"
    path = item.get("file")
    line = item.get("line")
    if not isinstance(path, str) or not path:
        return None, "evidence without a file"
    if not isinstance(line, int) or isinstance(line, bool) or line < 1:
        return None, "%s: no valid line number" % secrets.mask(path)[:120]
    resolved = repo.safe_path(root, path)
    if resolved is None:
        return None, "%s is outside the repository" % secrets.mask(path)[:120]
    real, rel = resolved
    # The path comes from the findings: masked here, as every reason is printed.
    shown = secrets.mask(rel)[:120]
    lines = repo.read_lines(real)
    if lines is None:
        return None, "%s does not exist or is not a text file" % shown
    if secrets.holds_private_key("\n".join(lines)):
        return None, "%s holds a private key; not used as evidence" % shown
    if not repo.is_tracked(root, rel):
        return None, "%s is not tracked by git (untracked, ignored or git's own files)" % shown
    if not repo.unchanged_since_head(root, rel):
        return None, "%s has uncommitted changes; cite committed code" % shown
    if line > len(lines):
        return None, "%s has %d lines, not %d" % (shown, len(lines), line)
    quote = item.get("quote")
    if not _strong_quote(quote):
        return None, "%s:%d: needs a quote of the cited code (at least %d letters or digits)" % (
            shown, line, MIN_QUOTE)
    # Lines are cut as in prepare's output, so a huge line cannot make the secret search slow; a quote past the cut is
    # not found.
    # The word at the cut is dropped, as in prepare: it may be part of a secret that no longer matches its pattern.
    window = [re.sub(r"\S*$", "", text[:probe.MASK_SPAN]) if len(text) > probe.MASK_SPAN else text
              for text in lines[max(0, line - 1 - QUOTE_WINDOW):line + QUOTE_WINDOW]]
    if not _quote_found(quote, window):
        return None, ("%s:%d: the quoted text is not there, or is a fragment (quote %d+ characters or most of the "
                      "line)" % (shown, line, LONG_QUOTE))
    # A quote of only a secret's value matches no pattern on its own: hide the values found in the cited lines.
    # Mask before cutting: a cut secret no longer matches its pattern and would print in part.
    near = secrets.found_values("\n".join(window))
    # Secret-shaped values in the cited lines are hidden in every field printed after this, not only in the quote.
    secrets.remember(secrets.found_values("\n".join(window), everywhere=True))
    out = {"file": rel, "line": line, "quote": secrets.mask(_hide_parts(secrets.hide(quote, near), near))[:200]}
    if isinstance(item.get("note"), str):
        out["note"] = secrets.mask(_hide_parts(secrets.hide(item["note"], near), near))[:300]
    return out, None


PART_MIN = 6


def _hide_parts(text, values):
    """text with every piece of PART_MIN+ characters of a found value hidden.

    A quote may cut a secret: the cut part matches no pattern and is not the whole value, so hide() alone misses it.
    The text is walked once per value, so the time grows with len(text) * len(value), not with len(value) squared.
    """
    spans = []
    for value in set(values or ()):
        if len(value) < PART_MIN:
            continue
        i = 0
        while i <= len(text) - PART_MIN:
            if text[i:i + PART_MIN] in value:
                j = i + PART_MIN
                while j < len(text) and text[i:j + 1] in value:
                    j += 1
                spans.append((i, j))
                i = j
            else:
                i += 1
    if not spans:
        return text
    spans.sort()
    out = []
    pos = 0
    for start, end in spans:
        if end <= pos:
            continue
        out.append(text[pos:max(pos, start)])
        if start >= pos:
            out.append("[hidden: secret]")
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _strong_quote(quote):
    """A quote with at least MIN_QUOTE letters or digits (underscores and punctuation do not count)."""
    return isinstance(quote, str) and len(re.sub(r"[\W_]", "", quote)) >= MIN_QUOTE


def _quote_found(quote, lines):
    """quote is in lines and is either long, or most of the one line it sits on."""
    q = _norm_space(quote)
    size = len(q.replace(" ", ""))
    if size >= LONG_QUOTE:
        return q in _norm_space(" ".join(lines))
    for text in lines:
        norm = _norm_space(text)
        if q in norm and size >= LINE_SHARE * len(norm.replace(" ", "")):
            return True
    return False


def _text(value, limit=MAX_TEXT):
    """Masked, then cut: a secret cut first would no longer match its pattern and print in part."""
    return secrets.mask(value)[:limit] if isinstance(value, str) else ""


def evaluate(findings, ctx, cfg_values, ticket_text=None):
    """Return the result dict, or raise FindingsError when the findings must be revised."""
    problems = []
    if not isinstance(findings, dict):
        raise FindingsError(["findings must be a JSON object"])
    root = ctx.get("repo_root")
    evidence_level = cfg_values.get("evidence", "code")
    raw_checks = findings.get("checks")
    if not isinstance(raw_checks, dict):
        raise FindingsError(["findings.checks must be an object with %s" % ", ".join(CHECKS)])
    missing = [c for c in CHECKS if c not in raw_checks]
    if missing:
        problems.append("checks missing: %s" % ", ".join(missing))
    unknown = [c for c in raw_checks if c not in CHECKS]
    if unknown:
        problems.append("unknown checks: %s" % ", ".join(sorted(unknown)))
    checks = {}
    claimed = {}
    dropped = []
    # All evidence is confirmed before any text field is masked, so a secret found in cited lines is hidden in every
    # summary and reason, including those of checks that come earlier.
    confirmed = {}
    for name in CHECKS:
        raw = raw_checks.get(name)
        evidence = raw.get("evidence") if isinstance(raw, dict) else None
        if root and isinstance(evidence, list):
            confirmed[name] = [confirm_evidence(root, ev) for ev in evidence[:20]]
    for name in CHECKS:
        raw = raw_checks.get(name) or {}
        if not isinstance(raw, dict):
            problems.append("checks.%s must be an object" % name)
            continue
        status = raw.get("status")
        if status not in STATUSES:
            problems.append("checks.%s.status must be one of %s" % (name, ", ".join(STATUSES)))
            continue
        claimed[name] = status
        item = {"status": status, "summary": _text(raw.get("summary"), 600),
                "reason": _text(raw.get("reason"), 600), "evidence": [], "downgraded": None}
        evidence = raw.get("evidence") or []
        if not isinstance(evidence, list):
            problems.append("checks.%s.evidence must be a list" % name)
            evidence = []
        if root:
            for ok, why in confirmed.get(name, []):
                if ok:
                    item["evidence"].append(ok)
                else:
                    dropped.append("%s: %s" % (CHECK_TITLES[name], why))
        needs_evidence = name in CODE_CHECKS or (evidence_level == "all" and name in TEXT_CHECKS)
        if status in ("pass", "fail", "warn") and evidence_level == "all" and name in TEXT_CHECKS:
            # Under evidence "all" a text check rests on the ticket's own words; a code line does not stand in.
            if not _has_ticket_quote(raw, ticket_text):
                item["status"] = "unverified"
                item["downgraded"] = "no ticket_quote found in the ticket"
        elif status in ("pass", "fail", "warn") and needs_evidence:
            if not root and not (name in TEXT_CHECKS and _has_ticket_quote(raw, ticket_text)):
                item["status"] = "unverified"
                item["downgraded"] = "no git repository, so this was not checked against code"
            elif not item["evidence"] and not (name in TEXT_CHECKS and _has_ticket_quote(raw, ticket_text)):
                item["status"] = "unverified"
                item["downgraded"] = "no confirmed file:line evidence"
        if status == "unverified" and not item["reason"] and not item["downgraded"]:
            problems.append("checks.%s is unverified but gives no reason" % name)
        checks[name] = item
    if problems:
        raise FindingsError(problems)

    decision = findings.get("decision")
    if decision not in DECISIONS:
        raise FindingsError(["decision must be one of %s" % ", ".join(DECISIONS)])
    rewrite = _text(findings.get("rewrite"))
    question = _text(findings.get("question"), 2000)
    reason = _text(findings.get("reason"), 2000)
    duplicate_of = _text(findings.get("duplicate_of"), 300)
    disproof = findings.get("disproof") or {}
    if not isinstance(disproof, dict):
        disproof = {}
    outcome = disproof.get("outcome", "not_run")
    if outcome not in DISPROOF:
        raise FindingsError(["disproof.outcome must be one of %s" % ", ".join(DISPROOF)])
    disproof_notes = _text(disproof.get("notes"), 2000)

    # The model's own "fail" blocks Ready even when missing evidence turned it into "unverified".
    blocking = [c for c in READY_BLOCKERS if claimed[c] == "fail"]
    if decision == "ready" and blocking:
        problems.append("decision is ready but these checks fail: %s. Choose fix, ask, close or park"
                        % ", ".join(blocking))
    unverified_code = [c for c in CODE_CHECKS if checks[c]["status"] == "unverified"]
    if decision == "ready" and root and unverified_code:
        problems.append("ready needs valid, reachable and references confirmed with file:line evidence; unverified: "
                        "%s. Add evidence or choose ask" % ", ".join(unverified_code))
    unverified_text = [c for c in TEXT_CHECKS if checks[c]["status"] == "unverified"]
    if decision == "ready" and evidence_level == "all" and unverified_text:
        problems.append("evidence is 'all', so ready needs clear, testable and safe verified; unverified: %s"
                        % ", ".join(unverified_text))
    if decision in ("duplicate", "close") and outcome == "stands" and not disproof_notes.strip():
        problems.append("disproof.notes must give the challenger's reply when the outcome is stands")
    # Fix means the work is real and only the text is wrong, so the work must be shown to be still valid.
    if decision == "fix" and claimed.get("valid") == "fail":
        problems.append("decision is fix but 'still valid' fails, so the work is not real. Choose close, ask or park")
    elif decision == "fix" and root and checks["valid"]["status"] == "unverified":
        problems.append("fix needs 'still valid' confirmed with file:line evidence. Add evidence or choose ask")
    if decision == "fix" and not rewrite.strip():
        problems.append("decision fix needs the rewritten ticket text in 'rewrite'")
    if decision == "ask" and not question.strip():
        problems.append("decision ask needs the drafted question in 'question'")
    if decision in ("park", "close", "duplicate") and not reason.strip():
        problems.append("decision %s needs a 'reason'" % decision)
    if decision == "duplicate" and not duplicate_of.strip():
        problems.append("decision duplicate needs 'duplicate_of' (the issue, PR or ticket it duplicates)")
    if problems:
        raise FindingsError(problems)

    final = decision
    fallback = None
    if decision in ("duplicate", "close"):
        if outcome != "stands":
            final = "ask"
            if outcome == "disproved":
                fallback = ("The %s verdict did not survive the disproof check, so this is a question instead."
                            % LABELS[decision])
            else:
                fallback = "No disproof check ran, so the %s verdict cannot stand." % LABELS[decision]
            if not question.strip():
                question = _fallback_question(decision, duplicate_of, reason, disproof_notes)
        elif (decision == "close" and checks["valid"]["status"] != "fail"
              and _status_category(findings, cfg_values, ticket_text) != "done"):
            final = "ask"
            fallback = "Close needs a failed 'still valid' check with confirmed evidence; it has none."
            if not question.strip():
                question = _fallback_question(decision, duplicate_of, reason, disproof_notes)

    capped = not root
    label = LABELS[final]
    if capped and final in ("ready", "fix"):
        label += " (not verified against code)"

    return {
        "decision": final,
        "proposed": decision,
        "label": label,
        "fallback": fallback,
        "capped": capped,
        "checks": checks,
        "dropped_evidence": dropped,
        "rewrite": rewrite if final == "fix" else "",
        "question": question if final == "ask" else "",
        "reason": reason,
        "duplicate_of": duplicate_of if final == "duplicate" else "",
        "disproof": {"outcome": outcome, "notes": disproof_notes},
        "status_category": _status_category(findings, cfg_values, ticket_text),
    }


def _has_ticket_quote(raw, ticket_text):
    """A text check can rest on a quote from the ticket, if the quote is really there."""
    quote = raw.get("ticket_quote")
    if not _strong_quote(quote) or not ticket_text:
        return False
    # Only the body counts: line 1 is the title and line 2 the status, which the findings also carry.
    return _quote_found(quote, ticket_text.split("\n")[2:])


def _status_category(findings, cfg_values, ticket_text=None):
    """The mapped category of the ticket's status, counted only when the status is written in the ticket file."""
    ticket = findings.get("ticket") if isinstance(findings.get("ticket"), dict) else {}
    status = ticket.get("status")
    if not isinstance(status, str) or not status.strip() or not ticket_text:
        return None
    header = _header_status_line(ticket_text)
    pattern = (r"(?i)\s*(?:status|state)\s*:\s*%s(?:\s+(?:completed|not_planned|duplicate|reopened))?\s*$"
               % re.escape(status.strip()))
    if not header or not re.match(pattern, header):
        return None
    wanted = status.strip().lower()
    for name, category in (cfg_values.get("status_map") or {}).items():
        if name.strip().lower() == wanted:
            return category
    return None


def _header_status_line(ticket_text):
    """Line 2, right after the title. `save ticket` and `issue` always put the status line there, so body text
    written by the ticket's author can never occupy it."""
    lines = ticket_text.split("\n")
    return lines[1] if len(lines) > 1 else None


def _fallback_question(decision, duplicate_of, reason, notes):
    if decision == "duplicate":
        text = "Is this the same work as %s, or is something here still needed?" % (duplicate_of or "the other item")
    else:
        text = "Is this still needed? %s" % (reason or "")
    if notes:
        text += " (What the check found: %s)" % notes
    return text.strip()


# Control characters other than newline and tab: a lone carriage return ends a Markdown line, and escape codes can
# redraw a terminal. Each becomes a space.
_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def _code(text):
    """A repository name, branch or path for an inline code span in a table cell.

    Git allows newlines, "|" and backticks in file names; any of them would end the span or the row and let a file
    name add lines to the report.
    """
    text = "".join(" " if ord(ch) < 32 or ord(ch) == 127 else ch for ch in secrets.mask(text or ""))
    return text.replace("`", "'").replace("|", "\\|")


def _cell(text):
    # Mask before escaping: an escaped "|" would stop a remembered secret from matching.
    return secrets.mask(text or "").replace("|", "\\|").replace("\n", " ").strip()


def render(result, ctx, findings, overlap_note=None, instruction_lines=None, ticket_text=None,
           rules_instruction_lines=None):
    """Markdown report. Every value passes through secrets.mask. The title comes from the saved ticket when given."""
    # A secret found anywhere in the ticket is hidden everywhere in the report: mask() hides remembered values.
    secrets.remember(secrets.found_values(ticket_text, everywhere=True))
    ticket = findings.get("ticket") if isinstance(findings.get("ticket"), dict) else {}
    saved_title = ticket_text.split("\n", 1)[0].lstrip("#").strip() if ticket_text else ""

    title = _cell(_text(saved_title or ticket.get("title"), 200)) or "Untitled ticket"
    source = _cell(_text(ticket.get("source"), 300))
    out = []
    out.append("# leadsman: %s" % result["label"])
    out.append("")
    out.append("**Ticket:** %s%s" % (title, " (%s)" % source if source else ""))
    if ctx.get("repo_root"):
        out.append("**Checked against:** `%s` at %s (branch `%s`)" % (
            _code(os.path.basename(ctx["repo_root"])), _code(ctx.get("head") or "?"),
            _code(ctx.get("branch") or "?")))
    out.append("")
    banners = []
    if result["capped"]:
        banners.append("No git repository here: the code checks were not run, so the verdict is capped.")
    if ctx.get("stale"):
        banners.append("The base may be stale (%s). Run `%s` and check again for a firmer answer."
                       % (ctx.get("stale_reason"), ctx.get("fetch_command")))
    if overlap_note:
        banners.append(overlap_note)
    if result["fallback"]:
        banners.append(result["fallback"])
    for b in banners:
        out.append("> %s" % b)
    if banners:
        out.append("")
    out.append("| Check | Result | Evidence |")
    out.append("|---|---|---|")
    for name in CHECKS:
        c = result["checks"][name]
        ev = ", ".join("`%s:%d`" % (_code(e["file"]), e["line"]) for e in c["evidence"][:6])
        note = c["summary"] or c["reason"]
        if c["downgraded"]:
            note = "%s (unverified: %s)" % (note, c["downgraded"]) if note else "unverified: %s" % c["downgraded"]
        elif c["status"] == "unverified" and c["reason"] and c["summary"]:
            note = "%s (unverified: %s)" % (c["summary"], c["reason"])
        out.append("| %s | %s | %s%s |" % (CHECK_TITLES[name], c["status"], _cell(note),
                                            (" " + ev) if ev else ""))
    out.append("")
    if result["decision"] == "fix":
        out.append("## Rewritten ticket")
        out.append("")
        out.append(_fenced(result["rewrite"]))
    elif result["decision"] == "ask":
        out.append("## Question to ask")
        out.append("")
        out.append(_fenced(result["question"]))
    elif result["decision"] == "duplicate":
        out.append("**Duplicate of:** %s" % _cell(result["duplicate_of"]))
    if result["decision"] in ("close", "park", "duplicate") and result["reason"]:
        out.append("**Why:** %s" % _cell(result["reason"]))
    if result["proposed"] in ("duplicate", "close"):
        out.append("")
        out.append("**Disproof check:** %s%s" % (result["disproof"]["outcome"].replace("_", " "),
                                                 (" - " + _cell(result["disproof"]["notes"]))
                                                 if result["disproof"]["notes"] else ""))
    if result["dropped_evidence"]:
        out.append("")
        out.append("**Evidence that could not be confirmed (left out):**")
        for d in result["dropped_evidence"][:20]:
            out.append("- %s" % _cell(d))
    for where, injected in (("the ticket", instruction_lines), ("the team rules", rules_instruction_lines)):
        if injected:
            out.append("")
            out.append("**Text in %s addressed to an AI (not followed):**" % where)
            for line in injected[:10]:
                if isinstance(line, dict):
                    out.append("- line %s: %s" % (line.get("line"), _cell(_text(line.get("text"), 200))))
    out.append("")
    out.append("_leadsman never writes to your tracker. Copy what you need._")
    return _CONTROL.sub(" ", secrets.mask("\n".join(out))) + "\n"


def _fenced(text):
    fence = "```"
    while fence in text:
        fence += "`"
    return "%s\n%s\n%s" % (fence, text.strip(), fence)
