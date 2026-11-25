"""Regression tests for the twenty-fourth review round. Each fails without its fix."""

import string
import time
import unittest

from helpers import RepoCase

from leadsman import verdict

CHARS = string.ascii_letters + string.digits


class LongLinesNearEvidenceStayFast(RepoCase):
    def test_many_citations_next_to_huge_line(self):
        self.init_repo({"app.py": "def handle_export_request(rows):\nx = '%s'\n    return rows\n" % ("-eyJ" * 300000)})
        cite = {"file": "app.py", "line": 1, "quote": "def handle_export_request(rows):"}
        start = time.time()
        for _ in range(20):
            ok, why = verdict.confirm_evidence(self.project, cite)
            self.assertIsNotNone(ok, why)
        self.assertLess(time.time() - start, 5)


class HidePartsIsLinear(unittest.TestCase):
    def test_long_value_fast(self):
        value = "".join(CHARS[(i * 17 + i // 7) % len(CHARS)] for i in range(6000))
        start = time.time()
        out = verdict._hide_parts("see " + value[100:140] + " here", [value])
        self.assertLess(time.time() - start, 0.5)
        self.assertNotIn(value[100:140], out)


if __name__ == "__main__":
    unittest.main()
