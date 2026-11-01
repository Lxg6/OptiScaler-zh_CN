from __future__ import annotations

from pathlib import Path

__version__ = "2.1.0"

ROOT = Path(__file__).resolve().parents[1]
DICT_DIR = ROOT / "dict"
FONT_NAME = "UI_Font.h"
FONT_SOURCES = ("msyh.ttc", "simsun.ttc")
MENU_PATH = Path("OptiScaler") / "menu"
KINDS = ("menu", "ini", "bat")

EXTRA_SOURCES = ("OptiScaler/dllmain.cpp",)

INI_OVERRIDES = {"LoadAsiPlugins": "true"}

GLYPH_RANGES = (
    (0x0020, 0x00FF),
    (0x2000, 0x206F),
    (0x3000, 0x303F),
    (0x4E00, 0x9FFF),
    (0xFF00, 0xFFEF),
)
