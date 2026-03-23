from __future__ import annotations

from datetime import datetime
from typing import Any


def render_dashboard_html(
    stock_metrics: list[dict[str, Any]],
    llm_result: dict[str, Any],
) -> str:
    stock_map = {item["code"]: item for item in stock_metrics}

    rows_html = []
    for rec in llm_result.get("stocks", []):
        code = rec.get("code", "")
        data = stock_map.get(code, {})
        name = data.get("name")
        display_name = f"{name}({code})" if name else code
        rows_html.append(
            "<tr>"
            f"<td>{display_name}</td>"
            f"<td>{data.get('close', '-')}</td>"
            f"<td>{data.get('change_pct', '-')}%</td>"
            f"<td>{data.get('ma5', '-')}</td>"
            f"<td>{data.get('ma20', '-')}</td>"
            f"<td>{data.get('rsi14', '-')}</td>"
            f"<td>{data.get('vol_ratio5', '-')}</td>"
            f"<td>{rec.get('action', '-')}</td>"
            f"<td>{rec.get('confidence', '-')}</td>"
            f"<td>{rec.get('reason', '-')}</td>"
            f"<td>{rec.get('risk', '-')}</td>"
            "</tr>"
        )

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    table_html = "\n".join(rows_html) if rows_html else "<tr><td colspan='11'>无数据</td></tr>"

    return f"""
<html>
<head>
  <meta charset="utf-8"/>
  <style>
    body {{ font-family: Arial, sans-serif; color: #1f2937; }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    h1 {{ color: #111827; }}
    .card {{ background: #f9fafb; padding: 14px; border-radius: 8px; margin-bottom: 12px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px; text-align: left; }}
    th {{ background: #f3f4f6; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>沪A股自选股 - 每日决策仪表盘</h1>
    <div class="card">
      <strong>大盘观点：</strong> {llm_result.get("market_view", "无")}
      <br/>
      <strong>生成时间：</strong> {generated_at}
    </div>
    <table>
      <thead>
        <tr>
          <th>名称</th><th>收盘价</th><th>涨跌幅</th><th>MA5</th><th>MA20</th>
          <th>RSI14</th><th>量比(5)</th><th>建议</th><th>置信度</th><th>理由</th><th>风险</th>
        </tr>
      </thead>
      <tbody>
        {table_html}
      </tbody>
    </table>
    <div class="card">
      <strong>免责声明：</strong> 本项目仅限学习与研究用途，不构成任何投资建议。股市投资存在风险，入市请务必谨慎。作者对因使用本项目所引发的任何损失不承担责任。
    </div>
  </div>
</body>
</html>
""".strip()
