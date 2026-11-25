"""Regression tests for the first review round. Each fails without its fix."""

import json
import os
import subprocess
import sys
import time
import unittest

from helpers import CHECK, CFGTOOL, RepoCase

from leadsman import config, context, ghread, intake, probe, repo, verdict


class OutputPaths(RepoCase):
    """Scripts read and write ticket, findings and report files only inside the data folder."""

    def test_issue_has_no_out_option(self):
        outside = os.path.join(self.tmp, "home", "startup")
        res = subprocess.run([sys.executable, CHECK, "--data", self.data, "issue", "1", "--out", outside],
                             env=self.env, cwd=self.project, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True, timeout=60)
        self.assertEqual(res.returncode, 2)
        self.assertIn("unrecognized arguments", res.stderr)
        self.assertFalse(os.path.exists(outside))

    def test_verdict_out_outside_data_refused(self):
        self.init_repo()
        findings = self.write_findings(self.findings())
        outside = os.path.join(self.tmp, "home", "report.md")
        out = self.check("verdict", "--findings", findings, "--out", outside, expect=2)
        self.assertIn("data folder", out)
        self.assertFalse(os.path.exists(outside))

    def test_ticket_outside_data_refused(self):
        self.init_repo()
        outside = self.write("notes.md", "Fix `parse_config`.\n", root=self.home)
        out = self.check("prepare", "--ticket", outside, expect=2)
        self.assertIn("data folder", out)

    def test_findings_outside_data_refused(self):
        self.init_repo()
        outside = self.write("f.json", json.dumps(self.findings()), root=self.home)
        self.assertIn("data folder", self.check("verdict", "--findings", outside, expect=2))

    def test_verdict_out_write_error_exits_2(self):
        self.init_repo()
        findings = self.write_findings(self.findings())
        bad = os.path.join(self.data, "missing", "deeper", "report.md")
        self.check("verdict", "--findings", findings, "--out", bad, expect=2)

    def test_overlap_reads_title_from_ticket_file(self):
        ticket = self.ticket("# Export $(id) fails `for` big reports\n\nbody\n")
        self.assertEqual(ghread.title_words(open(ticket).read()), "export fails for big reports")


class Evidence(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()

    def confirm(self, item):
        return verdict.confirm_evidence(self.project, item)

    def test_git_internals_refused(self):
        ok, why = self.confirm({"file": ".git/HEAD", "line": 1, "quote": "ref: refs/heads/master"})
        self.assertIsNone(ok)

    def test_untracked_file_refused(self):
        self.write(".env", "TOKEN=abc\n")
        ok, why = self.confirm({"file": ".env", "line": 1, "quote": "TOKEN=abc"})
        self.assertIsNone(ok)
        self.assertIn("not tracked", why)

    def test_quote_required_and_not_trivial(self):
        for quote in (None, "", "o", "  )"):
            ok, why = self.confirm({"file": "src/app.py", "line": 4, "quote": quote})
            self.assertIsNone(ok, quote)
            self.assertIn("quote", why)


class Decide(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()
        self.ctx = context.gather(self.project)
        self.cfg = dict(config.DEFAULTS)

    def evaluate(self, data, cfg=None, ticket=None):
        return verdict.evaluate(data, self.ctx, cfg or self.cfg, ticket_text=ticket)

    def test_ready_error_names_only_blocking_checks(self):
        data = self.findings(check_clear={"status": "fail", "summary": "two readings",
                                          "evidence": [{"file": "src/app.py", "line": 4, "quote": "parse_config"}]},
                             check_safe={"status": "fail", "summary": "drops data",
                                         "evidence": [{"file": "src/app.py", "line": 4, "quote": "parse_config"}]})
        with self.assertRaises(verdict.FindingsError) as cm:
            self.evaluate(data)
        self.assertIn("clear", str(cm.exception))
        self.assertNotIn("safe", str(cm.exception))

    def test_stands_needs_notes(self):
        data = self.findings(decision="duplicate", duplicate_of="#3", disproof={"outcome": "stands"})
        with self.assertRaises(verdict.FindingsError) as cm:
            self.evaluate(data)
        self.assertIn("disproof.notes", str(cm.exception))

    def test_close_status_must_be_in_ticket_text(self):
        cfg = dict(self.cfg, status_map={"Done": "done"})
        data = self.findings(decision="close", reason="shipped", ticket={"title": "t", "status": "Done"},
                             disproof={"outcome": "stands", "notes": "nothing found against it"})
        self.assertEqual(self.evaluate(data, cfg, ticket="# t\n\nStill broken.\n")["decision"], "ask")
        self.assertEqual(self.evaluate(data, cfg, ticket="# t\nStatus: Done\n")["decision"], "close")

    def test_strict_ready_needs_verified_text_checks(self):
        cfg = dict(self.cfg, evidence="all")
        with self.assertRaises(verdict.FindingsError) as cm:
            self.evaluate(self.findings(), cfg, ticket="# t\n\nbody\n")
        self.assertIn("unverified", str(cm.exception))


class ProjectConfig(RepoCase):
    def test_project_status_map_cannot_override_or_map_done(self):
        self.init_repo()
        self.write_config({"status_map": {"Open": "backlog"}})
        self.write_config({"status_map": {"Open": "done", "Shipped": "done", "Doing": "in_progress"}},
                          where="project")
        eff = config.resolve(self.data, self.project)
        self.assertEqual(eff.get("status_map"), {"Open": "backlog", "Doing": "in_progress"})
        self.assertEqual(len(eff.notes), 2)

    def test_project_config_symlink_outside_ignored(self):
        self.init_repo()
        outside = self.write("outside.json", json.dumps({"hello_from_outside": 1}), root=self.home)
        os.makedirs(os.path.join(self.project, ".leadsman"))
        os.symlink(outside, os.path.join(self.project, ".leadsman", "config.json"))
        eff = config.resolve(self.data, self.project)
        self.assertEqual(eff.get("overlap"), "on")
        self.assertTrue(any("outside" in n for n in eff.notes))

    def test_config_path_is_directory_reported(self):
        os.makedirs(os.path.join(self.data, "config.json"))
        with self.assertRaises(config.ConfigError):
            config.resolve(self.data, self.project)

    def test_unset_on_broken_config_no_traceback(self):
        with open(os.path.join(self.data, "config.json"), "w") as fh:
            fh.write("{")
        out = self.cfg("unset", "overlap", expect=1)
        self.assertNotIn("Traceback", out)


class Context(RepoCase):
    def _clone(self, head_branch="master"):
        upstream = os.path.join(self.tmp, "upstream")
        os.makedirs(upstream)
        self.git("init", "-q", "-b", head_branch, cwd=upstream)
        self.write("a.txt", "1\n", root=upstream)
        self.git("add", "a.txt", cwd=upstream)
        self.git("commit", "-q", "-m", "one", cwd=upstream)
        os.rmdir(self.project)
        self.git("clone", "-q", upstream, self.project, cwd=self.tmp)

    def test_fresh_clone_not_stale(self):
        self._clone()
        ctx = context.gather(self.project)
        self.assertEqual(ctx["default_branch"], "master")
        self.assertFalse(ctx["stale"], ctx["stale_reason"])

    def test_odd_branch_name_not_put_in_command(self):
        self._clone(head_branch="x;touch${IFS}y")
        ctx = context.gather(self.project, now=time.time() + 30 * 86400)
        self.assertNotIn(";", ctx["fetch_command"] or "")
        self.assertNotIn("$", ctx["fetch_command"] or "")


class Probe(RepoCase):
    def test_issue_number_needs_boundary(self):
        self.init_repo()
        self.write("b.txt", "x\n")
        self.git("add", "b.txt")
        self.git("commit", "-q", "-m", "fix #123 thing")
        self.assertFalse(probe.probe_issue(self.project, "#12")["found"])
        self.assertTrue(probe.probe_issue(self.project, "#123")["found"])

    def test_grep_path_with_colon(self):
        self.init_repo({"we:ird.py": "needle_here = 1\n"})
        hits, total = probe.grep(self.project, "needle_here")
        self.assertEqual(total, 1)
        self.assertEqual(hits[0]["file"], "we:ird.py")

    def test_empty_file_note(self):
        self.init_repo({"empty.py": "", "a.py": "x\n"})
        out = probe.probe(self.project, [{"kind": "path", "value": "empty.py", "line": 1, "at_line": 3}])
        self.assertIn("empty", out[0]["note"])


class Parsing(unittest.TestCase):
    def test_standards_not_issue_refs(self):
        refs = [r["value"] for r in intake.extract_refs("Use UTF-8 and SHA-256 per ISO-8601; see ABC-12.")
                if r["kind"] == "issue"]
        self.assertEqual(refs, ["ABC-12"])

    def test_slug_needs_hash(self):
        with self.assertRaises(ghread.GhError):
            ghread.parse_issue("owner/repo123")


class Environment(unittest.TestCase):
    def test_subprocess_env_is_minimal(self):
        os.environ["LEADSMAN_TEST_SECRETISH"] = "x"
        try:
            env = repo.child_env()
        finally:
            del os.environ["LEADSMAN_TEST_SECRETISH"]
        self.assertNotIn("LEADSMAN_TEST_SECRETISH", env)
        self.assertIn("PATH", env)


if __name__ == "__main__":
    unittest.main()
