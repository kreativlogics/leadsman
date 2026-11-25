"""Regression tests for the twenty-fifth review round. Each fails without its fix."""

import unittest

from helpers import RepoCase, fake

from leadsman import config, context, verdict


class SecretAtLineCut(RepoCase):
    def test_quote_of_secret_crossing_the_cut_refused(self):
        token = fake("github")
        self.init_repo({"long.py": "a = 1\nx = '%s';t=%s\n" % ("y" * 1960, token)})
        ok, why = verdict.confirm_evidence(self.project, {"file": "long.py", "line": 2,
                                                          "quote": "';t=" + token[:25]})
        self.assertIsNone(ok)


class AllEvidenceNeedsTicketQuote(RepoCase):
    def test_code_evidence_does_not_verify_text_check(self):
        self.init_repo()
        code = [{"file": "src/app.py", "line": 4, "quote": "def parse_config(path):"}]
        data = self.findings(check_clear={"status": "pass", "summary": "one reading", "evidence": code})
        cfg = dict(config.DEFAULTS, evidence="all")
        with self.assertRaises(verdict.FindingsError):
            verdict.evaluate(data, context.gather(self.project), cfg,
                             ticket_text="# Better config error\nStatus:\n\nShow the path in the error.\n")
        data["decision"] = "ask"
        data["question"] = "Which path?"
        out = verdict.evaluate(data, context.gather(self.project), cfg,
                               ticket_text="# Better config error\nStatus:\n\nShow the path in the error.\n")
        self.assertEqual(out["checks"]["clear"]["status"], "unverified")


if __name__ == "__main__":
    unittest.main()
