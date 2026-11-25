"""Test helpers: a throwaway git repository, data folder and CLI runners.

Secret-shaped test values are assembled from pieces at run time, so no
token-shaped string sits in the repository.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "plugins", "leadsman", "scripts")
CHECK = os.path.join(SCRIPTS, "check.py")
CFGTOOL = os.path.join(SCRIPTS, "cfgtool.py")
sys.path.insert(0, SCRIPTS)
# Keep compiled files out of the plugin folder: a shipped .pyc can run instead of its source.
sys.dont_write_bytecode = True

from leadsman import intake  # noqa: E402


def fake(kind):
    body = "Q7w9ErT2yU4iO6pA8sD1fG3hJ5kL0zX"
    if kind == "github":
        return "gh" + "p_" + body + "abcde"
    if kind == "aws-id":
        return "AK" + "IA" + "QW7ER9TY2UI4OP6A"
    raise KeyError(kind)


APP_PY = """\
import os


def parse_config(path):
    if not os.path.exists(path):
        raise ValueError("Missing config file")
    return {}


class ReportBuilder:
    def render_total(self, rows):
        return sum(r.amount for r in rows)
"""

ROUTES_PY = """\
ROUTES = {
    "/api/reports/export": "export_report",
    "/settings/profile": "profile",
}
"""


class RepoCase(unittest.TestCase):
    """A temp data folder and a project; init_repo() makes the project a git repository."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="leadsman-test-"))
        self.data = os.path.join(self.tmp, "data")
        self.project = os.path.join(self.tmp, "project")
        self.home = os.path.join(self.tmp, "home")
        for d in (self.data, self.project, self.home):
            os.makedirs(d)
        self.env = {
            "HOME": self.home,
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": tempfile.gettempdir(),
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
        self._old_env = dict(os.environ)
        os.environ.update({k: v for k, v in self.env.items() if k != "PATH"})
        os.environ.pop("CLAUDE_PLUGIN_OPTION_PRESET", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args, cwd=None):
        return subprocess.run(["git"] + list(args), cwd=cwd or self.project, env=self.env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, check=True)

    def write(self, rel, text, root=None):
        path = os.path.join(root or self.project, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def init_repo(self, files=None, message="first"):
        self.git("init", "-q", "-b", "master")
        for rel, text in (files if files is not None else {"src/app.py": APP_PY,
                                                             "src/routes.py": ROUTES_PY}).items():
            self.write(rel, text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def ticket(self, text, name="ticket.md"):
        return self.write(name, text, root=self.data)

    def run_cli(self, script, *args, expect=0):
        res = subprocess.run([sys.executable, script, "--data", self.data]
                             + list(args), env=self.env, cwd=self.project, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        self.assertEqual(res.returncode, expect, res.stdout + res.stderr)
        self.assertEqual(res.stderr, "", res.stderr)
        return res.stdout

    def check(self, *args, expect=0):
        return self.run_cli(CHECK, *args, expect=expect)

    def cfg(self, *args, expect=None):
        res = subprocess.run([sys.executable, CFGTOOL, "--data", self.data]
                             + list(args), env=self.env, cwd=self.project, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        if expect is not None:
            self.assertEqual(res.returncode, expect, res.stdout + res.stderr)
        return res.stdout + res.stderr

    def findings(self, **over):
        checks = {
            "valid": {"status": "pass", "summary": "parse_config still raises",
                      "evidence": [{"file": "src/app.py", "line": 6, "quote": "Missing config file"}]},
            "reachable": {"status": "pass", "summary": "route exists",
                          "evidence": [{"file": "src/routes.py", "line": 2,
                                        "quote": "\"/api/reports/export\": \"export_report\""}]},
            "references": {"status": "pass", "summary": "all names found",
                           "evidence": [{"file": "src/app.py", "line": 4, "quote": "def parse_config(path):"}]},
            "clear": {"status": "pass", "summary": "one reading"},
            "testable": {"status": "pass", "summary": "error message is observable"},
            "safe": {"status": "pass", "summary": "no data change"},
            "size_overlap": {"status": "pass", "summary": "one file"},
        }
        data = {"ticket": {"title": "Better config error", "source": "pasted"}, "checks": checks,
                "decision": "ready"}
        for k, v in over.items():
            if k.startswith("check_"):
                checks[k[6:]] = v
            else:
                data[k] = v
        return data

    def write_findings(self, data, ticket="# Better config error\nStatus:\n\nShow the path in the error.\n"):
        """Write the findings, and the saved ticket that verdict always reads (unless one is saved already)."""
        saved = os.path.join(self.data, "work", "ticket.md")
        if not os.path.exists(saved):
            os.makedirs(os.path.dirname(saved), exist_ok=True)
            with open(saved, "w") as fh:
                fh.write(ticket)
        if isinstance(data, dict) and isinstance(data.get("ticket"), dict) and "sha256" not in data["ticket"]:
            # Verdict needs the sha256 that prepare prints for the saved ticket.
            with open(saved, "rb") as fh:
                text = intake.load(fh.read())
            data = dict(data, ticket=dict(data["ticket"], sha256=intake.analyse(text)["sha256"]))
        path = os.path.join(self.data, "findings.json")
        with open(path, "w") as fh:
            json.dump(data, fh)
        return path

    def write_config(self, data, where="user"):
        if where == "user":
            path = os.path.join(self.data, "config.json")
        else:
            path = os.path.join(self.project, ".leadsman", "config.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(data, fh)
        return path
