"""Secret detection. Results name the kind and the line, never the value.

High-confidence patterns are token formats with a fixed prefix or structure.
Generic patterns (values assigned to secret-sounding names, quoted or not, and
passwords in connection strings) also need enough randomness and must not look like a
placeholder. SEC03 can hand the staged diff to gitleaks instead.
"""

import math
import re

HIGH = "high"
GENERIC = "generic"

# (id, label, regex, confidence, group index holding the value, min entropy)
_PATTERNS = [
    ("private-key", "private key block",
     # The whole block up to its END line, or to the end of the text when the END line is missing (a cut or partial
     # paste), so the key body is hidden too. A single match takes the rest of the text, so this stays linear.
     r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"
     r"(?:[\s\S]*?-----END [A-Z ]{0,30}PRIVATE KEY(?: BLOCK)?-----|[\s\S]*)", HIGH, 0, 0.0),
    ("aws-access-key-id", "AWS access key ID", r"\b((?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16})\b", HIGH, 1, 3.0),
    ("aws-secret-key", "AWS secret access key",
     r"(?i)aws_?secret_?access_?key[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9/+=]{40})\b", HIGH, 1, 3.5),
    ("github-token", "GitHub token", r"\b(gh[pousr]_[A-Za-z0-9]{36,255})\b", HIGH, 1, 3.0),
    ("github-pat", "GitHub fine-grained token", r"\b(github_pat_[A-Za-z0-9_]{60,255})\b", HIGH, 1, 3.0),
    ("gitlab-token", "GitLab token", r"\b(gl(?:pat|dt|rt|ptt|cbt|oas)-[A-Za-z0-9_\-]{20,255})", HIGH, 1, 3.0),
    ("slack-token", "Slack token", r"\b(xox[abposr]-[A-Za-z0-9-]{10,255})\b", HIGH, 1, 3.0),
    ("slack-webhook", "Slack webhook URL",
     r"(https://hooks\.slack\.com/(?:services|workflows)/[A-Za-z0-9+/_-]{20,255})", HIGH, 1, 3.0),
    ("stripe-live", "Stripe live key", r"\b((?:sk|rk)_live_[A-Za-z0-9]{20,255})\b", HIGH, 1, 3.0),
    ("anthropic-key", "Anthropic API key", r"\b(sk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_\-]{30,255})", HIGH, 1, 3.0),
    ("openai-key", "OpenAI API key",
     r"\b(sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,255}T3BlbkFJ[A-Za-z0-9_\-]{20,255})", HIGH, 1, 3.0),
    ("google-api-key", "Google API key", r"\b(AIza[0-9A-Za-z_\-]{35})\b", HIGH, 1, 3.0),
    ("npm-token", "npm token", r"\b(npm_[A-Za-z0-9]{36})\b", HIGH, 1, 3.0),
    ("pypi-token", "PyPI token", r"\b(pypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]{50,255})", HIGH, 1, 3.0),
    ("sendgrid-key", "SendGrid key", r"\b(SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43})\b", HIGH, 1, 3.0),
    ("jwt", "JSON web token",
     r"\b(eyJ[A-Za-z0-9_-]{10,1000}\.eyJ[A-Za-z0-9_-]{10,4000}\.[A-Za-z0-9_-]{16,1000})", HIGH, 1, 3.0),
    ("url-password", "password inside a connection URL",
     r"\b[a-zA-Z][a-zA-Z0-9+.\-]{1,20}://[^\s:/@\"'`]{1,64}:([^\s@/\"'`]{6,128})@[A-Za-z0-9.\-\[\]]", GENERIC, 1, 2.5),
    ("assigned-secret", "secret assigned in code or config",
     r"(?i)(?:password|passwd|pwd|secret|api[_\-]?key|apikey|access[_\-]?token|auth[_\-]?token|client[_\-]?secret|private[_\-]?key)"
     r"[\"']?\s*(?::|=|=>|:=)\s*[\"'`]([^\"'`\s]{8,200})[\"'`]", GENERIC, 1, 3.0),
    # Unquoted values (environment files, YAML, pasted logs) need a letter and a digit, so words and names pass.
    ("assigned-secret-bare", "secret assigned in code or config",
     r"(?i)(?<![a-z0-9])(?:password|passwd|pwd|secret|api[_\-]?key|apikey|access[_\-]?token|auth[_\-]?token|client[_\-]?secret|private[_\-]?key)"
     r"\s{0,5}(?::|=)\s{0,5}(?=[^\s\"'`,;]{0,200}\d)(?=[^\s\"'`,;]{0,200}[A-Za-z])([^\s\"'`,;]{8,200})", GENERIC, 1, 3.0),
]

PATTERNS = [(pid, label, re.compile(rx), conf, grp, ent) for pid, label, rx, conf, grp, ent in _PATTERNS]

_PLACEHOLDER_WORDS = (
    "example", "sample", "dummy", "placeholder", "changeme", "change_me", "your", "redacted",
    "fake", "xxxxx", "*****", "<", ">", "${", "{{", "%s", "todo", "replace", "insert", "foobar",
    "secret123", "password", "passw0rd", "12345678", "abcdefgh", "test", "demo", "mock",
)
_HIGH_PLACEHOLDER_WORDS = ("example", "sample", "dummy", "placeholder", "redacted", "fake", "xxxxxxxx")
_REFERENCE_PREFIXES = ("$", "process.env", "os.environ", "env(", "getenv", "env.", "secrets.", "vars.", "%")


def entropy(value):
    if not value:
        return 0.0
    counts = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    n = float(len(value))
    return -sum((c / n) * math.log(c / n, 2) for c in counts.values())


def _looks_placeholder(value, confidence):
    low = value.lower()
    words = _HIGH_PLACEHOLDER_WORDS if confidence == HIGH else _PLACEHOLDER_WORDS
    if any(w in low for w in words):
        return True
    if confidence != HIGH and low.startswith(_REFERENCE_PREFIXES):
        return True
    if len(set(value)) <= 3:
        return True
    return False


class Hit(object):
    __slots__ = ("kind", "label", "line", "confidence")

    def __init__(self, kind, label, line, confidence):
        self.kind = kind
        self.label = label
        self.line = line
        self.confidence = confidence

    def describe(self):
        return "%s (line %d)" % (self.label, self.line) if self.line else self.label


def scan_text(text, high_only=False, first_line=1):
    """Return a list of Hit for secrets found in text. Values are never kept."""
    hits = []
    if not text:
        return hits
    seen = set()
    for offset, line in enumerate(text.split("\n")):
        for pid, label, rx, conf, grp, min_ent in PATTERNS:
            if high_only and conf != HIGH:
                continue
            for m in rx.finditer(line):
                value = m.group(grp)
                if _looks_placeholder(value, conf):
                    continue
                if min_ent and entropy(value) < min_ent:
                    continue
                key = (offset, m.start(grp))
                if key in seen:
                    continue
                seen.add(key)
                hits.append(Hit(pid, label, first_line + offset, conf))
    return hits


def found_values(text, everywhere=False):
    """The secret values in text. Never printed or stored.

    everywhere=True keeps only values safe to hide in all later output (see remember). A generic match (a URL
    password, an assigned value) then counts only with 8+ characters, a letter and a digit: ticket text could
    otherwise name an ordinary word such as "unverified" and hide it from every report. Such a value is still masked
    where its pattern matches, and still kept out of search words.
    """
    values = []
    text = text or ""
    # Each line, then the whole text: a value can sit on the line after its name (YAML `password:` then the value).
    for part in text.split("\n") + [text]:
        for pid, label, rx, conf, grp, min_ent in PATTERNS:
            for m in rx.finditer(part):
                value = m.group(grp)
                if _looks_placeholder(value, conf) or (min_ent and entropy(value) < min_ent):
                    continue
                if everywhere and conf != HIGH and not _secret_shaped(value):
                    continue
                if value not in values:
                    values.append(value)
    return values


def _secret_shaped(value):
    return (len(value) >= 8 and any(ch.isdigit() for ch in value)
            and any(ch.isalpha() for ch in value))


# Secret values found in the ticket this run. mask() hides them wherever they appear, before any escaping or cutting.
_KNOWN = set()


def remember(values):
    """Hide these values in every later mask() call of this process."""
    _KNOWN.update(v for v in values if v)


def hide(text, values):
    """text with each given secret value replaced, wherever it appears (found once, hidden everywhere)."""
    if not text:
        return text
    for value in sorted(set(values or ()), key=len, reverse=True):
        text = text.replace(value, "[hidden: secret]")
    return text


def mask(text):
    """Replace secret values in text with [hidden: kind] for display.

    Pattern matches and remembered values are both found in the original text, then hidden together: hiding a
    remembered value first could cut a token's fixed prefix away and leave the rest unmatched.
    """
    if not text:
        return text
    spans = []
    for pid, label, rx, conf, grp, min_ent in PATTERNS:
        for m in rx.finditer(text):
            value = m.group(grp)
            if _looks_placeholder(value, conf) or (min_ent and entropy(value) < min_ent):
                continue
            spans.append((m.start(grp), m.end(grp), label, conf == HIGH))
    for value in _KNOWN:
        start = text.find(value)
        while start >= 0:
            spans.append((start, start + len(value), "secret", False))
            start = text.find(value, start + 1)
    if not spans:
        return text
    spans.sort(key=lambda s: (s[0], -s[1]))
    merged = []
    for start, end, label, high in spans:
        if merged and start <= merged[-1][1]:
            last = merged[-1]
            keep = last[2] if last[3] or not high else label
            merged[-1] = (last[0], max(last[1], end), keep, last[3] or high)
        else:
            merged.append((start, end, label, high))
    out = []
    pos = 0
    for start, end, label, _ in merged:
        out.append(text[pos:start])
        out.append("[hidden: %s]" % label)
        pos = end
    out.append(text[pos:])
    return "".join(out)


_KEY_HEADER = re.compile(r"-----BEGIN [A-Z ]{0,30}PRIVATE KEY")


def holds_private_key(text):
    """True when text holds a private key header: none of its lines may be shown, as the key body matches no pattern."""
    return bool(text) and bool(_KEY_HEADER.search(text))


def mask_tree(obj):
    """obj with every string masked. Mask before json.dumps: escaping quotes would hide secrets from the patterns."""
    if isinstance(obj, str):
        return mask(obj)
    if isinstance(obj, list):
        return [mask_tree(v) for v in obj]
    if isinstance(obj, dict):
        return {mask_tree(k): mask_tree(v) for k, v in obj.items()}
    return obj


def added_lines(old, new):
    """Lines of new that are not in old, as (line_number, text)."""
    old_counts = {}
    for line in (old or "").split("\n"):
        old_counts[line] = old_counts.get(line, 0) + 1
    added = []
    for idx, line in enumerate((new or "").split("\n"), 1):
        if old_counts.get(line, 0) > 0:
            old_counts[line] -= 1
            continue
        added.append((idx, line))
    return added


def scan_added(old, new, high_only=False):
    hits = []
    for number, line in added_lines(old, new):
        for hit in scan_text(line, high_only=high_only, first_line=number):
            hits.append(hit)
    return hits
