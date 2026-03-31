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


def _e(s: Any) -> str:
    if s is None:
        return ""
    return html.escape(str(s), quote=True)


def _first_line(text: str | None, max_len: int = 200) -> str:
    if not text or not str(text).strip():
        return ""
    line = str(text).strip().splitlines()[0].strip()
    if len(line) > max_len:
        return line[: max_len - 1] + "…"
    return line


def _checklist_items(rec: dict[str, Any]) -> tuple[list[str], list[str]]:
    """返回 (利好/中性要点, 风险要点) 基于 checklist status。"""
    cl = rec.get("checklist") or []
    good: list[str] = []
    bad: list[str] = []
    if not isinstance(cl, list):
        return good, bad
    for it in cl:
        if not isinstance(it, dict):
            continue
        item = str(it.get("item", "")).strip()
        status = str(it.get("status", "")).strip()
        if not item:
            continue
        line = f"{item}（{status}）"
        if status == "满足":
            good.append(line)
        elif status in ("注意", "不满足"):
            bad.append(line)
        else:
            good.append(line)
    return good, bad


def _action_rating_label(action: str, ma_label: str) -> str:
    a = (action or "观察").strip()
    m = (ma_label or "震荡").strip()
    if a == "买入":
        return f"{a} | {m}"
    if a == "减仓":
        return f"{a} | {m}"
    return f"{a} | {m}"


def _suggest_flat_no_position(action: str, reason: str) -> str:
    a = (action or "观察").strip()
    if a == "买入":
        return "可逢低分批关注，严格设止损；勿追高。"
    if a == "减仓":
        return "趋势偏弱，空仓者暂不新开仓，等待企稳信号。"
    return "等待方向明朗或关键位突破/回踩后再考虑。"


def _suggest_holding(action: str, risk: str) -> str:
    a = (action or "观察").strip()
    if a == "买入":
        return "可持有并跟踪止盈止损；若跌破纪律位则减仓。"
    if a == "减仓":
        return "建议逢高减仓或控制仓位，防范回撤扩大。"
    return "控制仓位观望，按计划执行止盈止损。"


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
        body = _e(str(digest)[:4000])
        blocks.append(
            f'<div style="margin-bottom:10px;"><strong>{_e(title)}</strong>'
            f'<pre style="white-space:pre-wrap;font-size:13px;margin:6px 0 0 0;">{body}</pre></div>'
        )
    if not blocks:
        return ""
    inner = "".join(blocks)
    return (
        f'<div class="card"><h2 style="font-size:17px;margin:0 0 8px 0;">'
        f'新闻摘要（多源检索）</h2><p style="font-size:13px;color:#6b7280;margin:0 0 8px 0;">'
        f'以下为联网检索摘要，仅供参考，请交叉验证来源与时效。</p>{inner}</div>'
    )


def _fmt_pct(v: Any) -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v):.2f}%"
    except Exception:
        return "-"


def _fmt_num(v: Any) -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v):.2f}"
    except Exception:
        return "-"


def _accuracy_section(summary: dict[str, Any] | None) -> str:
    if not summary:
        return ""
    w_map = summary.get("window_metrics")
    if isinstance(w_map, dict) and w_map:
        rows: list[str] = []
        days = summary.get("window_days") if isinstance(summary.get("window_days"), list) else []
        keys = [f"T+{int(d)}" for d in days if isinstance(d, int) or (isinstance(d, str) and str(d).isdigit())]
        if not keys:
            keys = ["T+1", "T+3", "T+5"]
        for key in keys:
            item = w_map.get(key)
            if not isinstance(item, dict):
                continue
            rows.append(
                f'{key}：方向 {item.get("direction_hit", 0)}/{item.get("direction_total", 0)}'
                f'（{_fmt_pct(item.get("direction_win_rate_pct"))}），'
                f'止盈 {item.get("take_profit_hit", 0)}/{item.get("take_profit_total", 0)}'
                f'（{_fmt_pct(item.get("take_profit_hit_rate_pct"))}），'
                f'止损 {item.get("stop_loss_hit", 0)}/{item.get("stop_loss_total", 0)}'
                f'（{_fmt_pct(item.get("stop_loss_hit_rate_pct"))}），'
                f'样本 {item.get("evaluated_records", 0)}'
            )
        detail = "<br/>".join(rows) if rows else "暂无窗口化评估样本"
        return (
            '<div class="card"><h2 style="font-size:17px;margin:0 0 8px 0;">历史分析准确率（固定窗口）</h2>'
            f'<div style="font-size:14px;line-height:1.8;">{detail}<br/>'
            f'总样本：{summary.get("total_records", 0)}，更新时间：{_e(summary.get("updated_at", "-"))}'
            f"</div></div>"
        )
    return (
        '<div class="card"><h2 style="font-size:17px;margin:0 0 8px 0;">历史分析准确率</h2>'
        f'<div style="font-size:14px;line-height:1.8;">'
        f'方向胜率：{summary.get("direction_hit", 0)}/{summary.get("direction_total", 0)}'
        f'（{_fmt_pct(summary.get("direction_win_rate_pct"))}）<br/>'
        f'止盈命中率：{summary.get("take_profit_hit", 0)}/{summary.get("take_profit_total", 0)}'
        f'（{_fmt_pct(summary.get("take_profit_hit_rate_pct"))}）<br/>'
        f'止损命中率：{summary.get("stop_loss_hit", 0)}/{summary.get("stop_loss_total", 0)}'
        f'（{_fmt_pct(summary.get("stop_loss_hit_rate_pct"))}）<br/>'
        f'样本：已评估 {summary.get("evaluated_records", 0)}，待评估 {summary.get("pending_records", 0)}，'
        f'总计 {summary.get("total_records", 0)}'
        f"</div></div>"
    )


def _overview_bullets(
    data: dict[str, Any],
    rec: dict[str, Any],
) -> str:
    digest = data.get("news_digest")
    sentiment = _first_line(str(digest) if digest else None) or "暂无联网摘要，以下以技术面为主。"

    trend = data.get("ma_trend")
    exp_parts = []
    if trend == "bull":
        exp_parts.append("均线呈多头形态，趋势偏多预期（非业绩预告）。")
    elif trend == "bear":
        exp_parts.append("均线呈空头形态，趋势偏弱预期（非业绩预告）。")
    else:
        exp_parts.append("均线震荡，方向待确认（非业绩预告）。")
    rsi = data.get("rsi14")
    if rsi is not None:
        try:
            exp_parts.append(f"RSI14≈{float(rsi):.1f}。")
        except Exception:
            pass
    earnings_line = "".join(exp_parts)

    risk_lines: list[str] = []
    rn = data.get("risk_notes") or []
    if isinstance(rn, list):
        for x in rn:
            if x:
                risk_lines.append(str(x))
    rtxt = rec.get("risk")
    if rtxt and str(rtxt).strip():
        risk_lines.append(str(rtxt).strip())
    _, checklist_bad = _checklist_items(rec)
    risk_lines.extend(checklist_bad)
    if not risk_lines:
        risk_lines.append("暂无明显规则层警报。")

    good_lines, _ = _checklist_items(rec)
    reason = rec.get("reason")
    if reason and str(reason).strip() and rec.get("action") == "买入":
        good_lines.insert(0, _first_line(str(reason), 120))
    if not good_lines:
        good_lines.append("暂无以 checklist 归纳的利好要点。")

    bar_date = data.get("date") or "-"
    latest = _first_line(str(digest) if digest else None, 160)
    if not latest:
        latest = "无摘要，请查看下方「新闻摘要」区块。"

    def ul(items: list[str]) -> str:
        lis = "".join(f"<li>{_e(it)}</li>" for it in items[:8])
        return f"<ul style='margin:4px 0 0 18px;padding:0;'>{lis}</ul>"

    return (
        f'<div class="ov-line">☁️ <strong>舆情情绪</strong> {_e(sentiment)}</div>'
        f'<div class="ov-line">📊 <strong>业绩预期</strong> {_e(earnings_line)}</div>'
        f'<div class="ov-line">🚨 <strong>风险警报</strong>{ul(risk_lines)}</div>'
        f'<div class="ov-line">✨ <strong>利好催化</strong>{ul(good_lines)}</div>'
        f'<div class="ov-line">📣 <strong>最新动态</strong> [{_e(bar_date)}] {_e(latest)}</div>'
    )


def _render_stock_card(
    data: dict[str, Any],
    rec: dict[str, Any],
) -> str:
    code = rec.get("code", "")
    mk = rec.get("market") or MARKET_CN_SH
    if data.get("market"):
        mk = data.get("market") or mk
    name = data.get("name")
    m_label = _market_display(str(mk))
    title = f"{name}（{code}）" if name else str(code)
    subtitle = f"{m_label} · 代码 {code}"

    ma_label = data.get("ma_alignment_label", "-")
    action = str(rec.get("action", "-"))
    confidence = rec.get("confidence", "-")
    reason = rec.get("reason") or "—"
    risk = rec.get("risk") or "—"
    buy_z = rec.get("buy_zone", "-") or "-"
    sl = rec.get("stop_loss", "-") or "-"
    tp = rec.get("take_profit", "-") or "-"

    rating = _action_rating_label(action, str(ma_label))
    bar_date = data.get("date") or "-"

    close_v = data.get("close")
    prev_v = data.get("prev_close")
    chg_amt = None
    if close_v is not None and prev_v is not None:
        try:
            chg_amt = round(float(close_v) - float(prev_v), 2)
        except Exception:
            chg_amt = None

    overview = _overview_bullets(data, rec)

    op_flat = _suggest_flat_no_position(action, str(reason))
    op_hold = _suggest_holding(action, str(risk))

    checklist_good, checklist_bad = _checklist_items(rec)
    cl_html = ""
    if checklist_good or checklist_bad:
        parts = []
        if checklist_good:
            parts.append("<strong>检查项（偏积极）</strong><ul>" + "".join(f"<li>{_e(x)}</li>" for x in checklist_good[:6]) + "</ul>")
        if checklist_bad:
            parts.append("<strong>检查项（需留意）</strong><ul>" + "".join(f"<li>{_e(x)}</li>" for x in checklist_bad[:6]) + "</ul>")
        cl_html = '<div style="margin-top:10px;font-size:14px;">' + "".join(parts) + "</div>"

    return f"""
<div class="stock-card">
  <table class="stock-head" cellpadding="0" cellspacing="0" border="0" width="100%">
    <tr>
      <td class="stock-dot-cell" valign="top" width="24">●</td>
      <td valign="top">
        <div class="stock-title">{_e(title)}</div>
        <div class="stock-sub">{_e(subtitle)}</div>
      </td>
    </tr>
  </table>
  <hr class="stock-hr"/>

  <div class="section-title">重要信息速览</div>
  <div class="overview-block">{overview}</div>

  <div class="section-title">📌 核心结论</div>
  <div class="core-block">
    <div class="rating-line"><span class="stock-dot-sm">●</span> <strong>{_e(rating)}</strong>
      <span class="conf-tag">置信度 {_e(confidence)}</span></div>
    <div class="quote-bar">{_e(_first_line(str(reason), 500))}</div>
    <div class="time-hint">⏰ 基准行情日：<strong>{_e(bar_date)}</strong>（邮件生成时可能已跨日，请以实盘为准）</div>
  </div>

  <div class="section-title">操作建议</div>
  <table class="mini-table">
    <thead><tr><th>持仓情况</th><th>操作建议</th></tr></thead>
    <tbody>
      <tr><td>📰 空仓者</td><td>{_e(op_flat)}</td></tr>
      <tr><td>💼 持仓者</td><td>{_e(op_hold)}</td></tr>
    </tbody>
  </table>
  <div class="levels-line"><strong>买点 / 止损 / 目标：</strong>
    买 {_e(buy_z)} ｜ 止 {_e(sl)} ｜ 标 {_e(tp)}</div>

  <div class="section-title">📈 当日行情与技术指标</div>
  <table class="data-table">
    <thead>
      <tr>
        <th>收盘</th><th>昨收</th><th>涨跌幅</th><th>涨跌额</th>
        <th>MA5</th><th>MA10</th><th>MA20</th>
        <th>乖离%(MA20)</th><th>RSI14</th><th>量比(5)</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>{_fmt_num(close_v)}</td>
        <td>{_fmt_num(prev_v)}</td>
        <td>{_fmt_pct(data.get("change_pct"))}</td>
        <td>{_fmt_num(chg_amt)}</td>
        <td>{_fmt_num(data.get("ma5"))}</td>
        <td>{_fmt_num(data.get("ma10"))}</td>
        <td>{_fmt_num(data.get("ma20"))}</td>
        <td>{_fmt_pct(data.get("bias_ma20_pct"))}</td>
        <td>{_fmt_num(data.get("rsi14"))}</td>
        <td>{_fmt_num(data.get("vol_ratio5"))}</td>
      </tr>
    </tbody>
  </table>
  <table class="data-table sub-row">
    <tbody>
      <tr>
        <th>均线形态</th><td>{_e(ma_label)}</td>
        <th>乖离预警</th><td>{'是' if data.get('bias_alert') else '否'}</td>
        <th>行情来源</th><td>多源聚合（AkShare / Stooq / yfinance 等）</td>
      </tr>
    </tbody>
  </table>
  {cl_html}
</div>
""".strip()


def render_dashboard_html(
    stock_metrics: list[dict[str, Any]],
    llm_result: dict[str, Any],
    *,
    accuracy_summary: dict[str, Any] | None = None,
) -> str:
    stock_map = {
        _metric_key(str(item["code"]), item.get("market")): item for item in stock_metrics
    }

    cards: list[str] = []
    for rec in llm_result.get("stocks", []):
        code = rec.get("code", "")
        mk = rec.get("market") or MARKET_CN_SH
        data = _lookup_metric(stock_map, str(code), str(mk))
        cards.append(_render_stock_card(data, rec))

    stocks_html = "\n".join(cards) if cards else '<div class="card">暂无个股分析数据</div>'

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    accuracy_html = _accuracy_section(accuracy_summary)
    news_html = _news_digest_section(stock_metrics)

    return f"""
<html>
<head>
  <meta charset="utf-8"/>
  <style>
    body {{ font-family: "Segoe UI", Arial, sans-serif; color: #1f2937; font-size: 19px; line-height: 1.5; }}
    .container {{ max-width: 720px; margin: 0 auto; padding: 8px; }}
    h1 {{ color: #111827; font-size: 22px; margin-bottom: 12px; }}
    .card {{ background: #f9fafb; padding: 14px; border-radius: 10px; margin-bottom: 14px; border: 1px solid #e5e7eb; }}
    .stock-card {{
      background: #ffffff;
      border: 1px solid #e5e7eb;
      border-radius: 12px;
      padding: 16px 18px;
      margin-bottom: 20px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }}
    .stock-head {{ width: 100%; }}
    .stock-dot-cell {{ color: #f59e0b; font-size: 14px; line-height: 1.6; padding-right: 8px; }}
    .stock-dot-sm {{ color: #f59e0b; font-size: 11px; margin-right: 4px; }}
    .stock-title {{ font-size: 20px; font-weight: 700; color: #111827; }}
    .stock-sub {{ font-size: 14px; color: #6b7280; margin-top: 2px; }}
    .stock-hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 12px 0; }}
    .section-title {{ font-size: 16px; font-weight: 700; margin: 14px 0 8px 0; color: #374151; }}
    .overview-block {{ font-size: 15px; color: #374151; }}
    .ov-line {{ margin-bottom: 10px; }}
    .core-block {{ font-size: 15px; }}
    .rating-line {{ margin-bottom: 8px; }}
    .conf-tag {{ margin-left: 8px; font-size: 13px; color: #6b7280; font-weight: normal; }}
    .quote-bar {{
      border-left: 4px solid #d1d5db;
      padding: 8px 12px;
      margin: 10px 0;
      background: #f9fafb;
      color: #374151;
    }}
    .time-hint {{ font-size: 14px; color: #6b7280; }}
    .mini-table {{ border-collapse: collapse; width: 100%; font-size: 15px; margin-top: 6px; }}
    .mini-table th, .mini-table td {{ border: 1px solid #e5e7eb; padding: 10px 12px; text-align: left; vertical-align: top; }}
    .mini-table th {{ background: #f3f4f6; width: 28%; }}
    .levels-line {{ margin-top: 10px; font-size: 15px; color: #374151; }}
    .data-table {{ border-collapse: collapse; width: 100%; font-size: 14px; margin-top: 6px; table-layout: fixed; }}
    .data-table th, .data-table td {{ border: 1px solid #e5e7eb; padding: 8px 6px; text-align: center; word-break: break-all; }}
    .data-table th {{ background: #f3f4f6; font-weight: 600; }}
    .data-table.sub-row th {{ width: 22%; background: #f3f4f6; text-align: left; padding-left: 10px; }}
    .data-table.sub-row td {{ text-align: left; padding-left: 10px; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>自选股 · 每日决策仪表盘</h1>
    <div class="card">
      <strong>大盘观点：</strong> {_e(llm_result.get("market_view", "无"))}
      <br/>
      <strong>生成时间：</strong> {_e(generated_at)}
    </div>
    {accuracy_html}
    {stocks_html}
    {news_html}
    <div class="card">
      <strong>免责声明：</strong> 本项目仅限学习与研究用途，不构成任何投资建议。股市投资存在风险，入市请务必谨慎。作者对因使用本项目所引发的任何损失不承担责任。
    </div>
  </div>
</body>
</html>
""".strip()
