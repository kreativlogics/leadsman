# Security policy

## Reporting a problem

Please report a way to make leadsman write to a tracker, run text from a ticket, read files outside the repository,
or reveal a secret, through GitHub's private vulnerability reporting: the **Security** tab of this repository, then
**Report a vulnerability**. Please do not open a public issue for these.

Include the leadsman version (`plugins/leadsman/scripts/leadsman/__init__.py`), the ticket text or a cut-down version,
and what happened. Never include a real secret: build test values from pieces, as `tests/helpers.py` does.

You should hear back within a week.

## Scope

In scope: a ticket or repository file that gets leadsman to write to a tracker, run a command, read or cite a file
outside the repository, accept evidence that is not there, let Duplicate or Close stand without a disproof, or print
a secret value. The items in [docs/limits.md](docs/limits.md) are known; a new way around one is still welcome.

## What leadsman does with your data

- **Ticket text** stays on your machine, in the plugin's data folder (`work/`), except what Claude Code itself sends
  to the model as part of the conversation.
- **Network:** only `gh`, and only when you check a GitHub issue or the overlap search is on. It reads the issue, or
  searches the repository's issues and pull requests with up to eight plain words from the title. `gh` is limited in
  code to `issue view`, `issue list` and `pr list`; `--web` is refused.
- **Tracker connectors** you already have are used only through their read tools, by the skill's instructions.
- No telemetry.

## Scanner notes

Scan the installable folder, `plugins/leadsman/`: it is what users install. `tests/` is left out because it holds
hostile inputs on purpose (injection phrases, `curl | sh`, `/etc/passwd` paths, shell metacharacters) to prove the
plugin refuses them, and a scanner rightly flags those.

Latest scan of `plugins/leadsman/` with SkillSpector (2026-11-25): **REVIEW**, no HIGH or CRITICAL. A later scan the
same day flagged one HIGH, PE3 credential access, on a code comment in `secrets.py` that named environment files as
where unquoted secrets appear; the comment was reworded and no code reads such files. Each MEDIUM:

| Finding | Where | Why it is expected |
|---|---|---|
| AST4 subprocess call | `scripts/leadsman/repo.py` (`run_git`) | Runs read-only `git` with an argument list, never a shell; minimal environment, no prompts, stdin closed, a timeout. Search terms follow `-e`; paths follow `--`. |
| AST4 subprocess call | `scripts/leadsman/ghread.py` (`run`) | Runs `gh` with an argument list; only `issue view`, `issue list` and `pr list`; `--web` refused; minimal environment with only the `gh` auth and proxy variables named in `GH_ENV`. |
| TT2 environment value to file write | `scripts/check.py` (`_write_text`) | The value is the plugin data folder Claude Code sets (`CLAUDE_PLUGIN_DATA`). Every path written is resolved and must stay inside it. |
| TT2 environment value to file write | `scripts/cfgtool.py` (`cmd_doctor`) | Same data folder; the doctor writes and removes one `.probe` file to check the folder is writable. |
| RA2 session persistence | `scripts/leadsman/workfiles.py` (docstring) | The match is the module's description of the `work/` folder. The only state kept is the current ticket, findings and report inside the plugin data folder; nothing is scheduled, started at login or run later. |
| EA1 unrestricted tool access | `skills/check/SKILL.md` | The match is the ground rule that forbids tracker tools. The skill's `allowed-tools` pre-approves only the check script; every other tool asks the user. |

Scan of the whole repository (same date), for completeness: **BLOCK**, from the test suite and one doc line only.

| Finding | Where | What it is |
|---|---|---|
| P1 instruction override | `tests/test_intake.py`, `tests/test_verdict.py` | Injection phrases the tests feed in to prove they are quoted, not followed. |
| SC2 external script fetching | `tests/test_intake.py` | A `curl \| sh` line in a test ticket, same purpose. |
| TM1, TM2 tool parameter abuse | `tests/test_ghread.py` | Issue refs with shell metacharacters that the parser must refuse. |
| PE3 credential access | `tests/test_config.py`, `tests/test_repo_probe.py`, `tests/test_hardening.py` | Traversal paths and an untracked `.env` that must be refused as config or evidence. |
| E2 environment harvesting | `tests/helpers.py` | Saves and restores the test process environment around each test. |
| AST4, TT2 subprocess calls | `tests/helpers.py`, other tests | Run the plugin's scripts and `git` in temporary folders. |
| AS3 skill enumeration | `THREAT-MODEL.md` | A row naming the skill file as a control. |
| The `plugins/leadsman/` MEDIUMs above | | Same as above. |
