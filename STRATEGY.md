# 交易策略文档

## 一、策略概述

币安合约逆势+趋势双空策略：
- **涨幅榜做空**：做空 24h 涨幅榜 TOP 币种，赚取过度拉升后的回落收益
- **跌幅榜做空**：做空 24h 跌幅榜 TOP 币种，赚取下跌趋势延续的收益

**核心逻辑**：涨幅大的币短期回落概率高；跌幅大的币短期继续下跌概率高。

## 二、开仓策略

### 时间
- **限价平仓**：每天 08:30 开始挂限价单平仓（省手续费）
- **市价兜底**：每天 08:50 未成交的改市价清仓
- **开仓时间**：每天 09:01（平仓完成后开新仓）

### 标的筛选
1. 获取所有 USDT 合约 24h 行情
2. 过滤 24h 交易量 < 1000 万 USDT 的币种
3. 从候选池中筛选：
   - **有市值**：通过 CoinGecko 验证，无市值币排除
   - **涨幅榜**：涨幅 ≥ 5%，取前 10 个开空单
   - **跌幅榜**：跌幅 ≥ 8%，取前 10 个开空单

### 开仓参数
| 参数 | 值 |
|------|-----|
| 方向 | 全部做空 |
| 数量 | 涨幅榜 10 个 + 跌幅榜 10 个 = 最多 20 个 |
| 杠杆 | 3 倍 |
| 保证金 | 10 USDT / 单 |
| 名义价值 | 30 USDT / 单 |
| 总保证金 | 最多 200 USDT |

### 下单方式
1. 以标记价挂 GTC 限价单
2. 每 60 秒检查未成交订单，按最新标记价换价重挂
3. 最多重试 10 次（约 10 分钟）
4. 仍未成交则改用市价单兜底

## 三、平仓策略

### 定时平仓（两阶段）

| 时间 | 动作 | 手续费 |
|------|------|--------|
| 08:30 | 限价平仓（按标记价挂单，每 60s 换价） | 低（Maker） |
| 08:50 | 未成交的改市价兜底 | 高（Taker） |

正常持仓约 23.5 小时。限价平仓可以节省手续费（Maker 费率通常比 Taker 低 50%-70%）。

### ROE 硬止损 — 已于 2026-05-21 移除

历史上 `monitor_positions.py` 跑过一段 ROE-200% 灰度止损，但 5-21 一次触发暴露了
回写链路缺陷（open_log 中 entry_price=NULL 时 FIFO 匹配失败，币安已平但本地脱节），
并且实盘运行 1 个月期间未见显著正贡献。**当前策略只走定时平仓 + ROE 爆仓兜底**。

### 微信通知

通过 Server酱 推送到微信：
- **每日平仓日报**（08:30）：账户余额、每笔盈亏、胜率

## 四、风险控制

### 爆仓保护
- 3 倍杠杆，强平线约 ROE -100%（价格反向 33%）
- 10U 保证金，单笔极端亏损 10U
- 20 笔全亏极端情况：亏 200U，账户不归零
- 不再启用 ROE 硬止损（见三）；币安自有的强平机制兜底

### BTC 联动
- BTC 跌时空单日均赚 +46U，BTC 涨时日均赚 +14U
- BTC 涨时空单仍然盈利，策略不依赖 BTC 方向
- 目前不根据 BTC 涨跌调整策略

## 五、模拟盘

同时运行 8 组虚拟仓位，全面覆盖涨幅榜/跌幅榜 × 做空/做多 × 有过滤/无过滤：

| side | 榜单 | 方向 | 过滤 |
|------|------|------|------|
| 涨幅榜-空（有过滤） | 涨幅榜 TOP10 | 做空 | 涨幅≥5% + 市值 |
| 涨幅榜-空（无过滤） | 涨幅榜 TOP10 | 做空 | 无 |
| 涨幅榜-多（有过滤） | 涨幅榜 TOP10 | 做多 | 涨幅≥5% + 市值 |
| 涨幅榜-多（无过滤） | 涨幅榜 TOP10 | 做多 | 无 |
| 跌幅榜-空（有过滤） | 跌幅榜 TOP10 | 做空 | 跌幅≥8% + 市值 |
| 跌幅榜-空（无过滤） | 跌幅榜 TOP10 | 做空 | 无 |
| 跌幅榜-多（有过滤） | 跌幅榜 TOP10 | 做多 | 跌幅≥8% + 市值 |
| 跌幅榜-多（无过滤） | 跌幅榜 TOP10 | 做多 | 无 |

### 持仓快照
- 每 20 分钟对所有未平仓虚拟仓位拍快照
- 记录标记价、PnL、ROE

## 六、监控与数据

### 持仓监控
- 每 2 分钟记录持仓快照（汇总 + 明细）
- 特殊快照：08:29（平仓前）、09:30（开仓后）

### 数据存储
- SQLite 数据库（trader.db）
- 主要表：open_log、batch_summary、events_log、positions_log、positions_detail、virtual_log、virtual_detail、virtual_log_4h、virtual_detail_4h、daily_summary、btc_indicator、btc_signal_log

### 周期虚拟盘（4h / 8h / 12h / 24h 四套并行）

> 旧主模拟盘（`virtual_trade.py`，每天 09:00 开、持仓 24h、**无 +10U**）已于 2026-07-13 废弃删除，
> 由下面走窗口逻辑（**含 +10U**）的 24h 虚拟盘取代。

四个独立 systemd 服务，逻辑完全一致仅周期不同：

| 周期 | 开仓时刻 | 数据表 | systemd 服务 |
|---|---|---|---|
| 4h | 00:30 / 04:30 / 08:30 / 12:30 / 16:30 / 20:30 | `virtual_log_4h` / `virtual_detail_4h` | `binance-virtual-4h` |
| 8h | 00:30 / 08:30 / 16:30 | `virtual_log_8h` / `virtual_detail_8h` | `binance-virtual-8h` |
| 12h | 08:30 / 20:30 | `virtual_log_12h` / `virtual_detail_12h` | `binance-virtual-12h` |
| 24h | 00:30 | `virtual_log_24h` / `virtual_detail_24h` | `binance-virtual-24h` |

**共同规则**：
- 8 组方向：涨幅榜/跌幅榜 × 做空/做多 × 有过滤/无过滤
- 开仓窗口：XX:30 ~ XX:34（5 分钟内幂等补开仓）
- 提前止盈：组内合计浮盈 ≥ +10 USDT 时整组平仓（`close_reason='组内+10u'`）
- 定时平仓：window_end（开仓时刻 +N 小时 -5min）仍未平的统一平仓（`close_reason='{N}h_timed'`）
- 快照：每 2 分钟，已平仓仓位仍持续快照到 window_end，便于"不止盈走完 Nh"对照分析
- 参数：3x 杠杆 / 10U/笔，沿用主模拟盘

**代码组织**：
- `virtual_trade_window.py` 通用 `WindowedSimulator`（8h / 12h / 24h 使用）
- `virtual_trade_4h.py` 是早期独立实现（逻辑等价，未迁移）
- `virtual_trade_8h.py` / `virtual_trade_12h.py` / `virtual_trade_24h.py` 是薄入口

**API**：`/api/virtual_log_window?window=4h|8h|12h|24h`、`/api/virtual_groups?window=...`、`/api/virtual_detail_window?window=...`

### 前端展示
- http://服务器IP:8080（密码保护）
- 页面：Dashboard、开仓记录、4h/8h/12h/24h 模拟盘、BTC趋势
- 看板：实时余额/保证金/浮盈亏 + 实盘vs模拟盘持仓对比

## 七、关键文件

| 文件 | 说明 |
|------|------|
| `open_top_shorts.py` | 24h 定时开仓策略（现已 disabled，2026-05-21 起停用） |
| `real_trade_4h.py` | 4h 周期实盘策略（独立运行，限价 10min + 市价兜底）**已停用（2026-06-10 起）** |
| `real_trade_8h.py` | **8h 周期实盘策略**（跌幅榜-空无过滤，batch 隔离，组内 +10U 提前平 / 否则跑满 8h；`REAL_8H_LIVE=1` 才下单） |
| `monitor_positions.py` | 持仓监控（每 2 分钟拍快照 + 整点报表）|
| `virtual_trade.py` | 主模拟盘（每天 09:00 开 / 08:50 平，对照组 + 模拟空 + 模拟多 + 快照） |
| `virtual_trade_4h.py` | 4h 周期模拟盘（独立实现） |
| `virtual_trade_window.py` | 通用窗口模拟器（被 8h / 12h 共享） |
| `virtual_trade_8h.py` / `virtual_trade_12h.py` | 8h / 12h 周期模拟盘薄入口 |
| `api.py` | Flask API 服务 |
| `db.py` | SQLite 数据库模块 |
| `binance_client.py` | 币安 API 客户端 |
| `notify.py` | 微信推送模块（Server酱） |
| `STRATEGY.md` | 本文档 |

## 八、服务管理

```bash
# 启动所有服务（含 git pull + 前端构建 + nginx）
bash start_service.sh

# 只重建前端
bash rebuild_frontend.sh

# 单独重启
systemctl restart binance-strategy    # 24h 开仓策略（停用中）
systemctl restart binance-real-4h     # 4h 实盘策略（当前在跑）
systemctl restart binance-basis-monitor  # 基差套利 Phase 1 数据采集
systemctl restart binance-monitor     # 持仓监控
systemctl restart binance-virtual     # 主模拟盘
systemctl restart binance-virtual-4h  # 4h 周期模拟盘
systemctl restart binance-virtual-8h  # 8h 周期模拟盘
systemctl restart binance-virtual-12h # 12h 周期模拟盘
systemctl restart binance-api         # API 服务

# 查看日志
tail -f logs/binance-strategy.log
tail -f logs/binance-monitor.log
tail -f logs/binance-virtual.log
tail -f logs/binance-virtual-4h.log
```
