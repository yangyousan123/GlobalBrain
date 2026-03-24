from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..analysis.accuracy import update_and_summarize_accuracy
from ..analysis.rules import annotate_trading_discipline
from ..config import Settings, load_settings
from ..dashboard import render_dashboard_html
from ..data.market_calendar import is_cn_trading_day
from ..data.stock_data import (
    fetch_stock_metrics,
    fetch_stock_metrics_without_yfinance,
    fetch_stock_metrics_yfinance_batch,
)
from ..data.watchlist import load_watchlist, watchlist_has_cn_sh
from ..llm import OpenAICompatClient, fallback_analysis
from ..news.tavily_news import fetch_stock_news_digest
from ..news.translate_zh import translate_tavily_payload_to_zh
from ..notify import dispatch_report

logger = logging.getLogger(__name__)


def resolve_watchlist_path(path_str: str) -> str:
    p = Path(path_str)
    if p.is_absolute():
        return str(p)
    root = Path(__file__).resolve().parent.parent.parent
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
                api_keys=list(settings.llm_api_keys),
                provider_api_keys={k: list(v) for k, v in settings.llm_provider_api_keys.items()},
                include_answer=settings.tavily_include_answer,
            )

        translator = _tr_body
    for m in stock_metrics:
        code = m.get("code")
        if not code:
            continue
        market = str(m.get("market") or "cn_sh")
        digest = fetch_stock_news_digest(
            key,
            str(code),
            m.get("name") if isinstance(m.get("name"), str) else None,
            market=market,
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
            logger.info("Tavily 新闻摘要已写入: %s %s", market, code)
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
    watchlist = load_watchlist(resolve_watchlist_path(watchlist_path))
    if settings.trading_day_check_enabled and not force_run and watchlist_has_cn_sh(watchlist):
        if not is_cn_trading_day():
            logger.info("自选股含沪A：今日非 A 股交易日，跳过分析（可 --force-run）")
            return {"skipped": True, "reason": "non_trading_day"}

    logger.info("开始分析，股票数量: %s", len(watchlist))

    stock_metrics: list[dict[str, Any]] = []
    name_map = {(item["code"], item["market"]): item.get("name") for item in watchlist}
    failed_items: list[tuple[str, str]] = []
    delay = max(0.0, settings.analysis_delay_seconds)

    for item in watchlist:
        code = item["code"]
        market = item["market"]
        name = item.get("name")
        try:
            metrics = fetch_stock_metrics(code, market=market, use_yfinance_fallback=False)
            metrics = annotate_trading_discipline(
                metrics,
                bias_threshold_pct=settings.bias_threshold_pct,
            )
            if name:
                metrics["name"] = name
            stock_metrics.append(metrics)
            logger.info("已获取数据: %s %s", market, code)
        except Exception as exc:
            failed_items.append((code, market))
            logger.error("获取股票 %s %s 数据失败: %s", market, code, exc)
        if delay > 0:
            time.sleep(delay)

    if failed_items:
        try:
            existing = {(m.get("code"), m.get("market")) for m in stock_metrics}
            batch_metrics = fetch_stock_metrics_yfinance_batch(failed_items, lookback_days=180)
            if batch_metrics:
                to_add = []
                for m in batch_metrics:
                    key = (m.get("code"), m.get("market"))
                    if key not in existing:
                        m = annotate_trading_discipline(
                            m,
                            bias_threshold_pct=settings.bias_threshold_pct,
                        )
                        n = name_map.get(key)
                        if n:
                            m["name"] = n
                        to_add.append(m)
                stock_metrics.extend(to_add)
                logger.info("yfinance 批量补全成功: %s", [(x.get("market"), x.get("code")) for x in to_add])
        except Exception as exc:
            logger.error("yfinance 批量补全失败: %s", exc)

    existing_after = {(m.get("code"), m.get("market")) for m in stock_metrics}
    still_failed = [(c, m) for c, m in failed_items if (c, m) not in existing_after]
    if still_failed:
        for code, market in still_failed:
            m = fetch_stock_metrics_without_yfinance(code, market=market, lookback_days=180)
            if not m:
                continue
            m = annotate_trading_discipline(
                m,
                bias_threshold_pct=settings.bias_threshold_pct,
            )
            n = name_map.get((code, market))
            if n:
                m["name"] = n
            stock_metrics.append(m)
            logger.info("非 Yahoo 源补全成功: %s %s", market, code)

    _enrich_news_from_tavily(settings, stock_metrics)

    if not stock_metrics:
        failed_label = [f"{m}:{c}" for c, m in failed_items[:5]]
        logger.error("未获取到任何股票数据，降级输出仪表盘。失败: %s", failed_label)
        llm_result = fallback_analysis([])
    else:
        llm_client = OpenAICompatClient(
            api_key=settings.llm_api_key,
            api_keys=list(settings.llm_api_keys),
            provider_api_keys={k: list(v) for k, v in settings.llm_provider_api_keys.items()},
            base_url=settings.llm_base_url,
            models=list(settings.llm_models),
        )
        try:
            llm_result = llm_client.analyze(stock_metrics)
            logger.info("LLM 分析完成（模型链: %s）", " -> ".join(settings.llm_models))
        except Exception as exc:
            logger.error("LLM 调用失败，启用降级规则: %s", exc)
            llm_result = fallback_analysis(stock_metrics)

    accuracy_summary = update_and_summarize_accuracy(
        stock_metrics,
        llm_result,
        window_days=settings.accuracy_windows,
    )
    html = render_dashboard_html(stock_metrics, llm_result, accuracy_summary=accuracy_summary)
    subject_date = f"{datetime.now():%Y-%m-%d}"
    subject = (
        f"自选股决策仪表盘 - {subject_date}"
        if stock_metrics
        else f"自选股决策仪表盘（无可用行情） - {subject_date}"
    )
    if not stock_metrics and failed_items:
        subject = f"{subject}，失败: {', '.join(f'{m}:{c}' for c, m in failed_items[:3])}"

    dispatch_report(settings, subject, html)
    logger.info("推送流程已执行，渠道: %s", ",".join(settings.notify_channels))
    return {"stock_metrics": stock_metrics, "llm_result": llm_result}
