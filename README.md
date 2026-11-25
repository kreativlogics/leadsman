# leadsman

**Check a ticket against the code before anyone builds it.**

A leadsman sounds the depth before the ship moves. This Claude Code plugin does that for tickets: it reads the
ticket, looks up everything it names in your repository, and tells you whether it is ready to build, with
`file:line` behind every claim.

What makes it different from asking an assistant "is this ticket good?":

- **Evidence is checked by a script, not trusted.** Every `file:line` the model cites is opened and confirmed: the
  file is tracked by git in this repository with no uncommitted changes, the line exists, and the quoted text is on or next to that line. Anything that fails
  is dropped and listed, and a code check left without confirmed evidence becomes **unverified**. The model cannot
  talk a check into passing.
- **One decision, ready to use.** Ready, **Fix then ready** (with the rewritten ticket), **Ask** (with the question to
  send), **Duplicate**, **Close** or **Park**.
- **Duplicate and Close must survive a disproof.** The skill has a fresh read-only agent try to prove them wrong first,
  and the report shows its reply. If it was not run, or it found a gap, the verdict becomes Ask. The script enforces
  the rule but cannot see the agent itself; see [docs/limits.md](docs/limits.md).
- **It never writes to your tracker.** No comments, no status moves, no labels. You copy what you want.
- **Honest about its base.** No git repository: the verdict is capped and says so. A base branch behind its remote or
  not fetched lately: a banner gives the exact `git fetch` to run. leadsman never fetches for you.

## Install

```
/plugin marketplace add kreativlogics/leadsman
/plugin install leadsman@leadsman
```

Needs Python 3.9 or newer and git. `gh` is optional (GitHub issues and the overlap search).

## Use

```
/leadsman:check 123                                # a GitHub issue in this repository
/leadsman:check https://github.com/owner/repo/issues/123
/leadsman:check <paste the ticket text>
/leadsman:check <a Jira or Linear link>            # read through a tracker connector you already have
```

The seven checks:

| Check | Asks |
|---|---|
| Still valid | Is the problem still there on this base? |
| Reachable | Can a user or caller get to that code path? |
| References true | Do the files, functions, routes and strings it names exist as described? |
| Clear | One reading, with who, what and done? |
| Testable | Can someone show it works? |
| Safe | Are data, auth, money and deletes called out and bounded? |
| Size and overlap | One change's worth? Already covered by open work? |

A report looks like this:

```
# leadsman: Fix then ready

**Ticket:** Export fails for large reports (owner/repo#41)
**Checked against:** `shop` at 3f2a91c (branch master)

| Check | Result | Evidence |
|---|---|---|
| Still valid | pass | export still loads every row into memory `src/reports/export.py:88` |
| References true | fail | ticket says ReportExporter.run; the method is export_all `src/reports/export.py:61` |
...

## Rewritten ticket
...
_leadsman never writes to your tracker. Copy what you need._
```

## Set up

```
/leadsman:config            # detect the repository and tools, suggest a preset, save it
/leadsman:config statuses   # map your tracker's status names, so Close can use "the tracker says done"
/leadsman:config doctor     # health check
```

Presets: `solo` (no overlap search), `standard`, `strict` (clear, testable and safe need a quote too, base stale after a day).
A committed `.leadsman/config.json` shares settings with the team and can only make them stricter. A
`.leadsman/rules.md` in the repository adds the team's own readiness rules to every check.

## Docs

- [Configuration](docs/config.md)
- [The findings file and decision rules](docs/findings.md)
- [What leadsman cannot do](docs/limits.md)
- [Security](SECURITY.md) and [threat model](THREAT-MODEL.md)

To scan leadsman with a skill scanner, point it at `plugins/leadsman/`, the folder that gets installed. `tests/` is
left out on purpose: it is full of hostile inputs the plugin must refuse, so scanners flag it. The latest results and
an explanation of each finding are in [SECURITY.md](SECURITY.md#scanner-notes).

## Licence

MIT. Copyright KreativLogics.
