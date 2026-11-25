"""Regression tests for the fifth review round. Each fails without its fix."""

import json
import os
import shutil
import stat
import tempfile
import unittest

from helpers import RepoCase

from leadsman import config, context, ghread, verdict

# A password-shaped value built from pieces, so none sits in the repository whole.
PASSWORD_VALUE = "Zq8" + "Lm4vRt9" + "wXk2Pn"


class IssueOutputMasked(RepoCase):
    def test_password_in_title_is_masked(self):
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        title = 'Login fails with password="%s"' % PASSWORD_VALUE
        issue = {"number": 1, "title": title, "state": "OPEN", "body": "b", "comments": []}
        script = os.path.join(bindir, "gh")
        with open(script, "w") as fh:
            fh.write("#!/bin/sh\ncat <<'JSON'\n%s\nJSON\n" % json.dumps(issue))
        os.chmod(script, stat.S_IRWXU)
        self.env["PATH"] = bindir + os.pathsep + self.env["PATH"]
        self.init_repo()
        out = self.check("issue", "1")
        self.assertNotIn(PASSWORD_VALUE, out)


class WorkFileLink(RepoCase):
    def test_planted_link_is_replaced_not_followed(self):
        self.init_repo()
        victim = self.write("victim.txt", "keep me\n", root=self.home)
        work = os.path.join(self.data, "work")
        os.makedirs(work, exist_ok=True)
        os.symlink(victim, os.path.join(work, "ticket.md"))
        drop = tempfile.mkdtemp(prefix="leadsman-handoff-")
        self.addCleanup(shutil.rmtree, drop, True)
        src = os.path.join(drop, "t.md")
        with open(src, "w") as fh:
            fh.write("# Fix export\nStatus: Open\n\nbody\n")
        self.check("save", "ticket", "--from", src)
        with open(victim) as fh:
            self.assertEqual(fh.read(), "keep me\n")
        self.assertFalse(os.path.islink(os.path.join(work, "ticket.md")))


class QuoteStrength(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()

    def test_short_fragment_refused(self):
        for quote in ("par", "def", "ret", "path"):
            ok, why = verdict.confirm_evidence(self.project, {"file": "src/app.py", "line": 4, "quote": quote})
            self.assertIsNone(ok, quote)
            self.assertIn("fragment", why)

    def test_long_or_whole_line_quote_accepted(self):
        ok, why = verdict.confirm_evidence(self.project, {"file": "src/app.py", "line": 4,
                                                          "quote": "def parse_config"})
        self.assertIsNotNone(ok, why)

    def test_short_ticket_quote_refused(self):
        raw = {"status": "pass", "summary": "clear", "ticket_quote": "the"}
        self.assertFalse(verdict._has_ticket_quote(raw, "# t\n\nExport the report as CSV.\n"))
        raw["ticket_quote"] = "Export the report"
        self.assertTrue(verdict._has_ticket_quote(raw, "# t\n\nExport the report as CSV.\n"))


class SplitKeys(unittest.TestCase):
    def test_key_split_by_slash_or_plus_not_searched(self):
        key = "aB3dE5" + "/" + "fG7hJ9" + "+" + "kL2mN4"
        self.assertEqual(ghread.title_words("# Rotate %s now\n" % key), "rotate now")


class ProjectConfigErrors(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()

    def test_invalid_project_config_ignored_with_note(self):
        self.write_config({"overlap": 5}, where="project")
        eff = config.resolve(self.data, self.project)
        self.assertEqual(eff.get("overlap"), "on")
        self.assertTrue(any("Ignored the project config" in n for n in eff.notes))

    def test_broken_project_json_ignored_with_note(self):
        os.makedirs(os.path.join(self.project, ".leadsman"))
        self.write(".leadsman/config.json", "{not json")
        eff = config.resolve(self.data, self.project)
        self.assertTrue(any("Ignored the project config" in n for n in eff.notes))

    def test_dangling_project_folder_link_no_traceback(self):
        os.symlink(os.path.join(self.project, "nowhere"), os.path.join(self.project, ".leadsman"))
        out = self.cfg("set", "overlap", "off", "--project", expect=1)
        self.assertNotIn("Traceback", out)


class StatusCase(RepoCase):
    def test_status_mapping_ignores_case(self):
        self.init_repo()
        cfg = dict(config.DEFAULTS, status_map={"Done": "done"})
        data = self.findings(decision="close", reason="shipped", ticket={"title": "t", "status": "done"},
                             disproof={"outcome": "stands", "notes": "nothing found against it"})
        out = verdict.evaluate(data, context.gather(self.project), cfg, ticket_text="# t\nStatus: DONE\n\nbody\n")
        self.assertEqual(out["decision"], "close")


if __name__ == "__main__":
    unittest.main()
