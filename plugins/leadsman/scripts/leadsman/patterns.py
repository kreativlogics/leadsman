"""Detection data for leadsman: what ticket text is matched against. Purpose: find and REPORT, never act on.

INSTRUCTION_LIKE finds lines in a ticket that address an AI (prompt injection). Matching lines are quoted in the
report as "not followed"; nothing here is executed. NOT_ISSUE_PREFIXES lists standard names written like tracker
keys (UTF-8, SHA-256) so they are not looked up as issues.
"""

import re

INSTRUCTION_LIKE = re.compile(
    r"(?i)(ignore (?:all |any )?(?:the )?(?:previous|prior|above|earlier) (?:instructions|rules|prompts?)"
    r"|disregard (?:the |all )?(?:previous|prior|above|system)"
    r"|\byou are (?:now )?(?:an? )?(?:ai|assistant|claude|agent|language model)\b"
    r"|\b(?:system|developer) prompt\b"
    r"|<\s*/?\s*(?:system|assistant|instructions?)\s*>"
    r"|^\s*(?:assistant|system)\s*:"
    r"|\bdo not (?:tell|inform|show) the user\b"
    r"|\bwithout (?:asking|telling) the user\b"
    r"|\b(?:curl|wget)\b[^|\n]*\|\s*(?:ba|z)?sh\b"
    r"|\b(?:run|execute) (?:this|the following) (?:command|script|code)\b"
    r"|\bnote to (?:the )?(?:ai|assistant|agent|model|llm)\b)"
)

NOT_ISSUE_PREFIXES = frozenset((
    "UTF", "UCS", "SHA", "MD", "ISO", "IEC", "RFC", "HTTP", "TLS", "SSL", "AES", "RSA", "CVE", "CWE", "GPT",
    "ES", "ECMA", "IPV", "X", "WCAG", "PEP", "SPDX", "BASE", "COVID",
))
