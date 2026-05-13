"""
通用窗口周期虚拟盘模拟器。
被 virtual_trade_8h.py / virtual_trade_12h.py 共用。
(4h 模拟盘 virtual_trade_4h.py 是早期独立实现，逻辑等价但未迁移到本模块。)

规则：
  - 每天若干个固定窗口（OPEN_HOURS:30 开仓）
  - 每个窗口 8 组方向（涨幅榜/跌幅榜 × 做空/做多 × 有过滤/无过滤）
  - 组内 +10u 提前平仓：每 2 分钟快照时聚合该组未平仓位的浮盈合计，
    若 ≥ +10 USDT，本组所有未平仓位一起平仓（close_reason = "组内+10u"）
  - 窗口到期：window_end 时刻仍未平仓的统一平仓（close_reason = "{N}h_timed"）
  - 已平仓仍持续快照（is_post_close=1）到 window_end
  - 开仓窗口：XX:30 ~ XX:34（5 分钟内幂等补开仓）

参数沿用 virtual_trade.py：3x 杠杆，10 USDT/笔，市值/涨跌幅过滤一致。
"""
from __future__ import annotations

import time
import logging
from datetime import datetime, timedelta
from binance_client import (
    get_exchange_info, get_ticker_24h, get_mark_price, get_all_mark_prices,
    get_coin_market_data, get_btc_change_pct, get_all_funding_rates,
    get_oi_changes, get_long_short_ratios,
)
import db

log = logging.getLogger(__name__)


# ── 共享参数 ──
LEVERAGE         = 3
MARGIN_PER_POS   = 10
MIN_VOLUME       = 10_000_000
TOP_N            = 10
LONG_TOP_N       = 10
LONG_MIN_CHANGE  = 8.0
SHORT_TOP_N      = 10
SHORT_MIN_CHANGE = 5.0
CANDIDATE_BUF    = 6

TARGET_GROUP_PNL      = 10.0  # 组内合计 ≥ 此值触发整组平仓
SNAPSHOT_INTERVAL_MIN = 5     # 快照间隔（2→5：降 CPU 压力 60%）
OPEN_MINUTE           = 30
OPEN_WINDOW_MIN       = 5     # 滑动开仓窗口
CHECK_INTERVAL        = 30    # 主循环秒数


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


class WindowedSimulator:
    """周期窗口模拟器。一个实例对应一组 (窗口长度, 表名后缀, 开仓时刻列表)。"""

    def __init__(self, window: str, hours: int, open_hours: tuple[int, ...],
                 label: str | None = None, snapshot_offset: int = 0):
        """
        window: 数据表后缀，'4h' / '8h' / '12h'
        hours:  窗口长度（小时）
        open_hours: 一天中开仓的整点列表，每个整点的 :30 触发
        label:  日志前缀，默认 window
        snapshot_offset: 快照分钟偏移（0~SNAPSHOT_INTERVAL_MIN-1），
                         用于错开多个服务的快照时刻，避免同时打 CPU
        """
        self.window = window
        self.hours = hours
        self.open_hours = open_hours
        self.label = label or window
        self.timed_reason = f"{window}_timed"
        self.table_log = f"virtual_log_{window}"
        self.snapshot_offset = snapshot_offset % SNAPSHOT_INTERVAL_MIN

    def _snapshot_slot_id(self, now: datetime) -> int:
        """计算当前所属的快照 slot 编号；当 slot_id 变化时触发新一次快照。
        偏移 offset 的服务在 :offset, :offset+INTERVAL, :offset+2*INTERVAL ... 这些分钟触发。"""
        total_min = now.hour * 60 + now.minute
        return (total_min - self.snapshot_offset) // SNAPSHOT_INTERVAL_MIN

    # ── 开仓 ──
    def open_batch(self, now: datetime):
        open_ts = now.strftime("%Y-%m-%d %H:%M:%S")
        window_end_dt = now + timedelta(hours=self.hours) - timedelta(minutes=OPEN_WINDOW_MIN)
        window_end_ts = window_end_dt.strftime("%Y-%m-%d %H:%M:%S")
        log.info(f"【{self.label} 虚拟开仓】{open_ts}  → window_end {window_end_ts}")

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

        try: btc_pct = get_btc_change_pct()
        except Exception: btc_pct = None
        try: funding_rates = get_all_funding_rates()
        except Exception: funding_rates = {}
        try: oi_changes = get_oi_changes(all_syms)
        except Exception: oi_changes = {}
        try: ls_ratios = get_long_short_ratios(all_syms)
        except Exception: ls_ratios = {}

        groups = [
            ("涨幅榜-空（有过滤）", gainer_filtered),
            ("涨幅榜-空（无过滤）", gainer_pool_raw),
            ("涨幅榜-多（有过滤）", gainer_filtered),
            ("涨幅榜-多（无过滤）", gainer_pool_raw),
            ("跌幅榜-空（有过滤）", loser_filtered),
            ("跌幅榜-空（无过滤）", loser_pool_raw),
            ("跌幅榜-多（有过滤）", loser_filtered),
            ("跌幅榜-多（无过滤）", loser_pool_raw),
        ]

        new_rows = []
        for side_label, ticker_group in groups:
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
            db.insert_virtual_log_window(self.window, new_rows)
        log.info(f"【{self.label} 虚拟开仓完成】共 {len(new_rows)} 笔")

    # ── 快照 + 组内 +10u 触发 ──
    def snapshot(self, now: datetime):
        ts = now.strftime("%Y-%m-%d %H:%M:%S")
        active = db.get_virtual_log_window_active(self.window, ts)
        if not active:
            return

        # 批量拉一次全市场标记价（替代每个仓位串行调用）
        try:
            price_map = get_all_mark_prices()
        except Exception as e:
            log.warning(f"{self.label} 批量拉价失败，本次快照跳过：{e}")
            return

        # 按 (open_time, side) 聚合
        groups: dict[tuple[str, str], list[dict]] = {}
        for r in active:
            groups.setdefault((r["open_time"], r["side"]), []).append(r)

        detail_rows = []
        triggered = []

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

            unclosed_pnl_sum = sum(per_row_pnl[r["id"]][1] for r in unclosed if r["id"] in per_row_pnl)
            if unclosed and unclosed_pnl_sum >= TARGET_GROUP_PNL:
                triggered.append((open_time, side, unclosed_pnl_sum, unclosed, per_row_pnl))

        if detail_rows:
            db.insert_virtual_detail_window(self.window, detail_rows)

        for open_time, side, sum_pnl, unclosed, per_row_pnl in triggered:
            log.info(f"  ★ 组内+10u 触发  {side}  open_time={open_time}  合计 {sum_pnl:+.2f}u  → 平 {len(unclosed)} 笔")
            for r in unclosed:
                if r["id"] not in per_row_pnl:
                    continue
                mark, pnl, roe = per_row_pnl[r["id"]]
                db.update_virtual_close_window(self.window, r["id"], {
                    "close_time":     ts,
                    "close_price":    mark,
                    "unrealized_pnl": pnl,
                    "roe_pct":        roe,
                    "close_reason":   "组内+10u",
                })

        log.info(f"{self.label} 快照：{len(detail_rows)} 条  active {len(active)}  触发组 {len(triggered)}")

    # ── 窗口到期定时平仓 ──
    def settle_expired(self, now: datetime):
        ts = now.strftime("%Y-%m-%d %H:%M:%S")
        to_settle = db.get_virtual_log_window_to_settle(self.window, ts)
        if not to_settle:
            return
        log.info(f"【{self.label} 定时平仓】{len(to_settle)} 笔 待平")
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
            db.update_virtual_close_window(self.window, r["id"], {
                "close_time":     ts,
                "close_price":    mark,
                "unrealized_pnl": pnl,
                "roe_pct":        roe,
                "close_reason":   self.timed_reason,
            })
        log.info(f"【{self.label} 定时平仓完成】")

    # ── 主循环 ──
    def _is_open_window(self, now: datetime) -> bool:
        return (now.hour in self.open_hours
                and OPEN_MINUTE <= now.minute < OPEN_MINUTE + OPEN_WINDOW_MIN)

    def _opened_already(self, anchor_ts: str) -> bool:
        with db.get_conn() as conn:
            row = conn.execute(
                f"SELECT 1 FROM {self.table_log} WHERE open_time = ? LIMIT 1",
                (anchor_ts,)
            ).fetchone()
            return row is not None

    def run(self):
        db.init_db()
        log.info(f"{self.label} 虚拟盘启动")
        log.info(f"  开仓时刻：每天 {self.open_hours} 点 {OPEN_MINUTE} 分（{OPEN_WINDOW_MIN} 分钟滑动窗口）")
        log.info(f"  组内 +10u 触发：≥ {TARGET_GROUP_PNL} USDT 整组平仓")
        log.info(f"  窗口长度：{self.hours} 小时   快照间隔：{SNAPSHOT_INTERVAL_MIN} 分钟  偏移：{self.snapshot_offset} 分钟")
        log.info(f"  8 组：涨幅榜/跌幅榜 × 做空/做多 × 有过滤/无过滤")

        last_snapshot_slot = None
        try:
            self.snapshot(datetime.now())
            last_snapshot_slot = self._snapshot_slot_id(datetime.now())
        except Exception as e:
            log.error(f"启动快照失败：{e}", exc_info=True)

        while True:
            time.sleep(CHECK_INTERVAL)
            now = datetime.now()

            try: self.settle_expired(now)
            except Exception as e: log.error(f"{self.label} 定时平仓出错：{e}", exc_info=True)

            if self._is_open_window(now):
                anchor = now.replace(minute=OPEN_MINUTE, second=0, microsecond=0)
                anchor_ts = anchor.strftime("%Y-%m-%d %H:%M:%S")
                if not self._opened_already(anchor_ts):
                    try: self.open_batch(anchor)
                    except Exception as e: log.error(f"{self.label} 虚拟开仓出错：{e}", exc_info=True)

            current_slot = self._snapshot_slot_id(now)
            if current_slot != last_snapshot_slot:
                try:
                    self.snapshot(now)
                    last_snapshot_slot = current_slot
                except Exception as e:
                    log.error(f"{self.label} 快照失败：{e}", exc_info=True)
