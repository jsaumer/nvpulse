"""Make untrusted strings safe to put on screen.

Process names and command lines are controlled by whoever started the process,
which on a shared machine can be another (hostile) user. Textual only strips a
handful of control codes (BEL, BS, VT, FF, CR), so without this module an ESC byte
in someone's argv would reach your terminal as a live escape sequence (title
spoofing, screen clearing, OSC 52 clipboard writes, ...). Bidi overrides and other
invisible format characters could also make a process look like something else.
"""

from __future__ import annotations

import re
import unicodedata

ELLIPSIS = "…"

# Unicode categories that never belong in a displayed command line:
#   Cc control (C0, DEL, C1), Cf format (bidi overrides, zero-width chars),
#   Zl/Zp line and paragraph separators, Co private use, Cs surrogates, Cn unassigned.
_UNSAFE_CATEGORIES = {"Cc", "Cf", "Zl", "Zp", "Co", "Cs", "Cn"}


def _escape_char(ch: str) -> str:
    cp = ord(ch)
    if ch in "\t\n":
        return " "
    if cp <= 0xFF:
        return f"\\x{cp:02x}"
    if cp <= 0xFFFF:
        return f"\\u{cp:04x}"
    return f"\\U{cp:08x}"


def clean(text: object, max_len: int = 256) -> str:
    """Return ``text`` with unsafe characters shown as visible ``\\xNN`` escapes.

    The result is truncated to ``max_len`` characters, so a multi-megabyte argv
    can't stall rendering.
    """
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    # Truncate before escaping (bounds the work), then again after (escapes expand).
    if len(s) > max_len * 4:
        s = s[: max_len * 4]
    out = []
    for ch in s:
        if ch.isprintable() and unicodedata.category(ch) not in _UNSAFE_CATEGORIES:
            out.append(ch)
        else:
            out.append(_escape_char(ch))
    result = "".join(out)
    if len(result) > max_len:
        result = result[: max(0, max_len - 1)] + ELLIPSIS
    return result


# ------------------------------------------------------------------ redaction
MASK = "•••"

_SECRET_WORD = (
    r"(?:password|passwd|pass|pwd|secret|token|api[-_]?key|apikey|access[-_]?key|secret[-_]?key"
    r"|auth[-_]?token|bearer|credentials?|private[-_]?key|client[-_]?secret)"
)
# --password=x  --api-key x  -token x   (flag name must END with the secret word,
# so --author / --tokenizer are left alone)
_FLAG_RE = re.compile(rf"(?i)(?<!\S)(--?(?:[\w.-]*[-_.])?{_SECRET_WORD})(=|\s+)(?!-)(\S+)")
# PASSWORD=x  HF_TOKEN=x  AWS_SECRET_ACCESS_KEY=x
_ENV_RE = re.compile(rf"(?i)(?<![\w-])([A-Z0-9_]*{_SECRET_WORD}[A-Z0-9_]*)=(\S+)")
# scheme://user:password@host
_URL_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+):([^/\s@]+)@")


def redact(cmdline: str) -> str:
    """Mask values that look like secrets in a command line."""
    if not cmdline:
        return cmdline
    s = _URL_RE.sub(rf"\1:{MASK}@", cmdline)
    s = _FLAG_RE.sub(rf"\1\2{MASK}", s)
    s = _ENV_RE.sub(rf"\1={MASK}", s)
    return s
