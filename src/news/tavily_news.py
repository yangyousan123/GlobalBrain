from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import requests

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def _build_news_digest(data: dict[str, Any], *, max_chars: int) -> str:
    parts: list[str] = []
    answer = data.get("answer")
    if isinstance(answer, str) and answer.strip():
        parts.append(f"【Tavily 摘要】{answer.strip()}")
    results = data.get("results") or []
    if isinstance(results, list):
        for i, r in enumerate(results[:8], start=1):
            if not isinstance(r, dict):
                continue
            title = (r.get("title") or "").strip()
            content = (r.get("content") or "").strip()
            url = (r.get("url") or "").strip()
            snippet = content[:280] + ("…" if len(content) > 280 else "")
            line = f"{i}. {title}"
            if snippet:
                line += f" — {snippet}"
            if url:
                line += f" ({url})"
            parts.append(line)
    text = "\n".join(parts).strip()
    if len(text) > max_chars:
        return text[: max_chars - 1] + "…"
    return text


def fetch_stock_news_digest(
    api_key: str,
    code: str,
    name: str | None,
    *,
    market: str = "cn_sh",
    max_results: int,
    search_depth: str,
    topic: str,
    time_range: str | None,
    include_answer: bool,
    digest_max_chars: int,
    timeout: float = 45.0,
    translate_payload: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> str:
    """
    调用 Tavily Search，返回面向 LLM/邮件的纯文本摘要；失败时返回空串并打日志。
    """
    label = f"{name.strip()} " if name and str(name).strip() else ""
    if market == "hk":
        query = f"{label}港股 {code} HKEX 财报 公告 新闻 最新"
    elif market == "us":
        query = f"{label}US stock {code} earnings news SEC latest"
    else:
        query = f"{label}沪A股 {code} 上市公司 公告 业绩 新闻 最新"
    payload: dict[str, Any] = {
        "api_key": api_key,
        "query": query,
        "search_depth": search_depth,
        "max_results": max(1, min(20, max_results)),
        "topic": topic,
        "include_answer": "basic" if include_answer else False,
    }
    if time_range:
        payload["time_range"] = time_range

    try:
        resp = requests.post(TAVILY_SEARCH_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        logger.warning("Tavily 请求失败 %s: %s", code, exc)
        return ""

    if not isinstance(body, dict):
        return ""

    if translate_payload:
        try:
            body = translate_payload(dict(body))
        except Exception as exc:
            logger.warning("Tavily 译文处理失败 %s: %s", code, exc)

    return _build_news_digest(body, max_chars=digest_max_chars)
