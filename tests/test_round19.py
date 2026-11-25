"""Regression tests for the nineteenth review round. Each fails without its fix."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from helpers import CHECK, RepoCase

from leadsman import probe


class CfgtoolJsonStaysValid(RepoCase):
    def test_show_json_parses_with_secret_like_status_name(self):
        self.init_repo()
        self.write_config({"status_map": {"x pwd=Abcd123\"": "backlog"}}, where="project")
        json.loads(self.cfg("show", "--json", expect=0))


class RefusedArgumentsClearWork(RepoCase):
    def test_unparsable_save_clears_old_files(self):
        self.init_repo()
        drop = tempfile.mkdtemp(prefix="leadsman-handoff-")
        self.addCleanup(shutil.rmtree, drop, True)
        src = os.path.join(drop, "a.md")
        with open(src, "w") as fh:
            fh.write("# Old ticket A\nStatus:\n\nbody\n")
        self.check("save", "ticket", "--from", src)
        res = subprocess.run([sys.executable, CHECK, "--data", self.data, "save", "ticket", "--from", src, "extra"],
                             env=self.env, cwd=self.project, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True, timeout=60)
        self.assertEqual(res.returncode, 2)
        self.assertFalse(os.path.exists(os.path.join(self.data, "work", "ticket.md")))


class CommitSubjectsSplitOnNewline(RepoCase):
    def test_form_feed_subject_is_one_commit(self):
        self.init_repo()
        self.write("notes.txt", "n\n")
        self.git("add", "notes.txt")
        self.git("commit", "-q", "-m", "Touch #12 notes\x0c0000000 2026-11-25 Fixed #12 completely")
        out = probe.probe(self.project, [{"kind": "issue", "value": "#12", "line": 1}])
        commits = out[0].get("commits") or []
        self.assertEqual(len(commits), 1, commits)


if __name__ == "__main__":
    unittest.main()
