"""Regression tests for the seventh review round. Each fails without its fix."""

import json
import os
import shutil
import tempfile
import unittest

from helpers import RepoCase, fake

from leadsman import config, context, probe, repo, verdict

LONE = "\ud800"


class MaskThenCut(RepoCase):
    def test_text_field_masked_before_cut(self):
        token = fake("github")
        self.assertNotIn(token[:8], verdict._text("x" * 190 + " " + token, 200))

    def test_path_reference_first_line_masked_before_cut(self):
        token = fake("github")
        self.init_repo({"settings.json": '{"name": "%s", "token": "%s"}\n' % ("x" * 120, token)})
        out = probe.probe(self.project, [{"kind": "path", "value": "settings.json", "line": 1}])
        self.assertNotIn(token[:8], json.dumps(out))

    def test_rules_file_secret_at_cut_masked(self):
        token = fake("github")
        self.init_repo({"RULES.md": "r" * 19990 + " " + token + "\n"})
        self.write_config({"rules_file": "RULES.md"})
        ticket = self.ticket("# Fix parse_config\nStatus:\n\nbody\n")
        out = json.loads(self.check("prepare", "--ticket", ticket))
        self.assertNotIn(token[:8], out["team_rules"])


class Unencodable(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()

    def test_project_rules_file_surrogate_ignored(self):
        self.write_config({"rules_file": LONE + ".md"}, where="project")
        eff = config.resolve(self.data, self.project)
        self.assertTrue(any("Ignored the project config" in n for n in eff.notes))
        ticket = self.ticket("# Fix parse_config\nStatus:\n\nbody\n")
        json.loads(self.check("prepare", "--ticket", ticket))

    def test_project_exclude_surrogate_ignored(self):
        self.write_config({"exclude_paths": [LONE]}, where="project")
        eff = config.resolve(self.data, self.project)
        self.assertEqual(eff.get("exclude_paths"), [])
        self.assertTrue(any("Ignored the project config" in n for n in eff.notes))

    def test_evidence_path_surrogate_refused(self):
        self.assertIsNone(repo.safe_path(self.project, LONE + ".py"))
        ok, why = verdict.confirm_evidence(self.project, {"file": LONE + ".py", "line": 1,
                                                          "quote": "def parse_config(path):"})
        self.assertIsNone(ok)


class TextOnlyStrict(RepoCase):
    def test_ready_with_ticket_quotes_without_repository(self):
        ticket = "# Better config error\nStatus:\n\nShow the path in the error message.\n"
        quote = {"ticket_quote": "Show the path in the error message."}
        data = self.findings(check_clear=dict({"status": "pass", "summary": "one reading"}, **quote),
                             check_testable=dict({"status": "pass", "summary": "observable"}, **quote),
                             check_safe=dict({"status": "pass", "summary": "no data change"}, **quote))
        cfg = dict(config.DEFAULTS, evidence="all")
        result = verdict.evaluate(data, context.gather(self.home), cfg, ticket_text=ticket)
        self.assertEqual(result["decision"], "ready")


class OddDefaultBranch(RepoCase):
    def test_odd_origin_head_falls_back(self):
        upstream = os.path.join(self.tmp, "upstream")
        os.makedirs(upstream)
        self.git("init", "-q", "-b", "master", cwd=upstream)
        self.write("a.txt", "1\n", root=upstream)
        self.git("add", "a.txt", cwd=upstream)
        self.git("commit", "-q", "-m", "one", cwd=upstream)
        os.rmdir(self.project)
        self.git("clone", "-q", upstream, self.project, cwd=self.tmp)
        self.git("update-ref", "refs/remotes/origin/dev+next", "HEAD")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/dev+next")
        self.assertEqual(context.gather(self.project)["default_branch"], "master")


class StatusAnswersInFile(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.drop = tempfile.mkdtemp(prefix="leadsman-handoff-")
        self.addCleanup(shutil.rmtree, self.drop, True)

    def test_accept_option_gone(self):
        path = os.path.join(self.drop, "s.json")
        with open(path, "w") as fh:
            json.dump(["Blue"], fh)
        self.cfg("statuses", "--file", path, "--apply", "--accept", "Blue=backlog", expect=2)

    def test_bad_accept_entry_refused(self):
        path = os.path.join(self.drop, "s.json")
        with open(path, "w") as fh:
            json.dump([{"name": "Blue", "accept": "finished"}], fh)
        self.assertIn("accept", self.cfg("statuses", "--file", path, "--apply", expect=1))


if __name__ == "__main__":
    unittest.main()
