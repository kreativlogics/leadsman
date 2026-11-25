"""Regression tests for the twentieth review round. Each fails without its fix."""

import json
import os
import shutil
import string
import subprocess
import sys
import tempfile
import unittest

from helpers import CHECK, RepoCase

from leadsman import probe, secrets, verdict

CHARS = string.ascii_letters + string.digits


def varied(n, seed=3):
    return "".join(CHARS[(seed * 11 + i * 17) % len(CHARS)] for i in range(n))


def key_block():
    """A PEM-shaped key built at run time from pieces; its body is random-looking base64, not a real key."""
    head = "-----" + "BEGIN RSA " + "PRIVATE KEY" + "-----"
    tail = "-----" + "END RSA " + "PRIVATE KEY" + "-----"
    first = "MIIEpAIBAAKCAQEA" + varied(48, 5)
    body = [first, varied(64, 7), varied(64, 9)]
    return "\n".join([head] + body + [tail]) + "\n", body


class RememberedPrefixDoesNotUnmaskTokens(unittest.TestCase):
    def setUp(self):
        self.addCleanup(secrets._KNOWN.clear)

    def test_anthropic_prefix_remembered(self):
        token = "sk-" + "ant-api03-" + varied(93)
        secrets.remember(["sk-" + "ant-api03"])
        out = secrets.mask('ANTHROPIC_API_KEY = "%s"' % token)
        self.assertNotIn(varied(93)[:20], out)

    def test_jwt_header_remembered(self):
        header = "eyJ" + "hbGciOiJIUzI1NiIs"
        token = header + varied(20) + ".eyJ" + varied(40, 4) + "." + varied(30, 6)
        secrets.remember([header])
        self.assertNotIn(varied(40, 4)[:20], secrets.mask("auth: " + token))


class PrivateKeyBodiesHidden(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.block, self.body = key_block()
        self.init_repo({"id_deploy.txt": self.block, "RULES.md": "Rules.\n" + self.block})

    def test_mask_hides_whole_block(self):
        out = secrets.mask(self.block)
        for line in self.body:
            self.assertNotIn(line[:24], out)

    def test_grep_hit_in_key_file_hidden(self):
        hits, total = probe.grep(self.project, "MIIEpAIBAAKCAQEA")
        self.assertEqual(total, 2)
        self.assertNotIn(self.body[0][:24], json.dumps(hits))

    def test_line_of_key_file_not_shown(self):
        out = probe.probe(self.project, [{"kind": "path", "value": "id_deploy.txt", "line": 1, "at_line": 3}])
        self.assertNotIn(self.body[1][:24], json.dumps(out))

    def test_rules_file_holding_key_ignored(self):
        self.write_config({"rules_file": "RULES.md"})
        ticket = self.ticket("# Fix parse_config\nStatus:\n\nbody\n")
        out = json.loads(self.check("prepare", "--ticket", ticket))
        self.assertNotIn(self.body[1][:24], json.dumps(out))

    def test_key_file_not_used_as_evidence(self):
        ok, why = verdict.confirm_evidence(self.project, {"file": "id_deploy.txt", "line": 3,
                                                          "quote": self.body[1]})
        self.assertIsNone(ok)
        self.assertIn("private key", why)


class RefusedDashDOptionClearsWork(RepoCase):
    def test_dry_run_refused_clears_old_files(self):
        self.init_repo()
        drop = tempfile.mkdtemp(prefix="leadsman-handoff-")
        self.addCleanup(shutil.rmtree, drop, True)
        src = os.path.join(drop, "a.md")
        with open(src, "w") as fh:
            fh.write("# Old ticket A\nStatus:\n\nbody\n")
        self.check("save", "ticket", "--from", src)
        res = subprocess.run([sys.executable, CHECK, "--data", self.data, "save", "ticket", "--from", src,
                              "--dry-run"], env=self.env, cwd=self.project, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        self.assertEqual(res.returncode, 2)
        self.assertFalse(os.path.exists(os.path.join(self.data, "work", "ticket.md")))


if __name__ == "__main__":
    unittest.main()
