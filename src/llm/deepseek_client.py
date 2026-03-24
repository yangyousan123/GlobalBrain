from __future__ import annotations

import json
from typing import Any

from .openai_compat import extract_message_content, post_chat_completions


class OpenAICompatClient:
    """OpenAI 兼容 /chat/completions，支持多模型按顺序回退。"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        models: list[str],
        api_keys: list[str] | None = None,
        provider_api_keys: dict[str, list[str]] | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_keys = api_keys or [api_key]
        self.provider_api_keys = provider_api_keys or {}
        self.base_url = base_url.rstrip("/")
        self.models = models

    def analyze(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        system_prompt = (
            "你是跨市场（沪A/港股/美股）量化研究员，输出严格 JSON（不要 Markdown）。"
            "输入中每只股票含 market 字段：cn_sh 沪A、hk 港股、us 美股。"
            "字段：market_view(字符串，跨市场风格与风险偏好一句话)；"
            "stocks(数组)，每项须含："
            "code, market（与输入一致：cn_sh|hk|us）, action(买入/观察/减仓), confidence(0-100整数), "
            "reason(<=100字), risk(<=100字), "
            "buy_zone(字符串：建议关注买入区间或价位), "
            "stop_loss(字符串：止损参考价或条件), "
            "take_profit(字符串：目标或减仓区域), "
            "checklist(数组，每项含 item 与 status，status 只能是 满足/注意/不满足 之一，"
            "至少包含：乖离风险、均线多空、量能配合 三类；"
            "若该股数据中含非空 news_digest，须额外增加一项「新闻舆情」，"
            "status 需反映公开报道与技术面是否一致，并注明信息可能滞后或片面)。"
            "请结合输入中的 bias_ma20_pct、ma_trend、risk_notes、bias_alert 做判断；"
            "若有 news_digest，须在 reason 或 risk 中简要体现舆情要点，且不得单独依据新闻给出强烈结论；"
            "若 bias_alert 为 true，须在 reason 或 checklist 中提示不追高或仓位纪律。"
        )
        user_prompt = (
            "请分析以下自选股数据（含 market、技术指标、规则标注及 Tavily 新闻摘要 news_digest，可能为空）：\n"
            f"{json.dumps(items, ensure_ascii=False)}"
        )
        payload = {
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        data = post_chat_completions(
            api_key=self.api_key,
            api_keys=self.api_keys,
            provider_api_keys=self.provider_api_keys,
            base_url=self.base_url,
            models=self.models,
            payload=payload,
            timeout=120.0,
        )
        content = extract_message_content(data)
        return json.loads(content)


# 兼容旧名称
DeepSeekClient = OpenAICompatClient


def _default_checklist(metrics: dict[str, Any]) -> list[dict[str, str]]:
    bias_ok = not metrics.get("bias_alert")
    trend = metrics.get("ma_trend")
    vol = metrics.get("vol_ratio5")
    cl: list[dict[str, str]] = [
        {
            "item": "乖离与追高",
            "status": "满足" if bias_ok else "注意",
        },
        {
            "item": "均线多空",
            "status": "满足" if trend == "bull" else ("注意" if trend == "mixed" else "不满足"),
        },
        {
            "item": "量能配合",
            "status": "满足" if vol is not None and float(vol) >= 1.0 else "注意",
        },
    ]
    if metrics.get("news_digest"):
        cl.append({"item": "新闻舆情", "status": "注意"})
    return cl


def fallback_analysis(items: list[dict[str, Any]]) -> dict[str, Any]:
    stocks = []
    for row in items:
        action = "观察"
        confidence = 55
        reason = "趋势不明，等待确认信号。"
        risk = "控制仓位，防止波动放大。"
        close = row.get("close")
        ma20 = row.get("ma20")
        ma5 = row.get("ma5")
        ma10 = row.get("ma10")
        rsi = float(row["rsi14"]) if row.get("rsi14") is not None else 50.0
        buy_zone = "-"
        stop_loss = "-"
        take_profit = "-"
        if row.get("bias_alert"):
            reason = "乖离偏高，避免追高；可等待回踩均线再评估。"
            risk = "严格执行仓位与止损纪律。"

        if ma5 and ma10 and ma20 and ma5 > ma10 > ma20 and rsi < 70:
            action = "买入"
            confidence = 68
            reason = "短期均线多头排列，趋势偏多。"
            risk = "若跌破MA20，需考虑止损。"
            if close and ma20:
                buy_zone = f"{round(float(ma20) * 0.98, 2)} ~ {round(float(close), 2)}"
                stop_loss = f"{round(float(ma20) * 0.97, 2)} 附近"
                take_profit = f"{round(float(close) * 1.05, 2)} 附近（前高/压力需实盘确认）"
        elif ma5 and ma10 and ma20 and ma5 < ma10 < ma20 and rsi > 40:
            action = "减仓"
            confidence = 64
            reason = "短期均线走弱，动能不足。"
            risk = "防止连续回撤扩大损失。"
            if close and ma20:
                stop_loss = f"{round(float(close) * 1.02, 2)} 突破则纠错"
                take_profit = "反弹至均线附近分批减仓"

        stocks.append(
            {
                "code": row["code"],
                "market": row.get("market") or "cn_sh",
                "action": action,
                "confidence": confidence,
                "reason": reason,
                "risk": risk,
                "buy_zone": buy_zone,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "checklist": _default_checklist(row),
            }
        )
    return {
        "market_view": "模型服务不可用，当前为规则引擎降级建议。",
        "stocks": stocks,
    }
