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
            "至少包含：量能配合 一类；"
            "若该股数据中含非空 news_digest，须额外增加一项「新闻舆情」，"
            "status 需反映公开报道与价格/量能是否大致一致，并注明信息可能滞后或片面)。"
            "若有 news_digest，须在 reason 或 risk 中简要体现舆情要点，且不得单独依据新闻给出强烈结论；"
            "可结合 change_pct、vol_ratio5、risk_notes 做简要判断。"
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
    vol = metrics.get("vol_ratio5")
    cl: list[dict[str, str]] = [
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
        chg = row.get("change_pct")
        buy_zone = "-"
        stop_loss = "-"
        take_profit = "-"
        try:
            pct = float(chg) if chg is not None else 0.0
        except (TypeError, ValueError):
            pct = 0.0
        if pct > 2.0:
            action = "观察"
            confidence = 60
            reason = "当日涨幅偏大，注意追高风险与波动。"
            risk = "控制仓位，避免情绪化加仓。"
            if close is not None:
                take_profit = f"{round(float(close) * 1.03, 2)} 附近（压力需实盘确认）"
        elif pct < -2.0:
            action = "观察"
            confidence = 58
            reason = "当日跌幅偏大，注意止损纪律与流动性。"
            risk = "防止在恐慌中放大亏损。"
        else:
            action = "观察"
            confidence = 55
            reason = "涨跌温和，等待更明确信号。"
            risk = "控制仓位，防止波动放大。"

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
