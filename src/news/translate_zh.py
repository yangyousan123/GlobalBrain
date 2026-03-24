from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..llm.openai_compat import extract_message_content, post_chat_completions

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def is_predominantly_chinese(text: str, *, cjk_ratio_vs_letters: float = 0.45) -> bool:
    """若汉字在「汉字+拉丁字母」中占比已高，则视为已是中文，跳过后续翻译。"""
    if not text or not text.strip():
        return True
    cjk = len(_CJK_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    total = cjk + latin
    if total == 0:
        return True
    return (cjk / total) >= cjk_ratio_vs_letters


def translate_to_zh_openai_compatible(
    text: str,
    *,
    api_key: str,
    base_url: str,
    models: list[str],
    api_keys: list[str] | None = None,
    provider_api_keys: dict[str, list[str]] | None = None,
    timeout: float = 60.0,
    max_input_chars: int = 8000,
) -> str:
    """
    使用 OpenAI 兼容 Chat Completions 将文本译为简体中文，多模型顺序回退。
    """
    raw = text.strip()
    if not raw:
        return text
    if is_predominantly_chinese(raw):
        return text
    if len(raw) > max_input_chars:
        raw = raw[: max_input_chars - 1] + "…"

    payload: dict[str, Any] = {
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是专业译者。将用户给出的证券/股票相关摘要译为简体中文。"
                    "只输出译文正文，不要标题、不要解释、不要用 Markdown 代码块。"
                    "公司名、股票代码、产品名、缩写可保留原文或常见中文译名。"
                ),
            },
            {
                "role": "user",
                "content": raw,
            },
        ],
    }
    try:
        data = post_chat_completions(
            api_key=api_key,
            api_keys=api_keys,
            provider_api_keys=provider_api_keys,
            base_url=base_url,
            models=models,
            payload=payload,
            timeout=timeout,
        )
        out = extract_message_content(data)
        if not isinstance(out, str):
            return text
        out = out.strip()
        if out.startswith("```"):
            out = re.sub(r"^```[a-zA-Z]*\s*", "", out)
            out = re.sub(r"\s*```$", "", out)
        return out.strip() or text
    except Exception as exc:
        logger.warning("摘要译为中文失败，保留原文: %s", exc)
        return text


def _strip_json_fence(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def translate_tavily_payload_to_zh(
    body: dict[str, Any],
    *,
    api_key: str,
    base_url: str,
    models: list[str],
    api_keys: list[str] | None = None,
    provider_api_keys: dict[str, list[str]] | None = None,
    include_answer: bool,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """
    将 Tavily 返回的 answer 与每条 result 的 title、content 一并译为简体中文（单次 API）。
    保留 results 中的 url 等字段；翻译失败则返回原 body。
    """
    if not isinstance(body, dict):
        return body

    results_in = body.get("results") or []
    if not isinstance(results_in, list):
        results_in = []

    ans_in = body.get("answer") if include_answer else None
    if isinstance(ans_in, str):
        ans_in = ans_in.strip() or None
    else:
        ans_in = None

    items_in: list[dict[str, str]] = []
    for r in results_in:
        if not isinstance(r, dict):
            continue
        items_in.append(
            {
                "title": ((r.get("title") or "")[:900]).strip(),
                "content": ((r.get("content") or "")[:2800]).strip(),
            }
        )

    blob = ""
    if include_answer and ans_in:
        blob += ans_in
    for it in items_in:
        blob += it["title"] + it["content"]

    if not blob.strip():
        return body
    if is_predominantly_chinese(blob):
        return body

    if include_answer:
        payload_in: dict[str, Any] = {"answer": ans_in, "items": items_in}
        sys_extra = "字段含 answer（可为 null）与 items。"
    else:
        payload_in = {"items": items_in}
        sys_extra = "仅含 items，无 answer 字段。"
    payload: dict[str, Any] = {
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是专业译者。用户将提供 JSON，"
                    f"{sys_extra}"
                    "请把其中所有自然语言文本译为简体中文，保持 items 条数与顺序不变。"
                    "不要编造事实；不要翻译 URL；股票代码、交易所缩写、公司专名可保留原文。"
                    "只输出一个 JSON 对象，不要 Markdown。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(payload_in, ensure_ascii=False),
            },
        ],
        "response_format": {"type": "json_object"},
    }
    try:
        data = post_chat_completions(
            api_key=api_key,
            api_keys=api_keys,
            provider_api_keys=provider_api_keys,
            base_url=base_url,
            models=models,
            payload=payload,
            timeout=timeout,
        )
        raw = extract_message_content(data)
        if not isinstance(raw, str):
            return body
        parsed = json.loads(_strip_json_fence(raw))
    except Exception as exc:
        logger.warning("Tavily 全文翻译失败，保留原文: %s", exc)
        return body

    if not isinstance(parsed, dict):
        return body

    out = dict(body)
    if include_answer:
        a = parsed.get("answer")
        if isinstance(a, str) and a.strip():
            out["answer"] = a.strip()
        else:
            out["answer"] = body.get("answer")

    items_out = parsed.get("items")
    if not isinstance(items_out, list):
        return out

    dict_indices = [i for i, r in enumerate(results_in) if isinstance(r, dict)]
    new_results: list[Any] = list(results_in)
    for j, idx in enumerate(dict_indices):
        if j >= len(items_out) or not isinstance(items_out[j], dict):
            continue
        r = results_in[idx]
        if not isinstance(r, dict):
            continue
        patch = items_out[j]
        nt = patch.get("title")
        nc = patch.get("content")
        merged = dict(r)
        if isinstance(nt, str):
            merged["title"] = nt.strip()
        if isinstance(nc, str):
            merged["content"] = nc.strip()
        new_results[idx] = merged

    out["results"] = new_results
    return out
