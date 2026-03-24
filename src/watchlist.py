from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .stock_data import validate_sh_a_stock


def load_watchlist(file_path: str = "watchlist.yaml") -> list[dict[str, Any]]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"未找到自选股文件: {file_path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    watchlist = data.get("watchlist", [])
    if not isinstance(watchlist, list) or not watchlist:
        raise ValueError("watchlist.yaml 中 watchlist 不能为空")

    parsed: list[dict[str, Any]] = []
    invalid_codes: list[str] = []
    for item in watchlist:
        if isinstance(item, str):
            code = str(item).strip()
            name: str | None = None
        elif isinstance(item, dict):
            code = str(item.get("code", "")).strip()
            raw_name = item.get("name", None)
            name = str(raw_name).strip() if raw_name else None
        else:
            raise ValueError(
                f"watchlist.yaml 中每项必须是字符串(code)或对象{{code,name}}，当前类型: {type(item)}"
            )

        if not validate_sh_a_stock(code):
            invalid_codes.append(code)
            continue

        parsed.append({"code": code, "name": name})

    if not parsed:
        raise ValueError("watchlist.yaml 中有效 watchlist 不能为空")
    if invalid_codes:
        raise ValueError(f"以下代码不是沪A股票或格式非法: {invalid_codes}")

    return parsed
