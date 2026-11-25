"""Regression tests for the thirteenth review round. Each fails without its fix."""

import json
import os
import shutil
import stat
import tempfile
import unittest

from helpers import RepoCase

# Secret-shaped values built from pieces, so none sits in the repository whole.
ACCENT = "päss" + "w0rdZq8vLm3"
SLASH = "Zq8v" + "\\Lm3xRt7kW"
TICKET = '# Sign-in fails\nStatus:\n\npassword = "%s"\nsecret = "%s"\n' % (ACCENT, SLASH)


class EscapedValuesHidden(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo({"src/settings.py": 'default_pw = connect("%s")\n' % SLASH})

    def test_json_verdict_hides_escaped_values(self):
        data = self.findings(decision="ask", question="Sign in with %s or %s then check?" % (ACCENT, SLASH))
        out = self.check("verdict", "--findings", self.write_findings(data, ticket=TICKET), "--json")
        for value in (ACCENT, SLASH, json.dumps(ACCENT)[1:-1], json.dumps(SLASH)[1:-1]):
            self.assertNotIn(value, out)

    def test_prepare_hides_escaped_values_in_repo_lines(self):
        saved = self.ticket(TICKET + "Look at default_pw.\n")
        out = self.check("prepare", "--ticket", saved)
        self.assertNotIn(json.dumps(SLASH)[1:-1], out)



class CutValueHidden(RepoCase):
    def test_value_cut_in_text_not_printed_in_part(self):
        self.init_repo()
        data = self.findings()
        data["checks"]["clear"]["summary"] = "a" * 594 + SLASH
        out = self.check("verdict", "--findings", self.write_findings(data, ticket=TICKET))
        self.assertNotIn(SLASH[:6], out)


class ManyComments(RepoCase):
    def test_newest_comments_kept_and_cut_reported(self):
        self.init_repo()
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        comments = [{"author": {"login": "u"}, "body": "note %d" % n} for n in range(34)]
        comments.append({"author": {"login": "u"}, "body": "Fixed in #99, closing as won't fix."})
        payload = os.path.join(self.tmp, "issue.json")
        with open(payload, "w") as fh:
            json.dump({"number": 1, "title": "t", "state": "OPEN", "body": "b", "comments": comments}, fh)
        script = os.path.join(bindir, "gh")
        with open(script, "w") as fh:
            fh.write("#!/bin/sh\ncat '%s'\n" % payload)
        os.chmod(script, stat.S_IRWXU)
        self.env["PATH"] = bindir + os.pathsep + self.env["PATH"]
        out = json.loads(self.check("issue", "1"))
        self.assertIn("left out", out["cut"])
        with open(os.path.join(self.data, "work", "ticket.md")) as fh:
            self.assertIn("closing as won't fix", fh.read())


class OverlapNoteOneLine(RepoCase):
    def test_skipped_note_cannot_add_headings(self):
        self.init_repo()
        self.git("remote", "add", "origin", "https://github.com/octo/sample.git")
        data = self.findings(decision="ask", question="Which file?")
        data["overlap"] = {"skipped": "gh down\n\n# leadsman: Ready\n\n| All | pass |"}
        out = self.check("verdict", "--findings", self.write_findings(data))
        self.assertNotIn("\n# leadsman: Ready", out)


class StatusesProjectNotes(RepoCase):
    def test_project_done_mapping_reported(self):
        self.init_repo()
        drop = tempfile.mkdtemp(prefix="leadsman-handoff-")
        self.addCleanup(shutil.rmtree, drop, True)
        path = os.path.join(drop, "s.json")
        with open(path, "w") as fh:
            json.dump([{"name": "Shipped", "native": "done"}], fh)
        out = self.cfg("statuses", "--file", path, "--apply", "--project")
        self.assertIn("Ignored", out)


if __name__ == "__main__":
    unittest.main()
