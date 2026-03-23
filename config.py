from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    mail_from: str
    mail_to: list[str]
    timezone: str
    run_time: str


def _required(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        raise ValueError(f"缺少环境变量: {key}")
    return value


def load_settings() -> Settings:
    return Settings(
        deepseek_api_key=_required("DEEPSEEK_API_KEY"),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip(),
        smtp_host=_required("SMTP_HOST"),
        smtp_port=int(os.getenv("SMTP_PORT", "465")),
        smtp_user=_required("SMTP_USER"),
        smtp_password=_required("SMTP_PASSWORD"),
        mail_from=_required("MAIL_FROM"),
        mail_to=[mail.strip() for mail in _required("MAIL_TO").split(",") if mail.strip()],
        timezone=os.getenv("TIMEZONE", "Asia/Shanghai").strip(),
        run_time=os.getenv("RUN_TIME", "18:30").strip(),
    )
