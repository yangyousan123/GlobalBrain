from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


def _needs_api_base(model: str) -> bool:
    """
    仅 OpenAI 兼容族模型使用 api_base。
    provider/model 形式下，只有 openai/azure/openai_like 走自定义 base_url。
    """
    m = (model or "").strip().lower()
    if "/" not in m:
        return True
    provider = m.split("/", 1)[0]
    return provider in {"openai", "azure", "openai_like"}


def _provider_of_model(model: str) -> str:
    m = (model or "").strip().lower()
    if "/" not in m:
        return "openai_like"
    return m.split("/", 1)[0]


def _select_key_pool(
    *,
    model: str,
    default_keys: list[str],
    provider_api_keys: dict[str, list[str]] | None,
) -> list[str]:
    provider = _provider_of_model(model)
    if provider_api_keys and provider in provider_api_keys and provider_api_keys[provider]:
        return provider_api_keys[provider]
    return default_keys


def post_chat_completions(
    *,
    api_key: str,
    base_url: str,
    models: list[str],
    payload: dict[str, Any],
    api_keys: list[str] | None = None,
    provider_api_keys: dict[str, list[str]] | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """
    统一通过 LiteLLM 调用，支持多模型 + 多 Key 轮询回退。
    若 LiteLLM 不可用，则回退到 OpenAI 兼容 HTTP 调用。
    """
    if not models:
        raise ValueError("models 不能为空")
    key_pool = [k for k in (api_keys or []) if isinstance(k, str) and k.strip()]
    if not key_pool:
        key_pool = [api_key]
    last_exc: Exception | None = None
    # 先走 LiteLLM
    try:
        from litellm import completion

        for model in models:
            selected_keys = _select_key_pool(
                model=model,
                default_keys=key_pool,
                provider_api_keys=provider_api_keys,
            )
            for idx, key in enumerate(selected_keys):
                try:
                    kwargs: dict[str, Any] = {
                        "model": model,
                        "api_key": key,
                        "messages": payload.get("messages", []),
                        "timeout": timeout,
                    }
                    if base_url and _needs_api_base(model):
                        kwargs["api_base"] = base_url.rstrip("/")
                    if "temperature" in payload:
                        kwargs["temperature"] = payload["temperature"]
                    if "response_format" in payload:
                        kwargs["response_format"] = payload["response_format"]
                    if "max_tokens" in payload:
                        kwargs["max_tokens"] = payload["max_tokens"]
                    resp = completion(**kwargs)
                    if hasattr(resp, "model_dump"):
                        return resp.model_dump()
                    if isinstance(resp, dict):
                        return resp
                    return dict(resp)  # type: ignore[arg-type]
                except Exception as exc:
                    last_exc = exc
                    logger.warning("LiteLLM 调用失败 model=%s key#%s: %s", model, idx + 1, exc)
    except Exception as exc:
        last_exc = exc
        logger.warning("LiteLLM 不可用，回退 OpenAI 兼容 HTTP: %s", exc)

    # 兜底：原有 OpenAI 兼容 HTTP
    url = f"{base_url.rstrip('/')}/chat/completions"
    for model in models:
        if not _needs_api_base(model):
            # 非 OpenAI 兼容 provider 不走 HTTP 兜底，避免误发到 base_url
            continue
        selected_keys = _select_key_pool(
            model=model,
            default_keys=key_pool,
            provider_api_keys=provider_api_keys,
        )
        for idx, key in enumerate(selected_keys):
            body = {**payload, "model": model}
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
            try:
                resp = requests.post(url, headers=headers, json=body, timeout=timeout)
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                last_exc = exc
                logger.warning("OpenAI 兼容接口失败 model=%s key#%s: %s", model, idx + 1, exc)
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
