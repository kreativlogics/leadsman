"""Regression tests for the eighth review round. Each fails without its fix."""

import json
import os
import string
import subprocess
import sys
import time
import unittest

from helpers import CHECK, RepoCase, fake

from leadsman import probe, secrets


def long_token(seed):
    """A 254-character GitHub-shaped token with high entropy, built at run time."""
    chars = string.ascii_letters + string.digits
    return "gh" + "p_" + "".join(chars[(seed * 7 + i * 13) % len(chars)] for i in range(250))


class SlowPatterns(unittest.TestCase):
    def test_repeated_jwt_prefix_is_fast(self):
        start = time.time()
        secrets.mask("-eyJ" * 50000)
        secrets.mask("-sk-" * 50000)
        self.assertLess(time.time() - start, 3)


class SlowLines(RepoCase):
    def test_huge_line_hit_is_fast(self):
        self.init_repo({"big.txt": "foo_bar " + "-eyJ" * 250000 + "\n"})
        start = time.time()
        hits, total = probe.grep(self.project, "foo_bar")
        self.assertEqual(total, 1)
        self.assertLess(time.time() - start, 10)


class VerdictTicket(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()

    def run_raw(self, *args):
        return subprocess.run([sys.executable, CHECK, "--data", self.data] + list(args), env=self.env,
                              cwd=self.project, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=60)

    def test_ticket_option_gone(self):
        findings = self.write_findings(self.findings())
        res = self.run_raw("verdict", "--findings", findings, "--ticket", findings)
        self.assertEqual(res.returncode, 2)

    def test_no_saved_ticket_refused(self):
        path = os.path.join(self.data, "findings.json")
        with open(path, "w") as fh:
            json.dump(self.findings(), fh)
        out = self.check("verdict", "--findings", path, expect=2)
        self.assertIn("save ticket", out)

    def test_quote_only_in_findings_not_found(self):
        self.write_config({"preset": "strict"})
        invented = {"ticket_quote": "Acceptance: returns 42 for every caller"}
        data = self.findings(check_clear=dict({"status": "pass", "summary": "one reading"}, **invented),
                             check_testable=dict({"status": "pass", "summary": "observable"}, **invented),
                             check_safe=dict({"status": "pass", "summary": "no data change"}, **invented))
        out = self.check("verdict", "--findings", self.write_findings(data), expect=3)
        self.assertIn("unverified", out)


class RulesCut(RepoCase):
    def test_masked_tokens_do_not_pull_a_cut_secret_in(self):
        head = "".join("key %s\n" % long_token(i) for i in range(6))
        token = fake("github")
        filler = "r" * (20981 - len(head) - 4)
        self.init_repo({"RULES.md": head + filler + "key " + token + "\n"})
        self.write_config({"rules_file": "RULES.md"})
        ticket = self.ticket("# Fix parse_config\nStatus:\n\nbody\n")
        out = json.loads(self.check("prepare", "--ticket", ticket))
        self.assertNotIn(token[:8], out["team_rules"])


class CfgtoolMasks(RepoCase):
    def test_rejected_value_masked(self):
        self.init_repo()
        self.write_config({"preset": fake("github")}, where="project")
        self.assertNotIn(fake("github")[:12], self.cfg("show"))
        self.assertNotIn(fake("github")[:12], self.cfg("doctor"))


if __name__ == "__main__":
    unittest.main()
