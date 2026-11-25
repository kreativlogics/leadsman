"""Regression tests for the eighteenth review round. Each fails without its fix."""

import json
import os
import shutil
import string
import tempfile
import unittest

from helpers import RepoCase

# A secret-shaped value built from pieces, so none sits in the repository whole.
VALUE = "Xy7k" + "Pq2mZr9Lw4Tb8"


class StaleWorkFiles(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()
        self.drop = tempfile.mkdtemp(prefix="leadsman-handoff-")
        self.addCleanup(shutil.rmtree, self.drop, True)

    def handoff(self, name, text):
        path = os.path.join(self.drop, name)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def test_refused_findings_save_leaves_nothing_to_grade(self):
        self.check("save", "ticket", "--from", self.handoff("a.md", "# Better config error\nStatus:\n\nbody\n"))
        self.check("save", "findings", "--from", self.handoff("a.json", json.dumps(self.findings())))
        self.check("save", "ticket", "--from", self.handoff("b.md", "# Delete old accounts\nStatus: Backlog\n\nb\n"))
        self.check("save", "findings", "--from", self.handoff("b.json", "{not json"), expect=2)
        findings = os.path.join(self.data, "work", "findings.json")
        self.assertFalse(os.path.exists(findings))

    def test_refused_ticket_save_clears_old_ticket(self):
        self.check("save", "ticket", "--from", self.handoff("a.md", "# Old ticket\nStatus: Done\n\nbody\n"))
        self.check("save", "ticket", "--from", self.handoff("b.md", "# New ticket\n\nno status\n"), expect=2)
        self.assertFalse(os.path.exists(os.path.join(self.data, "work", "ticket.md")))

    def test_findings_older_than_ticket_refused(self):
        findings = self.write_findings(self.findings())
        old = os.stat(findings).st_mtime - 10
        os.utime(findings, (old, old))
        out = self.check("verdict", "--findings", findings, expect=2)
        self.assertIn("older than the saved ticket", out)


class QuotedValueHidden(RepoCase):
    def test_quote_of_only_the_value_hidden_in_json(self):
        self.init_repo({"app.py": 'import os\n\nAPI_KEY = "%s"\n' % VALUE})
        data = self.findings(decision="ask", question="Which key?",
                             check_valid={"status": "pass", "summary": "key is set",
                                          "evidence": [{"file": "app.py", "line": 3, "quote": VALUE,
                                                        "note": "value %s" % VALUE}]})
        out = self.check("verdict", "--findings", self.write_findings(data), "--json")
        self.assertNotIn(VALUE, out)


class SecretsListCapped(RepoCase):
    def test_secret_list_capped_with_total(self):
        self.init_repo()
        chars = string.ascii_letters + string.digits
        lines = ["pwd=%s9" % "".join(chars[(n * 11 + i * 7) % len(chars)] for i in range(10)) for n in range(60)]
        out = json.loads(self.check("prepare", "--ticket", self.ticket("# t\nStatus:\n\n" + "\n".join(lines) + "\n")))
        self.assertEqual(len(out["ticket"]["secrets"]), 20)
        self.assertEqual(out["ticket"]["secrets_total"], 60)


if __name__ == "__main__":
    unittest.main()
