"""Regression tests for the twenty-first review round. Each fails without its fix."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from helpers import CHECK, RepoCase

from leadsman import secrets

# A password-shaped value built from pieces, so none sits in the repository whole.
PASSWORD_VALUE = "Zq8Rt5" + "Wm2Lx9" + "Pv4Kd7"


class FixNeedsRealWork(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()

    def test_fix_with_failed_valid_refused(self):
        data = self.findings(decision="fix", rewrite="Do the thing.",
                             check_valid={"status": "fail", "summary": "already done"})
        out = self.check("verdict", "--findings", self.write_findings(data), expect=3)
        self.assertIn("still valid", out)

    def test_fix_with_unconfirmed_valid_refused(self):
        data = self.findings(decision="fix", rewrite="Do the thing.",
                             check_valid={"status": "pass", "summary": "still there"})
        self.check("verdict", "--findings", self.write_findings(data), expect=3)

    def test_fix_with_confirmed_valid_accepted(self):
        data = self.findings(decision="fix", rewrite="Do the thing.")
        self.assertIn("Fix then ready", self.check("verdict", "--findings", self.write_findings(data)))


class CitedSecretHiddenEverywhere(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.addCleanup(secrets._KNOWN.clear)
        self.init_repo({"settings.py": 'DB_PASSWORD = "%s"\n' % PASSWORD_VALUE})

    def test_summary_and_reason_hide_cited_value(self):
        valid = {"status": "pass", "summary": "the value %s is still hardcoded" % PASSWORD_VALUE,
                 "evidence": [{"file": "settings.py", "line": 1, "quote": 'DB_PASSWORD = "%s"' % PASSWORD_VALUE}]}
        data = self.findings(decision="park", reason="blocked until %s is rotated" % PASSWORD_VALUE,
                             check_valid=valid)
        findings = self.write_findings(data)
        self.assertNotIn(PASSWORD_VALUE, self.check("verdict", "--findings", findings))
        self.assertNotIn(PASSWORD_VALUE, self.check("verdict", "--findings", findings, "--json"))


class RefusedIssueClearsTicket(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()
        drop = tempfile.mkdtemp(prefix="leadsman-handoff-")
        self.addCleanup(shutil.rmtree, drop, True)
        self.src = os.path.join(drop, "a.md")
        with open(self.src, "w") as fh:
            fh.write("# Old ticket A\nStatus:\n\nbody\n")
        self.check("save", "ticket", "--from", self.src)
        self.saved = os.path.join(self.data, "work", "ticket.md")

    def run_raw(self, *args):
        return subprocess.run([sys.executable, CHECK] + list(args), env=self.env, cwd=self.project,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)

    def test_issue_named_findings_refused_clears_ticket(self):
        res = self.run_raw("--data", self.data, "issue", "findings", "--bogus")
        self.assertEqual(res.returncode, 2)
        self.assertFalse(os.path.exists(self.saved))

    def test_second_data_refused_clears_pinned_folder_only(self):
        other = os.path.join(self.tmp, "other")
        os.makedirs(os.path.join(other, "work"))
        keep = os.path.join(other, "work", "ticket.md")
        with open(keep, "w") as fh:
            fh.write("keep\n")
        res = self.run_raw("--data", self.data, "save", "ticket", "--from", self.src, "--data", other)
        self.assertEqual(res.returncode, 2)
        self.assertFalse(os.path.exists(self.saved))
        self.assertTrue(os.path.exists(keep))


if __name__ == "__main__":
    unittest.main()
