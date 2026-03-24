from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import time
import urllib.parse
from typing import Any

import requests

from .config import Settings
from .mailer import send_html_email

logger = logging.getLogger(__name__)

_MAX_TEXT = 12000
_MAX_DISCORD = 1900
_MAX_WECHAT_MD = 3800


def html_to_plain_text(html: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p\s*>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


def truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _post_json(url: str, payload: dict[str, Any], *, timeout: float = 30.0) -> None:
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    if not r.content:
        return
    try:
        data = r.json()
    except Exception:
        return
    if not isinstance(data, dict):
        return
    if "errcode" in data and isinstance(data["errcode"], int) and data["errcode"] != 0:
        raise RuntimeError(f"Webhook 返回错误: {data}")
    if "StatusCode" in data and data.get("StatusCode") != 0:
        raise RuntimeError(f"Webhook 返回错误: {data}")


def send_feishu_text(webhook_url: str, text: str) -> None:
    payload = {"msg_type": "text", "content": {"text": truncate(text, _MAX_TEXT)}}
    _post_json(webhook_url, payload)


def send_wechat_markdown(webhook_url: str, title: str, body: str) -> None:
    content = f"## {title}\n\n{truncate(body, _MAX_WECHAT_MD)}"
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    _post_json(webhook_url, payload)


def send_telegram_text(
    bot_token: str,
    chat_id: str,
    text: str,
    *,
    message_thread_id: str | None = None,
) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": truncate(text, _MAX_TEXT),
        "disable_web_page_preview": True,
    }
    if message_thread_id and message_thread_id.isdigit():
        payload["message_thread_id"] = int(message_thread_id)
    r = requests.post(url, json=payload, timeout=45.0)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram: {data}")


def send_discord_webhook(webhook_url: str, content: str) -> None:
    payload = {"content": truncate(content, _MAX_DISCORD)}
    _post_json(webhook_url, payload)


def send_dingtalk_markdown(webhook_url: str, secret: str | None, title: str, body: str) -> None:
    text = f"### {title}\n\n{truncate(body, _MAX_TEXT)}"
    payload = {"msgtype": "markdown", "markdown": {"title": title, "text": text}}
    url = webhook_url
    if secret:
        ts = str(round(time.time() * 1000))
        string_to_sign = f"{ts}\n{secret}"
        sig = base64.b64encode(
            hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
        ).decode()
        sign = urllib.parse.quote_plus(sig)
        sep = "&" if "?" in webhook_url else "?"
        url = f"{webhook_url}{sep}timestamp={ts}&sign={sign}"
    _post_json(url, payload)


def dispatch_report(settings: Settings, subject: str, html_body: str) -> None:
    """
    按 NOTIFY_CHANNELS 向多个渠道推送：email 发 HTML，其余渠道发纯文本摘要。
    """
    channels = settings.notify_channels
    plain = html_to_plain_text(html_body)
    text_blob = f"{subject}\n\n{plain}"
    text_blob = truncate(text_blob, _MAX_TEXT)

    for ch in channels:
        try:
            if ch == "email":
                if not settings.smtp_host or not settings.mail_to:
                    logger.warning("已启用 email 渠道但未配置 SMTP_HOST/MAIL_TO，跳过")
                    continue
                send_html_email(
                    host=settings.smtp_host,
                    port=settings.smtp_port,
                    user=settings.smtp_user,
                    password=settings.smtp_password,
                    sender=settings.mail_from,
                    receivers=settings.mail_to,
                    subject=subject,
                    html_body=html_body,
                )
                logger.info("推送成功: email -> %s", settings.mail_to)
            elif ch == "feishu":
                if not settings.feishu_webhook_url:
                    logger.warning("已启用 feishu 但未配置 FEISHU_WEBHOOK_URL，跳过")
                    continue
                send_feishu_text(settings.feishu_webhook_url, text_blob)
                logger.info("推送成功: feishu")
            elif ch == "wechat":
                if not settings.wechat_webhook_url:
                    logger.warning("已启用 wechat 但未配置 WECHAT_WEBHOOK_URL，跳过")
                    continue
                send_wechat_markdown(settings.wechat_webhook_url, subject, plain)
                logger.info("推送成功: wechat")
            elif ch == "telegram":
                if not settings.telegram_bot_token or not settings.telegram_chat_id:
                    logger.warning("已启用 telegram 但未配置 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID，跳过")
                    continue
                send_telegram_text(
                    settings.telegram_bot_token,
                    settings.telegram_chat_id,
                    text_blob,
                    message_thread_id=settings.telegram_message_thread_id,
                )
                logger.info("推送成功: telegram")
            elif ch == "discord":
                if not settings.discord_webhook_url:
                    logger.warning("已启用 discord 但未配置 DISCORD_WEBHOOK_URL，跳过")
                    continue
                send_discord_webhook(settings.discord_webhook_url, text_blob)
                logger.info("推送成功: discord")
            elif ch == "dingtalk":
                if not settings.dingtalk_webhook_url:
                    logger.warning("已启用 dingtalk 但未配置 DINGTALK_WEBHOOK_URL，跳过")
                    continue
                send_dingtalk_markdown(
                    settings.dingtalk_webhook_url,
                    settings.dingtalk_secret,
                    subject,
                    plain,
                )
                logger.info("推送成功: dingtalk")
        except Exception as exc:
            logger.error("推送失败 [%s]: %s", ch, exc)
