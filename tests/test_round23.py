"""Regression tests for the twenty-third review round. Each fails without its fix."""

import json
import os
import unittest

from helpers import RepoCase

from leadsman import verdict

# A Stripe-shaped value built from pieces, so none sits in the repository whole.
STRIPE = "sk" + "_live_" + "4eC39HqLyjWDarjtT1zdp7dcAbCdEf"


class FindingsBelongToSavedTicket(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()

    def test_findings_for_another_ticket_refused(self):
        data = self.findings()
        data["ticket"]["sha256"] = "0" * 64
        out = self.check("verdict", "--findings", self.write_findings(data), expect=2)
        self.assertIn("sha256", out)

    def test_missing_sha_refused(self):
        path = self.write_findings(self.findings())
        with open(path) as fh:
            data = json.load(fh)
        del data["ticket"]["sha256"]
        with open(path, "w") as fh:
            json.dump(data, fh)
        self.check("verdict", "--findings", path, expect=2)


class CutQuoteHidesSecretPart(RepoCase):
    def test_quote_cut_inside_secret(self):
        self.init_repo({"pay.py": 'PAYMENT_CFG = "%s"\n' % STRIPE})
        ok, why = verdict.confirm_evidence(self.project, {"file": "pay.py", "line": 1,
                                                          "quote": 'PAYMENT_CFG = "%s' % STRIPE[:26],
                                                          "note": "starts %s" % STRIPE[8:22]})
        self.assertIsNotNone(ok, why)
        self.assertNotIn(STRIPE[8:22], ok["quote"])
        self.assertNotIn(STRIPE[8:22], ok["note"])


class RevisionOutputClean(RepoCase):
    def test_control_characters_in_problems_replaced(self):
        self.init_repo()
        data = self.findings()
        data["checks"]["\x1b[2J# leadsman: Ready"] = {"status": "pass", "summary": "x"}
        out = self.check("verdict", "--findings", self.write_findings(data), expect=3)
        self.assertNotIn("\x1b", out)


if __name__ == "__main__":
    unittest.main()
