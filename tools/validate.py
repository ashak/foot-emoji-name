#!/usr/bin/env python3
"""Regression tests for the foot regex-launch emoji pattern.

Compiles the pattern with glibc regcomp(REG_EXTENDED) via ctypes in both the
C.UTF-8 and en_GB.UTF-8 locales and asserts the invariants the feature relies
on:

  * the pattern compiles in both locales (a bare `foot -C` only checks the
    locale foot happens to run in),
  * every emoji in the database matches as one whole cluster, including the
    England/Scotland/Wales subdivision flags,
  * no ASCII character, and none of a suite of common non-emoji text
    (box-drawing, math, scripts, punctuation), matches,
  * no character of the Unicode tag block matches on its own, so the invisible
    formatting characters inside a subdivision flag cannot be labelled apart
    from their flag,
  * the pattern can never match an empty string (that would make foot's
    per-line match loop spin).

Nothing here touches the filesystem or your foot configuration.
"""

import argparse
import ctypes
import ctypes.util
import json
import os
import sys

REG_EXTENDED = 0x1
REG_STARTEND = 0x4
BUFFER = ctypes.c_char * 65536

db_default = "/usr/share/omarchy/shell/plugins/emojis/emojis.json"

FALSE_POSITIVES = [
    "23:33",
    "23:19 - Mercy says its late.",
    "It was lively :)",
    "#",
    "0",
    "13:37",
    "\U0001D54F",  # mathematical double-struck x
    "\u03b1\u03b2\u03b3\u03b4",
    "\u4f60\u597d\u4e16\u754c",
    "\u0416",
    "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645",
    "\u2502",
    "\u2500",
    "\u2026",
    "a",
    "A1",
    "@",
    "\u00df",
    "\u2192",
    "\u00a7",
    "\u00b6",
    "\u00be",
    "\u00b7",
    "\u201c",
    "3.14",
]

SAMPLES = [
    ("23:38 \u2190 \U0001F97C Gushie hath left the realm.", [(10, 14)]),
    ("07:14 - BigG \U0001F30A\U0001F30A\U0001F30A", [(13, 17), (17, 21), (21, 25)]),
    ("a\u2764\ufe0fb", [(1, 7)]),
    ("\U0001f1ec\U0001f1e7 in text", [(0, 8)]),
    ("1\uFE0F\u20E3", [(0, 7)]),
    ("\U0001F93F", [(0, 4)]),
    ("\U0001F469\u200d\U0001F4BB", [(0, 11)]),
    ("\U0001F469\u200d\U0001F469\u200d\U0001F467\u200d\U0001F466", [(0, 25)]),
]


class Matches(ctypes.Structure):
    _fields_ = [("rm_so", ctypes.c_int), ("rm_eo", ctypes.c_int)]


def regcomp(libc, regex_ptr, pattern):
    rc = libc.regcomp(regex_ptr, pattern.encode("utf-8"), REG_EXTENDED)
    if rc:
        err = ctypes.create_string_buffer(512)
        libc.regerror(rc, regex_ptr, err, 512)
        raise RuntimeError(err.value.decode("utf-8", "replace"))
    return True


def scan_all(libc, regex_ptr, text):
    data = text.encode("utf-8")
    out, start = [], 0
    while start < len(data):
        m = Matches()
        m.rm_so = start
        m.rm_eo = len(data)
        if libc.regexec(regex_ptr, data, 1, ctypes.byref(m), REG_STARTEND) != 0:
            break
        if m.rm_so == m.rm_eo:
            out.append(("EMPTY@%d" % start,))
            break
        out.append((m.rm_so, m.rm_eo))
        start = m.rm_eo
    return out


def check_locale(libc, setlocale, pattern, entries, name):
    setlocale(6, name)
    regex_ptr = BUFFER()
    try:
        regcomp(libc, regex_ptr, pattern)
    except RuntimeError as exc:
        raise AssertionError("[%s] compile failed: %s" % (name, exc))

    unexpected = []
    for em in entries:
        spans = scan_all(libc, regex_ptr, em)
        nbytes = len(em.encode("utf-8"))
        if spans != [(0, nbytes)]:
            unexpected.append((em, spans))
    assert not unexpected, "[%s] unexpected: %r" % (name, unexpected[:5])

    # The subdivision flags (England/Scotland/Wales) are a black flag plus tag
    # letters plus a cancel tag. Each has to match in one span, and the tag
    # characters must not be independently matchable: a tag character has no
    # width of its own, so matching one alone would label nothing visible.
    for em in entries:
        if any(0xE0000 <= ord(c) <= 0xE007F for c in em):
            nbytes = len(em.encode("utf-8"))
            assert scan_all(libc, regex_ptr, em) == [(0, nbytes)], (
                "[%s] subdivision flag not matched whole: %r" % (name, em)
            )
    for cp in list(range(0xE0061, 0xE007F)) + [0xE007F]:
        assert scan_all(libc, regex_ptr, chr(cp)) == [], (
            "[%s] tag block char %04X matches on its own" % (name, cp)
        )
    # A tag run with no letters is not a flag, and the cancel tag on its own is
    # not one either: both degrade to the bare black flag, which is a real
    # database entry in its own right.
    for text in ("🏴\U000e007f", "🏴\U000e0067"):
        assert scan_all(libc, regex_ptr, text) == [(0, 4)], (
            "[%s] %r did not degrade to the black flag: %r"
            % (name, text, scan_all(libc, regex_ptr, text))
        )

    assert scan_all(libc, regex_ptr, "") == [], "[%s] empty-string match!" % name
    for item in FALSE_POSITIVES:
        assert scan_all(libc, regex_ptr, item) == [], "[%s] false positive %r" % (name, item)
    for cp in range(0x20, 0x7F):
        assert scan_all(libc, regex_ptr, chr(cp)) == [], "[%s] ASCII leak %r" % (name, chr(cp))
    for text, expect in SAMPLES:
        assert scan_all(libc, regex_ptr, text) == expect, "[%s] sample %r != %r" % (name, text, expect)


def load_pattern(path):
    """Extract the regex from a file: either a bare pattern or a generated
    [regex:emoji] ini (surrounded by comment/header lines)."""
    text = open(path, encoding="utf-8").read()
    for line in text.splitlines():
        if line.startswith("regex="):
            return line[len("regex="):]
    return text.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=db_default)
    ap.add_argument("--pattern", default=None, help="path to a file containing the regex (default: read from --db and generate)")
    args = ap.parse_args()

    libc = ctypes.CDLL(ctypes.util.find_library("c"))
    libc.regcomp.restype = ctypes.c_int
    libc.regexec.restype = ctypes.c_int
    setlocale = ctypes.CFUNCTYPE(
        ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p
    )(("setlocale", libc), None)

    entries = [item["e"] for item in json.load(open(args.db, encoding="utf-8"))]

    if args.pattern:
        pattern = load_pattern(args.pattern)
    else:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from generate import build_pattern

        pattern = build_pattern(entries)

    for loc in (b"C.UTF-8", b"en_GB.UTF-8"):
        check_locale(libc, setlocale, pattern, entries, loc)

    print("OK: compiles + matches all %d emoji as whole clusters, no false" % len(entries))
    print("    positives, in both C.UTF-8 and en_GB.UTF-8")


if __name__ == "__main__":
    main()