from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..analysis.accuracy import update_and_summarize_accuracy
from ..config import Settings, load_settings
from ..dashboard import render_dashboard_html
from ..data.market_calendar import is_cn_trading_day
from ..data.markets import MARKET_CN_SH
from ..data.stock_data import (
    fetch_stock_metrics,
    fetch_stock_metrics_without_yfinance,
    fetch_stock_metrics_yfinance_batch,
)
from ..data.watchlist import load_watchlist, watchlist_has_cn_sh
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
    news_keys = {
        "tavily": settings.tavily_api_key,
        "serpapi": settings.serpapi_api_key,
        "bocha": settings.bocha_api_key,
        "brave": settings.brave_api_key,
        "minimax": settings.minimax_api_key,
    }
    if not any(news_keys.values()):
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
            key or "",
            str(code),
            m.get("name") if isinstance(m.get("name"), str) else None,
            market=market,
            provider_order=settings.news_provider_order,
            provider_api_keys=news_keys,
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
    主链路：交易日检查 → 拉取行情 → 规则标注 →（可选）多源新闻 → HTML 仪表盘 → 多渠道推送。
    不包含大模型生成的个股策略建议。
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
            if name:
                metrics["name"] = name
            stock_metrics.append(metrics)
            logger.info("已获取数据: %s %s", market, code)
        except Exception as exc:
            failed_items.append((code, market))
            logger.error("获取股票 %s %s 数据失败: %s", market, code, exc)
        if delay > 0:
            time.sleep(delay)

    # 先走 Stooq / 港股 AkShare，避免一上来就批量打 Yahoo 触发限流
    if failed_items:
        existing = {(m.get("code"), m.get("market")) for m in stock_metrics}
        for code, market in list(failed_items):
            if (code, market) in existing:
                continue
            time.sleep(max(2.0, delay * 2) if delay > 0 else 2.0)
            m = fetch_stock_metrics_without_yfinance(code, market=market, lookback_days=180)
            if not m:
                continue
            n = name_map.get((code, market))
            if n:
                m["name"] = n
            stock_metrics.append(m)
            existing.add((code, market))
            logger.info("首轮失败后 Stooq/非 Yahoo 补全成功: %s %s", market, code)

    if failed_items:
        try:
            existing = {(m.get("code"), m.get("market")) for m in stock_metrics}
            batch_metrics = fetch_stock_metrics_yfinance_batch(failed_items, lookback_days=180)
            if batch_metrics:
                to_add = []
                for m in batch_metrics:
                    key = (m.get("code"), m.get("market"))
                    if key not in existing:
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

    # 批量 yfinance 易触发限流；逐股延迟再试一次（含沪 A 的 yfinance 兜底）
    if still_failed:
        for code, market in list(still_failed):
            wait_s = max(45.0, delay * 8) if delay > 0 else 45.0
            time.sleep(wait_s)
            try:
                m = fetch_stock_metrics(
                    code,
                    market=market,
                    lookback_days=180,
                    use_yfinance_fallback=True,
                    skip_akshare=(market == MARKET_CN_SH),
                )
                key = (m.get("code"), m.get("market"))
                if key in {(x.get("code"), x.get("market")) for x in stock_metrics}:
                    continue
                n = name_map.get((code, market))
                if n:
                    m["name"] = n
                stock_metrics.append(m)
                logger.info("单股 yfinance 延迟补全成功: %s %s", market, code)
            except Exception as exc:
                logger.warning("单股 yfinance 补全仍失败 %s %s: %s", market, code, exc)

    existing_after = {(m.get("code"), m.get("market")) for m in stock_metrics}
    still_failed = [(c, m) for c, m in failed_items if (c, m) not in existing_after]
    if still_failed:
        for code, market in still_failed:
            m = fetch_stock_metrics_without_yfinance(code, market=market, lookback_days=180)
            if not m:
                continue
            n = name_map.get((code, market))
            if n:
                m["name"] = n
            stock_metrics.append(m)
            logger.info("非 Yahoo 源补全成功: %s %s", market, code)

    _enrich_news_from_tavily(settings, stock_metrics)

    llm_result: dict[str, Any] = {
        "market_view": "本报告为自选股行情与新闻汇总，不包含 AI 策略建议。",
        "stocks": [],
    }
    if not stock_metrics:
        failed_label = [f"{m}:{c}" for c, m in failed_items[:5]]
        logger.error("未获取到任何股票数据，仅输出空仪表盘。失败: %s", failed_label)

    accuracy_summary = update_and_summarize_accuracy(
        stock_metrics,
        llm_result,
        window_days=settings.accuracy_windows,
    )
    html = render_dashboard_html(stock_metrics, llm_result, accuracy_summary=accuracy_summary)
    subject_date = f"{datetime.now():%Y-%m-%d}"
    subject = (
        f"自选股行情与新闻简报 - {subject_date}"
        if stock_metrics
        else f"自选股行情简报（无可用行情） - {subject_date}"
    )
    if not stock_metrics and failed_items:
        subject = f"{subject}，失败: {', '.join(f'{m}:{c}' for c, m in failed_items[:3])}"

    dispatch_report(settings, subject, html)
    logger.info("推送流程已执行，渠道: %s", ",".join(settings.notify_channels))
    return {"stock_metrics": stock_metrics, "llm_result": llm_result}
