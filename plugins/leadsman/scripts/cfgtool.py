#!/usr/bin/env python3
"""leadsman settings.

  cfgtool.py show [--json]              Effective settings and where each came from.
  cfgtool.py explain <key>              What a key does and its current value.
  cfgtool.py set <key> <value> [--project] [--add|--remove]
                                        Change your config (or the project's with --project).
  cfgtool.py unset <key> [--project]    Remove a key from a layer.
  cfgtool.py detect [--json]            Look at this repository and machine; suggest settings.
  cfgtool.py init [--preset P] [--project] [--yes]
                                        Write a starting config from detect's suggestions (preview without --yes).
  cfgtool.py statuses --file F [--apply] [--project]
                                        Map tracker status names to categories (F: JSON list of names or
                                        {"name", "native"} objects). --apply saves high-confidence guesses
                                        and the ones you accepted.
  cfgtool.py doctor                     Check Python, git, gh, the data folder and the config.

Common: --data DIR, given once before the command. The repository is the current folder.
"""

import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True  # Never write __pycache__ into the plugin folder; only the data folder is written.

from leadsman import __version__, config, context, intake, probe, repo, secrets, statusmap, workfiles  # noqa: E402

VENDOR_DIRS = ("vendor", "node_modules", "dist", "build", "third_party", "external", ".venv", "Pods")


def _paths(args):
    data = args.data or os.environ.get("CLAUDE_PLUGIN_DATA")
    if not data:
        sys.exit("No data folder: pass --data (the skills pass the plugin's data folder).")
    project = os.path.realpath(os.getcwd())
    return data, project


def _resolve(data, project):
    try:
        return config.resolve(data, project)
    except config.ConfigError as exc:
        sys.exit("Config error: %s" % exc)


def cmd_show(args):
    data, project = _paths(args)
    eff = _resolve(data, project)
    if args.json:
        _print_json({"values": eff.values, "sources": eff.sources, "notes": eff.notes}, sort_keys=True)
        return
    print("Files: user %s | project %s" % (config.user_config_path(data), config.project_config_path(project)))
    for key in config.DEFAULTS:
        value = eff.get(key)
        # Strings are shown as JSON too, so a control character in a project config cannot forge a line.
        shown = json.dumps(secrets.mask_tree(value)) if isinstance(value, (list, dict, str)) else value
        print("%-14s %-40s (%s)" % (key, shown, eff.sources[key]))
    for note in eff.notes:
        print("Note: %s" % note)


def cmd_explain(args):
    data, project = _paths(args)
    eff = _resolve(data, project)
    if args.key not in config.SCHEMA:
        sys.exit("Unknown key %r.%s" % (args.key, config._hint(args.key, config.SCHEMA)))
    print("%s: %s" % (args.key, config.DESCRIPTIONS[args.key]))
    if args.key in config.DEFAULTS:
        print("Now: %s (from %s)" % (json.dumps(eff.get(args.key)), eff.sources[args.key]))
    cls = config.SCHEMA[args.key][1]
    if cls.startswith("safety"):
        print("A project file can only make this stricter.")


def _parse_value(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def _repo_of(args, path):
    """The repository a project layer must stay inside (its .leadsman folder's parent), or None for the user layer."""
    return os.path.dirname(os.path.dirname(path)) if args.project else None


def _layer_path(args, data, project):
    """The layer file. A project file that links out of the repository is refused before anything reads it."""
    if not args.project:
        return config.user_config_path(data)
    path = config.project_config_path(project)
    base = os.path.dirname(os.path.dirname(path)) if path else None
    if path and os.path.lexists(path) and repo.safe_path(base, os.path.relpath(path, base)) is None:
        sys.exit("Not changed: %s points outside the repository." % path)
    return path


def _read_layer(path):
    """The layer as a dict, or exit with a message when the file is broken or not an object."""
    try:
        layer = config.read_json(path)
    except config.ConfigError as exc:
        sys.exit("Not changed: %s Fix or remove it first." % exc)
    if layer is None:
        return {}
    if not isinstance(layer, dict) or not isinstance(layer.get("status_map", {}), dict):
        sys.exit("Not changed: %s must be a JSON object, with status_map an object. Fix or remove it first."
                 % path)
    return layer


def cmd_set(args):
    data, project = _paths(args)
    path = _layer_path(args, data, project)
    layer = _read_layer(path)
    key = args.key
    value = _parse_value(args.value)
    if key.startswith("status_map."):
        layer.setdefault("status_map", {})[key.split(".", 1)[1]] = value
    elif key in config.SCHEMA and config.SCHEMA[key][0] == "list" and (args.add or args.remove):
        current = layer.get(key)
        if current is not None and not isinstance(current, list):
            sys.exit("Not changed: %s in %s is not a list, so --add and --remove cannot change it."
                     % (key, path))
        items = list(current or [])
        if args.add and value not in items:
            items.append(value)
        if args.remove and value in items:
            items.remove(value)
        layer[key] = items
    else:
        layer[key] = value
    try:
        config.write_layer(path, layer, inside=_repo_of(args, path))
    except config.ConfigError as exc:
        sys.exit("Not saved: %s" % exc)
    print("Saved %s in %s." % (key, path))
    eff = _resolve(data, project)
    for note in eff.notes:
        print("Note: %s" % note)


def cmd_unset(args):
    data, project = _paths(args)
    path = _layer_path(args, data, project)
    layer = _read_layer(path)
    try:
        if args.key.startswith("status_map."):
            (layer.get("status_map") or {}).pop(args.key.split(".", 1)[1], None)
        else:
            layer.pop(args.key, None)
        config.write_layer(path, layer, inside=_repo_of(args, path))
    except config.ConfigError as exc:
        sys.exit("Not changed: %s" % exc)
    print("Removed %s from %s." % (args.key, path))


def detect(data, project):
    ctx = context.gather(project)
    root = ctx["repo_root"]
    facts = {
        "python": sys.version.split()[0],
        "git": ctx["git"],
        "repository": bool(root),
        "default_branch": ctx["default_branch"],
        "github_repo": ctx["github_repo"],
        "gh": ctx["gh"],
        "stale": ctx["stale_reason"],
        "rules_file": None,
        "vendor_dirs": [],
        "user_config": os.path.exists(config.user_config_path(data)),
        "project_config": bool(config.project_config_path(project))
        and os.path.exists(config.project_config_path(project)),
    }
    suggestions = []
    if root:
        for name in VENDOR_DIRS:
            if os.path.isdir(os.path.join(root, name)):
                code, out = repo.run_git(["ls-files", "--", name], cwd=root)
                if code == 0 and out.strip():
                    facts["vendor_dirs"].append(name)
        rules = repo.safe_path(root, config.DEFAULTS["rules_file"])
        facts["rules_file"] = config.DEFAULTS["rules_file"] if rules and os.path.isfile(rules[0]) else None
    if not root:
        suggestions.append({"key": "preset", "value": "solo",
                            "why": "no git repository here, so checks run on the ticket text only"})
    elif ctx["overlap_possible"]:
        suggestions.append({"key": "preset", "value": "standard",
                            "why": "gh and a GitHub remote are present, so overlap search can run"})
    else:
        suggestions.append({"key": "preset", "value": "solo",
                            "why": "overlap search is not possible here (%s)" % ctx["overlap_reason"]})
    for name in facts["vendor_dirs"]:
        suggestions.append({"key": "exclude_paths", "add": "%s/**" % name,
                            "why": "%s/ is committed third-party code; searching it adds noise" % name})
    if root and not facts["rules_file"]:
        suggestions.append({"key": "rules_file", "value": None,
                            "why": "no team rules file; add %s to check tickets against your own rules"
                                   % config.DEFAULTS["rules_file"]})
    return {"facts": facts, "suggestions": suggestions}


def cmd_detect(args):
    data, project = _paths(args)
    result = detect(data, project)
    if args.json:
        _print_json(result)
        return
    print("Found:")
    for k, v in result["facts"].items():
        print("  %s: %s" % (k, ", ".join(v) if isinstance(v, list) else v))
    print("Suggestions:")
    for s in result["suggestions"]:
        print("  %s: %s" % (s["key"], s["why"]))


def cmd_init(args):
    data, project = _paths(args)
    path = _layer_path(args, data, project)
    if not path:
        sys.exit("No project folder.")
    if os.path.exists(path) and not args.force:
        sys.exit("%s already exists. Use set to change it, or --force to start over." % path)
    result = detect(data, project)
    layer = {"version": config.SUPPORTED_VERSION}
    preset = args.preset or next((s["value"] for s in result["suggestions"] if s["key"] == "preset"), "standard")
    layer["preset"] = preset
    for s in result["suggestions"]:
        if s["key"] == "exclude_paths":
            layer.setdefault("exclude_paths", []).append(s["add"])
    if not args.yes:
        _print_json(layer, sort_keys=True)
        print("This is what init would write to %s. Run again with --yes to save it." % path)
        return
    try:
        config.write_layer(path, layer, inside=_repo_of(args, path))
    except config.ConfigError as exc:
        sys.exit("Not saved: %s" % exc)
    print("Saved %s." % path)


STATUSES_MAX = 200000


def cmd_statuses(args):
    data, project = _paths(args)
    try:
        items = json.loads(workfiles.read_handoff(args.file, STATUSES_MAX).decode("utf-8", errors="replace"))
    except RecursionError:
        sys.exit("Cannot read %s (nested too deeply)." % args.file)
    except ValueError as exc:
        sys.exit("Cannot read %s (%s)." % (args.file, exc))
    if not isinstance(items, list):
        sys.exit("Expected a JSON list of status names or {\"name\", \"native\"} objects.")
    guesses = statusmap.map_statuses(items[:200])
    # The user's answers travel in the file ({"name", "accept"}), so tracker-supplied names never reach a command line.
    accepted = {}
    for item in items[:200]:
        if isinstance(item, dict) and "accept" in item:
            name, cat = item.get("name"), item.get("accept")
            if not isinstance(name, str) or not name.strip() or cat not in config.CATEGORIES:
                sys.exit("\"accept\" needs a status name and one of %s." % ", ".join(config.CATEGORIES))
            accepted[name.strip()] = cat
    if not args.apply:
        _print_json({"guesses": guesses})
        return
    path = _layer_path(args, data, project)
    layer = _read_layer(path)
    mapping = dict(layer.get("status_map") or {})
    for g in guesses:
        if g["confidence"] == "high":
            mapping[g["name"]] = g["category"]
    mapping.update(accepted)
    layer["status_map"] = mapping
    try:
        config.write_layer(path, layer, inside=_repo_of(args, path))
    except config.ConfigError as exc:
        sys.exit("Not saved: %s" % exc)
    left = [g["name"] for g in guesses if g["name"] not in mapping]
    print("Saved %d status mappings in %s." % (len(mapping), path))
    if left:
        print("Not mapped (add \"accept\": CATEGORY to their entries in the file): %s" % ", ".join(left))
    # A project file may not map a status to done; say so now rather than let it look saved and working.
    for note in _resolve(data, project).notes:
        print("Note: %s" % note)


def cmd_doctor(args):
    data, project = _paths(args)
    problems = 0

    def line(ok, text, warn_only=False):
        nonlocal problems
        if not ok and not warn_only:
            problems += 1
        print("%s %s" % ("ok  " if ok else ("warn" if warn_only else "FAIL"), text))

    line(sys.version_info >= (3, 9), "Python %s (3.9 or newer needed)" % sys.version.split()[0])
    line(repo.git_available(), "git on PATH (without it, checks run on ticket text only)", warn_only=True)
    line(shutil.which("gh") is not None, "gh on PATH (without it, GitHub issues and overlap search are skipped)",
         warn_only=True)
    try:
        os.makedirs(data, exist_ok=True)
        probe_file = os.path.join(data, ".probe")
        workfiles.write_replace(probe_file, "x")
        os.unlink(probe_file)
        line(True, "data folder writable: %s" % data)
    except OSError as exc:
        line(False, "data folder not writable: %s (%s)" % (data, exc.strerror))
    try:
        eff = config.resolve(data, project)
        line(True, "config valid (preset %s)" % eff.get("preset"))
        for note in eff.notes:
            print("     note: %s" % note)
    except config.ConfigError as exc:
        eff = None
        line(False, "config: %s" % exc)
    ctx = context.gather(project)
    if ctx["repo_root"]:
        line(not ctx["stale"], "base branch fresh%s" % (": " + ctx["stale_reason"] if ctx["stale"] else ""),
             warn_only=True)
    if eff and eff.get("status_map"):
        print("     status map: %d statuses mapped" % len(eff.get("status_map")))
    start = time.time()
    sample = "Fix `parse_config` in src/config.py when \"Missing value\" appears."
    probe.probe(ctx["repo_root"], intake.analyse(sample)["refs"])
    line(True, "sample lookup ran in %.0f ms" % ((time.time() - start) * 1000))
    print("leadsman %s: %d problem(s)." % (__version__, problems))
    return 1 if problems else 0


def build_parser():
    p = argparse.ArgumentParser(prog="cfgtool", description="leadsman settings")
    # Given once, before the command: the skill pins --data, and a second value must not replace it.
    p.add_argument("--data", action=workfiles.Once)
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("show")
    s.add_argument("--json", action="store_true")
    e = sub.add_parser("explain")
    e.add_argument("key")
    st = sub.add_parser("set")
    st.add_argument("key")
    st.add_argument("value")
    st.add_argument("--project", action="store_true")
    st.add_argument("--add", action="store_true")
    st.add_argument("--remove", action="store_true")
    un = sub.add_parser("unset")
    un.add_argument("key")
    un.add_argument("--project", action="store_true")
    d = sub.add_parser("detect")
    d.add_argument("--json", action="store_true")
    i = sub.add_parser("init")
    i.add_argument("--preset", choices=config.PRESETS)
    i.add_argument("--project", action="store_true")
    i.add_argument("--yes", action="store_true")
    i.add_argument("--force", action="store_true")
    ss = sub.add_parser("statuses")
    ss.add_argument("--file", required=True)
    ss.add_argument("--apply", action="store_true")
    ss.add_argument("--project", action="store_true")
    sub.add_parser("doctor")
    return p


class _Masked(object):
    """A stream that masks secrets in everything written: config errors quote the values they reject."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        return self._stream.write(secrets.mask(text))

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _print_json(obj, sort_keys=False):
    """JSON with its values masked, written past the masking stream: masking the JSON text could break its syntax."""
    stream = sys.stdout._stream if isinstance(sys.stdout, _Masked) else sys.stdout
    stream.write(json.dumps(secrets.mask_tree(obj), indent=2, sort_keys=sort_keys) + "\n")


def main(argv=None):
    workfiles.safe_stdout()
    sys.stdout, sys.stderr = _Masked(sys.stdout), _Masked(sys.stderr)
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {"show": cmd_show, "explain": cmd_explain, "set": cmd_set, "unset": cmd_unset,
                "detect": cmd_detect, "init": cmd_init, "statuses": cmd_statuses, "doctor": cmd_doctor}
    if args.cmd not in handlers:
        parser.print_help()
        return 2
    return handlers[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
