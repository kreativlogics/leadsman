"""Regression tests for the third review round. Each fails without its fix."""

import json
import os
import shutil
import tempfile

from helpers import RepoCase

from leadsman import config, context, ghread, secrets, statusmap, verdict


class HandoffCase(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.drop = tempfile.mkdtemp(prefix="leadsman-handoff-")
        self.addCleanup(shutil.rmtree, self.drop, True)

    def handoff(self, name, text):
        path = os.path.join(self.drop, name)
        with open(path, "w") as fh:
            fh.write(text)
        return path


class StatusLine(HandoffCase):
    def test_body_status_on_first_body_line_does_not_close(self):
        self.init_repo()
        cfg = dict(config.DEFAULTS, status_map={"Done": "done"})
        data = self.findings(decision="close", reason="shipped", ticket={"title": "t", "status": "Done"},
                             disproof={"outcome": "stands", "notes": "nothing found against it"})
        pasted = "Add CSV export\nStatus:\n\nStatus: Done\nWe need a CSV export button.\n"
        self.assertEqual(verdict.evaluate(data, context.gather(self.project), cfg, ticket_text=pasted)["decision"],
                         "ask")

    def test_save_ticket_needs_status_line(self):
        out = self.check("save", "ticket", "--from", self.handoff("t.md", "Add CSV export\n\nStatus: Done\n"),
                         expect=2)
        self.assertIn("Line 2", out)
        self.check("save", "ticket", "--from", self.handoff("t.md", "Add CSV export\nStatus:\n\nbody\n"))


class OverlapWords(RepoCase):
    def test_key_in_title_not_searched(self):
        key = "AKIA" + "QWERTYUIOPASDFGH"
        words = ghread.title_words("# Rotate key %s leaked in deploy\n" % key)
        self.assertNotIn(key.lower(), words)
        self.assertEqual(secrets.mask(words), words)
        self.assertIn("rotate", words)

    def test_token_in_title_not_searched(self):
        token = "ghp" + "_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
        self.assertNotIn(token.lower()[4:], ghread.title_words("# Leaked %s here\n" % token))


class NestedJson(HandoffCase):
    def test_save_and_verdict_refuse_deep_nesting(self):
        deep = "[" * 200000 + "]" * 200000
        out = self.check("save", "findings", "--from", self.handoff("f.json", deep), expect=2)
        self.assertNotIn("Traceback", out)
        path = os.path.join(self.data, "work", "findings.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(deep)
        out = self.check("verdict", "--findings", path, expect=2)
        self.assertNotIn("Traceback", out)

    def test_statuses_refuse_deep_nesting(self):
        out = self.cfg("statuses", "--file", self.handoff("s.json", "[" * 200000 + "]" * 200000), expect=1)
        self.assertNotIn("Traceback", out)


class NativeNotString(HandoffCase):
    def test_non_string_native_ignored(self):
        self.assertEqual(statusmap.guess("Done", 5)["category"], "done")
        out = json.loads(self.cfg("statuses", "--file",
                                  self.handoff("s.json", '[{"name": "Done", "native": ["x"]}]'), expect=0))
        self.assertEqual(out["guesses"][0]["category"], "done")


class ReportPath(RepoCase):
    def test_report_cannot_overwrite_config(self):
        self.init_repo()
        findings = self.write_findings(self.findings())
        target = os.path.join(self.data, "config.json")
        self.check("verdict", "--findings", findings, "--out", target, expect=2)
        self.assertFalse(os.path.exists(target))
