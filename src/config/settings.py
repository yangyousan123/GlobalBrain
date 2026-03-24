from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _parse_notify_channels() -> tuple[str, ...]:
    raw = os.getenv("NOTIFY_CHANNELS", "email").strip()
    allowed = {"email", "feishu", "wechat", "telegram", "discord", "dingtalk"}
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    out = [p for p in parts if p in allowed]
    uniq: list[str] = []
    for p in out:
        if p not in uniq:
            uniq.append(p)
    return tuple(uniq) if uniq else ("email",)


@dataclass
class Settings:
    llm_api_key: str
    llm_base_url: str
    llm_models: tuple[str, ...]
    notify_channels: tuple[str, ...]
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    mail_from: str
    mail_to: list[str]
    feishu_webhook_url: str | None
    wechat_webhook_url: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    telegram_message_thread_id: str | None
    discord_webhook_url: str | None
    dingtalk_webhook_url: str | None
    dingtalk_secret: str | None
    timezone: str
    run_time: str
    trading_day_check_enabled: bool
    bias_threshold_pct: float
    analysis_delay_seconds: float
    tavily_api_key: str | None
    tavily_enabled: bool
    tavily_max_results: int
    tavily_search_depth: str
    tavily_topic: str
    tavily_time_range: str | None
    tavily_include_answer: bool
    tavily_request_delay_seconds: float
    news_digest_max_chars: int
    tavily_translate_answer_to_zh: bool


def _required(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        raise ValueError(f"缺少环境变量: {key}")
    return value


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _optional(key: str) -> str | None:
    v = os.getenv(key, "").strip()
    return v or None


def _resolve_llm_models() -> tuple[str, ...]:
    primary = (
        os.getenv("OPENAI_MODEL", "").strip()
        or os.getenv("LLM_MODEL", "").strip()
        or os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
    )
    fb = os.getenv("LLM_FALLBACK_MODELS", "").strip() or os.getenv("OPENAI_FALLBACK_MODELS", "").strip()
    extras = [x.strip() for x in fb.split(",") if x.strip()]
    out: list[str] = []
    for m in [primary] + extras:
        if m and m not in out:
            out.append(m)
    return tuple(out)


def _validate_notify(s: Settings) -> None:
    ok = False
    for ch in s.notify_channels:
        if ch == "email" and s.smtp_host and s.mail_to:
            ok = True
        elif ch == "feishu" and s.feishu_webhook_url:
            ok = True
        elif ch == "wechat" and s.wechat_webhook_url:
            ok = True
        elif ch == "telegram" and s.telegram_bot_token and s.telegram_chat_id:
            ok = True
        elif ch == "discord" and s.discord_webhook_url:
            ok = True
        elif ch == "dingtalk" and s.dingtalk_webhook_url:
            ok = True
    if not ok:
        raise ValueError(
            "NOTIFY_CHANNELS 中至少需完整配置一种渠道："
            "email 需 SMTP_* 与 MAIL_TO；Webhook 类需对应 *_WEBHOOK_URL 等。"
        )


def load_settings() -> Settings:
    tavily_key = os.getenv("TAVILY_API_KEY", "").strip() or None
    tavily_on = _env_bool("TAVILY_ENABLED", True) and tavily_key is not None
    tr = os.getenv("TAVILY_TIME_RANGE", "week").strip().lower()
    time_range = tr if tr in ("day", "week", "month", "year", "d", "w", "m", "y") else "week"
    depth = os.getenv("TAVILY_SEARCH_DEPTH", "basic").strip()
    if depth not in ("advanced", "basic", "fast", "ultra-fast"):
        depth = "basic"
    topic = os.getenv("TAVILY_TOPIC", "news").strip()
    if topic not in ("general", "news", "finance"):
        topic = "news"

    channels = _parse_notify_channels()
    if "email" in channels:
        smtp_host = _required("SMTP_HOST")
        smtp_port = int(os.getenv("SMTP_PORT", "465"))
        smtp_user = _required("SMTP_USER")
        smtp_password = _required("SMTP_PASSWORD")
        mail_from = _required("MAIL_FROM")
        mail_to = [m.strip() for m in _required("MAIL_TO").split(",") if m.strip()]
    else:
        smtp_host = os.getenv("SMTP_HOST", "").strip()
        smtp_port = int(os.getenv("SMTP_PORT", "465"))
        smtp_user = os.getenv("SMTP_USER", "").strip()
        smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
        mail_from = os.getenv("MAIL_FROM", "").strip()
        mail_to = [m.strip() for m in os.getenv("MAIL_TO", "").split(",") if m.strip()]

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    ds_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    llm_key = openai_key or ds_key
    if not llm_key:
        raise ValueError("缺少 OPENAI_API_KEY 或 DEEPSEEK_API_KEY（OpenAI 兼容接口）")
    if openai_key:
        llm_base = os.getenv("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1"
    else:
        llm_base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()

    s = Settings(
        llm_api_key=llm_key,
        llm_base_url=llm_base,
        llm_models=_resolve_llm_models(),
        notify_channels=channels,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_password=smtp_password,
        mail_from=mail_from,
        mail_to=mail_to,
        feishu_webhook_url=_optional("FEISHU_WEBHOOK_URL"),
        wechat_webhook_url=_optional("WECHAT_WEBHOOK_URL"),
        telegram_bot_token=_optional("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_optional("TELEGRAM_CHAT_ID"),
        telegram_message_thread_id=_optional("TELEGRAM_MESSAGE_THREAD_ID"),
        discord_webhook_url=_optional("DISCORD_WEBHOOK_URL"),
        dingtalk_webhook_url=_optional("DINGTALK_WEBHOOK_URL"),
        dingtalk_secret=_optional("DINGTALK_SECRET"),
        timezone=os.getenv("TIMEZONE", "Asia/Shanghai").strip(),
        run_time=os.getenv("RUN_TIME", "18:30").strip(),
        trading_day_check_enabled=_env_bool("TRADING_DAY_CHECK_ENABLED", True),
        bias_threshold_pct=float(os.getenv("BIAS_THRESHOLD", "5.0")),
        analysis_delay_seconds=float(os.getenv("ANALYSIS_DELAY_SECONDS", "0")),
        tavily_api_key=tavily_key,
        tavily_enabled=tavily_on,
        tavily_max_results=int(os.getenv("TAVILY_MAX_RESULTS", "5")),
        tavily_search_depth=depth,
        tavily_topic=topic,
        tavily_time_range=time_range,
        tavily_include_answer=_env_bool("TAVILY_INCLUDE_ANSWER", True),
        tavily_request_delay_seconds=float(os.getenv("TAVILY_REQUEST_DELAY_SECONDS", "1.0")),
        news_digest_max_chars=int(os.getenv("NEWS_DIGEST_MAX_CHARS", "2000")),
        tavily_translate_answer_to_zh=_env_bool("TAVILY_TRANSLATE_ANSWER_TO_ZH", True),
    )
    _validate_notify(s)
    return s
