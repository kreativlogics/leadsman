# Changelog

## 0.1.0 (unreleased)

First release.

- `/leadsman:check`: reads a ticket (pasted, a GitHub issue through `gh`, or a link through a tracker connector you
  already have), looks up what it names in the repository, runs seven checks and gives one decision: Ready, Fix then
  ready, Ask, Duplicate, Close or Park.
- Every cited `file:line` is confirmed by a script (a committed file git tracks, line exists, a quote on or near it);
  unconfirmed evidence is dropped and code checks without it become unverified.
- Ticket, findings and report files stay in the plugin's data folder. The skills write ticket and findings text to a temp
  file with the Write tool and `save --from` copies it in, so ticket text never goes through the shell. `git` and `gh` run with a minimal environment.
- Duplicate and Close need a disproof by a fresh read-only agent; otherwise they become Ask.
- No git repository: the verdict is capped. Stale base: a banner with the `git fetch` to run. Never fetches.
- Overlap search over the repository's GitHub issues and pull requests (read-only `gh`).
- Instruction-like lines in the ticket are quoted in the report and not followed; secret values are masked.
- `/leadsman:config`: detect, presets (solo, standard, strict), layered config where a project file can only tighten,
  tracker status mapping with confidence, and a doctor.
