import json
import os
import subprocess
import sys
import unittest

from helpers import CFGTOOL, RepoCase, fake

from leadsman import config, statusmap


class Resolve(RepoCase):
    def resolve(self):
        return config.resolve(self.data, self.project)

    def test_defaults(self):
        eff = self.resolve()
        self.assertEqual(eff.get("preset"), "standard")
        self.assertEqual(eff.get("overlap"), "on")
        self.assertEqual(eff.sources["overlap"], "default")

    def test_plugin_option_preset(self):
        os.environ["CLAUDE_PLUGIN_OPTION_PRESET"] = "solo"
        eff = self.resolve()
        self.assertEqual(eff.get("overlap"), "off")
        self.assertIn("plugin option", eff.sources["overlap"])

    def test_bad_plugin_option_reported(self):
        os.environ["CLAUDE_PLUGIN_OPTION_PRESET"] = "yolo"
        with self.assertRaises(config.ConfigError):
            self.resolve()

    def test_user_overrides_preset(self):
        self.write_config({"preset": "strict", "stale_days": 30})
        eff = self.resolve()
        self.assertEqual(eff.get("evidence"), "all")
        self.assertEqual(eff.get("stale_days"), 30)

    def test_project_tightens(self):
        self.init_repo()
        self.write_config({"overlap": "off", "evidence": "all", "stale_days": 2}, where="project")
        eff = self.resolve()
        self.assertEqual((eff.get("overlap"), eff.get("evidence"), eff.get("stale_days")), ("off", "all", 2))
        self.assertEqual(eff.notes, [])

    def test_project_cannot_loosen(self):
        self.init_repo()
        self.write_config({"preset": "strict"})
        self.write_config({"evidence": "code", "stale_days": 90, "overlap": "on"}, where="project")
        eff = self.resolve()
        self.assertEqual(eff.get("evidence"), "all")
        self.assertEqual(eff.get("stale_days"), 1)
        self.assertEqual(len(eff.notes), 2)

    def test_project_preset_cannot_loosen(self):
        self.init_repo()
        self.write_config({"preset": "strict"})
        self.write_config({"preset": "solo"}, where="project")
        eff = self.resolve()
        self.assertEqual(eff.get("evidence"), "all")
        self.assertEqual(eff.get("overlap"), "off")
        self.assertTrue(eff.notes)

    def test_project_exclude_paths_union(self):
        self.init_repo()
        self.write_config({"exclude_paths": ["a/**"]})
        self.write_config({"exclude_paths": ["b/**"]}, where="project")
        self.assertEqual(self.resolve().get("exclude_paths"), ["a/**", "b/**"])

    def test_project_file_found_from_subfolder(self):
        self.init_repo()
        self.write_config({"overlap": "off"}, where="project")
        eff = config.resolve(self.data, os.path.join(self.project, "src"))
        self.assertEqual(eff.get("overlap"), "off")

    def test_unknown_key_with_hint(self):
        self.write_config({"overlapp": "on"})
        with self.assertRaises(config.ConfigError) as cm:
            self.resolve()
        self.assertIn("overlap", str(cm.exception))

    def test_bad_values(self):
        for bad in ({"max_refs": 0}, {"max_refs": 500}, {"stale_days": -1}, {"stale_days": True},
                    {"rules_file": "/etc/passwd"}, {"rules_file": "../x.md"}, {"exclude_paths": "vendor"},
                    {"status_map": {"Open": "doing"}}, {"version": 99}, {"evidence": "none"}):
            self.write_config(bad)
            with self.assertRaises(config.ConfigError, msg=bad):
                self.resolve()

    def test_secret_value_refused(self):
        self.write_config({"exclude_paths": [fake("github")]})
        with self.assertRaises(config.ConfigError):
            self.resolve()

    def test_invalid_json_reported(self):
        with open(os.path.join(self.data, "config.json"), "w") as fh:
            fh.write("{")
        with self.assertRaises(config.ConfigError):
            self.resolve()


class StatusMap(unittest.TestCase):
    def test_native_done_is_high(self):
        g = statusmap.guess("Shipped", "done")
        self.assertEqual((g["category"], g["confidence"]), ("done", "high"))

    def test_name_only(self):
        self.assertEqual(statusmap.guess("Code Review")["category"], "review")
        self.assertEqual(statusmap.guess("Selected for Development")["category"], "ready")
        self.assertEqual(statusmap.guess("In QA")["confidence"], "high")

    def test_native_and_name_disagree_is_medium(self):
        g = statusmap.guess("Backlog", "done")
        self.assertEqual(g["confidence"], "medium")

    def test_unknown_is_low(self):
        self.assertEqual(statusmap.guess("Blue")["confidence"], "low")

    def test_map_skips_bad_items(self):
        self.assertEqual(len(statusmap.map_statuses(["Done", {"name": ""}, 5, {"x": 1}])), 1)


class Cfgtool(RepoCase):
    def test_show_json(self):
        out = json.loads(self.cfg("show", "--json", expect=0))
        self.assertEqual(out["values"]["preset"], "standard")

    def test_set_and_unset(self):
        self.cfg("set", "overlap", "off", expect=0)
        self.assertEqual(config.resolve(self.data, self.project).get("overlap"), "off")
        self.cfg("unset", "overlap", expect=0)
        self.assertEqual(config.resolve(self.data, self.project).get("overlap"), "on")

    def test_set_invalid_not_saved(self):
        out = self.cfg("set", "max_refs", "0", expect=1)
        self.assertIn("Not saved", out)
        self.assertFalse(os.path.exists(os.path.join(self.data, "config.json")))

    def test_set_list_add_remove(self):
        self.cfg("set", "exclude_paths", "dist/**", "--add", expect=0)
        self.cfg("set", "exclude_paths", "vendor/**", "--add", expect=0)
        self.cfg("set", "exclude_paths", "dist/**", "--remove", expect=0)
        self.assertEqual(config.resolve(self.data, self.project).get("exclude_paths"), ["vendor/**"])

    def test_set_project_loosening_reports_note(self):
        self.init_repo()
        self.cfg("set", "preset", "strict", expect=0)
        out = self.cfg("set", "evidence", "code", "--project", expect=0)
        self.assertIn("Ignored", out)

    def test_explain(self):
        out = self.cfg("explain", "evidence", expect=0)
        self.assertIn("stricter", out)
        self.assertIn("Did you mean", self.cfg("explain", "evidense", expect=1))

    def test_detect_no_git_suggests_solo(self):
        out = json.loads(self.cfg("detect", "--json", expect=0))
        self.assertEqual(out["suggestions"][0]["value"], "solo")

    def test_detect_finds_vendor_dir(self):
        self.init_repo({"vendor/lib.py": "x\n", "a.py": "y\n"})
        out = json.loads(self.cfg("detect", "--json", expect=0))
        self.assertIn("vendor", out["facts"]["vendor_dirs"])

    def test_init_previews_then_saves(self):
        self.init_repo({"node_modules/x.js": "x\n", "a.py": "y\n"})
        out = self.cfg("init", expect=0)
        self.assertIn("--yes", out)
        self.assertFalse(os.path.exists(os.path.join(self.data, "config.json")))
        self.cfg("init", "--yes", expect=0)
        eff = config.resolve(self.data, self.project)
        self.assertEqual(eff.get("exclude_paths"), ["node_modules/**"])
        self.assertIn("already exists", self.cfg("init", "--yes", expect=1))

    def test_statuses_apply_high_and_accepted(self):
        path = os.path.join(self.data, "statuses.json")
        with open(path, "w") as fh:
            json.dump([{"name": "Shipped", "native": "done"}, "Blue", "Code Review"], fh)
        preview = json.loads(self.cfg("statuses", "--file", path, expect=0))
        self.assertEqual(len(preview["guesses"]), 3)
        with open(path, "w") as fh:
            json.dump([{"name": "Shipped", "native": "done"}, {"name": "Blue", "accept": "backlog"}, "Code Review"], fh)
        out = self.cfg("statuses", "--file", path, "--apply", expect=0)
        self.assertNotIn("Not mapped", out)
        self.assertEqual(config.resolve(self.data, self.project).get("status_map"),
                         {"Shipped": "done", "Code Review": "review", "Blue": "backlog"})

    def test_no_data_folder_refused(self):
        res = subprocess.run([sys.executable, CFGTOOL, "show"], env=self.env, cwd=self.project,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        self.assertEqual(res.returncode, 1)
        self.assertIn("No data folder", res.stderr)

    def test_doctor(self):
        self.init_repo()
        out = self.cfg("doctor", expect=0)
        self.assertIn("0 problem(s)", out)
        self.assertIn("sample lookup ran", out)

    def test_doctor_reports_bad_config(self):
        self.write_config({"nope": 1})
        self.assertIn("FAIL config", self.cfg("doctor", expect=1))


if __name__ == "__main__":
    unittest.main()
