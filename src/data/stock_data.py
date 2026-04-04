from __future__ import annotations

import io
import json
import math
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import akshare as ak
import pandas as pd
import requests

from .markets import (
    MARKET_CN_SH,
    MARKET_HK,
    MARKET_US,
    code_to_yfinance_symbol,
    normalize_hk_code,
    validate_cn_sh,
)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache"

_STOOQ_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,*/*;q=0.8",
}


def _stooq_fetch_csv_text(url: str) -> str | None:
    """Stooq 对无浏览器特征的请求常返回空体；带 UA 并做有限次重试。"""
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=45, headers=_STOOQ_HEADERS)
        except Exception:
            if attempt < 3:
                time.sleep(2.0 * (attempt + 1))
                continue
            return None
        if r.status_code != 200:
            if attempt < 3:
                time.sleep(2.0 * (attempt + 1))
                continue
            return None
        text = (r.text or "").strip()
        if text and not text.lower().startswith("no data"):
            return text
        if attempt < 3:
            time.sleep(3.0 * (attempt + 1))
    return None


def validate_sh_a_stock(code: str) -> bool:
    """兼容旧调用：沪A 校验。"""
    return validate_cn_sh(code)


def _norm_cache_key(code: str) -> str:
    return str(code).replace(".", "_").replace("-", "_")


def _cache_path(market: str, code: str) -> Path:
    return CACHE_DIR / f"stock_{market}_{_norm_cache_key(code)}.json"


def _load_cached_stock_metrics(
    market: str, code: str, max_age_days: int
) -> dict[str, Any] | None:
    path = _cache_path(market, code)
    if not path.exists():
        return None

    age_days = (time.time() - path.stat().st_mtime) / 86400
    if age_days > max_age_days:
        return None

    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    metrics = cached.get("metrics") if isinstance(cached, dict) else None
    if isinstance(metrics, dict) and metrics.get("code") == code and metrics.get("market") == market:
        return metrics
    return None


def _save_cached_stock_metrics(market: str, code: str, metrics: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"saved_at": datetime.now().isoformat(timespec="seconds"), "metrics": metrics}
    _cache_path(market, code).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _finalize_ohlc_metrics(
    *,
    code: str,
    market: str,
    date_str: str,
    close: float,
    change_pct: float,
    prev_close: float,
    vol_ratio5: float | None,
) -> dict[str, Any]:
    def r2(x: float | None) -> float | None:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return None
        return round(float(x), 2)

    return {
        "code": code,
        "market": market,
        "date": date_str,
        "close": round(close, 2),
        "change_pct": round(change_pct, 2),
        "vol_ratio5": r2(vol_ratio5),
        "prev_close": round(prev_close, 2),
    }


def _is_yfinance_rate_limit(exc: BaseException) -> bool:
    name = type(exc).__name__
    if "YFRateLimit" in name or "RateLimit" in name:
        return True
    msg = str(exc).lower()
    return "rate limit" in msg or "too many requests" in msg


def _ohlc_from_close_volume_df(
    df: pd.DataFrame,
    *,
    code: str,
    market: str,
    close_col: str = "close",
    vol_col: str = "volume",
) -> dict[str, Any] | None:
    if df.empty or close_col not in df.columns:
        return None
    df = df.copy()
    df[close_col] = pd.to_numeric(df[close_col], errors="coerce")
    if vol_col in df.columns:
        df[vol_col] = pd.to_numeric(df[vol_col], errors="coerce")
    else:
        df[vol_col] = 0.0
    df = df.dropna(subset=[close_col])
    if df.empty:
        return None

    df["vol_ratio5"] = df[vol_col] / df[vol_col].rolling(5).mean()

    last = df.iloc[-1]
    prev_close = float(df[close_col].iloc[-2]) if len(df) > 1 else float(last[close_col])
    change_pct = (float(last[close_col]) - prev_close) / prev_close * 100 if prev_close else 0.0

    date_str = df.index[-1].strftime("%Y-%m-%d") if hasattr(df.index[-1], "strftime") else str(df.index[-1])[:10]

    return _finalize_ohlc_metrics(
        code=code,
        market=market,
        date_str=date_str,
        close=float(last[close_col]),
        change_pct=change_pct,
        prev_close=prev_close,
        vol_ratio5=float(last["vol_ratio5"]) if pd.notna(last["vol_ratio5"]) else None,
    )


def _fetch_stock_metrics_yfinance(
    code: str,
    market: str,
    lookback_days: int,
) -> dict[str, Any] | None:
    try:
        import yfinance as yf
    except Exception:
        return None

    yf_symbol = code_to_yfinance_symbol(code, market)
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    df = None
    for attempt in range(3):
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
        except Exception as exc:
            if _is_yfinance_rate_limit(exc) and attempt < 2:
                time.sleep(25 * (attempt + 1))
                continue
            return None

        if df is None or df.empty:
            if attempt < 2:
                time.sleep(12 * (attempt + 1))
                continue
            return None
        break

    if "Close" not in df.columns or "Volume" not in df.columns:
        return None

    df = df.copy()
    df["close"] = pd.to_numeric(df["Close"], errors="coerce")
    df["volume"] = pd.to_numeric(df["Volume"], errors="coerce")
    return _ohlc_from_close_volume_df(df, code=code, market=market)


def _fetch_stock_metrics_stooq(
    code: str,
    market: str,
    lookback_days: int,
) -> dict[str, Any] | None:
    if market == MARKET_CN_SH:
        # Stooq 上交所日线为 TICKER.ss（.cn 无法命中沪 A）
        symbol = f"{code}.ss"
    elif market == MARKET_HK:
        n = int(normalize_hk_code(code))
        symbol = f"{n:04d}.hk"
    elif market == MARKET_US:
        symbol = f"{str(code).strip().lower()}.us"
    else:
        return None

    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    start_dt = datetime.now() - timedelta(days=lookback_days)

    text = _stooq_fetch_csv_text(url)
    if not text:
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
    csv_df = csv_df[csv_df["Date"] >= pd.Timestamp(start_dt)]
    if csv_df.empty:
        return None

    if "Close" not in csv_df.columns:
        return None
    if "Volume" not in csv_df.columns:
        csv_df["Volume"] = 0.0

    csv_df["close"] = pd.to_numeric(csv_df["Close"], errors="coerce")
    csv_df["volume"] = pd.to_numeric(csv_df["Volume"], errors="coerce")
    csv_df = csv_df.dropna(subset=["close"])
    if csv_df.empty:
        return None

    vol_mean5 = csv_df["volume"].rolling(5).mean()
    csv_df["vol_ratio5"] = csv_df["volume"] / vol_mean5.replace(0, pd.NA)

    last = csv_df.iloc[-1]
    prev_close = float(csv_df["close"].iloc[-2]) if len(csv_df) > 1 else float(last["close"])
    change_pct = (float(last["close"]) - prev_close) / prev_close * 100 if prev_close else 0.0

    vr_raw = last["vol_ratio5"]
    if pd.isna(vr_raw):
        vol_ratio5 = None
    else:
        try:
            vr_f = float(vr_raw)
            vol_ratio5 = vr_f if math.isfinite(vr_f) else None
        except (TypeError, ValueError):
            vol_ratio5 = None

    return _finalize_ohlc_metrics(
        code=code,
        market=market,
        date_str=last["Date"].strftime("%Y-%m-%d"),
        close=float(last["close"]),
        change_pct=change_pct,
        prev_close=prev_close,
        vol_ratio5=vol_ratio5,
    )


def _cn_sh_stooq_yfinance_fallback(
    code: str,
    lookback_days: int,
    *,
    use_yfinance_fallback: bool,
    use_cache: bool,
    cache_ttl_days: int,
) -> dict[str, Any] | None:
    """沪 A：仅 Stooq →（可选）yfinance → 读缓存；不含 AkShare。"""
    if use_cache:
        cached = _load_cached_stock_metrics(MARKET_CN_SH, code, max_age_days=cache_ttl_days)
        if cached:
            return cached
    m = _fetch_stock_metrics_stooq(code, MARKET_CN_SH, lookback_days)
    if m:
        if use_cache:
            _save_cached_stock_metrics(MARKET_CN_SH, code, m)
        return m
    if use_yfinance_fallback:
        m = _fetch_stock_metrics_yfinance(code, MARKET_CN_SH, lookback_days)
        if m:
            if use_cache:
                _save_cached_stock_metrics(MARKET_CN_SH, code, m)
            return m
    if use_cache:
        cached = _load_cached_stock_metrics(MARKET_CN_SH, code, max_age_days=cache_ttl_days)
        if cached:
            return cached
    return None


def _fetch_hk_akshare(code: str, lookback_days: int) -> dict[str, Any] | None:
    sym = normalize_hk_code(code)
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y%m%d")
    try:
        df_try = ak.stock_hk_hist(
            symbol=sym,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="",
        )
    except Exception:
        return None

    if df_try is None or df_try.empty:
        return None

    df = df_try.sort_values("日期").copy()
    if "收盘" not in df.columns:
        return None
    df["收盘"] = pd.to_numeric(df["收盘"], errors="coerce")
    vol_col = "成交量" if "成交量" in df.columns else None
    if vol_col:
        df["成交量"] = pd.to_numeric(df["成交量"], errors="coerce")
    else:
        df["成交量"] = 0.0
    if "涨跌幅" not in df.columns:
        df["涨跌幅"] = df["收盘"].pct_change() * 100

    df["vol_ratio5"] = df["成交量"] / df["成交量"].rolling(5).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last

    return _finalize_ohlc_metrics(
        code=sym,
        market=MARKET_HK,
        date_str=str(last["日期"])[:10],
        close=float(last["收盘"]),
        change_pct=float(last["涨跌幅"]) if pd.notna(last["涨跌幅"]) else 0.0,
        prev_close=float(prev["收盘"]),
        vol_ratio5=float(last["vol_ratio5"]) if pd.notna(last["vol_ratio5"]) else None,
    )


def _fetch_stock_metrics_yfinance_batch(
    items: list[tuple[str, str]],
    lookback_days: int,
) -> dict[str, dict[str, Any]]:
    try:
        import yfinance as yf
    except Exception:
        return {}

    if not items:
        return {}

    yf_symbols = [code_to_yfinance_symbol(c, m) for c, m in items]
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
            if _is_yfinance_rate_limit(exc):
                time.sleep(25 * (attempt + 1))
                continue
            return {}

    if df is None or df.empty:
        return {}

    results: dict[str, dict[str, Any]] = {}
    close_field = "Close"
    vol_field = "Volume"

    if not isinstance(df.columns, pd.MultiIndex):
        if len(items) == 1:
            code, market = items[0]
            m = _fetch_stock_metrics_yfinance(code, market, lookback_days)
            if m:
                results[f"{market}:{code}"] = m
        return results

    level0 = set(df.columns.get_level_values(0))
    level1 = set(df.columns.get_level_values(1))

    for (code, market), sym in zip(items, yf_symbols):
        key = f"{market}:{code}"
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
        m = _ohlc_from_close_volume_df(tmp, code=code, market=market)
        if m:
            results[key] = m

    return results


def fetch_stock_metrics_yfinance_batch(
    items: list[tuple[str, str]],
    lookback_days: int = 180,
) -> list[dict[str, Any]]:
    results_map = _fetch_stock_metrics_yfinance_batch(items=items, lookback_days=lookback_days)
    return list(results_map.values())


def fetch_stock_metrics_without_yfinance(
    code: str,
    market: str,
    lookback_days: int = 180,
    use_cache: bool = True,
    cache_ttl_days: int = 7,
) -> dict[str, Any] | None:
    """
    不使用 Yahoo Finance：沪 A / 美股仅 Stooq；港股 AkShare → Stooq。
    用于首轮与批量 yfinance 均失败后的补全，避免反复触发限流。
    """
    if market not in (MARKET_CN_SH, MARKET_HK, MARKET_US):
        return None

    if market == MARKET_CN_SH:
        if not validate_cn_sh(code):
            return None
        code = str(code).strip()
    elif market == MARKET_HK:
        code = normalize_hk_code(code)
    elif market == MARKET_US:
        code = str(code).strip().upper().replace(" ", "")

    if use_cache:
        cached = _load_cached_stock_metrics(market, code, max_age_days=cache_ttl_days)
        if cached:
            return cached

    if market == MARKET_CN_SH:
        m = _fetch_stock_metrics_stooq(code, market, lookback_days)
    elif market == MARKET_HK:
        m = _fetch_hk_akshare(code, lookback_days)
        if not m:
            m = _fetch_stock_metrics_stooq(code, market, lookback_days)
    else:
        m = _fetch_stock_metrics_stooq(code, market, lookback_days)

    if m and use_cache:
        _save_cached_stock_metrics(market, code, m)
    return m


def fetch_stock_metrics(
    code: str,
    market: str = MARKET_CN_SH,
    lookback_days: int = 180,
    use_cache: bool = True,
    cache_ttl_days: int = 7,
    use_yfinance_fallback: bool = True,
    skip_akshare: bool = False,
) -> dict[str, Any]:
    if market not in (MARKET_CN_SH, MARKET_HK, MARKET_US):
        raise ValueError(f"不支持的市场: {market}")

    if market == MARKET_CN_SH and not validate_cn_sh(code):
        raise ValueError(f"仅支持沪A股票，当前代码不符合规则: {code}")
    if market == MARKET_HK:
        code = normalize_hk_code(code)
    elif market == MARKET_US:
        code = str(code).strip().upper().replace(" ", "")

    if market == MARKET_HK:
        if use_cache:
            cached = _load_cached_stock_metrics(market, code, max_age_days=cache_ttl_days)
            if cached:
                return cached
        # 优先 AkShare / Stooq，避免 Yahoo 限流导致港股整条链路失败
        m = _fetch_hk_akshare(code, lookback_days)
        if not m:
            m = _fetch_stock_metrics_stooq(code, market, lookback_days)
        if not m:
            m = _fetch_stock_metrics_yfinance(code, market, lookback_days)
        if m:
            if use_cache:
                _save_cached_stock_metrics(market, code, m)
            return m
        raise ValueError(f"港股 {code} 无可用数据")

    if market == MARKET_US:
        if use_cache:
            cached = _load_cached_stock_metrics(market, code, max_age_days=cache_ttl_days)
            if cached:
                return cached
        m = _fetch_stock_metrics_stooq(code, market, lookback_days)
        if not m:
            m = _fetch_stock_metrics_yfinance(code, market, lookback_days)
        if m:
            if use_cache:
                _save_cached_stock_metrics(market, code, m)
            return m
        raise ValueError(f"美股 {code} 无可用数据")

    # MARKET_CN_SH
    if skip_akshare:
        m = _cn_sh_stooq_yfinance_fallback(
            code,
            lookback_days,
            use_yfinance_fallback=use_yfinance_fallback,
            use_cache=use_cache,
            cache_ttl_days=cache_ttl_days,
        )
        if m:
            return m
        raise ValueError(f"股票 {code} 无可用数据（已跳过 AkShare，Stooq/yfinance 均未成功）")

    end_date = datetime.now().strftime("%Y%m%d")
    symbol = f"sh{code}"

    adjust_candidates = ["qfq", "hfq", ""]
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
            except Exception as exc:
                last_err = exc
                time.sleep(1.0)
                continue
            if df_try is not None and not df_try.empty:
                df = df_try
                break
        if df is not None and not df.empty:
            break

    if df is None or df.empty:
        detail = f"，最后一次异常: {last_err}" if last_err else ""
        m = _cn_sh_stooq_yfinance_fallback(
            code,
            lookback_days,
            use_yfinance_fallback=use_yfinance_fallback,
            use_cache=use_cache,
            cache_ttl_days=cache_ttl_days,
        )
        if m:
            return m
        raise ValueError(f"股票 {code} 无可用数据{detail}")

    df = df.sort_values("日期").copy()
    df["收盘"] = pd.to_numeric(df["收盘"], errors="coerce")
    df["成交量"] = pd.to_numeric(df["成交量"], errors="coerce")
    df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce")

    df["vol_ratio5"] = df["成交量"] / df["成交量"].rolling(5).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last

    metrics = _finalize_ohlc_metrics(
        code=code,
        market=MARKET_CN_SH,
        date_str=str(last["日期"])[:10],
        close=float(last["收盘"]),
        change_pct=float(last["涨跌幅"]),
        prev_close=float(prev["收盘"]),
        vol_ratio5=float(last["vol_ratio5"]) if pd.notna(last["vol_ratio5"]) else None,
    )

    if use_cache:
        _save_cached_stock_metrics(MARKET_CN_SH, code, metrics)

    return metrics
