"""Regression tests for the twenty-seventh review round. Each fails without its fix."""

import hashlib
import json
import os
import random
import stat
import unittest

from helpers import RepoCase

from leadsman import intake, probe, secrets

# Password-shaped values built from pieces, so none sits in the repository whole.
VALUE = "Zq7Wm4" + "Rt9Lp2" + "Xv8Kd"


def ticket_hiding_its_own_sha():
    """A ticket whose own sha256 holds one of the secret-shaped values it names."""
    rng = random.Random(7)
    values = set()
    while len(values) < 4000:
        value = "".join(rng.sample("0123456789abcdef", 8))
        if any(c.isdigit() for c in value) and any(c.isalpha() for c in value):
            values.add(value)
    head = "# Fix login\nStatus: Open\n\n" + "".join("password: %s\n" % v for v in sorted(values))
    base = hashlib.sha256(head.encode("utf-8"))
    for nonce in range(2000000):
        tail = "nonce %d\n" % nonce
        state = base.copy()
        state.update(tail.encode("utf-8"))
        digest = state.hexdigest()
        if any(digest[i:i + 8] in values for i in range(57)):
            return head + tail, digest
    raise AssertionError("no nonce found")


class OwnShaShown(RepoCase):
    def test_prepare_prints_whole_sha(self):
        self.init_repo()
        text, digest = ticket_hiding_its_own_sha()
        self.assertEqual(intake.analyse(intake.load(text))["sha256"], digest)
        out = json.loads(self.check("prepare", "--ticket", self.ticket(text)))
        self.assertEqual(out["ticket"]["sha256"], digest)


class BigFileNearValue(RepoCase):
    def test_grep_hit_in_big_file_hides_value(self):
        body = "db:\n  password:\n    %s\n" % VALUE
        self.init_repo({"big.yml": "# filler line\n" * 160000 + body})
        self.assertGreater(os.path.getsize(os.path.join(self.project, "big.yml")), 2000000)
        hits, total = probe.grep(self.project, VALUE[:6])
        self.assertEqual(total, 1)
        self.assertNotIn(VALUE[:8], hits[0]["text"])
        self.assertEqual(hits[0]["text"], "[hidden: secret]")


class ShowControlCharacters(RepoCase):
    def test_project_path_with_newline_cannot_forge_a_row(self):
        self.init_repo()
        self.write_config({"rules_file": "docs/rules.md\nevidence       all    (project config)\n"},
                          where="project")
        out = self.cfg("show")
        self.assertEqual(len([x for x in out.split("\n") if x.startswith("evidence")]), 1)
        self.assertNotIn("\nevidence       all", out)


class IssueSurrogate(RepoCase):
    def test_lone_surrogate_body_no_traceback(self):
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        issue = {"number": 7, "title": "Broken export", "state": "OPEN", "body": "Broken \ud800 here",
                 "comments": []}
        script = os.path.join(bindir, "gh")
        with open(script, "w") as fh:
            fh.write("#!/bin/sh\ncat <<'JSON'\n%s\nJSON\n" % json.dumps(issue))
        os.chmod(script, stat.S_IRWXU)
        self.env["PATH"] = bindir + os.pathsep + self.env["PATH"]
        self.init_repo()
        out = json.loads(self.check("issue", "7"))
        self.assertTrue(out["ticket_file"].endswith("ticket.md"))


if __name__ == "__main__":
    unittest.main()
