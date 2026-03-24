from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


def post_chat_completions(
    *,
    api_key: str,
    base_url: str,
    models: list[str],
    payload: dict[str, Any],
    timeout: float = 120.0,
) -> dict[str, Any]:
    """
    调用 OpenAI 兼容 POST /chat/completions，按 models 顺序依次尝试，成功则返回完整 JSON body。
    """
    if not models:
        raise ValueError("models 不能为空")
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_exc: Exception | None = None
    for model in models:
        body = {**payload, "model": model}
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_exc = exc
            logger.warning("OpenAI 兼容接口 模型 %s 调用失败: %s", model, exc)
    assert last_exc is not None
    raise last_exc


def extract_message_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not choices or not isinstance(choices, list):
        raise KeyError("响应无 choices")
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if not isinstance(content, str):
        raise KeyError("响应无 message.content")
    return content
