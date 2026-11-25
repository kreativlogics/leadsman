"""Regression tests for the ninth review round. Each fails without its fix."""

import json
import os
import unittest
from unittest import mock

from helpers import RepoCase

from leadsman import config, context, probe, secrets, verdict

# A password-shaped value built from pieces, so none sits in the repository whole.
VALUE = "Zq8" + "Lm4vRt9" + "wXk2Pn"


class BareAssignedSecret(unittest.TestCase):
    def test_env_and_yaml_values_masked(self):
        for text in ("DB_PASSWORD=" + VALUE, "password: " + VALUE, "api_key = " + VALUE):
            self.assertNotIn(VALUE, secrets.mask(text), text)
            self.assertTrue(secrets.scan_text(text), text)

    def test_plain_words_not_masked(self):
        for text in ("the password: is wrong", "password: changeme", "apiKey: config.apiKey"):
            self.assertEqual(secrets.mask(text), text)


class ReportCannotReplaceSavedFiles(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()

    def test_out_onto_saved_ticket_refused(self):
        findings = self.write_findings(self.findings())
        saved = os.path.join(self.data, "work", "ticket.md")
        with open(saved) as fh:
            before = fh.read()
        self.check("verdict", "--findings", findings, "--out", saved, expect=2)
        with open(saved) as fh:
            self.assertEqual(fh.read(), before)

    def test_out_onto_findings_refused(self):
        findings = self.write_findings(self.findings())
        target = os.path.join(self.data, "work", "findings.json")
        with open(findings) as src, open(target, "w") as dst:
            dst.write(src.read())
        self.check("verdict", "--findings", target, "--out", target, expect=2)
        with open(target) as fh:
            json.load(fh)


class TicketQuoteBodyOnly(unittest.TestCase):
    def test_title_and_status_lines_do_not_count(self):
        ticket = "# Export the monthly report as CSV\nStatus: Ready for work today\n\nSmall body.\n"
        for quote in ("Export the monthly report as CSV", "Status: Ready for work today"):
            self.assertFalse(verdict._has_ticket_quote({"ticket_quote": quote}, ticket), quote)
        body = "# t\nStatus:\n\nExport the monthly report as CSV.\n"
        self.assertTrue(verdict._has_ticket_quote({"ticket_quote": "Export the monthly report"}, body))


class ReportTitleFromSavedTicket(RepoCase):
    def test_title_comes_from_saved_ticket(self):
        self.init_repo()
        data = self.findings()
        data["ticket"]["title"] = "Delete every account"
        findings = self.write_findings(data, ticket="# Better config error\nStatus:\n\nShow the path.\n")
        out = self.check("verdict", "--findings", findings)
        self.assertIn("**Ticket:** Better config error", out)
        self.assertNotIn("Delete every account", out)


class ShowMasks(RepoCase):
    def test_show_masks_list_values(self):
        self.init_repo()
        self.write_config({"exclude_paths": ["password=" + VALUE]})
        self.assertNotIn(VALUE, self.cfg("show"))
        self.assertNotIn(VALUE, self.cfg("show", "--json"))


class GitFailureUnverified(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()

    def test_path_search_failure_is_unverified(self):
        with mock.patch.object(probe.repo, "run_git", return_value=(128, "")):
            out = probe.probe_path(self.project, {"kind": "path", "value": "nowhere/missing.py"})
        self.assertIsNone(out["found"])
        self.assertIn("unverified", out["note"])

    def test_issue_search_failure_is_unverified(self):
        with mock.patch.object(probe.repo, "run_git", return_value=(128, "")):
            out = probe.probe_issue(self.project, "#12")
        self.assertIsNone(out["found"])
        self.assertIn("unverified", out["note"])


class AddToNonList(RepoCase):
    def test_add_to_string_value_clean_error(self):
        self.init_repo()
        self.write_config({"exclude_paths": "vendor"})
        out = self.cfg("set", "exclude_paths", "dist", "--add", expect=1)
        self.assertNotIn("Traceback", out)
        self.assertIn("not a list", out)


if __name__ == "__main__":
    unittest.main()
