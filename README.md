# GlobalBrain

股票智能分析系统（沪A / 港股 / 美股）。

每天自动拉取自选股行情、生成策略建议、汇总新闻摘要、输出 HTML 决策仪表盘并推送通知。

## 最小可运行配置（复制即用）

将以下内容写入 `.env`（按你的实际账号替换）：

```env
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-chat
NOTIFY_CHANNELS=email
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=your_email@qq.com
SMTP_PASSWORD=your_smtp_auth_code
MAIL_FROM=your_email@qq.com
MAIL_TO=receiver@example.com
```

## 系统架构图

![](images/architecture.png)

**说明**

- 本项目以 `run_analysis_pipeline()` 为中心，将行情、新闻、LLM、评估、推送串成单条可降级链路。
- 数据与模型层均是“多源 + 回退”设计，目标是优先保证每日报告可产出。
- 新闻与模型都支持“优先级 / key 池 / fallback”策略，适合长期自动化运行场景。

## 核心能力

- **多市场支持**：`cn_sh`（沪A）、`hk`（港股）、`us`（美股）
- **行情多源回退**：
  - 沪A：AkShare 主链，失败回退 Stooq / yfinance / 本地缓存
  - 港股：AkShare -> Stooq -> yfinance
  - 美股：Stooq -> yfinance
- **LLM 统一接入 LiteLLM**：
  - 支持 OpenAI 兼容、DeepSeek、Claude、Gemini、通义千问等
  - 支持多模型 fallback、多 API Key 负载均衡
  - 支持按 provider 分组 key 池（避免不同厂商 key 混用）
- **新闻多源检索**：
  - Tavily、SerpAPI、Brave、Bocha、MiniMax
  - 可按优先级自动降级
- **策略输出与降级**：
  - LLM 正常时输出结构化建议（买入/观察/减仓）
  - 模型异常自动降级 `fallback_analysis`
- **历史准确率评估**：
  - 自动记录建议并回测
  - 支持固定窗口（如 `T+1/T+3/T+5`，可通过 `.env` 自定义）
  - 输出方向胜率、止盈命中率、止损命中率
- **通知与展示**：
  - HTML 决策仪表盘
  - 支持 `email / feishu / wechat / telegram / discord / dingtalk`

## 快速开始

### 1) 安装依赖

```bash
pip install -r requirements.txt
```

### 2) 配置环境变量

```bash
copy .env.example .env
```

至少配置以下关键项：

- `OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY`（建议使用 `LLM_API_KEYS`）
- `OPENAI_MODEL`（或 `LLM_MODEL`）
- `SMTP_*` 与 `MAIL_TO`（若使用邮件推送）
- `RUN_TIME`（定时执行时间）

### 3) 配置自选股

`watchlist.yaml` 示例：

```yaml
watchlist:
  - code: "600519"
    name: "贵州茅台"
    market: cn_sh
  - code: "00700"
    name: "腾讯控股"
    market: hk
  - code: "AAPL"
    name: "Apple"
    market: us
```

说明：

- 沪A：6 位数字（如 `600519`）
- 港股：建议 5 位数字字符串（如 `00700`）
- 美股：ticker（如 `AAPL`、`BRK-B`）

### 4) 运行

立即执行一次：

```bash
python -m src --once
```

定时运行：

```bash
python -m src --schedule
```

常用参数：

- `--watchlist <path>`：指定自选股文件路径
- `--force-run`：跳过交易日检查（非交易日也执行）

## 推送效果

![](images/email01.png)

![](images/email02.png)

![](images/email03.png)

## 关键配置说明（.env）

### LLM（LiteLLM 统一调用）

- `OPENAI_MODEL` / `LLM_FALLBACK_MODELS`：主模型与回退模型链
- `LLM_API_KEYS`：通用多 key（逗号分隔）
- provider 分组 key 池（可选）：
  - `OPENAI_API_KEYS`
  - `ANTHROPIC_API_KEYS`
  - `GEMINI_API_KEYS`
  - `QWEN_API_KEYS`
  - `DEEPSEEK_API_KEYS`

### 新闻检索

- `NEWS_PROVIDER_ORDER=tavily,serpapi,brave,bocha,minimax`
- 对应 key：
  - `TAVILY_API_KEY`
  - `SERPAPI_API_KEY`
  - `BRAVE_API_KEY`
  - `BOCHA_API_KEY`
  - `MINIMAX_API_KEY`

### 准确率评估

- `ACCURACY_WINDOWS=1,3,5`
  - 按固定交易日窗口评估，避免“持有越久越容易命中”的偏差

## 项目入口

- Python 模块入口：`python -m src`
- 运行逻辑入口：`src/app/main.py`

## 建议部署

- Windows：任务计划程序执行 `python -m src --schedule`
- Linux：`systemd` / `supervisor` 常驻
- 建议收盘后运行（并根据市场时区调整 `TIMEZONE` 与 `RUN_TIME`）

## License

- MIT License


- Copyright (c) 2026 杨友三

## 联系与合作

- Email：yangyousan@hotmail.com

## 免责声明

本项目仅限学习与研究用途，不构成任何投资建议。股市投资存在风险，入市请务必谨慎。作者对因使用本项目所引发的任何损失不承担责任。
