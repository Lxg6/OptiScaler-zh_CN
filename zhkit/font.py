from __future__ import annotations

from . import FONT_SOURCES, GLYPH_RANGES


def system_font_header() -> str:
    ranges = "\n".join(f"    0x{low:04X}, 0x{high:04X}," for low, high in GLYPH_RANGES)
    sources = ", ".join(f"L\"{name}\"" for name in FONT_SOURCES)
    return f"""#pragma once

#include <filesystem>
#include <system_error>
#include <windows.h>

static const ImWchar OptiScalerZhGlyphRanges[] = {{
{ranges}
    0,
}};

static ImFont* OptiScalerZhLoadSystemUIFont(ImFontAtlas* atlas, float size, ImFontConfig* config)
{{
    wchar_t windowsDirectory[MAX_PATH] = {{}};
    const UINT length = GetWindowsDirectoryW(windowsDirectory, MAX_PATH);
    if (length == 0 || length >= static_cast<UINT>(MAX_PATH))
        return nullptr;

    const std::filesystem::path fontDirectory = std::filesystem::path(windowsDirectory) / L"Fonts";
    for (const wchar_t* fileName : {{ {sources} }})
    {{
        const auto path = fontDirectory / fileName;
        std::error_code error;
        if (!std::filesystem::exists(path, error) || error)
            continue;

        const auto fileNameUtf8 = wstring_to_string(path.wstring());
        ImFont* font = atlas->AddFontFromFileTTF(fileNameUtf8.c_str(), size, config,
                                                 OptiScalerZhGlyphRanges);
        if (font != nullptr)
            return font;
    }}
    return nullptr;
}}
"""


def verify(header: str) -> None:
    required = ("AddFontFromFileTTF", *FONT_SOURCES, "OptiScalerZhGlyphRanges")
    if any(token not in header for token in required):
        raise ValueError("系统字体加载头文件内容不完整")
    if "ui_font_data" in header or "AddFontFromMemoryTTF" in header or "MergeMode" in header:
        raise ValueError("系统字体加载头文件不得包含内嵌字体或 MergeMode")
    if header.index(FONT_SOURCES[0]) > header.index(FONT_SOURCES[1]):
        raise ValueError("系统字体回退顺序必须是 msyh.ttc -> simsun.ttc")
