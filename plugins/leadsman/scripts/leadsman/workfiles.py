"""Files the skills hand to the scripts, kept in the plugin data folder's work/ folder.

The model cannot write into the data folder itself: Claude Code treats it (under ~/.claude) as sensitive. It also
cannot pass JSON or ticket text in a here-document, because Claude Code's shell check refuses `{"` in a command.
So the model writes the text with the Write tool to a file in a temp folder, and `save --from FILE` copies it in.
Only regular files under a temp folder are accepted, so the model cannot be steered into copying, say, a key file.
"""

import argparse
import os
import sys
import tempfile


class Once(argparse.Action):
    """An option that may be given only once, so a value added later cannot replace the pinned one."""

    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            parser.error("%s may be given only once" % option_string)
        setattr(namespace, self.dest, values)


def safe_stdout():
    """Print characters that cannot be encoded (a lone surrogate from JSON) as replacements, not a traceback."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")


def work_file(data, name):
    folder = os.path.join(data, "work")
    if os.path.islink(folder):
        raise OSError(0, "work folder is a link")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, name)


def write_replace(path, text):
    """Write text to path via mkstemp (a new file, never a planted link) and os.replace (swaps a link, not its target)."""
    fd, tmp = tempfile.mkstemp(prefix=".write-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="replace") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def temp_roots():
    roots = {os.path.realpath(tempfile.gettempdir())}
    for candidate in ("/tmp", "/var/tmp"):
        if os.path.isdir(candidate):
            roots.add(os.path.realpath(candidate))
    return roots


def read_handoff(path, max_bytes):
    """The file's bytes (up to max_bytes + 1), or raise ValueError saying why it is refused."""
    real = os.path.realpath(path)
    if not any(real.startswith(root + os.sep) for root in temp_roots()):
        raise ValueError("%s is not in a temp folder; write it to your scratchpad or the system temp folder" % path)
    if not os.path.isfile(real):
        raise ValueError("%s is not a regular file" % path)
    try:
        with open(real, "rb") as fh:
            return fh.read(max_bytes + 1)
    except OSError as exc:
        raise ValueError("%s cannot be read (%s)" % (path, exc.strerror))
