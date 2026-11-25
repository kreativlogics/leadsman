"""Regression tests for the twenty-sixth review round. Each fails without its fix."""

import json
import unittest

from helpers import RepoCase

from leadsman import probe, secrets, verdict

# A password-shaped value built from pieces, so none sits in the repository whole.
VALUE = "Qx7r" + "Tz29" + "LmPa" + "84Kd"
YAML = "app:\n  name: demo\n  password:\n    \"%s\"\n  port: 8080\n" % VALUE


class GlobPath(RepoCase):
    def test_bracket_path_is_literal(self):
        self.init_repo({"k1.txt": "tracked\n"})
        self.write("k[1].txt", "untracked note\n")
        out = probe.probe_path(self.project, {"kind": "path", "value": "k[1].txt"})
        self.assertFalse(out["found"])
        self.assertNotIn("untracked note", json.dumps(out))


class ValueOnNextLine(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        secrets._KNOWN.clear()
        self.addCleanup(secrets._KNOWN.clear)
        self.init_repo({"config/app.yml": YAML})

    def test_found_values_spans_lines(self):
        self.assertIn(VALUE, secrets.found_values(YAML))
        self.assertIn(VALUE, secrets.found_values(YAML, everywhere=True))

    def test_at_line_hides_value(self):
        out = probe.probe_path(self.project, {"kind": "path", "value": "config/app.yml", "at_line": 4})
        self.assertTrue(out["found"])
        self.assertNotIn(VALUE[:8], json.dumps(out))

    def test_grep_hit_hides_value(self):
        hits, total = probe.grep(self.project, VALUE[:10])
        self.assertEqual(total, 1)
        self.assertNotIn(VALUE[:8], hits[0]["text"])

    def test_verdict_quote_hides_value(self):
        ok, why = verdict.confirm_evidence(self.project, {"file": "config/app.yml", "line": 4,
                                                          "quote": "\"%s\"" % VALUE})
        self.assertIsNotNone(ok, why)
        self.assertNotIn(VALUE[:8], ok["quote"])


if __name__ == "__main__":
    unittest.main()
