from __future__ import annotations

import json
import re
from pathlib import Path

from . import DICT_DIR, KINDS, MENU_PATH

CJK = re.compile(r"[\u3000-\u303f\u4e00-\u9fff\uff01-\uff5e]")
LETTER = re.compile(r"[A-Za-z\u4e00-\u9fff]")
LOG_TOKEN = re.compile(
    r"\{[0-9A-Za-z_]*:?X?\}|"
    r"\berror\b|\bfailed\b|\bresult:|\bcaptured\b|\bcount\b|"
    r"%[0-9\.]*[dflus]|"
    r"LOG_|::|Handle|SwapChain|swapchain|pSwap|vk[A-Z]|ImGui_Impl|"
    r"PWSTR|HWND|CommandQueue|CommandList|allocator|Fence|Semaphore|Descriptor|"
    r"Backbuffer|_vulkanObjects|\{ADEC",
    re.IGNORECASE,
)
WIDGET = re.compile(
    r"ImGui::(Text|TextWrapped|TextDisabled|TextColored|Button|Checkbox|SliderFloat|"
    r"SliderInt|Combo|BeginCombo|MenuItem|BeginMenu|Selectable|InputInt|InputText|"
    r"CollapsingHeader|BeginTabItem|TreeNodeEx|SetTooltip|ProgressBar|RadioButton|"
    r"BeginTable|TableSetupColumn|BulletText|LabelText|SeparatorText)|"
    r"ScopedCollapsingHeader|ShowTooltip|ShowHelpMarker|AddOption|StatusFlag|"
    r"PopulateCombo|OpenWiki|TextLink"
)
PLAIN_IDENT = re.compile(r"^[\w\./\\\-+%#]+$")
CAPITAL_WORD = re.compile(r"^[A-Z][A-Za-z]+$")
FILE_SUFFIX = re.compile(r"\.(dll|exe|ini|json|log|txt|h|cpp)$", re.IGNORECASE)
SETTING_PAIR = re.compile(r"[A-Za-z_]\w*=[^;]*")
ID_ARG_CALL = re.compile(
    r"(?:BeginTable|BeginChild|PushID|OpenPopup|BeginPopup\w*)\(\s*$")
FORMAT_SPEC = re.compile(r"%(?! )[-+ 0#]*\d*(?:\.\d+)?(?:hh|h|ll|l|z|j|t|L)?[diouxXeEfgGaAcspn]|%%")
BRACED = re.compile(r"\{[^{}]*\}")


def has_cjk(text: str) -> bool:
    return CJK.search(text) is not None


def is_setting_blob(text: str) -> bool:
    return len(SETTING_PAIR.findall(text)) >= 2


def is_format_only(text: str) -> bool:
    if not FORMAT_SPEC.search(text):
        return False
    return not re.search(r"[A-Za-z]{3,}", FORMAT_SPEC.sub("", text))


def classify(value: str, context: str = "", comment_only: bool = False, is_id: bool = False) -> str:
    text = value.strip()
    if comment_only or context.lstrip().startswith("//"):
        return "comment"
    if not LETTER.search(text):
        return "other"
    if text.startswith("##") or is_id:
        return "other"
    if is_setting_blob(text):
        return "other"
    if text.startswith(("http://", "https://")):
        return "other"
    if FILE_SUFFIX.search(text):
        return "other"
    if is_format_only(text):
        return "other"

    widget = WIDGET.search(context) is not None
    if (" " not in text and PLAIN_IDENT.match(text) and not CAPITAL_WORD.match(text)
            and not (widget and "##" in text)):
        return "other"
    if widget:
        return "ui"
    if LOG_TOKEN.search(value) or "LOG_" in context or "spdlog::" in context:
        return "log"
    return "ui"


def placeholder_issues(catalog) -> list:
    problems = []
    for key, value in catalog.items():
        if "##" in key:
            want = key.split("##")[-1]
            got = value.split("##")[-1] if "##" in value else None
            if got != want:
                problems.append((key, value, "##id"))
        if sorted(FORMAT_SPEC.findall(key)) != sorted(FORMAT_SPEC.findall(value)):
            problems.append((key, value, "printf"))
        if sorted(BRACED.findall(key)) != sorted(BRACED.findall(value)):
            problems.append((key, value, "braced"))
        if key.count("\n") != value.count("\n"):
            problems.append((key, value, "换行"))
    return problems


def gbk_safe(text: str) -> bool:
    try:
        text.encode("gbk")
    except UnicodeEncodeError:
        return False
    return True


def decode_strict(raw: bytes, path: Path) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        line = raw.count(b"\n", 0, exc.start) + 1
        raise SystemExit(
            f"错误：{path.name} 第 {line} 行不是合法 UTF-8（{exc.reason}），请先确认上游文件编码") from exc


def read_text(path: Path) -> str:
    return decode_strict(path.read_bytes(), path)


def write_text(path: Path, text: str, bom: str = "auto", previous: bytes | None = None) -> bool:
    if previous is None:
        previous = path.read_bytes() if path.exists() else b""
    had_bom = previous.startswith(b"\xef\xbb\xbf")
    if bom == "never":
        wanted = False
    else:
        wanted = had_bom or has_cjk(text)
    payload = text.encode("utf-8")
    path.write_bytes(b"\xef\xbb\xbf" + payload if wanted else payload)
    return wanted


def catalog_path(kind: str) -> Path:
    if kind not in KINDS:
        raise SystemExit(f"错误：未知字典 {kind!r}，可选 {', '.join(KINDS)}")
    return DICT_DIR / f"{kind}.json"


class Catalog:
    def __init__(self, entries: dict):
        self.entries = entries

    @classmethod
    def load(cls, kind: str) -> "Catalog":
        path = catalog_path(kind)
        if not path.is_file():
            raise SystemExit(f"错误：找不到字典 {path}")
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise SystemExit(f"错误：{path.name} 应为 JSON 对象")
        blanks = [key for key, value in raw.items() if not value]
        if blanks:
            raise SystemExit(f"错误：{path.name} 有 {len(blanks)} 条空翻译，例如 {blanks[:3]!r}")
        if kind == "bat":
            broken = [key for key, value in raw.items() if not value.isascii() and not gbk_safe(value)]
            if broken:
                raise SystemExit(f"错误：{path.name} 有 {len(broken)} 条译文无法用 GBK 编码，例如 {broken[0]!r}")
        return cls(raw)

    def unused(self, seen: set) -> list:
        return [key for key, value in self.entries.items() if key not in seen and value not in seen]

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, key: str) -> bool:
        return key in self.entries

    def __getitem__(self, key: str) -> str:
        return self.entries[key]

    def get(self, key: str):
        return self.entries.get(key)

    def items(self):
        return self.entries.items()

    def keys(self):
        return self.entries.keys()


def resolve_menu(src: str) -> Path:
    base = Path(src).expanduser()
    if not base.is_dir():
        raise SystemExit(f"错误：源码目录不存在：{base}")
    if (base / MENU_PATH).is_dir():
        base = base / MENU_PATH
    return base.resolve()


def source_files(menu_dir: Path, headers: bool = False) -> list:
    patterns = ["*.cpp"] + (["*.h", "*.hpp"] if headers else [])
    found = []
    for pattern in patterns:
        found.extend(menu_dir.glob(pattern))
    return sorted(set(found))
