from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Iterator

SIMPLE_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "a": "\a", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
PLAIN_ESCAPES = "\\\"'?"
HEX_WIDTH = {"x": 2, "u": 4, "U": 8}
REVERSE_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
CHAR_PREFIXES = ("u8'", "u'", "U'", "L'")
RAW_PREFIXES = ('u8R"', 'uR"', 'UR"', 'LR"', 'R"')
IDENT_CHARS = frozenset("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    stop: int
    line: int
    in_comment: bool
    prefix: str = ""


def unescape(raw: str) -> str:
    out = []
    i = 0
    size = len(raw)
    while i < size:
        char = raw[i]
        if char != "\\" or i + 1 >= size:
            out.append(char)
            i += 1
            continue
        code = raw[i + 1]
        i += 2
        if code in SIMPLE_ESCAPES:
            out.append(SIMPLE_ESCAPES[code])
        elif code in PLAIN_ESCAPES:
            out.append(code)
        elif code in HEX_WIDTH:
            width = HEX_WIDTH[code]
            digits = raw[i:i + width]
            valid = len(digits) == width and all(c in HEX_DIGITS for c in digits)
            out.append(chr(int(digits, 16)) if valid and int(digits, 16) <= 0x10FFFF else code)
            i += len(digits)
        else:
            out.append(code)
    return "".join(out)


def escape(text: str) -> str:
    return "".join(REVERSE_ESCAPES.get(char, char) for char in text)


class Scanner:
    def __init__(self, source: str):
        self.source = source
        self.starts = [0] + [i + 1 for i, char in enumerate(source) if char == "\n"]

    def line_at(self, pos: int) -> int:
        return bisect_right(self.starts, pos)

    def _digit_separator(self, pos: int) -> bool:
        source = self.source
        return (pos > 0 and pos + 1 < len(source)
                and source[pos - 1].isalnum() and source[pos + 1].isalnum())

    def _char_literal_end(self, pos: int) -> int:
        source, size = self.source, len(self.source)
        cursor = pos + 1
        while cursor < size and source[cursor] != "'":
            cursor += 2 if source[cursor] == "\\" else 1
        return cursor + 1

    def _char_prefix(self, pos: int) -> int:
        for pref in CHAR_PREFIXES:
            if self.source.startswith(pref, pos):
                return pos + len(pref) - 1
        return -1

    def _raw_literal(self, pos: int):
        source, size = self.source, len(self.source)
        for pref in RAW_PREFIXES:
            if not source.startswith(pref, pos):
                continue
            if pos and source[pos - 1] in IDENT_CHARS:
                continue
            quote = pos + len(pref) - 1
            paren = source.find("(", quote + 1, quote + 18)
            if paren < 0:
                return None
            delim = source[quote + 1:paren]
            close = ")" + delim + '"'
            stop = source.find(close, paren + 1)
            if stop < 0:
                return pos, size, source[paren + 1:]
            return pos, stop + len(close), source[paren + 1:stop]
        return None

    def _string_end(self, pos: int) -> int:
        source, size = self.source, len(self.source)
        cursor = pos + 1
        while cursor < size:
            char = source[cursor]
            if char == "\\":
                cursor += 2
                continue
            if char in ('"', "\n"):
                break
            cursor += 1
        return cursor

    def tokens(self, min_len: int = 1) -> Iterator[Token]:
        source, size = self.source, len(self.source)
        mode = "code"
        pos = 0
        while pos < size:
            char = source[pos]
            if mode == "line":
                if char == "\n":
                    mode = "code"
                    pos += 1
                    continue
            elif mode == "block":
                if char == "*" and source.startswith("/", pos + 1):
                    mode = "code"
                    pos += 2
                    continue
            else:
                if char == "/" and source.startswith("/", pos + 1):
                    mode = "line"
                    pos += 2
                    continue
                if char == "/" and source.startswith("*", pos + 1):
                    mode = "block"
                    pos += 2
                    continue
                if char == "'" and not self._digit_separator(pos):
                    pos = self._char_literal_end(pos)
                    continue
                if char in "uUL":
                    quote = self._char_prefix(pos)
                    if quote >= 0:
                        pos = self._char_literal_end(quote)
                        continue
                if char in "RuUL":
                    raw = self._raw_literal(pos)
                    if raw is not None:
                        start, stop, text = raw
                        if len(text) >= min_len:
                            quote = source.find('"', start, stop)
                            prefix = source[start:quote].removesuffix("R")
                            yield Token(text, start, stop, self.line_at(pos), False, prefix)
                        pos = stop
                        continue

            if char == '"':
                end = self._string_end(pos)
                text = unescape(source[pos + 1:end])
                if len(text) >= min_len:
                    yield Token(text, pos, min(end + 1, size), self.line_at(pos), mode != "code")
                if mode == "line" and end < size and source[end] == "\n":
                    mode = "code"
                    pos = end
                    continue
                pos = end + 1
                continue
            pos += 1


def rewrite(text: str, mapping: dict, skip_comments: bool = True) -> tuple[str, int]:
    edits = []
    for token in Scanner(text).tokens(min_len=1):
        if skip_comments and token.in_comment:
            continue
        target = mapping.get(token.text)
        if target is None or target == token.text:
            continue
        edits.append((token.start, token.stop, token.prefix + '"' + escape(target) + '"'))
    if not edits:
        return text, 0
    chunks = []
    cursor = 0
    for start, stop, replacement in edits:
        chunks.append(text[cursor:start])
        chunks.append(replacement)
        cursor = stop
    chunks.append(text[cursor:])
    return "".join(chunks), len(edits)
