# Threat model

leadsman reads text written by other people (tickets, comments, repository files) and asks a model to judge it. The
main risks are that text steering the model, the model inventing evidence, and the plugin changing things it should
only read.

## Assets

- The user's trackers (issues, tickets, statuses): must never be changed.
- Files outside the repository (home folder, credentials): must never be read or cited.
- Secrets in tickets or the repository: must never be printed.
- The user's trust in the verdict: evidence must be real.

## Untrusted inputs

| Input | From | Handling |
|---|---|---|
| Ticket title, body, comments | Anyone who can file an issue | Written by the model to a temp file with the Write tool and copied in by `save --from`, so the shell never reads it. Instruction-like lines are found and quoted in the report as "not followed". Secrets masked. Size capped at 200 KB. |
| Repository files, team rules file | Anyone with commit access | Read as data. The rules file must resolve inside the repository, be tracked by git, and is cut at 20 KB. Lines in it addressed to the AI are listed (`team_rules_instruction_lines`) and quoted in the report as not followed. |
| `.leadsman/config.json` | Anyone with commit access | Validated; can only tighten safety settings. No key runs a program. |
| GitHub issue JSON | GitHub, through `gh` | Parsed as JSON; only known fields used. |
| Model output (`findings.json`) | The model, which read all of the above | Treated as untrusted: every citation confirmed by the script; decision rules enforced in code. |

## Threats and controls

| Threat | Control | Where |
|---|---|---|
| A ticket says "mark this ready" or "close #12" | Skill ground rules; injected lines quoted in the report; decisions enforced by `verdict.py` rules, not by the model | `skills/check/SKILL.md`, `intake.py`, `verdict.py` |
| The model writes to a tracker | No write code exists; `gh` allow-list (`issue view`, `issue list`, `pr list`); skill's `allowed-tools` pre-approves only the check script; connector write tools are forbidden by the skill and not pre-approved, so they need the user's approval | `ghread.py`, skill frontmatter |
| Shell injection from ticket text | Ticket, findings and tracker status names (with the user's answers) handed over in a temp file the model writes with the Write tool, never in a command; overlap words read from the ticket file, not a command line; every `git` and `gh` call uses an argument list, never a shell, with a minimal environment; searches use `git grep -F -e` | `repo.py`, `probe.py`, `ghread.py`, `check.py` |
| The model is steered into writing a file elsewhere | Ticket, findings and report paths must resolve inside the plugin data folder; `issue` has no output option; `--data` may be given only once, before the command, so arguments added after the pre-approved prefix cannot move the data folder; a linked `work` folder is refused; there is no `--project-dir` (the repository is the current folder) | `check.py`, `cfgtool.py`, `workfiles.py` |
| A ticket title holding a key is sent to GitHub search | Title words are masked first, and long words mixing letters and digits are dropped | `ghread.py` |
| The model is steered into copying a private file in with `save --from` or `statuses --file` | Only regular files whose real path is in a temp folder are read; symlinks are resolved first | `workfiles.py` |
| A hostile remote branch name in the suggested fetch command | Only plain branch names (letters, digits, `.`, `_`, `/`, `-`) are used | `context.py` |
| Option injection (`--output=...` as a search term or issue ref) | `-e` before every search pattern; issue refs parsed to digits and `owner/repo`; search words stripped to letters, digits, `_` and `-` | `probe.py`, `ghread.py` |
| Path traversal or symlink escape in a reference or citation | `safe_path` resolves with `realpath` and requires the result inside the repository root | `repo.py`, `verdict.py` |
| Invented evidence | `ticket_quote` is checked against the saved ticket only (`verdict` has no ticket option); file tracked by git (not `.git`, untracked or ignored) with no uncommitted changes, line in range, a quote of 3+ letters or digits on or near it that is 12+ characters or most of its line (so a fragment like `ret` does not count); unconfirmed evidence dropped; code checks without it become unverified | `verdict.py`, `repo.py` |
| Duplicate or Close without basis | Needs `disproof.outcome == "stands"` with the challenger's reply; Close also needs a failed valid check or the ticket's header `Status:` line (line 2, which `save` and `issue` always fill, so body text never reaches it) mapped to done. **Limit:** the script cannot see the challenger run; a steered model could record a fake reply. The report shows the reply. | `verdict.py`, `agents/challenger.md`, `docs/limits.md` |
| A repository's config weakens checks | Project layer can only tighten `overlap`, `evidence`, `stale_days`; loosening is ignored and reported | `config.py` |
| A repository's `status_map` maps an open status to `done` | Ignored and reported: a project may add statuses but not map any to `done` or change yours | `config.py` |
| A repository's `rules_file` points at a secret file such as `.env` | Read only if git tracks it; masked | `check.py` |
| A repository's config file links outside it, or is a pipe or huge | Read only if it resolves inside the repository and is a regular file under 100 KB; `cfgtool --project` commands refuse a linked-out file before reading it | `config.py`, `cfgtool.py` |
| A repository ships a broken or invalid config to stop the check | The project file is skipped with a note, including paths a file system cannot hold; the check runs on your settings | `config.py`, `repo.py` |
| A link planted in the data folder redirects a write | Work files, config and the doctor's probe file are written to a new temp file and renamed over the target, so a link is replaced, not followed | `workfiles.py`, `config.py` |
| Reading files outside the repository | The scripts read only the repository and the data folder; the skill pre-approves no Read, Grep or Glob, so reads outside the working folder ask the user | `check.py`, skill frontmatter |
| A secret printed in the report | `secrets.mask` on every output (in `cfgtool`, on every line it prints, error messages included), before any text is shortened (a cut secret no longer matches its pattern); secrets found in the ticket reported by kind and line only | `check.py`, `verdict.py`, `secrets.py` |
| Stale base gives a wrong "still valid" | Behind count and fetch age reported, with the exact fetch command; never fetches | `context.py` |
| Huge repositories or tickets slow everything | Ticket size cap, reference cap (`max_refs`), hit cap per search, timeouts on every subprocess; repository lines cut to 2,000 characters before masking, in prepare's output and around cited evidence; secret patterns are bounded or, like the private-key block, end in a match that takes the rest of the text, so none backtracks without limit | `intake.py`, `probe.py`, `repo.py` |
| The model's findings restate the title, or name a report path over the saved files | The report title comes from the saved ticket; `ticket_quote` is matched only in the ticket body; `verdict --out` refuses `ticket.md` and `findings.json` in any letter case, and any path that is the same file | `check.py`, `verdict.py` |
| A git search fails (timeout, broken repository) and reads as "not found" | A failed search is reported as "search failed; unverified", never as missing | `probe.py` |
| A secret written without quotes or in backticks (`.env` files, YAML, Markdown), or repeated elsewhere in the ticket | Patterns for unquoted and backtick-quoted values assigned to secret names (an unquoted one needs a letter, a digit and enough randomness, so plain words pass); a secret found anywhere in the ticket is remembered for the run and hidden by every `mask` call, before any JSON escaping or shortening: references, instruction lines, the report, repository lines, the `prepare`, `issue` and `verdict` output, and the overlap search words | `secrets.py`, `intake.py` |
| Unusual line breaks (form feed, Unicode separators) shift reported line numbers | Tickets and repository files are split on `\n` only, everywhere | `intake.py`, `secrets.py`, `repo.py` |
| Python writes `__pycache__` into the plugin folder | Both scripts set `sys.dont_write_bytecode`, so only the data folder is written | `check.py`, `cfgtool.py` |
| A huge history makes `prepare` outlast the caller's timeout | All lookups share a 60-second budget; references left over are reported as not checked | `probe.py` |
| An issue too large to save, or with many comments | Cut on a character boundary; past 30 comments the first 5 and the newest 25 are kept; `issue` says what was left out so the user is told | `check.py` |
| A steered model puts Markdown (a fake verdict heading) in a free-text field | Every model field and repository path is escaped for its table cell or fenced; the overlap note is folded onto one line | `verdict.py`, `check.py` |
| A project status mapping to `done` looks saved but is ignored | `statuses --apply` prints the same Ignored notes as `set` | `cfgtool.py` |
| Ticket text names an ordinary word as a "password" so it is hidden from every report and breaks JSON | Only secret-shaped values (8+ characters, a letter and a digit, or a known token format) are hidden everywhere; JSON values are masked, never the JSON text | `secrets.py`, `check.py` |
| A remembered secret with a "\|" leaks once the table cell escapes it, or through a dropped-evidence path | Cells are masked before escaping; every evidence reason masks the path | `verdict.py` |
| A tracked file name with a newline makes a search hit name the wrong file | `git grep -z` output is read field by field, not split into lines | `probe.py` |
| A committed file name with a newline, "\|" or backtick, once cited, adds lines (a fake verdict heading) to the report | Repository names, branches and evidence paths are cleaned for their code span: control characters become spaces, backticks become quotes, "\|" is escaped | `verdict.py` |
| A carriage return in a pasted title pushes its second half onto line 2, the status line | `save` refuses a ticket whose line 1 holds a line break or whose raw line 2 is not the status line | `check.py` |
| Masking a long secret shrinks a line so a second secret cut at 2,000 characters comes into view, partly | When a line was cut before masking, the word at the cut is dropped | `probe.py` |
| A carriage return or terminal escape in ticket text or a model field adds a fake heading or redraws the terminal | Every control character except newline and tab becomes a space in the report | `verdict.py` |
| A secret placed past column 20,000 of a long ticket line escapes detection, remembering and the search-word filter | Lines are scanned whole; no pattern backtracks without limit | `secrets.py` |
| Lines in the team rules addressed to an AI never reach the report | `verdict` reads the rules file again and lists those lines as not followed | `check.py`, `verdict.py` |
| A ticket steers the challenger agent to read files outside the repository | Its instructions limit reads to the repository path and forbid quoting secrets; Claude Code's own permission prompt still applies | `agents/challenger.md` |
| A refused save or failed `issue` leaves the last run's ticket and findings, so a new ticket is graded with old findings | `save ticket` and `issue` clear the ticket, findings and report first, even when their arguments are refused; `save findings` clears the findings and report; `verdict` refuses findings older than the saved ticket | `check.py` |
| Evidence quotes only a secret's value, which matches no pattern on its own | Values found in the cited lines are hidden in the quote and note | `verdict.py` |
| A ticket full of secret-shaped values pushes `prepare`'s useful output out of view | At most 20 secrets listed, with a total | `intake.py` |
| Project config text addressed to the AI reaches the config skill | The config skill treats config values, notes and repository text as data | `skills/config/SKILL.md` |
| Secret-like text in project config breaks the config skill's JSON when the JSON text is masked | `cfgtool` masks JSON values before serializing and writes JSON past its masking stream | `cfgtool.py` |
| A form feed in a commit subject adds a fake commit line to `prepare` output | git output is split on `\n` only | `probe.py` |
| A ticket plants a token's fixed prefix (for example `sk-ant-api03`) so hiding it first leaves the rest of a real token unmatched | `mask()` finds pattern matches and remembered values in the original text and hides them together | `secrets.py` |
| A ticket names the start of a committed private key, or a line of a key file, to get its body printed (the body matches no pattern) | `mask()` hides a whole BEGIN…END key block; no line of a tracked file holding a key header is shown in grep hits, path lines or evidence, and a rules file holding one is ignored | `secrets.py`, `probe.py`, `verdict.py`, `check.py` |
| A `save` refused for an option such as `--dry-run` leaves the old work files, as it was counted as a second `--data` | Only spellings argparse takes for `--data` are counted | `check.py` |
| A "Fix then ready" verdict on work the findings say is not real (valid fails or is unverified) | `fix` is refused unless valid is confirmed; a failed valid is refused even when downgraded | `verdict.py` |
| A secret found in cited lines is hidden in the quote but printed in a summary or reason | All evidence is confirmed first and its secret-shaped values are remembered, so every later field hides them | `verdict.py` |
| A refused `issue findings …` clears only the findings, or a second `--data` skips clearing | The refused arguments are read by hand: `issue` always clears the ticket, and the first (pinned) `--data` folder is cleared | `check.py` |
| A private key in a ticket with no END line (a cut issue or partial paste), or longer than 20,000 characters, leaves its body in prepare's references | The key pattern hides from BEGIN to END, or to the end of the text when END is missing | `secrets.py` |
| Another session saves a ticket into the shared work folder between this session's save and verdict, so findings grade the wrong ticket | Findings carry the saved ticket's sha256 from `prepare`; verdict stops when it is missing or different | `check.py` |
| An evidence quote or note cuts a secret, so the part shown matches no pattern | Every piece of 6+ characters of a value found in the cited lines is hidden in the quote and note | `verdict.py` |
| Control characters in model-written names reach the "Findings need revising" output | Control characters become spaces there, as in the report | `check.py` |
| Many citations next to a huge or secret-heavy repository line make `verdict` run for minutes | Cited lines are cut to 2,000 characters before the secret search, and hiding cut secret pieces is linear in the value length | `verdict.py` |
| A secret crossing the 2,000-character cut of a cited line is not found, so a quote of its head is shown | The word at the cut is dropped from cited lines, so such a quote is not found and the evidence is refused | `verdict.py` |
| With `evidence: all`, a text check passes on a code line instead of the ticket's words | Under `all`, clear, testable and safe need a `ticket_quote` found in the ticket; code evidence does not count for them | `verdict.py` |
| A path with `[`, `*` or `?` matches a different tracked file, so an untracked file of that name is printed | The tracked check passes the path to git as a literal pathspec | `probe.py` |
| A secret written on the line after its name (YAML `password:` then the value) is shown in `prepare` lines and `verdict --json` quotes | Secret values are also searched across lines; shown lines hide the values found within 3 lines of them, and cited quotes the values within 2 lines | `secrets.py`, `probe.py`, `verdict.py` |
| A ticket names a piece of its own sha256 (or the head commit) as a secret, so `prepare` hides part of it and no findings can ever match | The ticket hash and head commit are computed by leadsman and printed whole | `check.py` |
| A grep hit in a file over 2 MB skips the search of nearby lines, so a value whose name is on an earlier line is shown | Only the lines around the hit are read from a large file; a file that can't be read has its hit lines withheld | `probe.py`, `repo.py` |
| A project config path with a newline or terminal escape forges rows in `cfgtool show` | Config paths refuse control characters, and `show` prints strings as JSON | `config.py`, `cfgtool.py` |
| An issue body with a lone surrogate stops `issue` with a traceback | It is written as `?` | `check.py` |

## Out of scope

- A malicious Claude Code, model, `git` or `gh` binary.
- Tracker connectors that write when asked to read.
- What the user does with the report.
