from __future__ import annotations

import argparse
import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import load_settings
from .pipeline import run_analysis_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="自选股行情与新闻简报（沪A / 港股 / 美股，不含 AI 策略建议）",
    )
    parser.add_argument("--once", action="store_true", help="立即执行一次分析并推送")
    parser.add_argument("--schedule", action="store_true", help="进入每日定时模式")
    parser.add_argument(
        "--force-run",
        action="store_true",
        help="跳过交易日检查（非交易日也执行，与 TRADING_DAY_CHECK_ENABLED 配合）",
    )
    parser.add_argument(
        "--watchlist",
        default="watchlist.yaml",
        help="自选股 YAML 路径（默认在仓库根目录或当前工作目录查找）",
    )
    args = parser.parse_args()

    if args.once:
        settings = load_settings()
        run_analysis_pipeline(
            settings,
            watchlist_path=args.watchlist,
            force_run=args.force_run,
        )
        return

    settings = load_settings()
    watchlist_path = args.watchlist
    force_run = args.force_run

    hour, minute = settings.run_time.split(":")
    scheduler = BlockingScheduler(timezone=settings.timezone)

    def _job() -> None:
        run_analysis_pipeline(
            load_settings(),
            watchlist_path=watchlist_path,
            force_run=force_run,
        )

    scheduler.add_job(
        _job,
        trigger=CronTrigger(hour=int(hour), minute=int(minute), timezone=settings.timezone),
        id="daily_stock_dashboard",
        replace_existing=True,
    )
    logger.info("定时任务已启动，每天 %s (%s) 执行", settings.run_time, settings.timezone)
    scheduler.start()


if __name__ == "__main__":
    main()
