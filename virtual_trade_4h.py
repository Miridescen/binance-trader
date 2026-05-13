"""
4 小时周期虚拟盘（沙盘模式，独立运行，不影响现有 virtual_trade.py）

规则：
  - 每天 6 个 4 小时窗口：00:30 / 04:30 / 08:30 / 12:30 / 16:30 / 20:30 开仓
  - 每个窗口 8 组方向（涨幅榜/跌幅榜 × 做空/做多 × 有过滤/无过滤）
  - 组内 +10u 提前平仓：每 2 分钟快照时聚合该组未平仓位的浮盈合计，
    若 ≥ +10 USDT，本组所有未平仓位一起平仓（close_reason = "组内+10u"）
  - 4 小时定时平仓：window_end 时刻仍未平仓的，统一定时平仓（close_reason = "4h_timed"）
  - 已平仓的仓位仍持续快照（is_post_close=1），直到 window_end，便于事后对照
  - 开仓窗口：XX:30 ~ XX:34（5 分钟内允许补开仓，幂等）

参数沿用现有：3x 杠杆，10 USDT/笔，市值/涨跌幅过滤同 virtual_trade.py。

数据表：virtual_log_4h / virtual_detail_4h（与 virtual_log / virtual_detail 互不影响）
"""

import time
import logging
from datetime import datetime, timedelta
from binance_client import (
    get_exchange_info, get_ticker_24h, get_mark_price, get_all_mark_prices,
    get_coin_market_data, get_btc_change_pct, get_all_funding_rates,
    get_oi_changes, get_long_short_ratios,
)
import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ── 参数（与 virtual_trade.py 保持一致） ──
LEVERAGE         = 3
MARGIN_PER_POS   = 10
MIN_VOLUME       = 10_000_000
TOP_N            = 10
LONG_TOP_N       = 10
LONG_MIN_CHANGE  = 8.0
SHORT_TOP_N      = 10
SHORT_MIN_CHANGE = 5.0
CANDIDATE_BUF    = 6

# ── 4h 周期参数 ──
WINDOW_HOURS         = 4
TARGET_GROUP_PNL     = 10.0     # 组内合计达到 +10u 触发组内平仓
SNAPSHOT_INTERVAL_MIN = 5        # 快照间隔（2→5：降 CPU 压力 60%）
SNAPSHOT_OFFSET_MIN  = 1         # 错开：主盘 0 / 4h 1 / 8h 2 / 12h 3
OPEN_HOURS           = (0, 4, 8, 12, 16, 20)
OPEN_MINUTE          = 30
OPEN_WINDOW_MIN      = 5         # 开仓滑动窗口：XX:30 ~ XX:34


def fmt_large(n: float) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.2f}B"
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    if n > 0:
        return f"{n:.0f}"
    return "N/A"


def _calc_pnl(entry: float, mark: float, side: str) -> tuple[float, float]:
    notional = MARGIN_PER_POS * LEVERAGE
    is_short = "空" in side
    if is_short:
        pnl = (entry - mark) / entry * notional
    else:
        pnl = (mark - entry) / entry * notional
    roe = pnl / MARGIN_PER_POS * 100
    return pnl, roe


# ── 开仓 ─────────────────────────────────────────────

def virtual_open_4h(now: datetime):
    """在 XX:30 触发：开 8 组虚拟仓"""
    open_ts = now.strftime("%Y-%m-%d %H:%M:%S")
    window_end_dt = now + timedelta(hours=WINDOW_HOURS) - timedelta(minutes=OPEN_WINDOW_MIN)
    window_end_ts = window_end_dt.strftime("%Y-%m-%d %H:%M:%S")
    log.info(f"【4h 虚拟开仓】{open_ts}  → window_end {window_end_ts}")

    valid_symbols, _ = get_exchange_info()
    tickers = get_ticker_24h(valid_symbols, MIN_VOLUME)
    tickers.sort(key=lambda x: float(x["priceChangePercent"]), reverse=True)

    gainer_pool_raw = tickers[:TOP_N]
    loser_pool_raw  = tickers[-TOP_N:][::-1]
    gainer_pool_big = tickers[:SHORT_TOP_N * CANDIDATE_BUF]
    loser_pool_big  = tickers[-(LONG_TOP_N * CANDIDATE_BUF):][::-1]

    all_syms = list({t["symbol"] for t in
                     gainer_pool_raw + loser_pool_raw + gainer_pool_big + loser_pool_big})

    try:
        market_data = get_coin_market_data(all_syms)
    except Exception as e:
        log.warning(f"CoinGecko 获取失败：{e}")
        market_data = {}

    def has_mcap(t):
        return bool(market_data.get(t["symbol"], {}).get("market_cap"))

    if market_data:
        gainer_filtered = [t for t in gainer_pool_big
                           if has_mcap(t) and float(t["priceChangePercent"]) >= SHORT_MIN_CHANGE
                           ][:SHORT_TOP_N]
        loser_filtered  = [t for t in loser_pool_big
                           if has_mcap(t) and float(t["priceChangePercent"]) <= -LONG_MIN_CHANGE
                           ][:LONG_TOP_N]
    else:
        gainer_filtered = [t for t in gainer_pool_big
                           if float(t["priceChangePercent"]) >= SHORT_MIN_CHANGE
                           ][:SHORT_TOP_N]
        loser_filtered  = [t for t in loser_pool_big
                           if float(t["priceChangePercent"]) <= -LONG_MIN_CHANGE
                           ][:LONG_TOP_N]

    try:
        btc_pct = get_btc_change_pct()
    except Exception:
        btc_pct = None
    try:
        funding_rates = get_all_funding_rates()
    except Exception:
        funding_rates = {}
    try:
        oi_changes = get_oi_changes(all_syms)
    except Exception:
        oi_changes = {}
    try:
        ls_ratios = get_long_short_ratios(all_syms)
    except Exception:
        ls_ratios = {}

    groups = [
        ("涨幅榜-空（有过滤）", gainer_filtered, "空"),
        ("涨幅榜-空（无过滤）", gainer_pool_raw, "空"),
        ("涨幅榜-多（有过滤）", gainer_filtered, "多"),
        ("涨幅榜-多（无过滤）", gainer_pool_raw, "多"),
        ("跌幅榜-空（有过滤）", loser_filtered,  "空"),
        ("跌幅榜-空（无过滤）", loser_pool_raw,  "空"),
        ("跌幅榜-多（有过滤）", loser_filtered,  "多"),
        ("跌幅榜-多（无过滤）", loser_pool_raw,  "多"),
    ]

    new_rows = []
    for side_label, ticker_group, _direction in groups:
        log.info(f"── {side_label}（{len(ticker_group)} 个）──")
        for t in ticker_group:
            sym = t["symbol"]
            pct = float(t["priceChangePercent"])
            try:
                entry = get_mark_price(sym)
            except Exception as e:
                log.warning(f"  {sym} 获取标记价失败，跳过：{e}")
                continue
            md = market_data.get(sym, {})
            mc = md.get("market_cap", 0)
            cs = md.get("circulating_supply", 0)
            new_rows.append({
                "open_time":           open_ts,
                "window_end":          window_end_ts,
                "close_time":          None,
                "close_reason":        None,
                "symbol":              sym,
                "side":                side_label,
                "change_pct":          pct,
                "market_cap_usd":      fmt_large(mc) if mc else None,
                "circulating_supply":  fmt_large(cs) if cs else None,
                "has_mcap":            1 if mc else 0,
                "btc_change_pct":      btc_pct,
                "symbol_funding_rate": funding_rates.get(sym),
                "oi_change_pct":       oi_changes.get(sym),
                "long_short_ratio":    ls_ratios.get(sym),
                "entry_price":         entry,
                "close_price":         None,
                "unrealized_pnl":      None,
                "roe_pct":             None,
            })
            time.sleep(0.05)

    if new_rows:
        db.insert_virtual_log_4h(new_rows)
    log.info(f"【4h 虚拟开仓完成】共 {len(new_rows)} 笔")


# ── 快照 + 组内 +10u 触发 ────────────────────────────

def virtual_snapshot_4h(now: datetime):
    """对所有 active 仓位（window_end 未到）拍快照；
       未平仓的按组聚合 PnL，组内合计 ≥ +10u 时整组平仓。"""
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    active = db.get_virtual_log_4h_active(ts)
    if not active:
        return

    # 批量拉一次全市场标记价（替代循环串行调用）
    try:
        price_map = get_all_mark_prices()
    except Exception as e:
        log.warning(f"4h 批量拉价失败，本次快照跳过：{e}")
        return

    # 按组（open_time, side）聚合
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in active:
        groups.setdefault((r["open_time"], r["side"]), []).append(r)

    detail_rows = []
    triggered_groups = []

    for (open_time, side), rows in groups.items():
        unclosed = [r for r in rows if not r["close_time"]]
        per_row_pnl = {}
        for r in rows:
            entry = r["entry_price"]
            if entry is None:
                continue
            mark = price_map.get(r["symbol"])
            if mark is None:
                continue
            pnl, roe = _calc_pnl(entry, mark, side)
            per_row_pnl[r["id"]] = (mark, pnl, roe)
            detail_rows.append({
                "time":           ts,
                "log_id":         r["id"],
                "symbol":         r["symbol"],
                "side":           side,
                "entry_price":    entry,
                "mark_price":     mark,
                "unrealized_pnl": pnl,
                "roe_pct":        roe,
                "is_post_close":  1 if r["close_time"] else 0,
            })

        # 检查未平仓部分的合计是否触发
        unclosed_pnl_sum = sum(per_row_pnl[r["id"]][1] for r in unclosed
                               if r["id"] in per_row_pnl)
        if unclosed and unclosed_pnl_sum >= TARGET_GROUP_PNL:
            triggered_groups.append((open_time, side, unclosed_pnl_sum, unclosed, per_row_pnl))

    # 写快照
    if detail_rows:
        db.insert_virtual_detail_4h(detail_rows)

    # 处理触发组：把整组未平仓位一起平掉
    for open_time, side, sum_pnl, unclosed, per_row_pnl in triggered_groups:
        log.info(f"  ★ 组内+10u 触发  {side}  open_time={open_time}  合计 {sum_pnl:+.2f}u  → 平 {len(unclosed)} 笔")
        for r in unclosed:
            if r["id"] not in per_row_pnl:
                continue
            mark, pnl, roe = per_row_pnl[r["id"]]
            db.update_virtual_close_4h(r["id"], {
                "close_time":     ts,
                "close_price":    mark,
                "unrealized_pnl": pnl,
                "roe_pct":        roe,
                "close_reason":   "组内+10u",
            })

    log.info(f"4h 快照：{len(detail_rows)} 条  active 仓位 {len(active)}  触发组 {len(triggered_groups)}")


# ── 4h 定时平仓 ──────────────────────────────────────

def virtual_close_4h_timed(now: datetime):
    """对所有 window_end 已到、仍未平仓的仓位做定时平仓"""
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    to_settle = db.get_virtual_log_4h_to_settle(ts)
    if not to_settle:
        return
    log.info(f"【4h 定时平仓】{len(to_settle)} 笔 待平")
    try:
        price_map = get_all_mark_prices()
    except Exception as e:
        log.warning(f"  批量拉价失败，本次平仓跳过：{e}")
        return
    for r in to_settle:
        entry = r["entry_price"]
        if entry is None:
            continue
        mark = price_map.get(r["symbol"])
        if mark is None:
            log.warning(f"  {r['symbol']} 价格缺失，跳过")
            continue
        pnl, roe = _calc_pnl(entry, mark, r["side"])
        db.update_virtual_close_4h(r["id"], {
            "close_time":     ts,
            "close_price":    mark,
            "unrealized_pnl": pnl,
            "roe_pct":        roe,
            "close_reason":   "4h_timed",
        })
    log.info(f"【4h 定时平仓完成】")


# ── 主循环 ───────────────────────────────────────────

CHECK_INTERVAL = 30  # 主循环检查间隔（秒）


def _is_open_window(now: datetime) -> bool:
    """是否处于 XX:30 ~ XX:30+OPEN_WINDOW_MIN 的开仓窗口"""
    return (now.hour in OPEN_HOURS
            and OPEN_MINUTE <= now.minute < OPEN_MINUTE + OPEN_WINDOW_MIN)


def _opened_already(open_window_anchor_ts: str) -> bool:
    """该窗口是否已有开仓记录"""
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM virtual_log_4h WHERE open_time = ? LIMIT 1",
            (open_window_anchor_ts,)
        ).fetchone()
        return row is not None


def _snapshot_slot_id(now: datetime) -> int:
    """快照 slot 编号；偏移 SNAPSHOT_OFFSET_MIN 后按 INTERVAL 分桶。
    slot_id 变化时触发新一次快照。"""
    total_min = now.hour * 60 + now.minute
    return (total_min - SNAPSHOT_OFFSET_MIN) // SNAPSHOT_INTERVAL_MIN


def main():
    db.init_db()
    log.info("4h 虚拟盘启动")
    log.info(f"  开仓时刻：每天 {OPEN_HOURS} 点 {OPEN_MINUTE} 分（5 分钟滑动窗口）")
    log.info(f"  组内 +10u 触发：≥ {TARGET_GROUP_PNL} USDT 整组平仓")
    log.info(f"  快照间隔：{SNAPSHOT_INTERVAL_MIN} 分钟  偏移：{SNAPSHOT_OFFSET_MIN} 分钟")
    log.info(f"  8 组：涨幅榜/跌幅榜 × 做空/做多 × 有过滤/无过滤")

    last_snapshot_slot = None

    # 启动时立即快照一次
    try:
        virtual_snapshot_4h(datetime.now())
        last_snapshot_slot = _snapshot_slot_id(datetime.now())
    except Exception as e:
        log.error(f"启动快照失败：{e}", exc_info=True)

    while True:
        time.sleep(CHECK_INTERVAL)
        now = datetime.now()

        # 1) 4h 定时平仓（每分钟检查一次足够）
        try:
            virtual_close_4h_timed(now)
        except Exception as e:
            log.error(f"4h 定时平仓出错：{e}", exc_info=True)

        # 2) 开仓（XX:30 ~ XX:34 滑动窗口，幂等）
        if _is_open_window(now):
            anchor = now.replace(minute=OPEN_MINUTE, second=0, microsecond=0)
            anchor_ts = anchor.strftime("%Y-%m-%d %H:%M:%S")
            if not _opened_already(anchor_ts):
                try:
                    virtual_open_4h(anchor)
                except Exception as e:
                    log.error(f"4h 虚拟开仓出错：{e}", exc_info=True)

        # 3) 每 SNAPSHOT_INTERVAL_MIN 分钟快照一次（带偏移）
        current_slot = _snapshot_slot_id(now)
        if current_slot != last_snapshot_slot:
            try:
                virtual_snapshot_4h(now)
                last_snapshot_slot = current_slot
            except Exception as e:
                log.error(f"4h 快照失败：{e}", exc_info=True)


if __name__ == "__main__":
    main()
