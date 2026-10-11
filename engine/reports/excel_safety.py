"""Defence against Excel formula injection when writing user-controlled text."""

from __future__ import annotations

from typing import Any

# Cells must not start with formula trigger characters when opened in Excel.
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def excel_safe_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if not text:
        return text
    if text[0] in _FORMULA_PREFIXES or text.startswith("\t") or text.startswith("\r"):
        return "'" + text
    return text
