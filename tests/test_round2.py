"""Regression tests for the second review round and the smoke test. Each fails without its fix."""

import json
import os
import shutil
import tempfile
import unittest

from helpers import RepoCase

from leadsman import config, context, probe, repo, verdict

# This test file itself: a real file that is not in a temp folder.
OUTSIDE_TEMP = os.path.realpath(__file__)


class Decide(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()
        self.cfg_values = dict(config.DEFAULTS)

    def evaluate(self, data, ctx=None, cfg=None, ticket=None):
        return verdict.evaluate(data, ctx or context.gather(self.project), cfg or self.cfg_values,
                                ticket_text=ticket)

    def test_failing_check_without_evidence_still_blocks_ready(self):
        data = self.findings(check_references={"status": "fail", "summary": "named function does not exist",
                                                "evidence": []})
        with self.assertRaises(verdict.FindingsError) as cm:
            self.evaluate(data)
        self.assertIn("references", str(cm.exception))

    def test_failing_check_blocks_ready_without_repository(self):
        data = self.findings(check_references={"status": "fail", "summary": "missing", "evidence": []})
        with self.assertRaises(verdict.FindingsError):
            self.evaluate(data, ctx=context.gather(self.home))

    def test_close_status_only_from_header_line(self):
        cfg = dict(self.cfg_values, status_map={"Done": "done", "Open": "backlog"})
        data = self.findings(decision="close", reason="shipped", ticket={"title": "t", "status": "Done"},
                             disproof={"outcome": "stands", "notes": "nothing found against it"})
        forged = "# Fix export\nStatus: Open\n\nbody\nStatus: Done\n"
        self.assertEqual(self.evaluate(data, cfg=cfg, ticket=forged)["decision"], "ask")
        body_only = "# Fix export\n\nStatus: Done\n"
        self.assertEqual(self.evaluate(data, cfg=cfg, ticket=body_only)["decision"], "ask")
        header = "# Fix export\nStatus: Done\n\nbody\n"
        self.assertEqual(self.evaluate(data, cfg=cfg, ticket=header)["decision"], "close")

    def test_issue_state_line_counts(self):
        cfg = dict(self.cfg_values, status_map={"CLOSED": "done"})
        data = self.findings(decision="close", reason="shipped", ticket={"title": "t", "status": "CLOSED"},
                             disproof={"outcome": "stands", "notes": "nothing found against it"})
        ticket = "# Fix export\nState: CLOSED COMPLETED\n\nbody\n"
        self.assertEqual(self.evaluate(data, cfg=cfg, ticket=ticket)["decision"], "close")

    def test_duplicate_needs_reason(self):
        data = self.findings(decision="duplicate", duplicate_of="#3",
                             disproof={"outcome": "stands", "notes": "same work"})
        with self.assertRaises(verdict.FindingsError) as cm:
            self.evaluate(data)
        self.assertIn("reason", str(cm.exception))

    def test_ticket_quote_needs_letters_or_digits(self):
        cfg = dict(self.cfg_values, evidence="all")
        raw = {"status": "pass", "summary": "clear", "ticket_quote": "..."}
        self.assertFalse(verdict._has_ticket_quote(raw, "# t\n\nWait... what?\n"))
        raw["ticket_quote"] = "Wait... what"
        self.assertTrue(verdict._has_ticket_quote(raw, "# t\n\nWait... what?\n"))
        self.assertEqual(cfg["evidence"], "all")


class Evidence(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()

    def confirm(self, item):
        return verdict.confirm_evidence(self.project, item)

    def test_uncommitted_change_refused(self):
        path = os.path.join(self.project, "src", "app.py")
        lines = open(path).read().split("\n")
        lines[3] = "def parse_config(path):  # fixed locally"
        with open(path, "w") as fh:
            fh.write("\n".join(lines))
        ok, why = self.confirm({"file": "src/app.py", "line": 4, "quote": "fixed locally"})
        self.assertIsNone(ok)
        self.assertIn("uncommitted", why)

    def test_underscores_are_not_a_quote(self):
        self.write("u.py", "x = ___\n")
        self.git("add", "u.py")
        self.git("commit", "-q", "-m", "u")
        ok, why = self.confirm({"file": "u.py", "line": 1, "quote": "___"})
        self.assertIsNone(ok)
        self.assertIn("letters or digits", why)


class LineBreaks(RepoCase):
    def test_form_feed_does_not_shift_lines(self):
        self.init_repo({"ff.py": "line1\n\x0c\n\x0c\n\x0c\nTARGET_LINE here\n"})
        ok, why = verdict.confirm_evidence(self.project, {"file": "ff.py", "line": 5, "quote": "TARGET_LINE here"})
        self.assertIsNotNone(ok, why)

    def test_grep_text_keeps_form_feed_line_whole(self):
        self.init_repo({"a.py": 'x = "a\x0cneedle_word"\n'})
        hits, total = probe.grep(self.project, "needle_word")
        self.assertEqual(total, 1)
        self.assertIn("needle_word", hits[0]["text"])

    def test_crlf_lines_have_no_carriage_return(self):
        self.init_repo({"w.py": "one\r\ntwo\r\n"})
        self.assertEqual(repo.read_lines(os.path.join(self.project, "w.py")), ["one", "two"])


class TeamRules(RepoCase):
    def test_untracked_rules_file_ignored(self):
        self.init_repo()
        self.write(".env", "DB_PASSWORD=hunter2xyz\n")
        self.write_config({"rules_file": ".env"}, where="project")
        ticket = self.ticket("# Fix parse_config\n\nbody\n")
        out = json.loads(self.check("prepare", "--ticket", ticket))
        self.assertIsNone(out["team_rules"])
        self.assertIn("not tracked", out["team_rules_note"])


class CfgtoolBadLayer(RepoCase):
    def write_user(self, text):
        with open(os.path.join(self.data, "config.json"), "w") as fh:
            fh.write(text)

    def assert_clean_exit(self, *args):
        out = self.cfg(*args, expect=1)
        self.assertNotIn("Traceback", out)

    def test_statuses_apply_on_broken_json(self):
        self.write_user("{not json")
        path = os.path.join(self.data, "st.json")
        with open(path, "w") as fh:
            json.dump(["Done"], fh)
        self.assert_clean_exit("statuses", "--file", path, "--apply")

    def test_set_and_unset_on_non_object(self):
        self.write_user("[1]")
        self.assert_clean_exit("set", "overlap", "off")
        self.assert_clean_exit("unset", "status_map.X")

    def test_set_status_map_entry_when_map_is_string(self):
        self.write_user('{"version": 1, "status_map": "oops"}')
        self.assert_clean_exit("set", "status_map.X", "done")


class SaveFromTempFile(RepoCase):
    """The model writes the ticket or findings to a temp file and `save --from` copies it in."""

    def setUp(self):
        RepoCase.setUp(self)
        self.drop = tempfile.mkdtemp(prefix="leadsman-handoff-")
        self.addCleanup(shutil.rmtree, self.drop, True)

    def handoff(self, name, text):
        path = os.path.join(self.drop, name)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def test_save_ticket_and_findings(self):
        self.init_repo()
        text = "# Fix $(id) `whoami` {\"a\": 1}\nStatus: Open\n\nbody\n"
        self.check("save", "ticket", "--from", self.handoff("t.md", text))
        with open(os.path.join(self.data, "work", "ticket.md")) as fh:
            self.assertEqual(fh.read(), text)
        saved = os.path.join(self.data, "work", "ticket.md")
        sha = json.loads(self.check("prepare", "--ticket", saved))["ticket"]["sha256"]
        data = self.findings(ticket={"title": "t", "source": "pasted", "sha256": sha})
        self.check("save", "findings", "--from", self.handoff("f.json", json.dumps(data)))
        self.check("verdict", "--findings", os.path.join(self.data, "work", "findings.json"))

    def test_save_outside_temp_refused(self):
        out = self.check("save", "ticket", "--from", OUTSIDE_TEMP, expect=2)
        self.assertIn("temp folder", out)
        self.assertFalse(os.path.exists(os.path.join(self.data, "work", "ticket.md")))

    def test_save_symlink_out_of_temp_refused(self):
        link = os.path.join(self.drop, "t.md")
        os.symlink(OUTSIDE_TEMP, link)
        self.assertIn("temp folder", self.check("save", "ticket", "--from", link, expect=2))

    def test_save_findings_must_be_json(self):
        out = self.check("save", "findings", "--from", self.handoff("f.json", "{not json"), expect=2)
        self.assertIn("JSON", out)

    def test_save_directory_refused(self):
        self.assertIn("regular file", self.check("save", "ticket", "--from", self.drop + os.sep + ".", expect=2))


class StatusesFile(RepoCase):
    def test_statuses_file_outside_temp_refused(self):
        out = self.cfg("statuses", "--file", OUTSIDE_TEMP, expect=1)
        self.assertIn("temp folder", out)


if __name__ == "__main__":
    unittest.main()
