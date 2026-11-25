#!/usr/bin/env python3
"""Draw the 512 px plugin icon (a sounding lead on its line) with the standard library."""

import os
import struct
import zlib

SIZE = 512
BG = (16, 42, 67)
LINE = (214, 226, 236)
LEAD = (236, 176, 64)
MARK = (120, 160, 190)


def pixel(x, y):
    cx = SIZE // 2
    # Line from the top to the weight.
    if abs(x - cx) <= 5 and 70 <= y <= 300:
        return LINE
    # Depth marks on the line.
    for my in (120, 170, 220):
        if abs(y - my) <= 4 and abs(x - cx) <= 34:
            return MARK
    # The lead: a tapered body with a rounded base.
    if 290 <= y <= 420:
        t = (y - 290) / 130.0
        half = 34 + 46 * t
        if abs(x - cx) <= half:
            return LEAD
    if 420 < y <= 446 and (x - cx) ** 2 / 80.0 ** 2 + (y - 420) ** 2 / 26.0 ** 2 <= 1:
        return LEAD
    return BG


def png(path):
    rows = b"".join(b"\x00" + bytes(c for x in range(SIZE) for c in pixel(x, y)) for y in range(SIZE))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0)
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 9))
                 + chunk(b"IEND", b""))


if __name__ == "__main__":
    png(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins", "leadsman", ".claude-plugin",
                     "icon.png"))
