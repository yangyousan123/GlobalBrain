# GlobalBrain

Stock Watchlist Intelligent Analysis System

A Python + DeepSeek large language model-based system that automatically analyzes Shanghai A-share watchlists daily and delivers a "Decision Dashboard" via email.

## Features

- Supports Shanghai A-share code validation (e.g., `600xxx`, `601xxx`, `688xxx`)
- Fetches daily candlestick data using `akshare`
- Calculates MA5 / MA20 / RSI14 / Volume Ratio (5-day)
- Calls DeepSeek to generate stock-specific recommendations (Buy / Hold / Reduce)
- Automatically falls back to a rule-based engine in case of failure
- Sends an HTML decision dashboard to email via SMTP
- Supports daily scheduled execution

## Quick Start

1. Install dependencies

```bash
pip install -r requirements.txt
```

2. Configure environment variables

```bash
copy .env.example .env
```

Edit `.env`:

- `DEEPSEEK_API_KEY`: DeepSeek API Key
- `SMTP_*`: Email server configuration (it is recommended to use an authorization code)
- `MAIL_TO`: Use commas to separate multiple recipients
- `RUN_TIME`: Daily execution time in `HH:MM` format

3. Configure watchlist

Edit `watchlist.yaml` to include only Shanghai A-share six-digit codes:

```yaml
watchlist:
  - "600519"
  - "601318"
  - "688981"
```

4. Run

Execute immediately once:

```bash
python main.py --once
```

Run on a daily schedule (default):

```bash
python main.py --schedule
```

## Recommended Deployment

- Windows Task Scheduler: Run `python main.py --schedule` at startup
- Or use Linux `systemd` / `supervisor` as a daemon
- It is recommended to trigger after market close on trading days (e.g., `18:30`)

## Disclaimer

This system is for research and decision support purposes only and does not constitute investment advice. Please make independent judgments based on your risk tolerance.