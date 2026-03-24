from __future__ import annotations

from datetime import date

import pandas as pd

_trading_dates: set[date] | None = None


def is_cn_trading_day(day: date | None = None) -> bool:
    """
    使用新浪交易日历判断是否为 A 股交易日。
    首次调用会拉取完整日历并缓存于进程内；失败时退化为「周一到周五」。
    """
    global _trading_dates
    d = day or date.today()
    if _trading_dates is None:
        try:
            import akshare as ak

            df = ak.tool_trade_date_hist_sina()
            out: set[date] = set()
            for x in df["trade_date"].tolist():
                if isinstance(x, date):
                    out.add(x)
                else:
                    out.add(pd.Timestamp(x).date())
            _trading_dates = out
        except Exception:
            return 0 <= d.weekday() < 5
    assert _trading_dates is not None
    return d in _trading_dates
