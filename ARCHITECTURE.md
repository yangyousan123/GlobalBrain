# GlobalBrain 系统架构图

```mermaid
flowchart LR
    %% ===== 分层子图 =====
    subgraph U["用户与触发层"]
        CLI["src/main.py<br/>CLI 参数 (--once / --schedule)"]
        SCH["APScheduler<br/>每日定时触发"]
        WL["watchlist.yaml<br/>自选股代码/名称"]
        ENV[".env / src/config.py<br/>运行配置加载"]
    end

    subgraph O["编排与业务层"]
        PIPE["run_pipeline()<br/>任务编排与流程控制"]
        VAL["validate_sh_a_stock()<br/>沪A代码校验"]
        AGG["指标聚合列表<br/>stock_metrics[]"]
    end

    subgraph D["行情数据层（多源回退）"]
        AK["AkShare<br/>主数据源"]
        STOOQ["Stooq CSV<br/>二级兜底"]
        YF1["yfinance 单股<br/>兜底源"]
        YFB["yfinance 批量补全<br/>失败代码补齐"]
        CACHE["cache/*.json<br/>本地缓存读写"]
        IND["技术指标计算<br/>MA5 / MA20 / RSI14 / 量比5"]
    end

    subgraph A["智能分析层"]
        DS["DeepSeekClient.analyze()<br/>LLM JSON 输出"]
        FB["fallback_analysis()<br/>规则引擎降级"]
    end

    subgraph P["展示与推送层"]
        DASH["render_dashboard_html()<br/>HTML 决策仪表盘"]
        MAIL["send_html_email()<br/>SMTP SSL 发送"]
        USER["收件人邮箱<br/>每日报告接收"]
    end

    %% ===== 主流程 =====
    CLI --> PIPE
    SCH --> PIPE
    WL --> PIPE
    ENV --> PIPE
    PIPE --> VAL
    VAL --> AK
    AK --> IND
    IND --> AGG

    %% ===== 数据层回退链 =====
    AK -.失败.-> STOOQ
    STOOQ -.失败.-> YF1
    YF1 -.失败.-> CACHE
    AK -.部分失败代码.-> YFB
    YFB --> AGG
    IND --> CACHE

    %% ===== 分析层 =====
    AGG --> DS
    DS -.调用异常.-> FB
    AGG --> FB
    DS --> DASH
    FB --> DASH

    %% ===== 输出层 =====
    DASH --> MAIL
    MAIL --> USER

    %% ===== 样式（圆角 + 分区色彩）=====
    classDef rounded rx:14,ry:14,stroke-width:1.4px;

    classDef cUser fill:#E8F4FF,stroke:#4A90E2,color:#0B3A66;
    classDef cOrch fill:#EAFBEA,stroke:#39A96B,color:#1D5E39;
    classDef cData fill:#FFF5E6,stroke:#F5A623,color:#6A4300;
    classDef cAI fill:#F4ECFF,stroke:#8B5CF6,color:#432874;
    classDef cOut fill:#FFEFF4,stroke:#E75480,color:#6B1E35;

    class CLI,SCH,WL,ENV cUser,rounded;
    class PIPE,VAL,AGG cOrch,rounded;
    class AK,STOOQ,YF1,YFB,CACHE,IND cData,rounded;
    class DS,FB cAI,rounded;
    class DASH,MAIL,USER cOut,rounded;

    style U fill:#F5FAFF,stroke:#BBDDFB,stroke-width:1.2px,rx:18,ry:18
    style O fill:#F3FFF3,stroke:#BEECC8,stroke-width:1.2px,rx:18,ry:18
    style D fill:#FFF9F0,stroke:#FFD79A,stroke-width:1.2px,rx:18,ry:18
    style A fill:#FAF5FF,stroke:#D9C2FF,stroke-width:1.2px,rx:18,ry:18
    style P fill:#FFF4F7,stroke:#FFC4D5,stroke-width:1.2px,rx:18,ry:18
```

## 说明

- 主入口由 `src/main.py` 驱动：支持立即执行和定时任务两种模式。
- 行情获取以 `AkShare` 为主，失败后按 `Stooq -> yfinance -> 本地缓存` 回退，并在末尾对失败股票做 `yfinance` 批量补齐。
- 分析优先走 `DeepSeek`，异常时自动切换 `fallback_analysis()` 规则引擎，保证可用性。
- 输出统一汇总到 HTML 仪表盘，再通过 SMTP 推送至收件人邮箱。
