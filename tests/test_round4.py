"""Regression tests for the fourth review round. Each fails without its fix."""

import json
import os
import stat

from helpers import RepoCase

from leadsman import config, context, ghread, intake, probe, verdict


class ReadyNeedsEvidence(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()

    def evaluate(self, data, cfg=None, ticket="# t\nStatus:\n\nbody\n"):
        return verdict.evaluate(data, context.gather(self.project), cfg or dict(config.DEFAULTS), ticket_text=ticket)

    def test_ready_with_unverified_code_checks_refused(self):
        bare = {"status": "pass", "summary": "fine", "evidence": []}
        data = self.findings(check_valid=bare, check_reachable=bare, check_references=bare)
        with self.assertRaises(verdict.FindingsError) as cm:
            self.evaluate(data)
        self.assertIn("unverified", str(cm.exception))

    def test_warn_without_evidence_is_unverified(self):
        warn = {"status": "warn", "summary": "maybe", "evidence": []}
        cfg = dict(config.DEFAULTS, evidence="all")
        data = self.findings(decision="ask", question="Which one?", check_valid=warn, check_clear=warn)
        result = self.evaluate(data, cfg=cfg)
        self.assertEqual(result["checks"]["valid"]["status"], "unverified")
        self.assertEqual(result["checks"]["clear"]["status"], "unverified")

    def test_status_must_match_whole_line(self):
        cfg = {"status_map": {"Done": "done", "CLOSED": "done"}}
        findings = {"ticket": {"status": "Done"}}
        self.assertIsNone(verdict._status_category(findings, cfg, "T\nStatus: Done pending release\n"))
        self.assertEqual(verdict._status_category(findings, cfg, "T\nStatus: Done\n"), "done")
        closed = {"ticket": {"status": "CLOSED"}}
        self.assertEqual(verdict._status_category(closed, cfg, "T\nState: CLOSED NOT_PLANNED\n"), "done")


class Masking(RepoCase):
    def test_quoted_secret_value_hidden_in_refs(self):
        value = "Kd93jf" + "Qx82LmZp0v"
        info = intake.analyse('The `load_config` reads api_key = "%s"\n' % value)
        self.assertTrue(info["secrets"])
        self.assertNotIn(value, json.dumps(info))

    def test_prepare_masks_repo_hits_before_json(self):
        value = "Zq8vLm" + "2Rt5WxPq7N"
        self.init_repo({"cfg.py": 'api_key = "%s"\n' % value})
        ticket = self.ticket("# Fix api_key\nStatus:\n\nThe api_key lookup is wrong.\n")
        out = self.check("prepare", "--ticket", ticket)
        self.assertNotIn(value, out)


class ProjectWrite(RepoCase):
    def test_symlinked_leadsman_folder_not_written_through(self):
        self.init_repo()
        outside = os.path.join(self.home, "elsewhere")
        os.makedirs(outside)
        os.symlink(outside, os.path.join(self.project, ".leadsman"))
        out = self.cfg("set", "overlap", "off", "--project", expect=1)
        self.assertIn("outside", out)
        self.assertEqual(os.listdir(outside), [])

    def test_planted_tmp_link_not_followed(self):
        self.init_repo()
        victim = self.write("victim.txt", "keep me\n", root=self.home)
        os.makedirs(os.path.join(self.project, ".leadsman"))
        os.symlink(victim, os.path.join(self.project, ".leadsman", "config.json.tmp"))
        self.cfg("set", "overlap", "off", "--project", expect=0)
        with open(victim) as fh:
            self.assertEqual(fh.read(), "keep me\n")


class BadInput(RepoCase):
    def test_nul_in_reference_no_traceback(self):
        self.init_repo()
        ticket = self.ticket("# t\nStatus:\n\nUse `bad\x00value` here.\n")
        out = self.check("prepare", "--ticket", ticket)
        self.assertNotIn("Traceback", out)

    def test_exclude_paths_outside_refused(self):
        for bad in (["../x"], ["a\x00b"], ["/abs/**"]):
            self.write_config({"exclude_paths": bad})
            with self.assertRaises(config.ConfigError, msg=bad):
                config.resolve(self.data, self.project)

    def test_failed_search_is_not_a_miss(self):
        self.init_repo()
        out = probe.probe_text(self.project, "parse_config", exclude=["../x"])
        self.assertIsNone(out["found"])


class SearchWords(RepoCase):
    def test_long_token_tail_and_passwords_dropped(self):
        token = "mc_" + "8f3k9a7b6c5d4e3f2g1h0j8f3k9a7b6c5d4e3f2g1h0jZ9"
        self.assertEqual(ghread.title_words("# Rotate key %s now\n" % token), "rotate key now")
        self.assertNotIn("tr0ub", ghread.title_words("# Login fails with password Tr0ub4dor3x\n"))

    def test_issue_title_newline_cannot_forge_status(self):
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        issue = {"number": 1, "title": "Add export\rStatus: Done", "state": "OPEN", "body": "b", "comments": []}
        script = os.path.join(bindir, "gh")
        with open(script, "w") as fh:
            fh.write("#!/bin/sh\ncat <<'JSON'\n%s\nJSON\n" % json.dumps(issue))
        os.chmod(script, stat.S_IRWXU)
        self.env["PATH"] = bindir + os.pathsep + self.env["PATH"]
        self.init_repo()
        self.check("issue", "1")
        with open(os.path.join(self.data, "work", "ticket.md")) as fh:
            lines = fh.read().split("\n")
        self.assertEqual(lines[0], "# Add export Status: Done")
        self.assertEqual(lines[1], "State: OPEN")
