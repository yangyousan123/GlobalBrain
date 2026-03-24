from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings, load_settings
from .dashboard import render_dashboard_html
from .deepseek_client import OpenAICompatClient, fallback_analysis
from .notifications import dispatch_report
from .market_calendar import is_cn_trading_day
from .rules import annotate_trading_discipline
from .stock_data import fetch_stock_metrics, fetch_stock_metrics_yfinance_batch
from .tavily_news import fetch_stock_news_digest
from .translate_zh import translate_tavily_payload_to_zh
from .watchlist import load_watchlist

logger = logging.getLogger(__name__)


def resolve_watchlist_path(path_str: str) -> str:
    p = Path(path_str)
    if p.is_absolute():
        return str(p)
    root = Path(__file__).resolve().parent.parent
    for base in (root, Path.cwd()):
        cand = (base / p).resolve()
        if cand.exists():
            return str(cand)
    return str((root / p).resolve())


def _enrich_news_from_tavily(settings: Settings, stock_metrics: list[dict[str, Any]]) -> None:
    if not settings.tavily_enabled or not settings.tavily_api_key:
        return
    key = settings.tavily_api_key
    delay = max(0.0, settings.tavily_request_delay_seconds)
    translator = None
    if settings.tavily_translate_answer_to_zh:

        def _tr_body(b: dict[str, Any]) -> dict[str, Any]:
            return translate_tavily_payload_to_zh(
                b,
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                models=list(settings.llm_models),
                include_answer=settings.tavily_include_answer,
            )

        translator = _tr_body
    for m in stock_metrics:
        code = m.get("code")
        if not code:
            continue
        digest = fetch_stock_news_digest(
            key,
            str(code),
            m.get("name") if isinstance(m.get("name"), str) else None,
            max_results=settings.tavily_max_results,
            search_depth=settings.tavily_search_depth,
            topic=settings.tavily_topic,
            time_range=settings.tavily_time_range,
            include_answer=settings.tavily_include_answer,
            digest_max_chars=settings.news_digest_max_chars,
            translate_payload=translator,
        )
        if digest:
            m["news_digest"] = digest
            logger.info("Tavily 新闻摘要已写入: %s", code)
        if delay > 0:
            time.sleep(delay)


def run_analysis_pipeline(
    settings: Settings,
    *,
    watchlist_path: str = "watchlist.yaml",
    force_run: bool = False,
) -> dict[str, Any]:
    """
    主链路：交易日检查 → 拉取行情 → 规则标注 →（可选）Tavily 新闻 → LLM → 多渠道推送。
    """
    if settings.trading_day_check_enabled and not force_run:
        if not is_cn_trading_day():
            logger.info("今日非 A 股交易日，跳过分析（可设置 TRADING_DAY_CHECK_ENABLED=false 或 --force-run）")
            return {"skipped": True, "reason": "non_trading_day"}

    watchlist = load_watchlist(resolve_watchlist_path(watchlist_path))
    logger.info("开始分析，股票数量: %s", len(watchlist))

    stock_metrics: list[dict[str, Any]] = []
    name_map = {item["code"]: item.get("name") for item in watchlist}
    failed_codes: list[str] = []
    delay = max(0.0, settings.analysis_delay_seconds)

    for item in watchlist:
        code = item["code"]
        name = item.get("name")
        try:
            metrics = fetch_stock_metrics(code, use_yfinance_fallback=False)
            metrics = annotate_trading_discipline(
                metrics,
                bias_threshold_pct=settings.bias_threshold_pct,
            )
            if name:
                metrics["name"] = name
            stock_metrics.append(metrics)
            logger.info("已获取数据: %s", code)
        except Exception as exc:
            failed_codes.append(code)
            logger.error("获取股票 %s 数据失败: %s", code, exc)
        if delay > 0:
            time.sleep(delay)

    if failed_codes:
        try:
            existing_codes = {item.get("code") for item in stock_metrics}
            batch_metrics = fetch_stock_metrics_yfinance_batch(failed_codes, lookback_days=180)
            if batch_metrics:
                to_add = []
                for m in batch_metrics:
                    if m.get("code") not in existing_codes:
                        m = annotate_trading_discipline(
                            m,
                            bias_threshold_pct=settings.bias_threshold_pct,
                        )
                        n = name_map.get(m.get("code"))
                        if n:
                            m["name"] = n
                        to_add.append(m)
                stock_metrics.extend(to_add)
                logger.info("yfinance 批量补全成功: %s", [m["code"] for m in to_add])
        except Exception as exc:
            logger.error("yfinance 批量补全失败: %s", exc)

    _enrich_news_from_tavily(settings, stock_metrics)

    if not stock_metrics:
        logger.error("未获取到任何股票数据，降级输出仪表盘。失败代码: %s", failed_codes)
        llm_result = fallback_analysis([])
    else:
        llm_client = OpenAICompatClient(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            models=list(settings.llm_models),
        )
        try:
            llm_result = llm_client.analyze(stock_metrics)
            logger.info("LLM 分析完成（模型链: %s）", " -> ".join(settings.llm_models))
        except Exception as exc:
            logger.error("LLM 调用失败，启用降级规则: %s", exc)
            llm_result = fallback_analysis(stock_metrics)

    html = render_dashboard_html(stock_metrics, llm_result)
    subject_date = f"{datetime.now():%Y-%m-%d}"
    subject = (
        f"沪A股每日决策仪表盘 - {subject_date}"
        if stock_metrics
        else f"沪A股每日决策仪表盘（无可用行情） - {subject_date}"
    )
    if not stock_metrics and failed_codes:
        subject = f"{subject}，失败: {', '.join(failed_codes[:3])}"

    dispatch_report(settings, subject, html)
    logger.info("推送流程已执行，渠道: %s", ",".join(settings.notify_channels))
    return {"stock_metrics": stock_metrics, "llm_result": llm_result}


