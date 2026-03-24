from __future__ import annotations

import re

# 沪A（主板/科创板等常见前缀）
SH_A_PREFIXES = ("600", "601", "603", "605", "688", "689")

MARKET_CN_SH = "cn_sh"
MARKET_HK = "hk"
MARKET_US = "us"

VALID_MARKETS = (MARKET_CN_SH, MARKET_HK, MARKET_US)

_US_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")


def normalize_hk_code(code: str) -> str:
    c = str(code).strip()
    if not c.isdigit():
        raise ValueError(f"港股代码须为数字: {code}")
    if len(c) > 5:
        raise ValueError(f"港股代码长度非法: {code}")
    return c.zfill(5)


def validate_cn_sh(code: str) -> bool:
    return code.isdigit() and len(code) == 6 and code.startswith(SH_A_PREFIXES)


def validate_hk(code: str) -> bool:
    try:
        normalize_hk_code(code)
        return True
    except ValueError:
        return False


def validate_us(code: str) -> bool:
    c = str(code).strip().upper().replace(" ", "")
    if not c:
        return False
    return bool(_US_TICKER_RE.match(c))


def validate_code_for_market(code: str, market: str) -> bool:
    if market == MARKET_CN_SH:
        return validate_cn_sh(code)
    if market == MARKET_HK:
        return validate_hk(code)
    if market == MARKET_US:
        return validate_us(code)
    return False


def infer_market_from_code(code: str) -> str | None:
    """无显式 market 时根据代码形态推断。"""
    raw = str(code).strip()
    if not raw:
        return None
    if validate_cn_sh(raw):
        return MARKET_CN_SH
    if raw.isdigit() and 1 <= len(raw) <= 5:
        return MARKET_HK
    if validate_us(raw.upper()):
        return MARKET_US
    return None


def normalize_market(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    m = str(value).strip().lower()
    aliases = {
        "sh": MARKET_CN_SH,
        "cn": MARKET_CN_SH,
        "a": MARKET_CN_SH,
        "沪": MARKET_CN_SH,
        "沪a": MARKET_CN_SH,
        "hk": MARKET_HK,
        "h": MARKET_HK,
        "港股": MARKET_HK,
        "us": MARKET_US,
        "美股": MARKET_US,
        "nyse": MARKET_US,
        "nasdaq": MARKET_US,
    }
    if m in aliases:
        return aliases[m]
    if m in VALID_MARKETS:
        return m
    return None


def code_to_yfinance_symbol(code: str, market: str) -> str:
    if market == MARKET_CN_SH:
        return f"{code}.SS"
    if market == MARKET_HK:
        n = int(normalize_hk_code(code))
        return f"{n:04d}.HK"
    if market == MARKET_US:
        return str(code).strip().upper().replace(".", "-")
    raise ValueError(f"未知市场: {market}")
