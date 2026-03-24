from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import requests

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
BOCHA_SEARCH_URL = "https://api.bochaai.com/v1/web-search"
MINIMAX_SEARCH_URL = "https://api.minimaxi.com/v1/web-search"


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


def _build_query(code: str, name: str | None, market: str) -> str:
    label = f"{name.strip()} " if name and str(name).strip() else ""
    if market == "hk":
        return f"{label}港股 {code} HKEX 财报 公告 新闻 最新"
    if market == "us":
        return f"{label}US stock {code} earnings news SEC latest"
    return f"{label}沪A股 {code} 上市公司 公告 业绩 新闻 最新"


def _standardize_results(items: list[dict[str, Any]], provider: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in items:
        title = str(r.get("title") or "").strip()
        content = str(r.get("content") or "").strip()
        url = str(r.get("url") or "").strip()
        if not (title or content):
            continue
        out.append({"title": title, "content": content, "url": url, "provider": provider})
    return out


def _fetch_tavily(
    api_key: str,
    query: str,
    *,
    max_results: int,
    search_depth: str,
    topic: str,
    time_range: str | None,
    include_answer: bool,
    timeout: float,
) -> dict[str, Any] | None:
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
    resp = requests.post(TAVILY_SEARCH_URL, json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    if not isinstance(body, dict):
        return None
    return body


def _fetch_serpapi(
    api_key: str,
    query: str,
    *,
    max_results: int,
    timeout: float,
) -> dict[str, Any] | None:
    params = {
        "engine": "google_news",
        "q": query,
        "api_key": api_key,
        "num": max(1, min(20, max_results)),
    }
    resp = requests.get(SERPAPI_SEARCH_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    if not isinstance(body, dict):
        return None
    results: list[dict[str, Any]] = []
    for it in body.get("news_results") or []:
        if not isinstance(it, dict):
            continue
        results.append(
            {
                "title": it.get("title"),
                "content": it.get("snippet") or it.get("source"),
                "url": it.get("link"),
            }
        )
    return {"results": _standardize_results(results, "serpapi")}


def _fetch_brave(
    api_key: str,
    query: str,
    *,
    max_results: int,
    timeout: float,
) -> dict[str, Any] | None:
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    params = {"q": query, "count": max(1, min(20, max_results))}
    resp = requests.get(BRAVE_SEARCH_URL, headers=headers, params=params, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    if not isinstance(body, dict):
        return None
    web = body.get("web") or {}
    raw = web.get("results") if isinstance(web, dict) else []
    results: list[dict[str, Any]] = []
    for it in raw or []:
        if not isinstance(it, dict):
            continue
        results.append(
            {
                "title": it.get("title"),
                "content": it.get("description"),
                "url": it.get("url"),
            }
        )
    return {"results": _standardize_results(results, "brave")}


def _fetch_bocha(
    api_key: str,
    query: str,
    *,
    max_results: int,
    timeout: float,
) -> dict[str, Any] | None:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"query": query, "count": max(1, min(20, max_results))}
    resp = requests.post(BOCHA_SEARCH_URL, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    if not isinstance(body, dict):
        return None
    raw = body.get("results") or body.get("data") or []
    results: list[dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        results.append(
            {
                "title": it.get("title"),
                "content": it.get("snippet") or it.get("content"),
                "url": it.get("url") or it.get("link"),
            }
        )
    return {"results": _standardize_results(results, "bocha")}


def _fetch_minimax(
    api_key: str,
    query: str,
    *,
    max_results: int,
    timeout: float,
) -> dict[str, Any] | None:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"query": query, "count": max(1, min(20, max_results))}
    resp = requests.post(MINIMAX_SEARCH_URL, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    if not isinstance(body, dict):
        return None
    raw = body.get("results") or body.get("data") or []
    results: list[dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        results.append(
            {
                "title": it.get("title"),
                "content": it.get("snippet") or it.get("content"),
                "url": it.get("url") or it.get("link"),
            }
        )
    return {"results": _standardize_results(results, "minimax")}


def fetch_stock_news_digest(
    api_key: str,
    code: str,
    name: str | None,
    *,
    market: str = "cn_sh",
    provider_order: tuple[str, ...] = ("tavily",),
    provider_api_keys: dict[str, str | None] | None = None,
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
    多新闻源检索，返回面向 LLM/邮件的纯文本摘要；失败时返回空串并打日志。
    """
    query = _build_query(code, name, market)
    keys = provider_api_keys or {}
    for provider in provider_order:
        p = provider.strip().lower()
        try:
            if p == "tavily":
                k = keys.get("tavily") or api_key
                if not k:
                    continue
                body = _fetch_tavily(
                    str(k),
                    query,
                    max_results=max_results,
                    search_depth=search_depth,
                    topic=topic,
                    time_range=time_range,
                    include_answer=include_answer,
                    timeout=timeout,
                )
                if body and translate_payload:
                    body = translate_payload(dict(body))
                if body:
                    return _build_news_digest(body, max_chars=digest_max_chars)
            elif p == "serpapi":
                k = keys.get("serpapi")
                if not k:
                    continue
                body = _fetch_serpapi(str(k), query, max_results=max_results, timeout=timeout)
                if body:
                    return _build_news_digest(body, max_chars=digest_max_chars)
            elif p == "brave":
                k = keys.get("brave")
                if not k:
                    continue
                body = _fetch_brave(str(k), query, max_results=max_results, timeout=timeout)
                if body:
                    return _build_news_digest(body, max_chars=digest_max_chars)
            elif p == "bocha":
                k = keys.get("bocha")
                if not k:
                    continue
                body = _fetch_bocha(str(k), query, max_results=max_results, timeout=timeout)
                if body:
                    return _build_news_digest(body, max_chars=digest_max_chars)
            elif p == "minimax":
                k = keys.get("minimax")
                if not k:
                    continue
                body = _fetch_minimax(str(k), query, max_results=max_results, timeout=timeout)
                if body:
                    return _build_news_digest(body, max_chars=digest_max_chars)
        except Exception as exc:
            logger.warning("新闻源 %s 请求失败 %s: %s", p, code, exc)
            continue
    return ""
