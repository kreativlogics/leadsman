"""Regression tests for the tenth review round. Each fails without its fix."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from helpers import CHECK, RepoCase

from leadsman import verdict


class ReportCaseVariants(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()

    def test_case_variant_of_saved_ticket_refused(self):
        findings = self.write_findings(self.findings())
        saved = os.path.join(self.data, "work", "ticket.md")
        with open(saved) as fh:
            before = fh.read()
        self.check("verdict", "--findings", findings, "--out", os.path.join(self.data, "work", "Ticket.md"), expect=2)
        with open(saved) as fh:
            self.assertEqual(fh.read(), before)

    def test_case_variant_of_findings_refused(self):
        findings = self.write_findings(self.findings())
        work = os.path.join(self.data, "work")
        shutil.copy(findings, os.path.join(work, "findings.json"))
        self.check("verdict", "--findings", os.path.join(work, "findings.json"),
                   "--out", os.path.join(work, "Findings.JSON"), expect=2)
        with open(os.path.join(work, "findings.json")) as fh:
            json.load(fh)


class NoBytecode(RepoCase):
    def test_scripts_write_no_pycache(self):
        plugin = tempfile.mkdtemp(prefix="leadsman-plugin-")
        self.addCleanup(shutil.rmtree, plugin, True)
        scripts = os.path.join(plugin, "scripts")
        shutil.copytree(os.path.dirname(CHECK), scripts, ignore=shutil.ignore_patterns("__pycache__"))
        env = dict(self.env)
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        for name in ("check.py", "cfgtool.py"):
            subprocess.run([sys.executable, os.path.join(scripts, name), "--data", self.data, "version"
                            if name == "check.py" else "show"], env=env, cwd=self.project,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        found = [d for d, _, _ in os.walk(plugin) if d.endswith("__pycache__")]
        self.assertEqual(found, [])


class ProjectLayerLinkedOut(RepoCase):
    def test_set_does_not_read_linked_out_file(self):
        self.init_repo()
        outside = self.write("outside.json", json.dumps({"outside_private_key_name": "x"}), root=self.home)
        os.makedirs(os.path.join(self.project, ".leadsman"))
        os.symlink(outside, os.path.join(self.project, ".leadsman", "config.json"))
        out = self.cfg("set", "overlap", "off", "--project", expect=1)
        self.assertNotIn("outside_private_key_name", out)
        self.assertIn("outside the repository", out)


class DuplicateCloseReason(unittest.TestCase):
    def test_closed_duplicate_counts(self):
        cat = verdict._status_category({"ticket": {"status": "CLOSED"}}, {"status_map": {"closed": "done"}},
                                       "# t\nState: CLOSED DUPLICATE\n\nbody\n")
        self.assertEqual(cat, "done")


if __name__ == "__main__":
    unittest.main()
