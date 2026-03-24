from __future__ import annotations

from typing import Any


def annotate_trading_discipline(
    metrics: dict[str, Any],
    *,
    bias_threshold_pct: float,
) -> dict[str, Any]:
    """
    「交易纪律」：乖离率过高提示不追高、均线多空排列标注。
    在行情字典上追加 risk_notes / bias_alert / ma_alignment_label，供 LLM 与邮件展示。
    """
    out = dict(metrics)
    bias = metrics.get("bias_ma20_pct")
    trend = metrics.get("ma_trend")

    notes: list[str] = []
    bias_alert = False
    if bias is not None and abs(float(bias)) > bias_threshold_pct:
        bias_alert = True
        if float(bias) > 0:
            notes.append(f"乖离率偏高(+{bias}% vs MA20)，注意不追高")
        else:
            notes.append(f"乖离率偏低({bias}% vs MA20)，注意超跌反弹博弈风险")

    if trend == "bull":
        notes.append("均线呈多头排列(MA5>MA10>MA20)")
    elif trend == "bear":
        notes.append("均线呈空头排列(MA5<MA10<MA20)")

    out["risk_notes"] = notes
    out["bias_alert"] = bias_alert
    out["ma_alignment_label"] = {
        "bull": "多头",
        "bear": "空头",
        "mixed": "震荡",
        None: "-",
    }.get(trend, "-")

    rsi = metrics.get("rsi14")
    if bias_alert and trend == "bull" and rsi is not None and float(rsi) < 75:
        out["bias_alert"] = False

    return out
