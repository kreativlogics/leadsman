"""Layered configuration: defaults < plugin option < user < project.

- User layer: the plugin's `preset` option (CLAUDE_PLUGIN_OPTION_PRESET), then
  <data dir>/config.json. Only this layer may loosen anything.
- Project layer: <repo>/.leadsman/config.json, committed with the repository.
  Safety keys only tighten (overlap on -> off, evidence code -> all, stale_days
  down). A loosening is ignored and reported, never applied silently.

leadsman has no keys that run programs, so nothing needs approval.
"""

import difflib
import json
import os
import tempfile

from . import repo
from . import secrets

SUPPORTED_VERSION = 1
PRESETS = ("solo", "standard", "strict")
CATEGORIES = ("backlog", "ready", "in_progress", "review", "testing", "done")

# Ordered safety values, loosest first.
ORDERS = {
    "overlap": ("on", "off"),
    "evidence": ("code", "all"),
}

# key -> (kind, class)
SCHEMA = {
    "version": ("int", "meta"),
    "preset": ("preset", "preset"),
    "overlap": ("order", "safety-order"),
    "evidence": ("order", "safety-order"),
    "stale_days": ("number", "safety-min"),
    "max_refs": ("number", "preference"),
    "exclude_paths": ("list", "preference"),
    "rules_file": ("path", "preference"),
    "status_map": ("status_map", "preference"),
}

DESCRIPTIONS = {
    "version": "Config format version. Leave at 1.",
    "preset": "solo (no overlap search), standard, or strict (evidence for every check, base older than a day is "
              "stale). Keys set below the preset override it.",
    "overlap": "on or off. Search the repository's GitHub issues and pull requests for overlapping work (sends the "
               "search words to github.com through gh). A project file can turn it off, not on.",
    "evidence": "code: the valid, reachable and references checks need file:line evidence. all: clear, testable and "
                "safe need a quote too. A project file can raise it, not lower it.",
    "stale_days": "A base branch fetched longer ago than this is reported as stale. A project file can lower it.",
    "max_refs": "How many references from one ticket are looked up (1-200).",
    "exclude_paths": "Path globs left out of searches, e.g. vendor/** or dist/**.",
    "rules_file": "Your team's readiness rules, a Markdown file inside the repository. Read as data.",
    "status_map": "Tracker status name -> backlog, ready, in_progress, review, testing or done. "
                  "Set by /leadsman:config statuses.",
}

PRESET_VALUES = {
    "solo": {"overlap": "off", "evidence": "code", "stale_days": 14},
    "standard": {"overlap": "on", "evidence": "code", "stale_days": 7},
    "strict": {"overlap": "on", "evidence": "all", "stale_days": 1},
}

DEFAULTS = {
    "preset": "standard",
    "overlap": "on",
    "evidence": "code",
    "stale_days": 7,
    "max_refs": 40,
    "exclude_paths": [],
    "rules_file": ".leadsman/rules.md",
    "status_map": {},
}


class ConfigError(Exception):
    pass


def _hint(key, choices):
    close = difflib.get_close_matches(key, list(choices), n=1)
    return " Did you mean %r?" % close[0] if close else ""


def validate(data, where):
    """Raise ConfigError with the path, what was expected, what was found and the fix."""
    if not isinstance(data, dict):
        raise ConfigError("%s: expected a JSON object, got %s." % (where, type(data).__name__))
    version = data.get("version", SUPPORTED_VERSION)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ConfigError("%s: version: expected an integer, got %r." % (where, version))
    if version > SUPPORTED_VERSION:
        raise ConfigError("%s: version %d is newer than this leadsman understands (%d). Update the plugin."
                          % (where, version, SUPPORTED_VERSION))
    for key, value in data.items():
        if key not in SCHEMA:
            raise ConfigError("%s: unknown key %r.%s" % (where, key, _hint(key, SCHEMA)))
        kind = SCHEMA[key][0]
        if kind == "preset" and value not in PRESETS:
            raise ConfigError("%s: preset: expected one of %s, got %r." % (where, ", ".join(PRESETS), value))
        if kind == "order" and value not in ORDERS[key]:
            raise ConfigError("%s: %s: expected one of %s, got %r." % (where, key, ", ".join(ORDERS[key]), value))
        if kind == "number":
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ConfigError("%s: %s: expected a whole number of 0 or more, got %r." % (where, key, value))
            if key == "max_refs" and not 1 <= value <= 200:
                raise ConfigError("%s: max_refs: expected 1 to 200, got %r." % (where, value))
        if kind == "list" and (not isinstance(value, list) or not all(isinstance(v, str) and v for v in value)):
            raise ConfigError("%s: %s: expected a list of non-empty strings." % (where, key))
        if kind == "list" and any("\x00" in v or v.startswith("/") or ".." in v.split("/") or not repo.encodable(v)
                                  for v in value):
            raise ConfigError("%s: %s: expected globs inside the repository (no leading /, no .., no NUL)."
                              % (where, key))
        if kind == "path":
            if (not isinstance(value, str) or not value or os.path.isabs(value) or ".." in value.split("/")
                    or not repo.encodable(value) or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
                raise ConfigError("%s: %s: expected a relative path inside the repository, got %r."
                                  % (where, key, value))
        if kind == "status_map":
            if not isinstance(value, dict):
                raise ConfigError("%s: status_map: expected an object of status name -> category." % where)
            for name, cat in value.items():
                if cat not in CATEGORIES:
                    raise ConfigError("%s: status_map.%s: expected one of %s, got %r."
                                      % (where, name, ", ".join(CATEGORIES), cat))
    for text in _strings(data):
        if secrets.scan_text(text, high_only=True):
            raise ConfigError("%s: a value looks like a real secret. Config files never hold secrets." % where)
    return data


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            for s in _strings(v):
                yield s
    elif isinstance(obj, list):
        for v in obj:
            for s in _strings(v):
                yield s


MAX_CONFIG_BYTES = 100000


def read_json(path):
    """The parsed file, None when it does not exist, or ConfigError for anything unusable."""
    if not os.path.lexists(path):
        return None
    if not os.path.isfile(path):
        raise ConfigError("%s: not a regular file." % path)
    try:
        if os.path.getsize(path) > MAX_CONFIG_BYTES:
            raise ConfigError("%s: larger than %d KB." % (path, MAX_CONFIG_BYTES // 1000))
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except RecursionError:
        raise ConfigError("%s: nested too deeply." % path)
    except OSError as exc:
        raise ConfigError("%s: cannot be read (%s)." % (path, exc.strerror))
    except ValueError as exc:
        raise ConfigError("%s: not valid JSON (%s)." % (path, exc))


def user_config_path(data_dir):
    return os.path.join(data_dir, "config.json") if data_dir else None


def project_config_path(project_dir):
    root = repo.repo_root(project_dir) if project_dir else None
    base = root or project_dir
    return os.path.join(base, ".leadsman", "config.json") if base else None


class Effective(object):
    """The resolved config, where each value came from, and what was ignored."""

    def __init__(self):
        self.values = dict((k, (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v))
                           for k, v in DEFAULTS.items())
        self.sources = dict((k, "default") for k in DEFAULTS)
        self.notes = []

    def get(self, key):
        return self.values.get(key)


def _apply_preset(eff, preset, label):
    eff.values["preset"] = preset
    eff.sources["preset"] = label
    for key, value in PRESET_VALUES[preset].items():
        eff.values[key] = value
        eff.sources[key] = "%s (preset %s)" % (label, preset)


def _apply_user(eff, layer, label):
    if "preset" in layer:
        _apply_preset(eff, layer["preset"], label)
    for key, value in layer.items():
        if key in ("version", "preset"):
            continue
        eff.values[key] = value
        eff.sources[key] = label


def _tighter(key, proposed, current):
    if SCHEMA[key][1] == "safety-order":
        order = ORDERS[key]
        return order.index(proposed) > order.index(current), order.index(proposed) < order.index(current)
    if SCHEMA[key][1] == "safety-min":
        return proposed < current, proposed > current
    return True, False


def _apply_project(eff, layer):
    label = "project config"
    proposed = {}
    if "preset" in layer:
        proposed.update(PRESET_VALUES[layer["preset"]])
    explicit = set(k for k in layer if k not in ("version", "preset"))
    for key, value in layer.items():
        if key not in ("version", "preset"):
            proposed[key] = value
    for key, value in proposed.items():
        cls = SCHEMA[key][1]
        if cls in ("safety-order", "safety-min"):
            tighter, looser = _tighter(key, value, eff.values[key])
            if tighter:
                eff.values[key] = value
                eff.sources[key] = label
            elif looser and (key in explicit or "preset" in layer):
                eff.notes.append("Ignored: the project config asks for %s = %r, looser than your %r. "
                                 "Only your own config can loosen it." % (key, value, eff.values[key]))
        elif key == "exclude_paths":
            eff.values[key] = sorted(set(eff.values[key]) | set(value))
            eff.sources[key] = "%s + %s" % (eff.sources[key], label)
        elif key == "status_map":
            _merge_project_statuses(eff, value, label)
        else:
            eff.values[key] = value
            eff.sources[key] = label


def _merge_project_statuses(eff, statuses, label):
    """A project may add statuses, but not change yours or map any to done (done lets Close be proposed)."""
    merged = dict(eff.values["status_map"])
    added = False
    for name, category in statuses.items():
        if name in merged and merged[name] != category:
            eff.notes.append("Ignored: the project config maps status %r to %s; your config says %s."
                             % (name, category, merged[name]))
        elif category == "done" and name not in merged:
            eff.notes.append("Ignored: the project config maps status %r to done. Only your own config can map "
                             "a status to done." % name)
        elif name not in merged:
            merged[name] = category
            added = True
    eff.values["status_map"] = merged
    if added:
        eff.sources["status_map"] = "%s + %s" % (eff.sources["status_map"], label)


def _env_layer():
    preset = os.environ.get("CLAUDE_PLUGIN_OPTION_PRESET", "").strip()
    return {"preset": preset} if preset else {}


def resolve(data_dir=None, project_dir=None):
    eff = Effective()
    env_layer = validate(_env_layer(), "plugin option preset")
    _apply_user(eff, env_layer, "plugin option")
    user_path = user_config_path(data_dir)
    user_file = read_json(user_path) if user_path else None
    if user_file is not None:
        validate(user_file, user_path)
        _apply_user(eff, user_file, "user config")
    proj_path = project_config_path(project_dir)
    proj_file = None
    if proj_path and os.path.lexists(proj_path):
        base = os.path.dirname(os.path.dirname(proj_path))
        if repo.safe_path(base, os.path.relpath(proj_path, base)) is None:
            eff.notes.append("Ignored: %s points outside the repository." % proj_path)
        else:
            try:
                proj_file = read_json(proj_path)
            except ConfigError as exc:
                eff.notes.append("Ignored the project config: %s" % exc)
    if proj_file is not None:
        # The project layer comes from the repository, so a broken one is skipped with a note, never fatal.
        try:
            validate(proj_file, proj_path)
        except ConfigError as exc:
            eff.notes.append("Ignored the project config: %s" % exc)
        else:
            _apply_project(eff, proj_file)
    return eff


def write_layer(path, data, inside=None):
    """Validate and write a config layer atomically. Returns the old content. inside: the folder it must stay in."""
    data.setdefault("version", SUPPORTED_VERSION)
    validate(data, path)
    old = read_json(path)
    folder = os.path.dirname(path)
    if inside is not None and repo.safe_path(inside, os.path.relpath(folder, inside)) is None:
        raise ConfigError("%s points outside the repository; not written." % folder)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        raise ConfigError("Cannot create %s (%s)." % (folder, exc.strerror))
    # mkstemp creates a new file (never follows a planted link); os.replace swaps a link at path, not its target.
    fd, tmp = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return old
