"""Ticket intake: size limits, secret masking, reference extraction, instruction-shaped lines.

The ticket is data. Nothing here runs or follows it; the extracted references
are looked up later with fixed-string searches.
"""

import hashlib
import re

from . import secrets
from .patterns import INSTRUCTION_LIKE, NOT_ISSUE_PREFIXES

MAX_BYTES = 200000
MAX_LINE = 4000

CODE_EXT = (
    "py|js|jsx|ts|tsx|mjs|cjs|vue|svelte|rb|go|rs|java|kt|kts|scala|swift|m|mm|c|h|cc|cpp|hpp|cs|php|"
    "sql|sh|bash|zsh|ps1|yml|yaml|json|toml|ini|cfg|conf|env|xml|html|htm|css|scss|sass|less|md|rst|txt|"
    "graphql|gql|proto|tf|lock|gradle|dart|ex|exs|erl|clj|lua|pl|r|ipynb|csv"
)

_PATH = re.compile(r"(?<![\w@/.\-])((?:[\w.\-]+/)*[\w.\-]+\.(?:%s))(?::(\d{1,6}))?(?![\w/])" % CODE_EXT)
_DIR_PATH = re.compile(r"(?<![\w@:/.\-])((?:[\w.\-]+/){2,}[\w.\-]*)(?![\w])")
_BACKTICK = re.compile(r"`([^`\n]{2,120})`")
_URL = re.compile(r"\bhttps?://[^\s<>\"'`)\]]{3,300}")
_ROUTE = re.compile(r"(?<![\w.:/])(/(?:[\w\-{}:.]+/)*[\w\-{}:.]+/?)(?=[\s\"'`),.;]|$)")
_ISSUE = re.compile(r"(?<![\w/])((?:[\w.\-]+/[\w.\-]+)?#\d{1,7})\b|\b([A-Z][A-Z0-9]{1,9}-\d{1,7})\b")
_QUOTED = re.compile(r"[\"“]([^\"”\n]{6,120})[\"”]")
_CALL = re.compile(r"\b([A-Za-z_][\w]*(?:(?:::|\.|->)[A-Za-z_]\w*)+|[A-Za-z_]\w{2,}(?=\(\)))")
_CAMEL = re.compile(r"\b([a-z]+[A-Z]\w*|[A-Z][a-z0-9]+[A-Z]\w*)\b")
_SNAKE = re.compile(r"\b([a-z][a-z0-9]*_[a-z0-9_]+)\b")
_IDENT = re.compile(r"^[A-Za-z_][\w$]*(?:(?:::|\.|->|#)[A-Za-z_][\w$]*)*(?:\(\))?$")


_STOP_SYMBOLS = {
    "e.g", "i.e", "etc", "vs", "a.m", "p.m", "node.js", "vue.js", "next.js", "nuxt.js",
}


class IntakeError(Exception):
    pass


def _add(refs, seen, kind, value, line, extra=None):
    value = value.strip().strip(".,;:")
    if not value or len(value) > 300:
        return
    key = (kind, value)
    if key in seen:
        return
    seen.add(key)
    item = {"kind": kind, "value": value, "line": line}
    if extra:
        item.update(extra)
    refs.append(item)


def extract_refs(text, limit=200):
    """References the ticket names: paths, symbols, routes, urls, issues and quoted strings."""
    refs = []
    seen = set()
    for number, line in enumerate(text.split("\n"), 1):
        line = line[:MAX_LINE]
        urls = [m.group(0) for m in _URL.finditer(line)]
        for url in urls:
            _add(refs, seen, "url", url.rstrip(".,;:"), number)
        scrubbed = _URL.sub(" ", line)
        path_spans = []
        for m in _PATH.finditer(scrubbed):
            extra = {"at_line": int(m.group(2))} if m.group(2) else None
            _add(refs, seen, "path", m.group(1), number, extra)
            path_spans.append(m.span())
        for m in _DIR_PATH.finditer(scrubbed):
            if any(s <= m.start() < e for s, e in path_spans):
                continue
            _add(refs, seen, "path", m.group(1).rstrip("/"), number)
        for m in _ROUTE.finditer(scrubbed):
            if any(s <= m.start(1) < e for s, e in path_spans):
                continue
            value = m.group(1)
            if value.count("/") >= 1 and len(value) > 2 and not _PATH.fullmatch(value.lstrip("/")):
                _add(refs, seen, "route", value, number)
        for m in _ISSUE.finditer(scrubbed):
            if m.group(2) and m.group(2).split("-", 1)[0] in NOT_ISSUE_PREFIXES:
                continue
            _add(refs, seen, "issue", m.group(1) or m.group(2), number)
        for m in _BACKTICK.finditer(scrubbed):
            inner = m.group(1).strip()
            if _IDENT.match(inner) and inner.lower() not in _STOP_SYMBOLS:
                _add(refs, seen, "symbol", inner.rstrip("()"), number)
            elif not _PATH.fullmatch(inner):
                _add(refs, seen, "string", inner, number)
        for m in _QUOTED.finditer(scrubbed):
            _add(refs, seen, "string", m.group(1), number)
        for rx in (_CALL, _CAMEL, _SNAKE):
            for m in rx.finditer(scrubbed):
                value = m.group(1)
                if value.lower() in _STOP_SYMBOLS or _PATH.fullmatch(value):
                    continue
                if any(s <= m.start() < e for s, e in path_spans):
                    continue
                _add(refs, seen, "symbol", value, number)
        if len(refs) >= limit:
            break
    return refs[:limit]


def instruction_lines(text, limit=20):
    """Lines that read like instructions to an AI. They are reported to the user, never followed."""
    lines = []
    for number, line in enumerate(text.split("\n"), 1):
        if INSTRUCTION_LIKE.search(line[:MAX_LINE]):
            lines.append({"line": number, "text": secrets.mask(line.strip())[:200]})
            if len(lines) >= limit:
                break
    return lines


def load(raw):
    """Decode and check raw ticket bytes or text. Returns the text."""
    if isinstance(raw, bytes):
        if len(raw) > MAX_BYTES:
            raise IntakeError("The ticket is larger than %d KB. Paste the part that matters." % (MAX_BYTES // 1000))
        raw = raw.decode("utf-8", errors="replace")
    if len(raw.encode("utf-8", errors="replace")) > MAX_BYTES:
        raise IntakeError("The ticket is larger than %d KB. Paste the part that matters." % (MAX_BYTES // 1000))
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise IntakeError("The ticket is empty.")
    return text


# A ticket full of secret-shaped values must not push the rest of the output out of view.
MAX_SECRETS_LISTED = 20


def analyse(text, max_refs=40):
    hits = secrets.scan_text(text)
    refs = extract_refs(text, limit=max_refs)
    masked_text = secrets.mask(text)
    found = secrets.found_values(text)
    secrets.remember(secrets.found_values(text, everywhere=True))
    return {
        "sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
        "chars": len(text),
        "lines": len(text.rstrip("\n").split("\n")),
        "secrets": [{"kind": h.label, "line": h.line} for h in hits[:MAX_SECRETS_LISTED]],
        "secrets_total": len(hits),
        "refs": [_masked_ref(r, masked_text, found) for r in refs],
        "instruction_lines": instruction_lines(text),
    }


def _masked_ref(ref, masked_text, found=()):
    """Hidden when it holds or is part of a secret found anywhere in the ticket, or vanishes once the ticket is masked."""
    out = dict(ref)
    raw = out["value"]
    out["value"] = secrets.mask(raw)
    if out["value"] not in masked_text or any(v in raw or raw in v for v in found):
        out["value"] = "[hidden: part of a secret]"
    return out
