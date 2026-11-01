from __future__ import annotations

import re
from pathlib import Path

from . import FONT_NAME
from .catalog import write_text

INCLUDE_ANCHOR = '#include "font/Hack_Compressed.h"'
INCLUDE_LINE = f'#include "font/{FONT_NAME}"'

ANCHOR = """        if (Config::Instance()->TTFFontPath.has_value())
        {
            io.FontDefault =
                atlas->AddFontFromFileTTF(wstring_to_string(Config::Instance()->TTFFontPath.value()).c_str(), fontSize,
                                          &fontConfig, io.Fonts->GetGlyphRangesDefault());
        }
        else
        {
            io.FontDefault = atlas->AddFontFromMemoryCompressedBase85TTF(hack_compressed_compressed_data_base85,
                                                                         fontSize, &fontConfig);
        }
"""

BLOCK = """        io.FontDefault = OptiScalerZhLoadSystemUIFont(atlas, fontSize, &fontConfig);
        if (io.FontDefault == nullptr)
        {
            LOG_WARN("Neither msyh.ttc nor simsun.ttc could be loaded; using the upstream font fallback");
""" + "\n".join("    " + line if line.strip() else line for line in ANCHOR.splitlines()) + "\n        }\n"

BLOCK_PATTERN = re.compile(
    re.escape(BLOCK.splitlines()[0]) + r"\n.*?\n        \}\n    \}\n", re.S)

PROJECT_FILES = ("OptiScaler.vcxproj", "OptiScaler.vcxproj.filters")
PROJECT_ANCHOR = '    <ClInclude Include="menu\\font\\Hack_Compressed.h" />'
FILTER_ANCHOR = '<ClInclude Include="menu\\font\\Hack_Compressed.h">'


def install(menu_dir: Path, header: str, check_only: bool) -> tuple:
    problems = _precheck(menu_dir)
    if problems:
        return False, problems

    notes = []
    ok = _write_header(menu_dir, header, check_only, notes)
    ok = _patch_cpp(menu_dir, check_only, notes) and ok
    ok = _patch_project(menu_dir.parent, check_only, notes) and ok
    return ok, notes


def _precheck(menu_dir: Path) -> list:
    path = menu_dir / "menu_common.cpp"
    if not path.is_file():
        return [f"[失败] 找不到 {path.name}"]

    text = path.read_text(encoding="utf-8-sig")
    problems = []
    if INCLUDE_LINE not in text and INCLUDE_ANCHOR not in text:
        problems.append(f"[失败] 找不到 include 锚点：{INCLUDE_ANCHOR}")
    if not BLOCK_PATTERN.search(text) and ANCHOR not in text:
        problems.append("[失败] 找不到字体初始化锚点（上游结构可能变了）")
    return problems


def _write_header(menu_dir: Path, header: str, check_only: bool, notes: list) -> bool:
    target = menu_dir / "font" / FONT_NAME
    payload = header.encode("ascii")
    if check_only:
        same = target.is_file() and target.read_bytes() == payload
        notes.append(f"[{'=' if same else '!'}] font/{FONT_NAME} "
                     + ("系统字体加载器一致" if same else "缺失或不是当前系统字体加载器"))
        return same
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    notes.append(f"[+] 已生成 font/{FONT_NAME}（{len(payload)} 字节，无内嵌字体）")
    return True


def _patch_cpp(menu_dir: Path, check_only: bool, notes: list) -> bool:
    path = menu_dir / "menu_common.cpp"
    if not path.is_file():
        notes.append(f"[失败] 找不到 {path.name}")
        return False

    text = path.read_text(encoding="utf-8-sig")
    original = text

    if INCLUDE_LINE in text:
        notes.append("[=] include 已存在")
    elif INCLUDE_ANCHOR in text:
        text = text.replace(INCLUDE_ANCHOR, INCLUDE_ANCHOR + "\n" + INCLUDE_LINE, 1)
        notes.append(f'[!] 缺少 #include "font/{FONT_NAME}"' if check_only
                     else f'[+] 已添加 #include "font/{FONT_NAME}"')
    else:
        notes.append(f"[失败] 找不到 include 锚点：{INCLUDE_ANCHOR}")
        return False

    found = BLOCK_PATTERN.search(text)
    if found:
        if found.group(0) == BLOCK + "    }\n":
            notes.append("[=] 系统字体块已是最新")
        else:
            text = text[:found.start()] + BLOCK + "    }\n" + text[found.end():]
            notes.append("[!] 系统字体块与当前配方不一致" if check_only else "[~] 系统字体块已更新")
    elif ANCHOR in text:
        text = text.replace(ANCHOR, BLOCK, 1)
        notes.append("[!] 缺少系统字体加载块" if check_only
                     else "[+] 已接入 msyh.ttc -> simsun.ttc 系统字体")
    else:
        notes.append("[失败] 找不到字体初始化锚点（上游结构可能变了）")
        return False

    if check_only:
        return text == original
    if text != original:
        write_text(path, text, bom="auto")
    return True


def _patch_project(project_dir: Path, check_only: bool, notes: list) -> bool:
    ok = True
    found = False
    for name in PROJECT_FILES:
        path = project_dir / name
        if not path.is_file():
            continue
        found = True
        text = path.read_text(encoding="utf-8-sig")
        if FONT_NAME in text:
            notes.append(f"[=] {name}: 已包含 {FONT_NAME}")
            continue
        anchor = PROJECT_ANCHOR if name.endswith(".vcxproj") else FILTER_ANCHOR
        if anchor not in text:
            notes.append(f"[!] {name}: 找不到 Hack_Compressed.h 条目，跳过（只影响 IDE 里的归类，不影响编译）")
            continue
        if name.endswith(".vcxproj"):
            text = text.replace(anchor, anchor + f'\n    <ClInclude Include="menu\\font\\{FONT_NAME}" />', 1)
        else:
            start = text.index(anchor)
            stop = text.index("</ClInclude>", start) + len("</ClInclude>")
            indent = text[text.rfind("\n", 0, start) + 1:start]
            block = indent + text[start:stop].replace("Hack_Compressed.h", FONT_NAME)
            text = text[:stop] + "\n" + block + text[stop:]
        if check_only:
            notes.append(f"[!] {name}: 缺少 {FONT_NAME}")
            ok = False
            continue
        notes.append(f"[+] {name}: 已加入 {FONT_NAME}")
        path.write_text(text, encoding="utf-8-sig")
    if not found:
        notes.append(f"[失败] {project_dir.name} 下找不到 {PROJECT_FILES[0]} / {PROJECT_FILES[1]}")
        return False
    return ok
