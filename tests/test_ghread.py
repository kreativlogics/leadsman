import os
import stat
import unittest

from helpers import RepoCase

from leadsman import ghread


class Allowlist(unittest.TestCase):
    def test_write_subcommands_refused_before_running(self):
        for args in (["issue", "comment", "1", "--body", "x"], ["issue", "close", "1"], ["issue", "edit", "1"],
                     ["pr", "merge", "1"], ["api", "repos/o/r/issues"], ["issue", "create"],
                     ["label", "create", "x"], ["pr", "comment", "1"]):
            with self.assertRaises(ghread.GhError) as cm:
                ghread.run(args)
            self.assertIn("only reads", str(cm.exception))

    def test_web_flag_refused(self):
        with self.assertRaises(ghread.GhError):
            ghread.run(["issue", "view", "1", "--web"])

    def test_parse_issue(self):
        self.assertEqual(ghread.parse_issue("123", "o/r"), ("o/r", "123"))
        self.assertEqual(ghread.parse_issue("#7"), (None, "7"))
        self.assertEqual(ghread.parse_issue("a/b#9"), ("a/b", "9"))
        self.assertEqual(ghread.parse_issue("https://github.com/a/b/issues/5"), ("a/b", "5"))
        for bad in ("1; rm -rf /", "--repo=x", "https://evil.invalid/a/b/issues/5", "abc"):
            with self.assertRaises(ghread.GhError):
                ghread.parse_issue(bad)

    def test_search_words_strip_options_and_syntax(self):
        self.assertEqual(ghread.search_words("--repo evil $(id) export_report `rm`"),
                         "repo evil export_report")
        self.assertEqual(ghread.search_words("a b"), "")


class FakeGh(RepoCase):
    """A fake gh on PATH records its arguments."""

    def setUp(self):
        RepoCase.setUp(self)
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        self.log = os.path.join(self.tmp, "gh.log")
        script = os.path.join(bindir, "gh")
        with open(script, "w") as fh:
            fh.write("#!/bin/sh\nprintf '%%s\\n' \"$@\" >> '%s'\necho '[]'\n" % self.log)
        os.chmod(script, stat.S_IRWXU)
        os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")

    def test_overlap_runs_two_read_commands(self):
        result = ghread.overlap("Export report fails", "o/r")
        self.assertEqual(result["query"], "export report fails")
        with open(self.log) as fh:
            args = fh.read().split("\n")
        self.assertIn("--search=export report fails", args)
        self.assertEqual(args.count("list"), 2)

    def test_overlap_refuses_bad_slug(self):
        with self.assertRaises(ghread.GhError):
            ghread.overlap("x y z", "--repo")


class NoGh(RepoCase):
    def test_missing_gh(self):
        os.environ["PATH"] = self.tmp
        with self.assertRaises(ghread.GhError) as cm:
            ghread.run(["issue", "view", "1"])
        self.assertIn("not installed", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
