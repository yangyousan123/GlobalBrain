from __future__ import annotations

import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from ..data.markets import MARKET_CN_SH, MARKET_HK, MARKET_US, normalize_hk_code

HISTORY_FILE = Path(__file__).resolve().parent.parent.parent / "cache" / "analysis_history.jsonl"
DEFAULT_WINDOW_DAYS = (1, 3, 5)

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _r2(v: float | None) -> float | None:
    if v is None:
        return None
    return round(float(v), 2)


def _extract_first_number(raw: Any) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s == "-":
        return None
    m = _NUM_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def _to_stooq_symbol(code: str, market: str) -> str | None:
    if market == MARKET_CN_SH:
        return f"{code}.cn"
    if market == MARKET_HK:
        return f"{int(normalize_hk_code(code)):04d}.hk"
    if market == MARKET_US:
        return f"{str(code).strip().lower()}.us"
    return None


def _fetch_stooq_history(code: str, market: str) -> pd.DataFrame | None:
    symbol = _to_stooq_symbol(code, market)
    if not symbol:
        return None
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
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
        df = pd.read_csv(io.StringIO(text))
    except Exception:
        return None
    need_cols = {"Date", "High", "Low", "Close"}
    if df.empty or not need_cols.issubset(df.columns):
        return None
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    for c in ("High", "Low", "Close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Date", "High", "Low", "Close"]).sort_values("Date")
    if df.empty:
        return None
    return df


def _load_history() -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
    except Exception:
        return []
    return rows


def _save_history(rows: list[dict[str, Any]]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(x, ensure_ascii=False) for x in rows)
    if content:
        content += "\n"
    HISTORY_FILE.write_text(content, encoding="utf-8")


def _append_today_predictions(
    rows: list[dict[str, Any]],
    stock_metrics: list[dict[str, Any]],
    llm_result: dict[str, Any],
) -> list[dict[str, Any]]:
    metric_map = {
        (str(m.get("code")), str(m.get("market") or MARKET_CN_SH)): m for m in stock_metrics
    }
    today = datetime.now().strftime("%Y-%m-%d")
    existing_ids = {str(x.get("id")) for x in rows}
    out = list(rows)
    for s in llm_result.get("stocks", []):
        code = str(s.get("code", "")).strip()
        if not code:
            continue
        market = str(s.get("market") or MARKET_CN_SH)
        data = metric_map.get((code, market))
        if not data:
            continue
        action = str(s.get("action") or "观察")
        rec_id = f"{today}:{market}:{code}"
        if rec_id in existing_ids:
            continue
        out.append(
            {
                "id": rec_id,
                "date": today,
                "market": market,
                "code": code,
                "name": data.get("name"),
                "action": action,
                "entry_close": _r2(data.get("close")),
                "take_profit": _extract_first_number(s.get("take_profit")),
                "stop_loss": _extract_first_number(s.get("stop_loss")),
                "window_evaluations": {},
                "evaluated": False,
                "direction_hit": None,
                "take_profit_hit": None,
                "stop_loss_hit": None,
                "eval_date": None,
                "days_held": None,
                "latest_close": None,
            }
        )
        existing_ids.add(rec_id)
    return out


def _window_key(days: int) -> str:
    return f"T+{days}"


def _ensure_window_evaluations(rec: dict[str, Any], windows: tuple[int, ...]) -> dict[str, Any]:
    raw = rec.get("window_evaluations")
    if not isinstance(raw, dict):
        raw = {}
    for d in windows:
        k = _window_key(d)
        if not isinstance(raw.get(k), dict):
            raw[k] = {"ready": False}
    rec["window_evaluations"] = raw
    return raw


def _normalize_windows(windows: tuple[int, ...] | list[int] | None) -> tuple[int, ...]:
    if not windows:
        return DEFAULT_WINDOW_DAYS
    vals: list[int] = []
    for w in windows:
        try:
            v = int(w)
        except Exception:
            continue
        if v <= 0:
            continue
        if v not in vals:
            vals.append(v)
    if not vals:
        return DEFAULT_WINDOW_DAYS
    return tuple(sorted(vals))


def _evaluate_window(
    *,
    rec: dict[str, Any],
    action: str,
    entry_close: float,
    forward: pd.DataFrame,
    days: int,
) -> dict[str, Any]:
    k = _window_key(days)
    item = dict(rec.get("window_evaluations", {}).get(k) or {})
    if bool(item.get("ready")):
        return item
    if len(forward) < days:
        item["ready"] = False
        return item

    seg = forward.iloc[:days]
    latest = seg.iloc[-1]
    latest_close = float(latest["Close"])
    high_max = float(seg["High"].max())
    low_min = float(seg["Low"].min())

    direction_hit: bool | None = None
    if action == "买入":
        direction_hit = latest_close > float(entry_close)
    elif action == "减仓":
        direction_hit = latest_close < float(entry_close)

    tp = rec.get("take_profit")
    sl = rec.get("stop_loss")
    tp_hit: bool | None = None
    sl_hit: bool | None = None
    if isinstance(tp, (int, float)):
        if action == "减仓":
            tp_hit = low_min <= float(tp)
        else:
            tp_hit = high_max >= float(tp)
    if isinstance(sl, (int, float)):
        if action == "减仓":
            sl_hit = high_max >= float(sl)
        else:
            sl_hit = low_min <= float(sl)

    item.update(
        {
            "ready": True,
            "direction_hit": direction_hit,
            "take_profit_hit": tp_hit,
            "stop_loss_hit": sl_hit,
            "eval_date": datetime.now().strftime("%Y-%m-%d"),
            "window_end_date": latest["Date"].strftime("%Y-%m-%d"),
            "latest_close": _r2(latest_close),
            "days_held": int((latest["Date"] - pd.Timestamp(rec["date"])).days),
        }
    )
    return item


def _evaluate_one(rec: dict[str, Any], windows: tuple[int, ...]) -> dict[str, Any]:
    entry_date = str(rec.get("date") or "")
    action = str(rec.get("action") or "观察")
    market = str(rec.get("market") or MARKET_CN_SH)
    code = str(rec.get("code") or "")
    entry_close = rec.get("entry_close")
    if not entry_date or not code or entry_close is None:
        return rec

    hist = _fetch_stooq_history(code, market)
    if hist is None or hist.empty:
        return rec

    try:
        entry_dt = pd.Timestamp(entry_date)
    except Exception:
        return rec
    forward = hist[hist["Date"] > entry_dt]
    if forward.empty:
        return rec

    wins = _ensure_window_evaluations(rec, windows)
    for d in windows:
        wins[_window_key(d)] = _evaluate_window(
            rec=rec,
            action=action,
            entry_close=float(entry_close),
            forward=forward,
            days=d,
        )

    # 兼容旧字段：以最长期窗口作为总览
    longest = wins.get(_window_key(max(windows)), {})
    rec["evaluated"] = bool(longest.get("ready"))
    rec["direction_hit"] = longest.get("direction_hit")
    rec["take_profit_hit"] = longest.get("take_profit_hit")
    rec["stop_loss_hit"] = longest.get("stop_loss_hit")
    rec["eval_date"] = longest.get("eval_date")
    rec["days_held"] = longest.get("days_held")
    rec["latest_close"] = longest.get("latest_close")
    return rec


def _pct(hit: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(hit * 100.0 / total, 2)


def _summarize(rows: list[dict[str, Any]], eval_windows: tuple[int, ...]) -> dict[str, Any]:
    window_metrics: dict[str, Any] = {}
    for d in eval_windows:
        k = _window_key(d)
        items = []
        for r in rows:
            ev = r.get("window_evaluations", {})
            if not isinstance(ev, dict):
                continue
            cur = ev.get(k)
            if isinstance(cur, dict) and cur.get("ready"):
                items.append(cur)

        direction_rows = [x for x in items if x.get("direction_hit") is not None]
        direction_hit = sum(1 for x in direction_rows if bool(x.get("direction_hit")))

        tp_rows = [x for x in items if x.get("take_profit_hit") is not None]
        tp_hit = sum(1 for x in tp_rows if bool(x.get("take_profit_hit")))

        sl_rows = [x for x in items if x.get("stop_loss_hit") is not None]
        sl_hit = sum(1 for x in sl_rows if bool(x.get("stop_loss_hit")))

        window_metrics[k] = {
            "evaluated_records": len(items),
            "pending_records": len(rows) - len(items),
            "direction_total": len(direction_rows),
            "direction_hit": direction_hit,
            "direction_win_rate_pct": _pct(direction_hit, len(direction_rows)),
            "take_profit_total": len(tp_rows),
            "take_profit_hit": tp_hit,
            "take_profit_hit_rate_pct": _pct(tp_hit, len(tp_rows)),
            "stop_loss_total": len(sl_rows),
            "stop_loss_hit": sl_hit,
            "stop_loss_hit_rate_pct": _pct(sl_hit, len(sl_rows)),
        }

    # 兼容旧展示字段，默认用 T+5
    base = window_metrics.get(_window_key(max(eval_windows)), {})
    return {
        "total_records": len(rows),
        "evaluated_records": base.get("evaluated_records", 0),
        "pending_records": base.get("pending_records", len(rows)),
        "direction_total": base.get("direction_total", 0),
        "direction_hit": base.get("direction_hit", 0),
        "direction_win_rate_pct": base.get("direction_win_rate_pct"),
        "take_profit_total": base.get("take_profit_total", 0),
        "take_profit_hit": base.get("take_profit_hit", 0),
        "take_profit_hit_rate_pct": base.get("take_profit_hit_rate_pct"),
        "stop_loss_total": base.get("stop_loss_total", 0),
        "stop_loss_hit": base.get("stop_loss_hit", 0),
        "stop_loss_hit_rate_pct": base.get("stop_loss_hit_rate_pct"),
        "window_days": list(eval_windows),
        "window_metrics": window_metrics,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def update_and_summarize_accuracy(
    stock_metrics: list[dict[str, Any]],
    llm_result: dict[str, Any],
    *,
    window_days: tuple[int, ...] | list[int] | None = None,
) -> dict[str, Any]:
    windows = _normalize_windows(window_days)
    rows = _load_history()
    rows = _append_today_predictions(rows, stock_metrics, llm_result)
    rows = [_evaluate_one(r, windows) for r in rows]
    _save_history(rows)
    return _summarize(rows, windows)
