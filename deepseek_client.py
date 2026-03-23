from __future__ import annotations

import json
from typing import Any

import requests


class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def analyze(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        system_prompt = (
            "你是A股量化研究员。"
            "请基于输入的技术指标输出严格JSON，字段为："
            "market_view(字符串), stocks(数组)。"
            "stocks中的每个元素字段为：code, action(买入/观察/减仓), "
            "confidence(0-100整数), reason(<=80字), risk(<=80字)。"
        )
        user_prompt = f"请分析以下沪A自选股数据：\n{json.dumps(items, ensure_ascii=False)}"
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)


def fallback_analysis(items: list[dict[str, Any]]) -> dict[str, Any]:
    stocks = []
    for row in items:
        action = "观察"
        confidence = 55
        reason = "趋势不明，等待确认信号。"
        risk = "控制仓位，防止波动放大。"
        if row.get("ma5") and row.get("ma20") and row["ma5"] > row["ma20"] and row.get("rsi14", 50) < 70:
            action = "买入"
            confidence = 68
            reason = "短期均线强于中期，趋势偏多。"
            risk = "若跌破MA20，需考虑止损。"
        elif row.get("ma5") and row.get("ma20") and row["ma5"] < row["ma20"] and row.get("rsi14", 50) > 40:
            action = "减仓"
            confidence = 64
            reason = "短期均线走弱，动能不足。"
            risk = "防止连续回撤扩大损失。"

        stocks.append(
            {
                "code": row["code"],
                "action": action,
                "confidence": confidence,
                "reason": reason,
                "risk": risk,
            }
        )
    return {
        "market_view": "模型服务不可用，当前为规则引擎降级建议。",
        "stocks": stocks,
    }
