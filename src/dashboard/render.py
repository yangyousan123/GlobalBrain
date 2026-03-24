from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from ..data.markets import MARKET_CN_SH, MARKET_HK, MARKET_US


def _market_display(market: str | None) -> str:
    m = market or MARKET_CN_SH
    if m == MARKET_HK:
        return "港股"
    if m == MARKET_US:
        return "美股"
    return "沪A"


def _metric_key(code: str, market: str | None) -> tuple[str, str]:
    m = market or MARKET_CN_SH
    return (str(code), m)


def _lookup_metric(
    stock_map: dict[tuple[str, str], dict[str, Any]],
    code: str,
    market: str | None,
) -> dict[str, Any]:
    key = _metric_key(str(code), market)
    data = stock_map.get(key)
    if data:
        return data
    for k, v in stock_map.items():
        if k[0] == str(code):
            return v
    return {}


def _fmt_checklist(rec: dict[str, Any]) -> str:
    cl = rec.get("checklist") or []
    if not isinstance(cl, list):
        return "-"
    parts: list[str] = []
    for it in cl:
        if isinstance(it, dict):
            parts.append(f"{it.get('item', '')}:{it.get('status', '')}")
    return "; ".join(parts) if parts else "-"


def _news_digest_section(stock_metrics: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for m in stock_metrics:
        digest = m.get("news_digest")
        if not digest or not str(digest).strip():
            continue
        code = m.get("code", "")
        mk = m.get("market") or MARKET_CN_SH
        name = m.get("name")
        title = f"{_market_display(str(mk))} {name}({code})" if name else f"{_market_display(str(mk))} {code}"
        body = html.escape(str(digest)[:4000])
        blocks.append(
            f'<div style="margin-bottom:10px;"><strong>{html.escape(str(title))}</strong>'
            f'<pre style="white-space:pre-wrap;font-size:11px;margin:6px 0 0 0;">{body}</pre></div>'
        )
    if not blocks:
        return ""
    inner = "".join(blocks)
    return (
        f'<div class="card"><h2 style="font-size:14px;margin:0 0 8px 0;">'
        f'Tavily 新闻摘要</h2><p style="font-size:11px;color:#6b7280;margin:0 0 8px 0;">'
        f'以下为联网检索摘要，仅供参考，请交叉验证来源与时效。</p>{inner}</div>'
    )


def render_dashboard_html(
    stock_metrics: list[dict[str, Any]],
    llm_result: dict[str, Any],
) -> str:
    stock_map = {
        _metric_key(str(item["code"]), item.get("market")): item for item in stock_metrics
    }

    rows_html = []
    for rec in llm_result.get("stocks", []):
        code = rec.get("code", "")
        mk = rec.get("market") or MARKET_CN_SH
        data = _lookup_metric(stock_map, str(code), str(mk))
        if data.get("market"):
            mk = data.get("market") or mk
        name = data.get("name")
        m_label = _market_display(str(mk))
        display_name = f"{name}({code})" if name else code
        bias_pct = data.get("bias_ma20_pct")
        bias_str = f"{bias_pct}%" if bias_pct is not None else "-"
        ma_label = data.get("ma_alignment_label", "-")
        alert = "是" if data.get("bias_alert") else "否"
        buy_z = rec.get("buy_zone", "-") or "-"
        sl = rec.get("stop_loss", "-") or "-"
        tp = rec.get("take_profit", "-") or "-"
        levels = f"买:{buy_z} | 止:{sl} | 标:{tp}"
        rows_html.append(
            "<tr>"
            f"<td>{m_label}</td>"
            f"<td>{display_name}</td>"
            f"<td>{data.get('close', '-')}</td>"
            f"<td>{data.get('change_pct', '-')}%</td>"
            f"<td>{data.get('ma5', '-')}</td>"
            f"<td>{data.get('ma10', '-')}</td>"
            f"<td>{data.get('ma20', '-')}</td>"
            f"<td>{bias_str}</td>"
            f"<td>{data.get('rsi14', '-')}</td>"
            f"<td>{data.get('vol_ratio5', '-')}</td>"
            f"<td>{ma_label}</td>"
            f"<td>{alert}</td>"
            f"<td>{rec.get('action', '-')}</td>"
            f"<td>{rec.get('confidence', '-')}</td>"
            f"<td>{levels}</td>"
            f"<td>{rec.get('reason', '-')}</td>"
            f"<td>{rec.get('risk', '-')}</td>"
            f"<td>{_fmt_checklist(rec)}</td>"
            "</tr>"
        )

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    table_html = "\n".join(rows_html) if rows_html else "<tr><td colspan='18'>无数据</td></tr>"
    news_html = _news_digest_section(stock_metrics)

    return f"""
<html>
<head>
  <meta charset="utf-8"/>
  <style>
    body {{ font-family: Arial, sans-serif; color: #1f2937; }}
    .container {{ max-width: 1400px; margin: 0 auto; }}
    h1 {{ color: #111827; }}
    .card {{ background: #f9fafb; padding: 14px; border-radius: 8px; margin-bottom: 12px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 6px; text-align: left; }}
    th {{ background: #f3f4f6; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>自选股 - 每日决策仪表盘</h1>
    <div class="card">
      <strong>大盘观点：</strong> {llm_result.get("market_view", "无")}
      <br/>
      <strong>生成时间：</strong> {generated_at}
    </div>
    <table>
      <thead>
        <tr>
          <th>市场</th><th>名称</th><th>收盘</th><th>涨跌幅</th><th>MA5</th><th>MA10</th><th>MA20</th>
          <th>乖离%(MA20)</th><th>RSI14</th><th>量比(5)</th><th>均线</th><th>乖离预警</th>
          <th>建议</th><th>置信度</th><th>买点/止损/目标</th><th>理由</th><th>风险</th><th>检查清单</th>
        </tr>
      </thead>
      <tbody>
        {table_html}
      </tbody>
    </table>
    {news_html}
    <div class="card">
      <strong>免责声明：</strong> 本项目仅限学习与研究用途，不构成任何投资建议。股市投资存在风险，入市请务必谨慎。作者对因使用本项目所引发的任何损失不承担责任。
    </div>
  </div>
</body>
</html>
""".strip()
