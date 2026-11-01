from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import KINDS
from .catalog import Catalog, has_cjk, read_text, resolve_menu
from .targets import (INI_COMMENT, UNINSTALL_NEW, UNINSTALL_OLD, echo_body,
                      extra_source_files, ini_comment, prompt_text, read_bat, scan, setp_prompt)

ROOT_MARKERS = ("OptiScaler.ini", "setup_windows.bat")


@dataclass
class Summary:
    menu_dir: Path
    entries: int
    total: int = 0
    inplace: int = 0
    unapplied: int = 0
    pending: int = 0
    missing: list = field(default_factory=list)
    gaps: list = field(default_factory=list)
    stale: dict = field(default_factory=dict)
    report: Path | None = None
    root: Path | None = None
    rows: list = field(default_factory=list, repr=False)

    @property
    def percent(self) -> float:
        return (self.inplace + self.unapplied) * 100 / self.total if self.total else 0.0


def find_root(menu_dir: Path):
    for parent in list(menu_dir.parents)[:3]:
        if any((parent / marker).is_file() for marker in ROOT_MARKERS):
            return parent
    return None


def _closest(value: str, keys: list):
    found = difflib.get_close_matches(value, keys, n=1, cutoff=0.7)
    return found[0] if found else None


def evaluate(entries: list, catalog: Catalog) -> tuple:
    keys = list(catalog.keys())
    missing = []
    inplace = unapplied = pending = 0

    for entry in entries:
        if entry.kind() != "ui":
            continue
        value = entry.value
        if has_cjk(value):
            inplace += 1
            continue
        if value not in catalog:
            pending += 1
            reuse = _closest(value, keys)
            file_name, line, context, _ = entry.first
            missing.append({
                "value": value,
                "count": entry.count,
                "file": file_name,
                "line": line,
                "ctx": context,
                "joined": entry.joined,
                "suggest_from": reuse,
                "suggest_text": catalog.get(reuse) if reuse else None,
            })
            continue
        translated = catalog[value]
        if translated == value or not has_cjk(translated):
            inplace += 1
        else:
            unapplied += 1

    return missing, inplace, unapplied, pending


def file_gaps(root: Path | None, ini: Catalog, bat: Catalog) -> list:
    if root is None:
        return []
    gaps = []
    ini_path = root / "OptiScaler.ini"
    if ini_path.is_file():
        for number, line in enumerate(read_text(ini_path).splitlines(), 1):
            matched = INI_COMMENT.match(line)
            body = matched.group(2).strip() if matched else ""
            if matched and ini_comment(body) and not has_cjk(body) and body not in ini:
                gaps.append({"file": "OptiScaler.ini", "line": number, "text": body})
    bat_path = root / "setup_windows.bat"
    if bat_path.is_file():
        for number, line in enumerate(read_bat(bat_path).splitlines(), 1):
            target = echo_body(line)
            if target:
                body = target[1]
                if not has_cjk(body) and body not in bat:
                    gaps.append({"file": "setup_windows.bat", "line": number, "text": body})
                continue
            sp = setp_prompt(line)
            if sp:
                body = sp[1]
                if prompt_text(body) and not has_cjk(body) and body not in bat:
                    gaps.append({"file": "setup_windows.bat", "line": number, "text": body})
    return gaps


def _ini_keys_seen(path: Path) -> set:
    if not path.is_file():
        return set()
    seen = set()
    for line in read_text(path).splitlines():
        matched = INI_COMMENT.match(line)
        if not matched:
            continue
        body = matched.group(2).strip()
        if ini_comment(body):
            seen.add(body)
    return seen


def write_report(summary: Summary, out_dir: Path, catalogs: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = date.today().strftime("%Y%m%d")
    markdown = out_dir / f"todo-{stamp}.md"
    payload = out_dir / f"todo-{stamp}.json"

    lines = [
        f"# 上游同步检查 {stamp}",
        "",
        f"- 源码目录：`{summary.menu_dir}`",
        f"- ini/bat 目录：`{summary.root}`" if summary.root else "- ini/bat 目录：**未找到**（找不到 OptiScaler.ini / setup_windows.bat，这两项检查已跳过）",
        f"- 上游字符串：{summary.entries} 条（界面文本 {summary.total}）",
        f"- 字典条目：菜单 {len(catalogs['menu'])} / ini {len(catalogs['ini'])} / bat {len(catalogs['bat'])}",
        f"- **待翻译界面文本：{summary.pending} 条**",
        f"- 已就位 {summary.inplace}（含有意保留英文），已译未应用 {summary.unapplied}",
        f"- 过期键：菜单 {len(summary.stale.get('menu', []))} / ini {len(summary.stale.get('ini', []))}"
        f" / bat {len(summary.stale.get('bat', []))}",
        "",
    ]

    if summary.missing:
        lines += ["## 待翻译（补进 dict/menu.json）", "",
                  "| # | 英文原文 | 次数 | 位置 | 可复用旧译文 | 备注 |", "|---|---|---|---|---|---|"]
        for index, item in enumerate(sorted(summary.missing, key=lambda row: -row["count"]), 1):
            reuse = f"`{item['suggest_from']}` → {item['suggest_text']}" if item["suggest_from"] else ""
            value = item["value"].replace("|", "\\|").replace("\n", "\\n")
            note = "与相邻字面量相连" if item.get("joined") else ""
            lines.append(f"| {index} | `{value}` | {item['count']} | {item['file']}:{item['line']} "
                         f"| {reuse} | {note} |")
        lines += ["", "> 保留 `##id`、`%s`、`{0:X}`、`\\n` 等占位符；`Key=Value;...` 配置串不要翻译。",
                  "> 备注为「与相邻字面量相连」时，源码把一句话拆成多个字符串，译文要按整句读起来通顺来写。", ""]
    else:
        lines += ["## 待翻译", "", "没有新增界面文本。", ""]

    lines += ["## ini / bat 未翻译行（补进 dict/ini.json 或 dict/bat.json）", ""]
    if summary.root is None:
        lines += ["没找到 OptiScaler.ini / setup_windows.bat，跳过这两项。", ""]
    elif summary.gaps:
        lines += [f"共 {len(summary.gaps)} 行：", ""]
        for gap in summary.gaps[:40]:
            lines.append(f"- `{gap['file']}:{gap['line']}` {gap['text'][:90]}")
        if len(summary.gaps) > 40:
            lines.append(f"- ... 其余 {len(summary.gaps) - 40} 行")
        lines.append("")
    else:
        lines += ["OptiScaler.ini 注释与 setup_windows.bat 说明全部有译文。", ""]

    for kind, title in (("menu", "菜单"), ("ini", "ini"), ("bat", "bat")):
        stale = summary.stale.get(kind, [])
        if not stale:
            continue
        lines += [f"## {title} 字典中已失效的键", ""]
        for key in sorted(stale)[:40]:
            lines.append(f"- `{key}` → {catalogs[kind][key]}")
        if len(stale) > 40:
            lines.append(f"- ... 其余 {len(stale) - 40} 条")
        lines.append("")

    markdown.write_text("\n".join(lines), encoding="utf-8")
    payload.write_text(json.dumps({
        "generated": stamp,
        "source": str(summary.menu_dir),
        "file_root": str(summary.root) if summary.root else None,
        "missing_ui": summary.missing,
        "stale": summary.stale,
        "files_untranslated": summary.gaps,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return markdown


def _bat_keys_seen(path: Path) -> set:
    if not path.is_file():
        return set()
    seen = set()
    for line in read_bat(path).splitlines():
        target = echo_body(line)
        if target:
            seen.add(target[1])
            continue
        sp = setp_prompt(line)
        if sp and prompt_text(sp[1]):
            seen.add(sp[1])
    return seen


def inspect(src: str, headers: bool = False) -> tuple:
    menu_dir = resolve_menu(src)
    root = find_root(menu_dir)
    catalogs = {kind: Catalog.load(kind) for kind in KINDS}

    entries, _seen, writable = scan(menu_dir, headers, extra_source_files(root))
    missing, inplace, unapplied, pending = evaluate(entries, catalogs["menu"])
    summary = Summary(
        menu_dir=menu_dir,
        entries=len(entries),
        total=inplace + unapplied + pending,
        inplace=inplace,
        unapplied=unapplied,
        pending=pending,
        missing=missing,
        gaps=file_gaps(root, catalogs["ini"], catalogs["bat"]),
        root=root,
        rows=entries,
    )
    summary.stale = {"menu": [], "ini": [], "bat": []}
    summary.stale["menu"] = catalogs["menu"].unused(writable)
    if root is not None:
        summary.stale["ini"] = catalogs["ini"].unused(_ini_keys_seen(root / "OptiScaler.ini"))
        bat_seen = _bat_keys_seen(root / "setup_windows.bat")
        bat_seen |= {value.replace(UNINSTALL_NEW, UNINSTALL_OLD) for value in bat_seen}
        summary.stale["bat"] = catalogs["bat"].unused(bat_seen)
    return summary, catalogs
