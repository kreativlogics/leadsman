"""Regression tests for the fourteenth review round. Each fails without its fix."""

import json
import unittest

from helpers import RepoCase

from leadsman import probe, secrets

# A secret-shaped value with a "|", built from pieces, so none sits in the repository whole.
PIPE = "Zq8" + "|wR4kTn7vXp2m"
WORDS = "# Sign-in fails\nStatus:\n\nSee db://u:false,@h and db://u:unverified@h\n"


class OrdinaryWordsNotRemembered(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()

    def test_url_password_words_not_remembered(self):
        self.assertEqual(secrets.found_values(WORDS, everywhere=True), [])
        value = "Zq8" + "Lm4vRt9wXk2Pn"
        self.assertEqual(secrets.found_values("db://u:%s@h" % value, everywhere=True), [value])

    def test_prepare_json_still_parses(self):
        out = json.loads(self.check("prepare", "--ticket", self.ticket(WORDS)))
        self.assertIn("references", out)

    def test_downgrade_still_shown(self):
        data = self.findings(decision="ask", question="Which page?",
                             check_valid={"status": "pass", "summary": "still there",
                                          "evidence": [{"file": "src/none.py", "line": 1,
                                                        "quote": "nothing like this here"}]})
        out = self.check("verdict", "--findings", self.write_findings(data, ticket=WORDS))
        self.assertIn("unverified", out)


class PipeValueInDroppedEvidence(RepoCase):
    def test_remembered_value_with_pipe_hidden(self):
        self.init_repo()
        data = self.findings(decision="ask", question="Which page?",
                             check_valid={"status": "pass", "summary": "still there",
                                          "evidence": [{"file": PIPE, "line": 1, "quote": "nothing like this here"}]})
        ticket = '# Sign-in fails\nStatus:\n\npassword = "%s"\n' % PIPE
        out = self.check("verdict", "--findings", self.write_findings(data, ticket=ticket))
        self.assertNotIn("Zq8", out)


class NewlineFileName(RepoCase):
    def test_hit_names_the_real_file(self):
        self.init_repo({"zz\nsrc/app.py": "x\n" * 9 + "PLANTED_NEEDLE_here = 1\n", "src/app.py": "y\n"})
        hits, total = probe.grep(self.project, "PLANTED_NEEDLE_here")
        self.assertEqual(total, 1)
        self.assertEqual((hits[0]["file"], hits[0]["line"]), ("zz\nsrc/app.py", 10))


if __name__ == "__main__":
    unittest.main()
