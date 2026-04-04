from __future__ import annotations

from typing import Any


def annotate_trading_discipline(metrics: dict[str, Any]) -> dict[str, Any]:
    """
    在行情字典上追加 risk_notes / bias_alert，供 LLM 与邮件展示。
    当前不计算乖离与均线，仅保留空标注以兼容下游结构。
    """
    out = dict(metrics)
    out["risk_notes"] = []
    out["bias_alert"] = False
    return out
