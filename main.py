from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config import load_settings
from dashboard import render_dashboard_html
from deepseek_client import DeepSeekClient, fallback_analysis
from mailer import send_html_email
from stock_data import fetch_stock_metrics, fetch_stock_metrics_yfinance_batch, validate_sh_a_stock


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def load_watchlist(file_path: str = "watchlist.yaml") -> list[dict[str, Any]]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"未找到自选股文件: {file_path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    watchlist = data.get("watchlist", [])
    if not isinstance(watchlist, list) or not watchlist:
        raise ValueError("watchlist.yaml 中 watchlist 不能为空")

    parsed: list[dict[str, Any]] = []
    invalid_codes: list[str] = []
    for item in watchlist:
        if isinstance(item, str):
            code = str(item).strip()
            name: str | None = None
        elif isinstance(item, dict):
            code = str(item.get("code", "")).strip()
            raw_name = item.get("name", None)
            name = str(raw_name).strip() if raw_name else None
        else:
            raise ValueError(f"watchlist.yaml 中每项必须是字符串(code)或对象{{code,name}}，当前类型: {type(item)}")

        if not validate_sh_a_stock(code):
            invalid_codes.append(code)
            continue

        parsed.append({"code": code, "name": name})

    if not parsed:
        raise ValueError("watchlist.yaml 中有效 watchlist 不能为空")
    if invalid_codes:
        raise ValueError(f"以下代码不是沪A股票或格式非法: {invalid_codes}")

    return parsed


def run_pipeline() -> dict[str, Any]:
    settings = load_settings()
    watchlist = load_watchlist()
    logger.info("开始分析，股票数量: %s", len(watchlist))

    stock_metrics = []
    name_map = {item["code"]: item.get("name") for item in watchlist}
    failed_codes: list[str] = []
    for item in watchlist:
        code = item["code"]
        name = item.get("name")
        try:
            # 这里先只依赖 akshare + 缓存；yfinance 统一在最后批量补全，避免 RateLimit
            metrics = fetch_stock_metrics(code, use_yfinance_fallback=False)
            if name:
                metrics["name"] = name
            stock_metrics.append(metrics)
            logger.info("已获取数据: %s", code)
        except Exception as exc:
            failed_codes.append(code)
            # 股票行情拉取失败通常是瞬时/外部依赖问题，避免刷出大量 traceback
            logger.error("获取股票 %s 数据失败: %s", code, exc)

    # 对 akshare 全失败/部分失败的代码，使用 yfinance 批量补全
    if failed_codes:
        try:
            existing_codes = {item.get("code") for item in stock_metrics}
            batch_metrics = fetch_stock_metrics_yfinance_batch(failed_codes, lookback_days=180)
            if batch_metrics:
                to_add = [m for m in batch_metrics if m.get("code") not in existing_codes]
                for m in to_add:
                    n = name_map.get(m.get("code"))
                    if n:
                        m["name"] = n
                stock_metrics.extend(to_add)
                logger.info("yfinance 批量补全成功: %s", [m["code"] for m in to_add])
        except Exception as exc:
            logger.error("yfinance 批量补全失败: %s", exc)

    # 若取数失败导致完全没有数据，不要直接终止；改为降级规则生成空表仪表盘。
    if not stock_metrics:
        logger.error("未获取到任何股票数据，降级输出仪表盘。失败代码: %s", failed_codes)
        llm_result = fallback_analysis([])
    else:
        llm_client = DeepSeekClient(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
        )
        try:
            llm_result = llm_client.analyze(stock_metrics)
            logger.info("DeepSeek 分析完成")
        except Exception as exc:
            logger.error("DeepSeek 调用失败，启用降级规则: %s", exc)
            llm_result = fallback_analysis(stock_metrics)

    html = render_dashboard_html(stock_metrics, llm_result)
    subject_date = f"{datetime.now():%Y-%m-%d}"
    subject = (
        f"沪A股每日决策仪表盘 - {subject_date}"
        if stock_metrics
        else f"沪A股每日决策仪表盘（无可用行情） - {subject_date}"
    )
    if not stock_metrics and failed_codes:
        # 邮件标题里带上少量失败代码，方便定位；不影响正文表格生成。
        subject = f"{subject}，失败: {', '.join(failed_codes[:3])}"
    send_html_email(
        host=settings.smtp_host,
        port=settings.smtp_port,
        user=settings.smtp_user,
        password=settings.smtp_password,
        sender=settings.mail_from,
        receivers=settings.mail_to,
        subject=subject,
        html_body=html,
    )
    logger.info("邮件推送成功: %s", settings.mail_to)
    return {"stock_metrics": stock_metrics, "llm_result": llm_result}


def run_schedule() -> None:
    settings = load_settings()
    hour, minute = settings.run_time.split(":")
    scheduler = BlockingScheduler(timezone=settings.timezone)
    scheduler.add_job(
        run_pipeline,
        trigger=CronTrigger(hour=int(hour), minute=int(minute), timezone=settings.timezone),
        id="daily_stock_dashboard",
        replace_existing=True,
    )
    logger.info("定时任务已启动，每天 %s (%s) 执行", settings.run_time, settings.timezone)
    scheduler.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="沪A股自选股智能分析系统")
    parser.add_argument("--once", action="store_true", help="立即执行一次分析并推送")
    parser.add_argument("--schedule", action="store_true", help="进入每日定时模式")
    args = parser.parse_args()

    if args.once:
        run_pipeline()
    else:
        run_schedule()


if __name__ == "__main__":
    main()
