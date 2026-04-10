# BTC 长期趋势信号虚拟盘

## 一、策略概述

基于技术指标和市场情绪，对 BTC 进行长期趋势跟踪。纯虚拟盘，不下真实订单，用于验证信号有效性。

## 二、信号指标

| 指标 | 数据源 | 用途 |
|------|--------|------|
| 200 日均线 (SMA200) | 币安日线 K 线 | 判断长期趋势方向 |
| EMA50 / EMA200 | 币安日线 K 线 | 判断中长期趋势交叉（金叉/死叉） |
| 周线 RSI(14) | 币安周线 K 线 | 判断动量强弱 |
| 周线 MACD | 币安周线 K 线 | 判断趋势动量方向 |
| 资金费率 | 币安 premiumIndex | 辅助参考，市场多空情绪 |
| 恐惧贪婪指数 | Alternative.me API | 辅助参考，市场整体情绪 |

## 三、开仓规则（投票机制）

3 个维度各投一票，2 票以上同方向即开仓：

| 维度 | 多票条件 | 空票条件 |
|------|---------|---------|
| 趋势 | 价格 > SMA200 | 价格 < SMA200 |
| 动量 | 周线 RSI > 50 | 周线 RSI < 50 |
| 确认 | EMA50 > EMA200 且 MACD柱 > 0 | EMA50 < EMA200 且 MACD柱 < 0 |

| 信号 | 条件 | 动作 |
|------|------|------|
| 多 | ≥2 票多 | 模拟开多 |
| 空 | ≥2 票空 | 模拟开空 |
| 观望 | 票数相同或确认维度矛盾 | 不开仓 |

## 四、平仓规则

- 信号反转时平仓并反向开仓
- 信号变为观望时平仓不开仓
- 无固定持仓周期，完全跟随信号

## 五、虚拟仓位参数

| 参数 | 值 |
|------|-----|
| 标的 | BTCUSDT |
| 保证金 | 100 USDT |
| 杠杆 | 3 倍 |
| 名义价值 | 300 USDT |

## 六、检查频率

- 每小时检查一次指标并记录
- 信号变化时立即执行模拟开平仓

## 七、数据存储

### btc_indicator 表（每小时一条）

| 字段 | 说明 |
|------|------|
| time | 采集时间 |
| price | BTC 当前价格 |
| sma200 | 200 日均线 |
| ema50 | 50 日 EMA |
| ema200 | 200 日 EMA |
| rsi_weekly | 周线 RSI(14) |
| macd | 周线 MACD (DIF) |
| macd_signal | 周线 MACD 信号线 (DEA) |
| macd_histogram | 周线 MACD 柱 |
| funding_rate | 当前资金费率 |
| fear_greed | 恐惧贪婪指数 (0-100) |
| fear_greed_label | 指数标签（Extreme Fear / Fear / Neutral / Greed / Extreme Greed） |
| signal | 当前信号（多/空/观望） |

### btc_signal_log 表（每次开平仓一条）

| 字段 | 说明 |
|------|------|
| open_time | 开仓时间 |
| close_time | 平仓时间（持仓中为空） |
| side | 方向（多/空） |
| entry_price | 入场价 |
| close_price | 平仓价 |
| signal_reason | 信号原因 |
| unrealized_pnl | 盈亏 (USDT) |
| roe_pct | ROE (%) |

## 八、前端展示

页面：BTC趋势（菜单最后一项）

- 状态卡片：BTC价格、当前信号、RSI、恐惧贪婪、累计盈亏、胜率
- 当前持仓卡片（如有）
- 信号交易记录表
- 指标历史表

## 九、服务管理

```bash
# 首次安装
sudo bash start_btc_trend.sh

# 日常管理
systemctl status binance-btc-trend     # 查看状态
systemctl restart binance-btc-trend    # 重启
systemctl stop binance-btc-trend       # 停止
tail -f logs/binance-btc-trend.log     # 查看日志
```

## 十、关键文件

| 文件 | 说明 |
|------|------|
| `btc_trend.py` | 主程序：指标采集 + 信号判断 + 虚拟开平仓 |
| `binance_client.py` | K线、SMA、RSI、恐惧贪婪指数等函数 |
| `db.py` | btc_indicator / btc_signal_log 表操作 |
| `api.py` | /api/btc_indicators、/api/btc_signals 接口 |
| `start_btc_trend.sh` | systemd 服务安装脚本 |
| `BTC_TREND.md` | 本文档 |
