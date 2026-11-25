# Configuration

Settings come in layers, each overriding the one before:

1. Built-in defaults.
2. The plugin's **Preset** option (set when you enable the plugin).
3. Your own file: `config.json` in the plugin's data folder. Written by `/leadsman:config`.
4. The project's file: `.leadsman/config.json` at the repository root, committed for the team.

The project file **can only tighten** the safety settings (`overlap`, `evidence`, `stale_days`). A looser value there
is ignored and reported ("Ignored: the project config asks for ..."), never applied silently. `exclude_paths` from
both files are combined. The project's `status_map` can add statuses you have not mapped, but cannot change yours or
map any status to `done` (that would let Close be proposed); both are ignored and reported. The project file is read
only if it resolves inside the repository, not through a link pointing out of it. A project file that is broken or
invalid is skipped as a whole with a note ("Ignored the project config: ..."); your own file still applies.

Run `/leadsman:config show` to see each value and where it came from, and `/leadsman:config explain <key>` for one key.

## Keys

| Key | Values | Default | Notes |
|---|---|---|---|
| `version` | `1` | `1` | Config format. |
| `preset` | `solo`, `standard`, `strict` | `standard` | Sets `overlap`, `evidence` and `stale_days` together. Keys set after it win. |
| `overlap` | `on`, `off` | `on` | Search this repository's GitHub issues and pull requests for overlapping work. Sends up to eight plain words from the title to github.com through `gh`. Project: can turn off, not on. |
| `evidence` | `code`, `all` | `code` | `code`: valid, reachable and references need confirmed `file:line`. `all`: clear, testable and safe also need a `ticket_quote` found in the ticket (code evidence does not count for them). Size and overlap stays a judgement either way. Project: can raise, not lower. |
| `stale_days` | whole number | `7` | A base fetched longer ago than this is reported as stale. Project: can lower, not raise. |
| `max_refs` | 1-200 | `40` | References from one ticket looked up. |
| `exclude_paths` | list of globs | `[]` | Left out of searches, e.g. `vendor/**`. |
| `rules_file` | relative path | `.leadsman/rules.md` | Team readiness rules, read as data. Must stay inside the repository and be tracked by git. |
| `status_map` | status name -> category | `{}` | Categories: `backlog`, `ready`, `in_progress`, `review`, `testing`, `done`. |

## Presets

| | solo | standard | strict |
|---|---|---|---|
| `overlap` | off | on | on |
| `evidence` | code | code | all |
| `stale_days` | 14 | 7 | 1 |

## Status mapping

`/leadsman:config statuses` takes your tracker's status names (read through a connector, or pasted) and guesses a
category for each, with a confidence:

- **high**: the tracker's own category agrees with the name (Jira's status category, Linear's state type, GitHub's
  open/closed), or the name is an exact known word. Saved with `--apply`.
- **medium** and **low**: shown and asked; saved only when the file's entry carries the answer, as in
  `{"name": "In QA", "accept": "review"}` (status names stay in the file, never on a command line).

Close can rest on a status mapped to `done` (in your own config) instead of a failed "still valid" check, when the
ticket file carries that status on its `Status:` line, line 2, right after the title. It still needs the
disproof.

## Commands

The config skill runs `scripts/cfgtool.py`:

| Command | Does |
|---|---|
| `show [--json]` | Effective values, their sources and any notes. |
| `explain <key>` | What the key does and its current value. |
| `set <key> <value> [--project] [--add/--remove]` | Validates and writes one key. Status names from a tracker go through `statuses --file`, never `set`. |
| `unset <key> [--project]` | Removes a key from a file. |
| `detect [--json]` | What is here: git, default branch, GitHub remote, `gh`, vendor folders, rules file, freshness. |
| `init [--preset P] [--project] [--yes] [--force]` | Writes a starting file from `detect`. Previews unless `--yes`. |
| `statuses --file F [--apply] [--project]` | Maps status names; answers go in the file as `"accept"`. |
| `doctor` | Python, git, gh, data folder, config, freshness and lookup timing. |
