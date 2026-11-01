from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import EXTRA_SOURCES
from .catalog import (ID_ARG_CALL, classify, decode_strict, has_cjk, read_text, source_files,
                      write_text)
from .lexer import Scanner, rewrite

CONTEXT_CHARS = 160
PLACES_PER_VALUE = 6
ID_LOOKBEHIND = 64
COMPARE_LOOKBEHIND = 48
COMPARE_LOOKAHEAD = 16
UNINSTALL_OLD = "Remove_OptiScaler.bat"
UNINSTALL_NEW = "卸载_OptiScaler.bat"
UNINSTALL_MIGRATE = (f'if exist "{UNINSTALL_OLD}" if not exist "{UNINSTALL_NEW}" '
                     f'ren "{UNINSTALL_OLD}" "{UNINSTALL_NEW}" 2>nul')
MIGRATE_ANCHOR = re.compile(r'^if exist "' + re.escape(UNINSTALL_OLD) + r'"')

INI_COMMENT = re.compile(r"^(\s*;\s?)(.*)$")
INI_VALUE = re.compile(r"^(\s*)([A-Za-z_]\w*)\s*=\s*(.*?)(\s*)$")
ECHO_TEXT = re.compile(r"^(\s*(?:.*\s)?echo\s+)(.+?)\s*$")
ECHO_SKIP = re.compile(
    r"^(?:@[\w ]+$|cls$|pause$|echo\.$|REM .*$|set .*$|setlocal .*$|for .*$|if .*$|del .*$|rd .*$|"
    r"v\d[\w.+-]*$|chcp .*$|[-\s]*[\w.]+\.(?:dll|asi|bat|exe|txt)$|^-\s[\w ]+\.(?:bat|asi)$|"
    r"\^\) else \^\(|\^)$"
)
SETP_WHOLE_QUOTED = re.compile(r'^(\s*set /p\s+"[^=]+=)(.*)"\s*$', re.IGNORECASE)
SETP_PROMPT_QUOTED = re.compile(r'^(\s*set /p\s+[^="]+?=")(.*)"\s*$', re.IGNORECASE)
SETP_INLINE = re.compile(r'^(set /p\s+[^="]+=")(.*)"$', re.IGNORECASE)
PS_INI_WRITE = re.compile(
    r"\(Get-Content '([^']+)'\)\s*-replace\s*'([^']*)'\s*,\s*'([^']*)'\s*\|\s*Set-Content '\1'")
COMPARE_BEFORE = re.compile(
    r"(?:==|!=)\s*$|"
    r"(?:\.find|\.rfind|\.compare|strcmp|strncmp|_stricmp|stricmp|strstr)\s*\(\s*$|"
    r"case\s+$")
COMPARE_AFTER = re.compile(r"^\s*(?:==|!=)")


@dataclass
class Entry:
    value: str
    count: int = 0
    places: list = field(default_factory=list)
    ids: list = field(default_factory=list)
    joined: bool = False

    @property
    def first(self) -> tuple:
        return self.places[0] if self.places else ("", 0, "", False)

    def kind(self) -> str:
        if not self.places:
            return "other"
        kinds = {classify(self.value, context, comment, is_id)
                 for (_, _, context, comment), is_id in zip(self.places, self.ids)}
        for preferred in ("ui", "log", "other", "comment"):
            if preferred in kinds:
                return preferred
        return "other"


def extra_source_files(root: Path | None) -> list:
    if root is None:
        return []
    return [root / rel for rel in EXTRA_SOURCES if (root / rel).is_file()]


def scan(menu_dir: Path, headers: bool = False, extra: list | None = None) -> tuple:
    found = {}
    seen = set()
    writable = set()
    for path in source_files(menu_dir, headers) + list(extra or []):
        text = read_text(path)
        lines = text.split("\n")
        previous = None
        joined_next = False
        for token in Scanner(text).tokens(min_len=1):
            seen.add(token.text)
            if not token.in_comment:
                writable.add(token.text)
            adjacent = (previous is not None and previous.stop <= token.start
                        and not text[previous.stop:token.start].strip())
            if adjacent and previous.text in found:
                found[previous.text].joined = True
            joined_next = adjacent
            previous = token
            if len(token.text) < 2:
                continue
            entry = found.get(token.text)
            if entry is None:
                entry = found[token.text] = Entry(token.text)
            if joined_next:
                entry.joined = True
            entry.count += 1
            if len(entry.places) < PLACES_PER_VALUE:
                index = token.line - 1
                context = lines[index].strip()[:CONTEXT_CHARS] if index < len(lines) else ""
                entry.places.append((path.name, token.line, context, token.in_comment))
                entry.ids.append(bool(ID_ARG_CALL.search(
                    text[max(0, token.start - ID_LOOKBEHIND):token.start])))
    rows = sorted(found.values(), key=lambda row: -row.count)
    return rows, seen, writable


def compare_context(text: str, token) -> bool:
    return bool(COMPARE_BEFORE.search(text[max(0, token.start - COMPARE_LOOKBEHIND):token.start])
                or COMPARE_AFTER.match(text[token.stop:token.stop + COMPARE_LOOKAHEAD]))


def compare_only(texts: list) -> set:
    counts = {}
    for text in texts:
        for token in Scanner(text).tokens(min_len=1):
            total, compared = counts.get(token.text, (0, 0))
            counts[token.text] = (total + 1, compared + (1 if compare_context(text, token) else 0))
    return {value for value, (total, compared) in counts.items() if compared and total == compared}


def apply_menu(menu_dir: Path, catalog, headers: bool, skip_comments: bool, dry_run: bool,
               extra: list | None = None) -> tuple:
    paths = source_files(menu_dir, headers) + list(extra or [])
    originals = {path: path.read_bytes() for path in paths}
    texts = {path: decode_strict(originals[path], path) for path in paths}
    guarded = compare_only(list(texts.values()))
    mapping = {key: value for key, value in catalog.entries.items() if key not in guarded}
    total = 0
    touched = []
    for path in paths:
        original = originals[path]
        updated, hits = rewrite(texts[path], mapping, skip_comments=skip_comments)
        needs_bom = has_cjk(updated) and not original.startswith(b"\xef\xbb\xbf")
        if not dry_run and (hits or needs_bom):
            write_text(path, updated, bom="auto", previous=original)
        total += hits
        if hits:
            touched.append(path.name)
    return total, touched, sorted(key for key in guarded if key in catalog)


def ini_comment(body: str) -> bool:
    if not re.search(r"[A-Za-z]{3}", body):
        return False
    if body.startswith("http") or body.startswith("D3D12_RESOURCE_STATE"):
        return False
    if re.match(r"^[\w.+-]+$", body):
        return False
    if re.match(r"^[\w\s]+:\s*[\d.]+$", body):
        return False
    return not re.search(r"\| (?:0x)?\d+ = ", body)


def translate_ini(text: str, catalog) -> tuple:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = [line.rstrip("\r") for line in text.split("\n")]
    hit = total = 0
    for index, line in enumerate(lines):
        matched = INI_COMMENT.match(line)
        if not matched:
            continue
        body = matched.group(2).strip()
        if not ini_comment(body):
            continue
        total += 1
        zh = catalog.get(body)
        if zh:
            replaced = f"{matched.group(1)}{zh}"
            if replaced != line:
                lines[index] = replaced
                hit += 1
    return newline.join(lines), hit, total


def apply_ini_values(text: str, overrides: dict) -> tuple:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = [line.rstrip("\r") for line in text.split("\n")]
    hit = 0
    present = set()
    for index, line in enumerate(lines):
        if line.lstrip().startswith(";"):
            continue
        matched = INI_VALUE.match(line)
        if matched is None:
            continue
        present.add(matched.group(2))
        wanted = overrides.get(matched.group(2))
        if wanted is None or matched.group(3) == wanted:
            continue
        lines[index] = f"{matched.group(1)}{matched.group(2)}={wanted}{matched.group(4)}"
        hit += 1
    missing = sorted(key for key in overrides if key not in present)
    return newline.join(lines), hit, missing


def echo_text(body: str) -> bool:
    if not re.search(r"[A-Za-z]{3}", body):
        return False
    if re.match(r"^\[\d+\]", body) or body in ("Yes", "No"):
        return False
    return not ECHO_SKIP.match(body)


def echo_body(line: str) -> tuple | None:
    matched = ECHO_TEXT.match(line)
    if matched is None:
        return None
    body = matched.group(2)
    inner = SETP_INLINE.match(body)
    if inner and prompt_text(inner.group(2)):
        return matched.group(1) + inner.group(1), inner.group(2), '"'
    if echo_text(body):
        return matched.group(1), body, ""
    return None


def setp_prompt(line: str) -> tuple | None:
    matched = SETP_WHOLE_QUOTED.match(line) or SETP_PROMPT_QUOTED.match(line)
    if matched is None:
        return None
    return matched.group(1), matched.group(2)


def prompt_text(body: str) -> bool:
    if not re.search(r"[A-Za-z]{3}", body):
        return False
    return body not in ("Yes", "No")


def read_bat(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("gbk")
    except UnicodeDecodeError:
        return raw.decode("utf-8-sig")


def encode_bat(text: str) -> bytes:
    try:
        return text.encode("gbk")
    except UnicodeEncodeError as exc:
        line = text.count("\n", 0, exc.start) + 1
        char = text[exc.start]
        raise SystemExit(
            f"错误：setup_windows.bat 第 {line} 行的 {char!r}（U+{ord(char):04X}）无法用 GBK 编码，"
            f"请换掉这个字符或改字典译文") from exc


def ps_ini_write(matched) -> str:
    path, old, new = matched.group(1), matched.group(2), matched.group(3)
    return (f"$p = '{path}'; $nl = [string][char]13 + [char]10; "
            f"$c = Get-Content -LiteralPath $p -Encoding UTF8; "
            f"$c = $c -replace '{old}', '{new}'; "
            f"[IO.File]::WriteAllText($p, ($c -join $nl) + $nl, "
            f"[System.Text.UTF8Encoding]::new($false))")


def translate_bat(text: str, catalog) -> tuple:
    lines = [line.rstrip("\r") for line in text.split("\n")]
    output = []
    hit = total = 0
    migrated = UNINSTALL_MIGRATE in text
    for line in lines:
        if line.strip() == UNINSTALL_MIGRATE:
            output.append(line)
            continue
        if "powershell" in line and "(Get-Content" in line:
            line = PS_INI_WRITE.sub(ps_ini_write, line)

        target = echo_body(line)
        if target:
            total += 1
            head, body, tail = target
            zh = catalog.get(body)
            if zh and zh != body:
                line = head + zh + tail
                hit += 1
        else:
            sp = setp_prompt(line)
            if sp:
                prefix, prompt = sp
                if prompt_text(prompt):
                    total += 1
                    zh = catalog.get(prompt)
                    if zh and zh != prompt:
                        line = prefix + zh + '"'
                        hit += 1

        if UNINSTALL_OLD in line:
            if not migrated and MIGRATE_ANCHOR.match(line):
                output.append(UNINSTALL_MIGRATE)
                migrated = True
            line = line.replace(UNINSTALL_OLD, UNINSTALL_NEW)
        output.append(line)
    return "\r\n".join(output), hit, total
