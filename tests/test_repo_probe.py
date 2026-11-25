import os
import time
import unittest

from helpers import RepoCase

from leadsman import context, probe, repo


class SafePath(RepoCase):
    def test_refuses_traversal_and_absolute_outside(self):
        self.init_repo()
        self.assertIsNone(repo.safe_path(self.project, "../data/x"))
        self.assertIsNone(repo.safe_path(self.project, "/etc/hosts"))
        self.assertIsNone(repo.safe_path(self.project, "src/../../x"))
        self.assertIsNone(repo.safe_path(self.project, "a\x00b"))

    def test_refuses_symlink_escape(self):
        self.init_repo()
        os.symlink(self.data, os.path.join(self.project, "out"))
        self.assertIsNone(repo.safe_path(self.project, "out/ticket.md"))

    def test_accepts_nested(self):
        self.init_repo()
        real, rel = repo.safe_path(self.project, "./src/app.py")
        self.assertEqual(rel, "src/app.py")
        self.assertTrue(os.path.isfile(real))

    def test_repo_root_none_without_git(self):
        self.assertIsNone(repo.repo_root(self.project))


class Probe(RepoCase):
    def refs(self, *pairs):
        return [{"kind": k, "value": v, "line": 1} for k, v in pairs]

    def test_tracked_file_found_with_line(self):
        self.init_repo()
        out = probe.probe(self.project, [{"kind": "path", "value": "src/app.py", "line": 1, "at_line": 4}])
        self.assertTrue(out[0]["found"])
        self.assertEqual(out[0]["evidence"][0], {"file": "src/app.py", "line": 4,
                                                 "text": "def parse_config(path):"})

    def test_line_past_end_noted(self):
        self.init_repo()
        out = probe.probe(self.project, [{"kind": "path", "value": "src/app.py", "line": 1, "at_line": 999}])
        self.assertIn("not 999", out[0]["note"])

    def test_missing_file_reported(self):
        self.init_repo()
        out = probe.probe(self.project, self.refs(("path", "src/gone.py")))
        self.assertFalse(out[0]["found"])

    def test_file_found_by_bare_name(self):
        self.init_repo()
        out = probe.probe(self.project, self.refs(("path", "routes.py")))
        self.assertTrue(out[0]["found"])
        self.assertEqual(out[0]["evidence"][0]["file"], "src/routes.py")

    def test_traversal_reference_not_checked(self):
        self.init_repo()
        out = probe.probe(self.project, self.refs(("path", "../../etc/passwd")))
        self.assertFalse(out[0]["found"])
        self.assertIn("outside", out[0]["note"])

    def test_symbol_and_string_hits_with_lines(self):
        self.init_repo()
        out = probe.probe(self.project, self.refs(("symbol", "parse_config"), ("string", "Missing config file")))
        self.assertEqual(out[0]["evidence"][0]["file"], "src/app.py")
        self.assertEqual(out[0]["evidence"][0]["line"], 4)
        self.assertEqual(out[1]["evidence"][0]["line"], 6)

    def test_dotted_symbol_falls_back_to_last_part(self):
        self.init_repo()
        out = probe.probe(self.project, self.refs(("symbol", "ReportBuilder.render_total")))
        self.assertTrue(out[0]["found"])
        self.assertIn("render_total", out[0]["note"])

    def test_pattern_that_looks_like_an_option_is_searched_literally(self):
        self.init_repo({"a.txt": "--output=x\n"})
        out = probe.probe(self.project, self.refs(("string", "--output=x")))
        self.assertTrue(out[0]["found"])
        out = probe.probe(self.project, self.refs(("string", ".*")))
        self.assertFalse(out[0]["found"])

    def test_route_parameters_stripped(self):
        self.init_repo()
        out = probe.probe(self.project, self.refs(("route", "/api/reports/export/{id}")))
        self.assertTrue(out[0]["found"])

    def test_commit_mention_found(self):
        self.init_repo(message="Fix config error (#42)")
        out = probe.probe(self.project, self.refs(("issue", "#42"), ("issue", "#43")))
        self.assertTrue(out[0]["found"])
        self.assertFalse(out[1]["found"])

    def test_excluded_paths_skipped(self):
        self.init_repo({"vendor/lib.py": "def parse_config(): pass\n", "src/a.py": "x = 1\n"})
        out = probe.probe(self.project, self.refs(("symbol", "parse_config")), exclude=["vendor/**"])
        self.assertFalse(out[0]["found"])

    def test_hits_capped(self):
        self.init_repo({"a.py": "token_name\n" * 50})
        out = probe.probe(self.project, self.refs(("symbol", "token_name")))
        self.assertEqual(out[0]["count"], 50)
        self.assertEqual(len(out[0]["evidence"]), probe.MAX_HITS)

    def test_no_git_everything_unchecked(self):
        out = probe.probe(None, self.refs(("symbol", "parse_config")))
        self.assertFalse(out[0]["checked"])

    def test_masked_secret_not_searched(self):
        self.init_repo()
        out = probe.probe(self.project, self.refs(("string", "key [hidden: GitHub token]")))
        self.assertFalse(out[0]["checked"])

    @unittest.expectedFailure
    def test_known_miss_renamed_symbol(self):
        # Known miss: a renamed function is reported missing, not found under its new name.
        self.init_repo()
        out = probe.probe(self.project, self.refs(("symbol", "load_config")))
        self.assertTrue(out[0]["found"])


class Context(RepoCase):
    def test_no_git_repository(self):
        ctx = context.gather(self.project)
        self.assertIsNone(ctx["repo_root"])
        self.assertFalse(ctx["overlap_possible"])

    def test_repo_without_remote(self):
        self.init_repo()
        ctx = context.gather(self.project)
        self.assertEqual(ctx["repo_root"], os.path.realpath(self.project))
        self.assertEqual(ctx["branch"], "master")
        self.assertIsNone(ctx["default_branch"])
        self.assertFalse(ctx["stale"])
        self.assertFalse(ctx["overlap_possible"])

    def _clone_behind(self):
        upstream = os.path.join(self.tmp, "upstream")
        os.makedirs(upstream)
        self.git("init", "-q", "-b", "master", cwd=upstream)
        self.write("a.txt", "1\n", root=upstream)
        self.git("add", "-A", cwd=upstream)
        self.git("commit", "-q", "-m", "one", cwd=upstream)
        os.rmdir(self.project)
        self.git("clone", "-q", upstream, self.project, cwd=self.tmp)
        self.write("a.txt", "2\n", root=upstream)
        self.git("commit", "-q", "-am", "two", cwd=upstream)
        self.git("fetch", "-q", "origin")
        return upstream

    def test_behind_count_from_local_refs(self):
        self._clone_behind()
        ctx = context.gather(self.project)
        self.assertEqual(ctx["default_branch"], "master")
        self.assertEqual(ctx["behind"], 1)
        self.assertTrue(ctx["stale"])
        self.assertEqual(ctx["fetch_command"], "git fetch origin master")

    def test_old_fetch_is_stale(self):
        self._clone_behind()
        self.git("merge", "-q", "--ff-only", "origin/master")
        ctx = context.gather(self.project, now=time.time() + 30 * 86400)
        self.assertEqual(ctx["behind"], 0)
        self.assertTrue(ctx["stale"])
        self.assertIn("days ago", ctx["stale_reason"])
        self.assertFalse(context.gather(self.project)["stale"])

    def test_github_slug(self):
        self.assertEqual(context.github_slug("git@github.com:o/r.git"), "o/r")
        self.assertEqual(context.github_slug("https://github.com/o/r"), "o/r")
        self.assertIsNone(context.github_slug("https://gitlab.example.invalid/o/r.git"))
        self.assertIsNone(context.github_slug("https://github.com.evil.invalid/o/r"))


if __name__ == "__main__":
    unittest.main()
