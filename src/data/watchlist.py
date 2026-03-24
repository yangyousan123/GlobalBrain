from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .markets import (
    MARKET_CN_SH,
    MARKET_HK,
    MARKET_US,
    infer_market_from_code,
    normalize_hk_code,
    normalize_market,
    validate_code_for_market,
)


def load_watchlist(file_path: str = "watchlist.yaml") -> list[dict[str, Any]]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"未找到自选股文件: {file_path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    watchlist = data.get("watchlist", [])
    if not isinstance(watchlist, list) or not watchlist:
        raise ValueError("watchlist.yaml 中 watchlist 不能为空")

    parsed: list[dict[str, Any]] = []
    invalid: list[str] = []
    for item in watchlist:
        if isinstance(item, str):
            code = str(item).strip()
            name: str | None = None
            m_raw: str | None = None
        elif isinstance(item, dict):
            code = str(item.get("code", "")).strip()
            raw_name = item.get("name", None)
            name = str(raw_name).strip() if raw_name else None
            m_raw = item.get("market", None)
            if m_raw is not None:
                m_raw = str(m_raw).strip()
        else:
            raise ValueError(
                f"watchlist.yaml 中每项必须是字符串(code)或对象{{code,name,market}}，当前类型: {type(item)}"
            )

        market = normalize_market(m_raw) if m_raw else infer_market_from_code(code)
        if market is None:
            invalid.append(f"{code}(无法推断市场，请显式填写 market: cn_sh|hk|us)")
            continue

        if market == MARKET_HK:
            try:
                code = normalize_hk_code(code)
            except ValueError as exc:
                invalid.append(f"{code}({exc})")
                continue
        elif market == MARKET_US:
            code = code.upper().replace(" ", "")

        if not validate_code_for_market(code, market):
            invalid.append(f"{code}[{market}]")
            continue

        parsed.append({"code": code, "name": name, "market": market})

    if not parsed:
        raise ValueError("watchlist.yaml 中有效 watchlist 不能为空")
    if invalid:
        raise ValueError(f"以下条目无效（代码与市场不匹配或无法识别）: {invalid}")

    return parsed


def watchlist_has_cn_sh(watchlist: list[dict[str, Any]]) -> bool:
    return any(item.get("market") == MARKET_CN_SH for item in watchlist)
