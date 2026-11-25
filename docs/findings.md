# The findings file and decision rules

The check skill has the model write its findings to `work/findings.json` in the plugin's data folder, then runs
`check.py verdict`. The script, not the model, decides what stands.

## Format

```json
{
  "ticket": {"title": "Export fails for large reports", "source": "owner/repo#41", "status": "In Progress",
             "sha256": "the ticket.sha256 that prepare printed"},
  "checks": {
    "valid": {"status": "pass", "summary": "still loads every row",
              "evidence": [{"file": "src/reports/export.py", "line": 88, "quote": "rows = query.all()"}]},
    "reachable": {"status": "pass", "summary": "...", "evidence": [{"file": "...", "line": 1}]},
    "references": {"status": "fail", "summary": "...", "evidence": []},
    "clear": {"status": "pass", "summary": "...", "ticket_quote": "exact words from the ticket"},
    "testable": {"status": "warn", "summary": "..."},
    "safe": {"status": "unverified", "reason": "the job's retry policy lives in another repository"},
    "size_overlap": {"status": "pass", "summary": "..."}
  },
  "decision": "fix",
  "rewrite": "the full corrected ticket",
  "question": "",
  "reason": "",
  "duplicate_of": "",
  "disproof": {"outcome": "not_run", "notes": ""},
  "overlap": {"skipped": null}
}
```

`ticket.sha256` must match the saved ticket, or verdict stops (exit 2): the work folder is shared by every session,
so another session may have saved a different ticket since.

Statuses: `pass`, `warn`, `fail`, `unverified`. Decisions: `ready`, `fix`, `ask`, `duplicate`, `close`, `park`.

## Evidence

Each evidence item is confirmed:

- `file` resolves (following links) to a path inside the repository;
- the file exists, is text, and is tracked by git (not untracked, ignored, or inside `.git`);
- the file has no uncommitted changes, so the citation describes the commit the report names;
- `line` is a whole number within the file;
- `quote` is given, has at least three letters or digits (underscores and punctuation do not count), and appears (ignoring spacing) within two lines of `line`.
- `quote` is at least 12 characters (spaces not counted), or covers most (60%) of the one line it is on, so a fragment such as `ret` proves nothing. The same rule applies to `ticket_quote`.

Items that fail are dropped and listed under "Evidence that could not be confirmed". A `pass`, `warn` or `fail`
on `valid`, `reachable` or `references` with no confirmed item becomes `unverified`. With `evidence: all`, `clear`,
`testable` and `safe` need a `ticket_quote` found in the ticket body (from line 3; the title and status lines do not
count); code evidence does not count for them, and without the quote they become `unverified`.

Without a git repository, the three code checks become `unverified` and the verdict label says
"(not verified against code)". With `evidence: all`, `clear`, `testable` and `safe` still count there when they carry a
confirmed `ticket_quote`; without one they become `unverified`.

## Decision rules

Rejected (exit 3, the model must revise):

- `ready` while valid, reachable, references, clear or testable is `fail` (only these are named in the message),
  even when the `fail` had no confirmed evidence and so shows as `unverified`;
- `ready` in a git repository while valid, reachable or references is `unverified`;
- `ready` with `evidence: all` while clear, testable or safe is `unverified`;
- `fix` while valid is `fail`, or in a git repository while valid is `unverified` (fix means the work is real);
- `duplicate` or `close` with `disproof.outcome` `stands` but no `disproof.notes`;
- `fix` without `rewrite`; `ask` without `question`; `park`, `close` or `duplicate` without `reason`; `duplicate`
  without `duplicate_of`;
- missing or unknown checks, a bad status, or `unverified` without a reason.

Changed to Ask (with a drafted question if none was given):

- `duplicate` or `close` whose `disproof.outcome` is not `stands`;
- `close` when `valid` did not fail with confirmed evidence and the ticket's status does not map to `done`. The status
  counts only when line 2, right after the title, is `Status: <name>` or `State: <name>` naming it; a
  status line further down (the body or a comment) never counts.

`safe` and `size_overlap` failing do not block `ready`: they are shown in the report for the reader to weigh.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Report written. |
| 2 | Bad input: unreadable or empty ticket, bad JSON, bad config. |
| 3 | The findings break a rule; the reasons are printed. |
