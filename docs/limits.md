# What leadsman cannot do

leadsman checks that cited evidence exists. It does not prove that the evidence supports the claim: a real line can
still be the wrong line. The disproof step covers Duplicate and Close; for the other decisions, read the cited lines
yourself before acting on a surprising result.

## The disproof is the skill's step, not the script's

The script refuses Duplicate and Close unless `findings.json` records the challenger's outcome as `stands` with its
reply. It cannot see whether the challenger really ran: the model writes that file. A model steered by the ticket
could fake it. The report always shows the recorded reply, so read it before closing anything.

## Known misses

These are tested as expected failures, so a change that fixes one shows up.

- **Things described in words.** "The blue save button on the profile page" is not extracted as a reference. The model
  may still find it by reading, but `prepare` does not look it up. (`test_known_miss_prose_reference`)
- **Renamed code.** A ticket that names `load_config` after it was renamed to `parse_config` is reported as a missing
  reference, not as found under the new name. The model is told to look, but nothing checks it did.
  (`test_known_miss_renamed_symbol`)

## By design

- **No tracker writes.** Not even with your permission. The report is text to copy.
- **No fetching.** leadsman reads local git refs only. If your base is stale it tells you the command; it never runs
  `git fetch`, `pull` or `checkout`.
- **Tracked files only.** Searches use `git grep` over tracked files. Untracked and ignored files, other branches and
  other repositories are not searched. Evidence must come from committed code: a file with uncommitted changes is
  not accepted, so commit or stash your edits before a check if you want them cited.
- **No running the app.** Reachability is judged by reading routes, menus and callers, not by clicking through.
- **Overlap search is GitHub only.** It runs `gh issue list` and `gh pr list` on this repository's GitHub remote, with
  plain words from the title. Other trackers are not searched; linked items in the ticket are read only if your
  tracker connector returns them.
- **Other trackers need a connector you already have.** leadsman reads a Jira or Linear link only through a tracker
  connector connected in your session, using its read tools. Without one, paste the ticket.
- **Text checks are judgement.** Clear, testable and safe rest on the model's reading. With `evidence: all` each needs
  a quote that is checked to be in the ticket (12+ characters or most of its line), but the quote can still be read
  wrongly.
- **One ticket at a time.** No batch mode in this version. Sessions share one work folder: a ticket saved by another
  session stops this session's verdict (the sha256 check), and the ticket must be saved and checked again.
- **Pattern-based secret masking.** Known token formats are masked in all output. A secret in an unusual format can
  pass through. A password found in the ticket is hidden everywhere else only when it has 8+ characters with a
  letter and a digit; a shorter or letters-only one is masked where its pattern matches and kept out of searches,
  but could show if repeated elsewhere without its context.
  Lines of a tracked file that holds a private key header are never shown; a key whose header was removed is just
  base64 and can show.
