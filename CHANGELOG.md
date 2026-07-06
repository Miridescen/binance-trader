# 策略变更日志

记录每次策略参数调整和重要改动，便于回溯和复盘。

## 2026-07-06

- **新增 8h 周期实盘策略 `real_trade_8h.py`（batch 隔离 + 组内 +10U 提前平仓）**
  - 方向：仅 **跌幅榜-空（无过滤）TOP10**，选股复用 `real_trade_4h.select_top10("跌幅榜")`
    （= 8h 虚拟盘 `跌幅榜-空（无过滤）` 选股逻辑：24h 量 ≥ 1000 万 U，涨跌幅升序取末 10 做空）
  - 开仓：每天 00:30 / 08:30 / 16:30，3x 杠杆 / 10U 保证金 / 名义 30U，限价 ladder + 市价兜底
  - 平仓（**与 4h 不同**）：
    - **batch =（open_anchor, side）**，用 DB 记录的 `entry_price` + 实时标记价自算合计浮盈（税前，做空），各 batch 互不干扰
    - 合计浮盈 ≥ **+10U** → 整组立即市价平（`close_reason=组内+10u`）
    - 到 8h 窗口末前 10 分钟仍未触发 → 定时平（限价 ladder + 市价兜底，`close_reason=8h_timed`）
  - 数据：新表 `open_log_8h`（结构同 `open_log_4h`），成交后回填真实 commission / funding
  - 安全开关：环境变量 `REAL_8H_LIVE=1` 才真正下单；未设置为观察模式（只选币/打印/算浮盈，不下单不写库）
  - 服务：`deploy/binance-real-8h.service`（默认带 `REAL_8H_LIVE=1`）
  - 前端：Dashboard 改为展示 8h 实盘（`/api/open_log_8h`），隐藏原 4h 实盘板块
  - 说明：4h 实盘（`binance-real-4h`）此前已停（disabled，最后成交 2026-06-10），8h 复用同一实盘账户

## 2026-06-03

- **新增 `basis/` 子项目（基差套利 Phase 1：数据采集）**
  - 完全独立于主项目流程，不污染 trader.db / open_top_shorts / real_trade_4h
  - 独立 SQLite 数据库 `basis/basis.db`（永久保留所有快照）
  - `basis/monitor.py`：每 15 分钟拉一次 BTC/ETH 现货 + 当季/次季合约价
    - 当前监控 4 个合约：BTCUSDT_260626 / BTCUSDT_260925 / ETHUSDT_260626 / ETHUSDT_260925
    - 计算 basis / basis_pct / annualized_pct
  - `basis/db.py`：独立 db 模块；basis_snapshot 表
  - `basis/start_basis.sh`：注册 systemd 服务 `binance-basis-monitor`
  - 共享：服务器 Python 环境、git 仓库、systemd（资源消耗近零）
  - 隔离：数据库文件、代码目录、日志、服务
  - 下一步：跑 1-2 周累积数据，看真实年化基差水平，再决定 Phase 2（回测）

## 2026-05-21（晚）

- **新增 4h 周期实盘策略 (`binance-real-4h`)**：与原 24h 策略并列，独立运行
  - 6 个开仓周期/天：00:30 / 04:30 / 08:30 / 12:30 / 16:30 / 20:30
  - 2 个方向：涨幅榜-空（无过滤）+ 跌幅榜-空（无过滤），各 TOP10
  - 仅过滤 24h 交易量 ≥ 1000 万 USDT，沿用 3x 杠杆 / 10U/单
  - 全部 4h 定平，没有 +10u 提前止盈
- **开仓机制**：限价单 + 10 分钟超时市价兜底
  - XX:30:00 拉两榜 TOP10 → 按标记价挂限价 SELL
  - XX:32 / 34 / 36 / 38 撤单换价重挂（5 轮限价，跟随最新标记价）
  - XX:40 仍未成交 → 市价兜底
- **平仓机制**：提前 10 分钟限价平仓 + 市价兜底
  - XX:20:00 对所有持仓挂限价 BUY (reduceOnly)
  - XX:22 / 24 / 26 / 28 撤单换价重挂
  - XX:29 强制市价兜底，确保 XX:30 前账户清空
- **数据表 `open_log_4h`**（精简版）：开仓时间、平仓时间、币种、方向、开仓价、平仓价、数量、PnL、ROE、开/平手续费、资金费、close_reason
  - **所有字段等实际成交后回填**，从 `/fapi/v1/userTrades` 取真实成交均价、`/fapi/v1/income` 取手续费和资金费，保证数据真实性
  - 不再记 change_pct / btc_pct / market_cap / funding_rate 等信号字段（保持表精简）
- **资金费收集**：通过 `/fapi/v1/income?incomeType=FUNDING_FEE` 按 symbol + [open_ms, close_ms] 区间累计
- **systemd 服务**：`binance-real-4h`，`bash start_real_4h.sh` 一键注册
- **代码**：`real_trade_4h.py` 独立程序，与 `open_top_shorts.py`（原 24h 实盘，当前 disabled）并行

## 2026-05-21（下午）

- **暂停实盘开仓**：`binance-strategy` 服务 systemctl stop + disable，不再开/平实盘
  - 所有虚拟盘（main / 4h / 8h / 12h）保留运行，作为观察对照
  - 当前 15 个空单已通过 `scripts/close_all_positions.py --execute` 一次性市价平仓
  - 平仓时浮盈 -0.97 USDT，close_reason='手工平仓'
- **新增 scripts/close_all_positions.py**：一次性手工平仓所有实盘持仓
  - 默认 dry-run，加 --execute 真平
  - 流程：拉 positionRisk → 市价平仓 → sleep 2s → FIFO 回填 open_log
  - 兜底：FIFO 找不到匹配（entry_price=NULL 的悬挂记录）时仅标 close_time + reason，避免本地与账户脱节

## 2026-05-21

- **移除 ROE 硬止损**：`monitor_positions.py` 不再监控 ROE 触发市价平仓
  - 触发原因：5-21 03:02 BSBUSDT 触发 ROE -200% 止损，币安平仓成功（亏 -29.30u）但因 open_log 中两条 BSBUSDT 记录 entry_price=NULL（开仓时未回填），`get_oldest_open_position` 的 `WHERE entry_price IS NOT NULL` 过滤导致 FIFO 匹配不到，**回写失败**——账户与本地 open_log 脱节，Dashboard 仍显示"持仓中"
  - 回测显示 ROE 止损对长期收益无显著正贡献（原 2026-04-28 灰度上线是 -200% 几乎不触发）
  - 手工修补：把 id=728 / id=747 两条悬挂记录 close_time 填为 2026-05-21 03:02:11，close_reason='ROE止损'
  - 代码改动：`monitor_positions.py` 移除 STOPLOSS_*、_do_stoploss、_market_close_one、_in_close_window、check_and_stoploss 等函数；保留持仓快照和报表逻辑
  - 不再需要的导入：`auth_post`, `is_hedge_mode`, `get_mark_price` 同步移除

## 2026-05-13（下午-第二轮）

- **真正大头：批量拉价**：`get_mark_price` 单币种调用改为 `get_all_mark_prices` 一次拉全市场
  - 起因：第一轮（5 分钟 + 错开）部署后 dashboard 仍 6-16 秒，因为单次 snapshot 里 80+ 仓位串行调用币安 API，单次快照 30-60 秒，CPU 持续被占
  - 新增 `binance_client.get_all_mark_prices()` 一次返回全市场 `{symbol: markPrice}`
  - 改 4 个服务的 `snapshot()` 和 `settle_expired()`：批量拉价一次，循环里读字典；去掉 sleep(0.03/0.05)
  - 预期：单次 snapshot 从 30-60 秒 → 1-2 秒，CPU 占用降 95%+

## 2026-05-13（下午）

- **降低 CPU 压力**：4 个模拟盘服务的快照频率从 2 分钟改为 5 分钟，并错开偏移
  - 起因：1 vCPU 服务器在 :30 开仓时刻 + 每分钟快照集中 → load 飙到 7+，dashboard 退化到 10-19 秒
  - 间隔：`SNAPSHOT_INTERVAL_MIN = 2 → 5`（数据库增长率也降 60%）
  - 偏移：主模拟盘 0 / 4h 1 / 8h 2 / 12h 3 分钟，slot_id 用 `(total_min - offset) // INTERVAL`
  - 预期：CPU 峰值从 100% 降到 ~25%，dashboard 回到秒级响应
  - 影响：+10u 触发判定延迟最多从 2 分钟变 5 分钟，对策略可忽略

## 2026-05-13

- **服务器加固**：955MB 内存机器，业务进程已 8 个，加防护
  - **加 1GB swap**（`/swapfile`）+ `vm.swappiness=10`，缓冲 OOM 风险
  - **日志轮转**：`logrotate.binance-trader.conf` + `scripts/setup_logrotate.sh`，每日轮转 / 超 10MB 立即轮转 / 保留 7 份压缩
  - **归档脚本**：`scripts/archive_old_details.py`，把 60 天前的 `*_detail` 表数据导出到 `archive/*.csv.gz` 并从主库删除（分批 DELETE 避免锁库；不自动 cron，需要时手动跑）
  - 详见 ssh 操作记录

## 2026-05-11

- **新增 8h / 12h 周期虚拟盘**：与 4h 模拟盘逻辑一致，仅开仓时刻和窗口长度不同
  - 8h：每天开仓 00:30 / 08:30 / 16:30
  - 12h：每天开仓 08:30 / 20:30
  - 组内 +10u 提前平仓 + 已平仓持续快照规则同 4h
  - 新表 `virtual_log_8h` / `virtual_detail_8h` / `virtual_log_12h` / `virtual_detail_12h`
  - 新模块 `virtual_trade_window.py` 抽出通用 `WindowedSimulator`，`virtual_trade_8h.py` / `virtual_trade_12h.py` 是 5 行薄入口
  - API 参数化：`/api/virtual_log_window?window=4h|8h|12h`、`/api/virtual_groups?window=...`、`/api/virtual_detail_window?window=...`（保留旧 `/api/virtual_log_4h` 等作兼容别名）
  - 前端：原 `VirtualLog4h` 组件改为通用 `VirtualLogWindow`，接受 `window` prop；菜单新增"8h模拟盘""12h模拟盘"
  - systemd：`binance-virtual-8h` / `binance-virtual-12h`，分别由 `start_virtual_8h.sh` / `start_virtual_12h.sh` 注册

## 2026-05-09

- **新增 4h 周期虚拟盘**：`virtual_trade_4h.py` 独立运行，与现有 `virtual_trade.py` 互不影响
  - 每天 6 个 4 小时窗口（00:30 / 04:30 / 08:30 / 12:30 / 16:30 / 20:30 开仓）
  - 8 组方向（涨幅榜/跌幅榜 × 做空/做多 × 有过滤/无过滤），与现有沙盘一致
  - **组内 +10u 提前平仓**：每 2 分钟快照时按 `(open_time, side)` 聚合未平仓位 PnL，合计 ≥ +10 USDT 时整组平仓（`close_reason='组内+10u'`）
  - **4h 定时平仓**：window_end（开仓 +4h-5min）仍未平的统一平仓（`close_reason='4h_timed'`）
  - **已平仓持续快照**：组内 +10u 触发后，仓位仍每 2 分钟快照到 window_end，便于和"不止盈走完 4h"的对照分析
  - 新表 `virtual_log_4h` / `virtual_detail_4h`（schema 在 `db.py`）
  - 启动：`sudo bash start_virtual_4h.sh` 注册 systemd 服务 `binance-virtual-4h`
- **回测依据**：30 天实盘数据回测（2026-04-08 ~ 05-09）显示，按"批次合计 +10u 触发整批平仓"的规则可显著改善涨幅空收益（实盘 -91.57u → 模拟 +174.10u）；4h 高频版本是该规则的进一步细化探索

## 2026-05-08

- **修复幽灵开仓记录 bug**：以前 `save_open_csv` 在挂单成功后就 INSERT open_log，但限价单 60 秒后未成交且市价兜底也跳过的币种（如已有持仓）会留下 entry_price=NULL 的「幽灵记录」，导致后续平仓 FIFO 错位回填、历史 PnL 张冠李戴
- **修复方案**：`run_open` 在两批开仓结束后调 `auth_get('/fapi/v2/positionRisk')` 拉真实持仓，传给 `save_open_csv` 过滤；只有币安账户里真实成交的币种才写入 open_log
- **数据清理**：删除 4 条历史幽灵记录（id=484/489/490/509，TAG/LAB/DOGS）

## 2026-04-28

- **新增 ROE 硬止损**：`monitor_positions.py` 每 2 分钟扫描持仓，ROE ≤ 阈值且连续 2 次确认则市价平仓，标记 `close_reason='ROE止损'`
- **灰度上线**：阈值先设 -200%（几乎不触发，纯打通链路），观察 2 天稳定后切到 -100%
- **时间锁**：08:25~08:55 跳过止损扫描，避开定时平仓窗口
- **回测依据**：04-07~04-28 348 笔，-100% 止损可改善净 PnL +117 U（从 -84 → +33）；附带验证「止盈+100%」反而损害收益 -52 U，故只加止损不加止盈
- **代码复用**：`db.py` 抽出 `get_oldest_open_position(symbol)`，定时平仓和止损路径共用 FIFO 匹配逻辑

## 2026-04-07

- **统一 side 命名规范**：实盘和虚拟盘统一使用「涨幅榜-空（有过滤）」格式
- **虚拟盘重构为8组**：涨幅榜/跌幅榜 × 做空/做多 × 有过滤/无过滤，全面覆盖
- **旧虚拟盘数据备份**：virtual_log/virtual_detail 表备份为 _bak_0407，新建空表
- **Dashboard 更新**：实盘vs虚拟盘对照展示，统一新命名
- **OpenLog 更新**：适配新 side 标记

## 2026-04-03

- **策略大改版**：
  - 保证金 60U → 10U，降低单笔风险
  - 新增跌幅榜做空 TOP10（跌幅≥8%，10U保证金），与涨幅榜空单组成双空策略
  - 去掉止盈止损，改为纯定时平仓（08:30 市价平仓）
  - 去掉涨幅上限 35% 过滤，不再限制高涨幅币种
  - 保留两阶段平仓（08:30限价 + 08:50市价兜底），节省手续费

## 2026-04-02

- **修复定时平仓手续费缺失**：手续费查询时间范围从限价平仓开始覆盖到市价兜底结束，确保限价成交的手续费也被记录
- **开仓日志展示资金费率**：实盘和虚拟盘开仓时在日志中展示该币种的资金费率，便于观察和复盘
- **涨幅上限 35%**：新增空单涨幅上限过滤，排除涨幅>35%的暴涨币。历史数据显示涨幅>35%大亏率50%，排除后PnL提升146U
- **止损 -80% → -50%**：收紧止损线。历史触过-50%的9笔无一翻正，单笔最大亏损从48U降至30U
- **检查间隔 60s → 20s**：止盈止损检查更频繁，更快响应
- **快照间隔 20min → 2min**：持仓明细采集更密，数据更精细
- **开仓时间 09:05 → 09:01**：提前开仓
- **防重复开仓**：修复限价单换价重试时可能导致双倍持仓的bug

## 2026-03-31

- **动态止盈切换 16:00 → 15:30**：避开16:00资金费率结算时间
- **两阶段平仓**：08:30限价平仓+08:50市价兜底，节省手续费
- **微信推送**：止盈/止损即时通知 + 每日平仓日报（Server酱）

## 2026-03-30

- **动态止盈上线**：15:30前 ROE>=50%，之后 ROE>=20%。历史回测比固定时间平仓多赚10%
- **止盈/止损平仓记录手续费**：close_commission 字段回填

## 2026-03-29

- **停开多单**：多单累计亏损-31U，胜率仅36%，转入模拟盘观察
- **空单保证金提升**：10U → 20U → 30U → 60U

## 2026-03-28

- **CSV → SQLite 迁移**：全部数据存储改用 SQLite，前端通过 API 读取
- **模拟盘扩展**：新增「模拟空」「模拟多」组，与实盘相同参数，纯定时平仓作为对照

## 2026-03-27

- **初始策略上线**：涨幅榜 TOP20 空单 + 跌幅榜 TOP10 多单
- **3倍杠杆，10U保证金/单**
- **止损 ROE <= -80%**
