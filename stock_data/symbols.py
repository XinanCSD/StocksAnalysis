"""Symbol parsing shared by the CLI, API, and downloader."""
from __future__ import annotations

import re


def normalize_symbol(value: str) -> tuple[str, str]:
    """Return (user_input, yahoo_symbol) without corrupting exchange suffixes.

    Yahoo uses a dash for common US class shares (BRK-B, BF-B), while an
    exchange suffix such as 7203.T must keep its period.
    """
    entered = value.strip().upper()
    if not entered:
        raise ValueError("股票代码不能为空")
    compact = re.sub(r"\s+", "", entered)
    if not re.fullmatch(r"[A-Z0-9^=.-]+", compact):
        raise ValueError(f"股票代码包含不支持的字符: {value}")
    yahoo = compact
    if re.fullmatch(r"[A-Z]{1,5}\.[AB]", compact):
        yahoo = compact.replace(".", "-")
    return compact, yahoo


def split_symbols(value: str) -> list[str]:
    return [part for part in re.split(r"[\s,]+", value.strip()) if part]
