"""Regression tests for the twenty-second review round. Each fails without its fix."""

import json
import string
import time
import unittest

from helpers import RepoCase

from leadsman import secrets

CHARS = string.ascii_letters + string.digits + "+/"


def body_lines(count, seed=1):
    return ["".join(CHARS[(seed * 13 + n * 31 + i * 7) % len(CHARS)] for i in range(64)) for n in range(count)]


HEAD = "-----" + "BEGIN OPENSSH " + "PRIVATE KEY" + "-----"
TAIL = "-----" + "END OPENSSH " + "PRIVATE KEY" + "-----"


class TicketKeyBodyHidden(RepoCase):
    def setUp(self):
        RepoCase.setUp(self)
        self.init_repo()

    def prepare(self, text):
        return self.check("prepare", "--ticket", self.ticket(text))

    def test_key_without_end_line(self):
        body = body_lines(13)
        out = self.prepare("# Fix parse_config\nStatus:\n\nKey:\n%s\n%s\n" % (HEAD, "\n".join(body)))
        for line in body:
            self.assertNotIn(line[:20], out)

    def test_key_block_longer_than_old_limit(self):
        body = body_lines(345)
        out = self.prepare("# Fix parse_config\nStatus:\n\n%s\n%s\n%s\n" % (HEAD, "\n".join(body), TAIL))
        for line in body[::20]:
            self.assertNotIn(line[:20], out)


class RepeatedHeadersStayFast(unittest.TestCase):
    def test_many_headers_without_end(self):
        start = time.time()
        secrets.mask((HEAD + "\nabc\n") * 5000)
        self.assertLess(time.time() - start, 3)


if __name__ == "__main__":
    unittest.main()
