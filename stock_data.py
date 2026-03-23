from __future__ import annotations

import json
import io
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import time

import akshare as ak
import pandas as pd
import requests


SH_A_PREFIXES = ("600", "601", "603", "605", "688", "689")

CACHE_DIR = Path(__file__).resolve().parent / "cache"


def validate_sh_a_stock(code: str) -> bool:
    return code.isdigit() and len(code) == 6 and code.startswith(SH_A_PREFIXES)


def _cache_path(code: str) -> Path:
    return CACHE_DIR / f"stock_{code}.json"


def _load_cached_stock_metrics(code: str, max_age_days: int) -> dict[str, Any] | None:
    path = _cache_path(code)
    if not path.exists():
        return None

    # 用文件 mtime 判定缓存新鲜度
    age_days = (time.time() - path.stat().st_mtime) / 86400
    if age_days > max_age_days:
        return None

    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    metrics = cached.get("metrics") if isinstance(cached, dict) else None
    if isinstance(metrics, dict) and metrics.get("code") == code:
        return metrics
    return None


def _save_cached_stock_metrics(code: str, metrics: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"saved_at": datetime.now().isoformat(timespec="seconds"), "metrics": metrics}
    _cache_path(code).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _fetch_stock_metrics_yfinance(
    code: str,
    lookback_days: int,
) -> dict[str, Any] | None:
    """
    当 akshare 无法获取行情时，用 yfinance 兜底。
    对于沪A代码，Yahoo 通常使用后缀 `.SS`。
    """
    try:
        import yfinance as yf  # 延迟导入：避免依赖缺失导致程序启动失败
    except Exception:
        return None

    # Yahoo: 上海股票用 .SS
    yf_symbol = f"{code}.SS"

    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    try:
        df = yf.download(
            yf_symbol,
            start=start_date,
            end=end_date,
            interval="1d",
            progress=False,
            auto_adjust=False,
            threads=False,
        )
    except Exception:
        return None

    if df is None or df.empty:
        return None

    if "Close" not in df.columns or "Volume" not in df.columns:
        return None

    df = df.copy()
    df["close"] = pd.to_numeric(df["Close"], errors="coerce")
    df["volume"] = pd.to_numeric(df["Volume"], errors="coerce")
    df = df.dropna(subset=["close"])
    if df.empty:
        return None

    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["rsi14"] = _calc_rsi(df["close"], 14)
    df["vol_ratio5"] = df["volume"] / df["volume"].rolling(5).mean()

    last = df.iloc[-1]
    prev_close = float(df["close"].iloc[-2]) if len(df) > 1 else float(last["close"])
    change_pct = (float(last["close"]) - prev_close) / prev_close * 100 if prev_close else 0.0

    return {
        "code": code,
        "date": df.index[-1].strftime("%Y-%m-%d"),
        "close": round(float(last["close"]), 2),
        "change_pct": round(change_pct, 2),
        "ma5": round(float(last["ma5"]), 2) if pd.notna(last["ma5"]) else None,
        "ma20": round(float(last["ma20"]), 2) if pd.notna(last["ma20"]) else None,
        "rsi14": round(float(last["rsi14"]), 2) if pd.notna(last["rsi14"]) else None,
        "vol_ratio5": round(float(last["vol_ratio5"]), 2) if pd.notna(last["vol_ratio5"]) else None,
        "prev_close": round(prev_close, 2),
    }


def _fetch_stock_metrics_stooq(
    code: str,
    lookback_days: int,
) -> dict[str, Any] | None:
    """
    stooq 免费公开行情源（CSV），用于在 akshare/yfinance 不可用时兜底。
    沪A代码使用后缀 `.cn`（例如 600519.cn）。
    """
    symbol = f"{code}.cn"
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"

    start_dt = datetime.now() - timedelta(days=lookback_days)

    try:
        r = requests.get(url, timeout=30)
    except Exception:
        return None

    if r.status_code != 200:
        return None

    text = (r.text or "").strip()
    if not text or text.lower().startswith("no data"):
        return None

    try:
        csv_df = pd.read_csv(io.StringIO(text))
    except Exception:
        return None

    if csv_df.empty or "Date" not in csv_df.columns:
        return None

    csv_df["Date"] = pd.to_datetime(csv_df["Date"], errors="coerce")
    csv_df = csv_df.dropna(subset=["Date"])
    csv_df = csv_df.sort_values("Date")

    # 按 lookback_days 截断
    csv_df = csv_df[csv_df["Date"] >= pd.Timestamp(start_dt)]
    if csv_df.empty:
        return None

    if "Close" not in csv_df.columns or "Volume" not in csv_df.columns:
        return None

    csv_df["close"] = pd.to_numeric(csv_df["Close"], errors="coerce")
    csv_df["volume"] = pd.to_numeric(csv_df["Volume"], errors="coerce")
    csv_df = csv_df.dropna(subset=["close"])
    if csv_df.empty:
        return None

    csv_df["ma5"] = csv_df["close"].rolling(5).mean()
    csv_df["ma20"] = csv_df["close"].rolling(20).mean()
    csv_df["rsi14"] = _calc_rsi(csv_df["close"], 14)
    csv_df["vol_ratio5"] = csv_df["volume"] / csv_df["volume"].rolling(5).mean()

    last = csv_df.iloc[-1]
    prev_close = float(csv_df["close"].iloc[-2]) if len(csv_df) > 1 else float(last["close"])
    change_pct = (float(last["close"]) - prev_close) / prev_close * 100 if prev_close else 0.0

    return {
        "code": code,
        "date": last["Date"].strftime("%Y-%m-%d"),
        "close": round(float(last["close"]), 2),
        "change_pct": round(change_pct, 2),
        "ma5": round(float(last["ma5"]), 2) if pd.notna(last["ma5"]) else None,
        "ma20": round(float(last["ma20"]), 2) if pd.notna(last["ma20"]) else None,
        "rsi14": round(float(last["rsi14"]), 2) if pd.notna(last["rsi14"]) else None,
        "vol_ratio5": round(float(last["vol_ratio5"]), 2) if pd.notna(last["vol_ratio5"]) else None,
        "prev_close": round(prev_close, 2),
    }


def _fetch_stock_metrics_yfinance_batch(
    codes: list[str],
    lookback_days: int,
) -> dict[str, dict[str, Any]]:
    """
    批量拉取，避免 yfinance 对每只股票多次请求导致 RateLimit。
    失败时返回空 dict。
    """
    try:
        import yfinance as yf
    except Exception:
        return {}

    if not codes:
        return {}

    yf_symbols = [f"{code}.SS" for code in codes]
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    df = None
    for attempt in range(3):
        try:
            df = yf.download(
                yf_symbols,
                start=start_date,
                end=end_date,
                interval="1d",
                progress=False,
                auto_adjust=False,
                threads=False,
                group_by="ticker",
                timeout=30,
            )
            break
        except Exception as exc:
            msg = str(exc)
            # yfinance 可能会临时限流，等待后重试
            if "Rate limited" in msg or "YFRateLimitError" in msg:
                time.sleep(10 * (attempt + 1))
                continue
            return {}

    if df is None:
        return {}

    if df is None or df.empty:
        return {}

    results: dict[str, dict[str, Any]] = {}
    close_field = "Close"
    vol_field = "Volume"

    if not isinstance(df.columns, pd.MultiIndex):
        # 仅有 1 个 ticker 时的兜底（但 batch 情况通常不会走到）
        single_code = codes[0]
        metrics = _fetch_stock_metrics_yfinance(single_code, lookback_days)
        if metrics:
            results[single_code] = metrics
        return results

    level0 = set(df.columns.get_level_values(0))
    level1 = set(df.columns.get_level_values(1))

    for code, sym in zip(codes, yf_symbols):
        try:
            if sym in level0:
                close_series = df[sym][close_field]
                volume_series = df[sym][vol_field]
            elif sym in level1:
                close_series = df[close_field][sym]
                volume_series = df[vol_field][sym]
            else:
                continue
        except Exception:
            continue

        tmp = pd.DataFrame({"close": close_series, "volume": volume_series}).dropna(subset=["close"])
        if tmp.empty:
            continue

        tmp["ma5"] = tmp["close"].rolling(5).mean()
        tmp["ma20"] = tmp["close"].rolling(20).mean()
        tmp["rsi14"] = _calc_rsi(tmp["close"], 14)
        tmp["vol_ratio5"] = tmp["volume"] / tmp["volume"].rolling(5).mean()

        last = tmp.iloc[-1]
        prev_close = float(tmp["close"].iloc[-2]) if len(tmp) > 1 else float(last["close"])
        change_pct = (float(last["close"]) - prev_close) / prev_close * 100 if prev_close else 0.0

        results[code] = {
            "code": code,
            "date": tmp.index[-1].strftime("%Y-%m-%d"),
            "close": round(float(last["close"]), 2),
            "change_pct": round(change_pct, 2),
            "ma5": round(float(last["ma5"]), 2) if pd.notna(last["ma5"]) else None,
            "ma20": round(float(last["ma20"]), 2) if pd.notna(last["ma20"]) else None,
            "rsi14": round(float(last["rsi14"]), 2) if pd.notna(last["rsi14"]) else None,
            "vol_ratio5": round(float(last["vol_ratio5"]), 2) if pd.notna(last["vol_ratio5"]) else None,
            "prev_close": round(prev_close, 2),
        }

    return results


def fetch_stock_metrics_yfinance_batch(
    codes: list[str],
    lookback_days: int = 180,
) -> list[dict[str, Any]]:
    results_map = _fetch_stock_metrics_yfinance_batch(codes=codes, lookback_days=lookback_days)
    return list(results_map.values())


def _calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def fetch_stock_metrics(
    code: str,
    lookback_days: int = 180,
    use_cache: bool = True,
    cache_ttl_days: int = 7,
    use_yfinance_fallback: bool = True,
) -> dict[str, Any]:
    if not validate_sh_a_stock(code):
        raise ValueError(f"仅支持沪A股票，当前代码不符合规则: {code}")

    end_date = datetime.now().strftime("%Y%m%d")
    symbol = f"sh{code}"

    # AkShare 在网络/数据源波动时可能返回空 DataFrame。
    # 这里做少量参数降级与重试，尽量拿到可用的历史数据。
    # akshare 的 adjust 参数默认是空字符串 '' 表示不复权
    adjust_candidates = ["qfq", "hfq", ""]
    # 优先尝试更短时间窗，降低单次请求压力；再逐步扩大。
    lookback_candidates = sorted(
        {max(30, min(lookback_days, 90)), lookback_days, max(lookback_days, 90) * 2}
    )

    last_err: Exception | None = None
    df = None
    for days in lookback_candidates:
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        for adjust in adjust_candidates:
            try:
                df_try = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust,
                    timeout=60,
                )
            except Exception as exc:  # akshare 可能在异常时直接抛出
                last_err = exc
                # 避免无间隔快速重试导致对端直接断开
                time.sleep(1.0)
                continue
            if df_try is not None and not df_try.empty:
                df = df_try
                break
        if df is not None and not df.empty:
            break

    if df is None or df.empty:
        detail = f"，最后一次异常: {last_err}" if last_err else ""
        # akshare 无数据时：先尝试 stooq，再尝试 yfinance，最后回退到本地缓存
        stooq_metrics = _fetch_stock_metrics_stooq(code, lookback_days)
        if stooq_metrics:
            if use_cache:
                _save_cached_stock_metrics(code, stooq_metrics)
            return stooq_metrics

        if use_yfinance_fallback:
            yfinance_metrics = _fetch_stock_metrics_yfinance(code, lookback_days)
            if yfinance_metrics:
                if use_cache:
                    _save_cached_stock_metrics(code, yfinance_metrics)
                return yfinance_metrics

        if use_cache:
            cached = _load_cached_stock_metrics(code, max_age_days=cache_ttl_days)
            if cached:
                return cached
        raise ValueError(f"股票 {code} 无可用数据{detail}")

    df = df.sort_values("日期").copy()
    df["收盘"] = pd.to_numeric(df["收盘"], errors="coerce")
    df["成交量"] = pd.to_numeric(df["成交量"], errors="coerce")
    df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce")

    df["ma5"] = df["收盘"].rolling(5).mean()
    df["ma20"] = df["收盘"].rolling(20).mean()
    df["rsi14"] = _calc_rsi(df["收盘"], 14)
    df["vol_ratio5"] = df["成交量"] / df["成交量"].rolling(5).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last

    metrics = {
        "code": code,
        "date": str(last["日期"])[:10],
        "close": round(float(last["收盘"]), 2),
        "change_pct": round(float(last["涨跌幅"]), 2),
        "ma5": round(float(last["ma5"]), 2) if pd.notna(last["ma5"]) else None,
        "ma20": round(float(last["ma20"]), 2) if pd.notna(last["ma20"]) else None,
        "rsi14": round(float(last["rsi14"]), 2) if pd.notna(last["rsi14"]) else None,
        "vol_ratio5": round(float(last["vol_ratio5"]), 2) if pd.notna(last["vol_ratio5"]) else None,
        "prev_close": round(float(prev["收盘"]), 2),
    }

    if use_cache:
        _save_cached_stock_metrics(code, metrics)

    return metrics
