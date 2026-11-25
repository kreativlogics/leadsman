#!/usr/bin/env python3
"""leadsman: check a ticket against the code.

  check.py save ticket|findings --from FILE
                                           Copy a ticket or findings file from a temp folder into
                                           DATA/work/ticket.md or DATA/work/findings.json (see workfiles.py).
  check.py prepare --ticket FILE        Read the ticket, look up what it names in the repository,
                                           and report what the checks can rely on (JSON).
  check.py issue <number|url>           Read a GitHub issue with gh (read-only) into DATA/work/ticket.md.
  check.py overlap --ticket FILE        Search this repository's GitHub issues and PRs for words from the
                                           ticket's title (read-only).
  check.py verdict --findings FILE [--json] [--out FILE]   (always against the saved work/ticket.md)
                                           Confirm the evidence, apply the decision rules, write the report.
  check.py version

Common: --data DIR (the plugin data folder; required unless CLAUDE_PLUGIN_DATA is set), given once before the
command. The repository is always the current folder, so a pre-approved command cannot be pointed at another.
Ticket, findings and report files must be inside the data folder.
Exit codes: 0 done, 2 bad input or config, 3 findings need revising (reasons on stdout).
Nothing here writes to a tracker, fetches from git, or runs text from the ticket.
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True  # Never write __pycache__ into the plugin folder; only the data folder is written.

from leadsman import __version__, config, context, ghread, intake, probe, repo, secrets, verdict, workfiles  # noqa: E402,E501

RULES_MAX = 20000
FINDINGS_MAX = 1000000
SAVE_NAMES = {"ticket": "ticket.md", "findings": "findings.json"}


def _paths(args):
    data = args.data or os.environ.get("CLAUDE_PLUGIN_DATA")
    if not data:
        _fail("No data folder: pass --data (the skills pass the plugin's data folder).")
    project = os.path.realpath(os.getcwd())
    return data, project


def _resolve(data, project):
    try:
        return config.resolve(data, project)
    except config.ConfigError as exc:
        _fail("Config error: %s" % exc)


def _fail(message, code=2):
    print(secrets.mask(message))
    sys.exit(code)


def _work_file(data, name):
    try:
        return workfiles.work_file(data, name)
    except OSError as exc:
        _fail("Cannot use the data folder %s (%s)." % (data, exc.strerror))


STATUS_LINE = re.compile(r"(?i)\s*status\s*:")


def _second_line(text):
    lines = text.split("\n")
    return lines[1] if len(lines) > 1 else ""


def _clear_work(data, names):
    """Remove earlier work files, so a refused save or a failed read never leaves the last run's files to be graded."""
    for name in names:
        path = _work_file(data, name)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            _fail("Cannot clear %s (%s)." % (path, exc.strerror))


def _dump(obj):
    # Mask the values, never the JSON text: a hidden value must not be able to replace JSON syntax.
    return json.dumps(secrets.mask_tree(obj), indent=2)


def _data_file(data, path, what):
    """path resolved inside the data folder, or exit 2. Keeps every file these commands touch in one place."""
    data_real = os.path.realpath(data)
    real = os.path.realpath(path)
    if real != data_real and not real.startswith(data_real + os.sep):
        _fail("The %s file must be inside the data folder (%s): %s" % (what, data_real, path))
    return real


def _replaces_saved(path, saved):
    """True when path names one of the saved files, in any letter case (macOS and Windows ignore case)."""
    if os.path.normcase(os.path.basename(path)).lower() in SAVE_NAMES.values():
        return True
    for other in saved:
        if os.path.normcase(path).lower() == os.path.normcase(other).lower():
            return True
        try:
            if os.path.exists(path) and os.path.exists(other) and os.path.samefile(path, other):
                return True
        except OSError:
            return True
    return False


def _write_text(path, text):
    """Write through a new temp file and a rename, so a link planted at path is replaced, never followed."""
    try:
        workfiles.write_replace(path, text)
    except OSError as exc:
        _fail("Cannot write %s (%s)." % (path, exc.strerror))


def _read_ticket(data, path):
    path = _data_file(data, path, "ticket")
    try:
        with open(path, "rb") as fh:
            raw = fh.read(intake.MAX_BYTES + 1)
    except OSError as exc:
        _fail("Cannot read the ticket file %s (%s)." % (path, exc.strerror))
    try:
        text = intake.load(raw)
    except intake.IntakeError as exc:
        _fail(str(exc))
    secrets.remember(secrets.found_values(text, everywhere=True))
    return text


def _team_rules(root, rules_file):
    if not root:
        return None, "no repository"
    resolved = repo.safe_path(root, rules_file)
    if resolved is None:
        return None, "%s is outside the repository; ignored" % rules_file
    real, rel = resolved
    if not os.path.isfile(real):
        return None, "no %s" % rel
    if not repo.is_tracked(root, rel):
        return None, "%s is not tracked by git; ignored" % rel
    try:
        with open(real, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read(RULES_MAX + 1)
    except OSError:
        return None, "%s could not be read" % rel
    if secrets.holds_private_key(text):
        return None, "%s holds a private key; ignored" % rel
    note = "%s (cut at %d characters)" % (rel, RULES_MAX) if len(text) > RULES_MAX else rel
    if len(text) > RULES_MAX:
        # Drop the partial word at the cut, so a secret straddling it is dropped rather than shown in part.
        text = re.sub(r"\S*$", "", text[:RULES_MAX])
    return secrets.mask(text), note


def cmd_save(args):
    """Copy the ticket or findings the model wrote to a temp file into the work folder."""
    data, _ = _paths(args)
    # A new ticket makes the old findings and report stale; new findings make the old report stale.
    _clear_work(data, ["ticket.md", "findings.json", "report.md"] if args.kind == "ticket"
                else ["findings.json", "report.md"])
    limit = intake.MAX_BYTES if args.kind == "ticket" else FINDINGS_MAX
    try:
        raw = workfiles.read_handoff(args.from_file, limit)
    except ValueError as exc:
        _fail("Not saved: %s." % exc)
    if args.kind == "ticket":
        try:
            text = intake.load(raw)
        except intake.IntakeError as exc:
            _fail(str(exc))
        # Checked before a lone carriage return becomes a line break: a title holding one would push its second
        # half onto line 2, the status line.
        plain = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
        if "\r" in plain.split("\n", 2)[0]:
            _fail("Line 1 of the ticket must be its title alone, with no line breaks in it.")
        if not STATUS_LINE.match(_second_line(text)) or not STATUS_LINE.match(_second_line(plain)):
            _fail("Line 2 of the ticket must be its status line: `Status: <status>`, or `Status:` alone when the "
                  "tracker gave none. Put the body after it.")
    else:
        if len(raw) > FINDINGS_MAX:
            _fail("The findings are larger than %d KB." % (FINDINGS_MAX // 1000))
        text = raw.decode("utf-8", errors="replace")
        try:
            json.loads(text)
        except RecursionError:
            _fail("The findings are not valid JSON (nested too deeply).")
        except ValueError as exc:
            _fail("The findings are not valid JSON (%s)." % exc)
    path = _work_file(data, SAVE_NAMES[args.kind])
    _write_text(path, text)
    print("Saved %s" % path)


def cmd_prepare(args):
    data, project = _paths(args)
    eff = _resolve(data, project)
    text = _read_ticket(data, args.ticket)
    info = intake.analyse(text, max_refs=eff.get("max_refs"))
    ctx = context.gather(project, stale_days=eff.get("stale_days"))
    root = ctx["repo_root"]
    probes = probe.probe(root, info["refs"], exclude=eff.get("exclude_paths"), max_refs=eff.get("max_refs"))
    rules_text, rules_note = _team_rules(root, eff.get("rules_file"))
    overlap = "on" if eff.get("overlap") == "on" and ctx["overlap_possible"] else "skipped"
    out = {
        "leadsman": __version__,
        "ticket": {k: info[k] for k in ("sha256", "chars", "lines", "secrets", "secrets_total",
                                                "instruction_lines")},
        "context": ctx,
        "mode": "code" if root else "text-only (no git repository: code checks are capped)",
        "overlap": overlap,
        "overlap_reason": None if overlap == "on" else (
            "turned off in config" if eff.get("overlap") == "off" else ctx["overlap_reason"]),
        "evidence_level": eff.get("evidence"),
        "status_map": eff.get("status_map"),
        "references": probes,
        "team_rules": rules_text,
        "team_rules_note": rules_note,
        "team_rules_instruction_lines": intake.instruction_lines(rules_text) if rules_text else [],
        "config_notes": eff.notes,
    }
    shown = secrets.mask_tree(out)
    # Hashes leadsman computed itself are shown whole: a ticket naming a piece of one as a secret could otherwise
    # hide it, and findings could never carry the right sha256.
    shown["ticket"]["sha256"] = info["sha256"]
    shown["context"]["head"] = ctx["head"]
    print(json.dumps(shown, indent=2))


MAX_COMMENTS = 30


def _cut_note(cut, left_out):
    notes = []
    if left_out:
        notes.append("%d comments in the middle were left out (the first 5 and the newest %d were kept)"
                     % (left_out, MAX_COMMENTS - 5))
    if cut:
        notes.append("the issue is larger than %d KB, so only its first part was saved" % (intake.MAX_BYTES // 1000))
    if not notes:
        return None
    text = "; ".join(notes)
    return text[0].upper() + text[1:] + ". Tell the user."


def cmd_issue(args):
    data, project = _paths(args)
    _clear_work(data, ["ticket.md", "findings.json", "report.md"])
    ctx = context.gather(project)
    try:
        issue = ghread.issue_view(args.ref, default_repo=ctx["github_repo"])
    except ghread.GhError as exc:
        _fail(str(exc))
    if not isinstance(issue, dict):
        _fail("gh returned no issue.")
    state = " ".join(str(issue.get(k)) for k in ("state", "stateReason") if issue.get(k))
    title = " ".join(str(issue.get("title") or "").split())
    parts = ["# %s" % title, "State: %s" % (state or "unknown"), "",
             issue.get("body") or ""]
    comments = [c for c in (issue.get("comments") or []) if isinstance(c, dict)]
    left_out = max(0, len(comments) - MAX_COMMENTS)
    if left_out:
        # Keep the first few and the newest: the latest comments are the likeliest to say "fixed" or "won't fix".
        comments = comments[:5] + [None] + comments[-(MAX_COMMENTS - 5):]
    for comment in comments:
        if comment is None:
            parts += ["", "---", "(%d comments in between were left out.)" % left_out]
        else:
            author = (comment.get("author") or {}).get("login", "someone") if isinstance(
                comment.get("author"), dict) else "someone"
            parts += ["", "---", "Comment by %s:" % author, comment.get("body") or ""]
    text = "\n".join(parts)
    secrets.remember(secrets.found_values(text, everywhere=True))
    # A lone surrogate cannot be written as UTF-8; it becomes "?" rather than stopping the run.
    raw = text.encode("utf-8", "replace")
    cut = len(raw) > intake.MAX_BYTES
    try:
        # Cut on a character boundary, and say so: a silent cut would check part of the issue as if it were all.
        text = intake.load(raw[:intake.MAX_BYTES].decode("utf-8", errors="ignore"))
    except intake.IntakeError as exc:
        _fail(str(exc))
    out_path = _work_file(data, "ticket.md")
    _write_text(out_path, text)
    labels = [lb.get("name") for lb in (issue.get("labels") or []) if isinstance(lb, dict)]
    print(_dump({"ticket_file": out_path, "number": issue.get("number"), "title": issue.get("title"),
                 "state": issue.get("state"), "state_reason": issue.get("stateReason"),
                 "closed_at": issue.get("closedAt"), "labels": labels, "url": issue.get("url"),
                 "cut": _cut_note(cut, left_out)}))


def cmd_overlap(args):
    data, project = _paths(args)
    eff = _resolve(data, project)
    if eff.get("overlap") != "on":
        print(json.dumps({"skipped": "overlap search is turned off in config (%s)" % eff.sources["overlap"]}))
        return
    ctx = context.gather(project)
    if not ctx["overlap_possible"]:
        print(json.dumps({"skipped": ctx["overlap_reason"]}))
        return
    try:
        result = ghread.overlap(_read_ticket(data, args.ticket), ctx["github_repo"])
    except ghread.GhError as exc:
        print(_dump({"skipped": str(exc)}))
        return
    print(_dump(result))


def cmd_verdict(args):
    data, project = _paths(args)
    eff = _resolve(data, project)
    findings_path = _data_file(data, args.findings, "findings")
    out_path = _data_file(os.path.dirname(_work_file(data, "report.md")), args.out, "report") if args.out else None
    if out_path and _replaces_saved(out_path, [findings_path] + [_work_file(data, n) for n in SAVE_NAMES.values()]):
        # The report must never replace the saved ticket or the findings it was built from.
        _fail("The report cannot overwrite the saved ticket or findings: %s" % args.out)
    try:
        with open(findings_path, "r", encoding="utf-8") as fh:
            findings = json.load(fh)
    except (OSError, ValueError, RecursionError) as exc:
        _fail("Cannot read findings %s (%s)." % (args.findings, exc))
    # Always the saved ticket: a chosen file (the findings, say) would make any quote "found".
    ticket_path = os.path.join(data, "work", "ticket.md")
    if not os.path.isfile(ticket_path):
        _fail("No saved ticket. Run `save ticket` first.")
    if os.stat(findings_path).st_mtime_ns < os.stat(ticket_path).st_mtime_ns:
        _fail("The findings are older than the saved ticket, so they may be for another ticket. Check this ticket "
              "and save its findings again.")
    ticket_text = _read_ticket(data, ticket_path)
    # The work folder is shared by every session: the findings name the ticket they were made for by its sha256.
    given = findings.get("ticket") if isinstance(findings, dict) else None
    given = given.get("sha256") if isinstance(given, dict) else None
    if given != intake.analyse(ticket_text)["sha256"]:
        _fail("findings.ticket.sha256 must be the sha256 that prepare printed for the saved ticket, and it is %s. "
              "If another session saved a ticket since, save this ticket again and run prepare and the checks again."
              % ("missing" if not given else "different"))
    ctx = context.gather(project, stale_days=eff.get("stale_days"))
    try:
        result = verdict.evaluate(findings, ctx, eff.values, ticket_text=ticket_text)
    except verdict.FindingsError as exc:
        print("Findings need revising:")
        for p in exc.problems:
            # Problems quote model-written names and text: control characters become spaces, as in the report.
            print("- %s" % verdict._CONTROL.sub(" ", secrets.mask(p)))
        sys.exit(3)
    overlap_note = None
    if eff.get("overlap") != "on":
        overlap_note = "Overlap search was off (config), so open issues and pull requests were not checked."
    elif not ctx["overlap_possible"]:
        overlap_note = "Overlap search was skipped: %s." % ctx["overlap_reason"]
    elif isinstance(findings.get("overlap"), dict) and findings["overlap"].get("skipped"):
        overlap_note = "Overlap search was skipped: %s." % secrets.mask(" ".join(str(findings["overlap"]["skipped"]).split()))[:200]
    injected = intake.analyse(ticket_text)["instruction_lines"]
    # The team rules are read again here, so their lines addressed to an AI are listed in the report itself.
    rules_text, _ = _team_rules(ctx["repo_root"], eff.get("rules_file"))
    rules_injected = intake.instruction_lines(rules_text) if rules_text else []
    report = verdict.render(result, ctx, findings, overlap_note, instruction_lines=injected, ticket_text=ticket_text,
                            rules_instruction_lines=rules_injected)
    if out_path:
        _write_text(out_path, report)
    if args.json:
        print(_dump(result))
    else:
        sys.stdout.write(report)


def build_parser():
    p = argparse.ArgumentParser(prog="check.py", description="Check a ticket against the code.")
    # Given once, before the command: the skill pins --data, and a second value must not replace it.
    p.add_argument("--data", action=workfiles.Once)
    sub = p.add_subparsers(dest="cmd")
    sv = sub.add_parser("save")
    sv.add_argument("kind", choices=sorted(SAVE_NAMES))
    sv.add_argument("--from", dest="from_file", required=True)
    pr = sub.add_parser("prepare")
    pr.add_argument("--ticket", required=True)
    iss = sub.add_parser("issue")
    iss.add_argument("ref")
    ov = sub.add_parser("overlap")
    ov.add_argument("--ticket", required=True)
    vd = sub.add_parser("verdict")
    vd.add_argument("--findings", required=True)
    vd.add_argument("--json", action="store_true")
    vd.add_argument("--out")
    sub.add_parser("version")
    return p


def _is_data_option(arg):
    name = arg.split("=", 1)[0]
    return len(name) >= 3 and "--data".startswith(name)


def _clear_after_refused(argv):
    """A `save` or `issue` refused by the argument parser still clears the earlier work files, as a refused save does.

    The arguments are read by hand: the first --data is the pinned one (a later one is refused), and an issue
    reference must not be taken for the kind of a save.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    data = None
    rest = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if _is_data_option(arg):
            value = arg.split("=", 1)[1] if "=" in arg else (argv[i + 1] if i + 1 < len(argv) else None)
            if data is None:
                data = value
            i += 1 if "=" in arg else 2
            continue
        rest.append(arg)
        i += 1
    data = data or os.environ.get("CLAUDE_PLUGIN_DATA")
    if not rest or rest[0] not in ("save", "issue") or not data or not os.path.isdir(data):
        return
    if rest[0] == "save" and len(rest) > 1 and rest[1] == "findings":
        _clear_work(data, ["findings.json", "report.md"])
    else:
        _clear_work(data, ["ticket.md", "findings.json", "report.md"])


def main(argv=None):
    workfiles.safe_stdout()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code:
            _clear_after_refused(argv)
        raise
    if args.cmd == "version":
        print("leadsman %s" % __version__)
        return 0
    handlers = {"save": cmd_save, "prepare": cmd_prepare, "issue": cmd_issue, "overlap": cmd_overlap, "verdict": cmd_verdict}
    if args.cmd not in handlers:
        parser.print_help()
        return 2
    return handlers[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
