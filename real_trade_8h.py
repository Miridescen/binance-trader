"""
8h 周期实盘策略（batch 隔离 + 组内 +10U 提前平仓）。

规则：
  - 每天 3 个开仓周期：00:30 / 08:30 / 16:30
  - 方向：跌幅榜-空（无过滤）TOP10（= 虚拟盘 8h 跌幅空无过滤选股逻辑）
    · 选币复用 real_trade_4h.select_top10("跌幅榜")：24h 量 ≥ 1000 万 U，按涨跌幅升序取最末 10 个做空
  - 杠杆 3x，每单保证金 10 USDT，名义 30 USDT
  - 平仓（batch 隔离）：
      · 每个 batch =（open_anchor, side）一组 ~10 单，用 DB 记录的 entry_price + 实时标记价
        自行计算“合计浮盈”（税前，和虚拟盘 _calc_pnl 一致），互不干扰
      · 合计浮盈 ≥ +10U → 整组立即市价平仓（close_reason=组内+10u）
      · 到 8h 窗口末（open_anchor+8h 前 10 分钟起）仍没触发 → 定时平仓
        （限价 ladder + 市价兜底，close_reason=8h_timed）
  - 数据：open_log_8h 表，成交后回填真实 commission / funding_fee

安全开关：
  - 环境变量 REAL_8H_LIVE=1 才会真正下单。未设置时为“观察模式”：
    照常选币 / 打印将要下的单 / 到点计算浮盈，但不下真单、不写库。
    用于上线前在服务器上核对选股与时间调度。
"""
from __future__ import annotations
import os
import time
import logging
from datetime import datetime, timedelta

from binance_client import (
    auth_get, get_exchange_info, get_mark_price, get_all_mark_prices,
)
# 复用 4h 实盘里已经过实盘验证的下单/撤单/精度/选币原语
from real_trade_4h import (
    select_top10, set_leverage,
    place_open_limit, place_open_market,
    place_close_limit, place_close_market,
    get_order, cancel_order, cancel_all_orders,
    query_funding,
    LEVERAGE, MARGIN_PER_POS, TOP_N,
    ATTEMPT_INTERVAL_SEC, MAX_LIMIT_ATTEMPTS,
)
import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("real_8h")

LIVE = os.environ.get("REAL_8H_LIVE") == "1"

# ── 策略参数 ──
WINDOW_HOURS      = 8
TARGET_GROUP_PNL  = 10.0                 # 组内合计浮盈 ≥ 此值 → 整组提前市价平
OPEN_HOURS        = (0, 8, 16)           # 开仓整点
OPEN_MINUTE       = 30
OPEN_WINDOW_MIN   = 5                     # 开仓滑动窗口（幂等）
CLOSE_PREP_MIN    = 10                    # 窗口末前 N 分钟开始挂限价平
CLOSE_MARKET_MIN  = 1                     # 窗口末前 N 分钟市价兜底
CHECK_INTERVAL    = 30                    # 主循环 / 监控节奏（秒）
SETTLE_DELAY_SEC  = 12                    # 平仓后等几秒再查账单回填

# 开的方向（后续加方向只在此追加，batch 天然隔离）
# (side_label, board_keyword)
DIRECTIONS = [
    ("跌幅榜-空（无过滤）", "跌幅榜"),
]


# ── 开仓 ──

def insert_open_record_8h(symbol: str, side_label: str, order_id: int, anchor_ts: str) -> int | None:
    """开仓成交后按实际成交数据 INSERT open_log_8h。"""
    try:
        order = get_order(symbol, order_id)
    except Exception as e:
        log.error(f"  {symbol}#{order_id} 查 order 失败：{e}")
        return None
    if order.get("status") not in ("FILLED", "PARTIALLY_FILLED"):
        log.warning(f"  {symbol}#{order_id} 状态非 FILLED：{order.get('status')}")
        return None
    avg_price = float(order.get("avgPrice", 0))
    executed  = float(order.get("executedQty", 0))
    update_ms = int(order.get("updateTime", time.time() * 1000))
    if avg_price == 0 or executed == 0:
        log.warning(f"  {symbol}#{order_id} 成交数据为 0，跳过 INSERT")
        return None
    open_time = datetime.fromtimestamp(update_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
    row = {
        "open_anchor": anchor_ts,
        "open_time": open_time, "close_time": None,
        "symbol": symbol, "side": side_label,
        "entry_price": avg_price, "close_price": None,
        "position_amt": executed, "leverage": LEVERAGE,
        "unrealized_pnl": None, "roe_pct": None,
        "open_commission": None, "close_commission": None,
        "funding_fee": None, "close_reason": None,
    }
    new_id = db.insert_open_log_8h(row)
    log.info(f"  {symbol} INSERT open_log_8h#{new_id}: entry={avg_price} qty={executed} @ {open_time}")
    return new_id


def run_open_cycle(anchor: datetime):
    """对每个方向开一批（batch）。限价 ladder + 市价兜底。阻塞执行。"""
    anchor_ts = anchor.strftime("%Y-%m-%d %H:%M:%S")
    log.info(f"═══ 开仓周期开始 {anchor_ts}  LIVE={LIVE} ═══")

    _, symbol_info = get_exchange_info()

    # 逐方向拉 TOP10
    targets = []  # (symbol, side_label)
    for side_label, board in DIRECTIONS:
        tickers, _ = select_top10(board)
        for t in tickers:
            targets.append((t["symbol"], side_label))
        log.info(f"{side_label} TOP{len(tickers)}: {[t['symbol'] for t in tickers]}")

    if not LIVE:
        log.info(f"[观察模式] 将开 {len(targets)} 单（未真实下单、未写库）")
        for sym, side_label in targets:
            info = symbol_info.get(sym)
            log.info(f"  [dry] SELL {sym}  名义 {MARGIN_PER_POS*LEVERAGE}U  ({side_label})")
        log.info(f"═══ 开仓周期结束 {anchor_ts}（观察模式） ═══\n")
        return

    # ── 限价首挂 ──
    pending = {}
    for sym, side_label in targets:
        info = symbol_info.get(sym)
        if not info:
            log.warning(f"  {sym} 无 info，跳过")
            continue
        if not set_leverage(sym):
            continue
        try:
            ref = get_mark_price(sym)
        except Exception as e:
            log.warning(f"  {sym} 取 mark 失败：{e}")
            continue
        res = place_open_limit(sym, info, ref)
        if res:
            res["side_label"] = side_label
            pending[sym] = res
        time.sleep(0.15)

    # ── 每 2 分钟换价（共 5 轮限价） ──
    for attempt in range(2, MAX_LIMIT_ATTEMPTS + 1):
        if not pending:
            break
        log.info(f"等待 {ATTEMPT_INTERVAL_SEC}s 进入第 {attempt} 轮开仓检查...")
        time.sleep(ATTEMPT_INTERVAL_SEC)
        try:
            price_map = get_all_mark_prices()
        except Exception:
            price_map = {}
        still = {}
        for sym, data in pending.items():
            try:
                order = get_order(sym, data["orderId"])
            except Exception as e:
                log.warning(f"  {sym} 查 order 异常：{e}")
                still[sym] = data
                continue
            status = order.get("status", "UNKNOWN")
            if status == "FILLED":
                log.info(f"  {sym} ✅ 已成交")
                insert_open_record_8h(sym, data["side_label"], data["orderId"], anchor_ts)
                continue
            if status == "PARTIALLY_FILLED":
                still[sym] = data
                continue
            cancel_order(sym, data["orderId"])
            time.sleep(0.3)
            if get_order(sym, data["orderId"]).get("status") == "FILLED":
                insert_open_record_8h(sym, data["side_label"], data["orderId"], anchor_ts)
                continue
            ref = price_map.get(sym) or 0
            if not ref:
                try:
                    ref = get_mark_price(sym)
                except Exception:
                    continue
            new_res = place_open_limit(sym, data["info"], ref)
            if new_res:
                new_res["side_label"] = data["side_label"]
                still[sym] = new_res
            time.sleep(0.15)
        pending = still

    # ── 市价兜底 ──
    if pending:
        log.warning(f"仍有 {len(pending)} 个未成交，市价兜底")
        positions = auth_get("/fapi/v2/positionRisk")
        held = {p["symbol"] for p in positions if float(p["positionAmt"]) != 0}
        for sym, data in pending.items():
            cancel_order(sym, data["orderId"])
            time.sleep(0.3)
            if get_order(sym, data["orderId"]).get("status") == "FILLED":
                insert_open_record_8h(sym, data["side_label"], data["orderId"], anchor_ts)
                continue
            if sym in held:
                continue
            res = place_open_market(sym, data["info"])
            if res:
                time.sleep(1)
                insert_open_record_8h(sym, data["side_label"], res["orderId"], anchor_ts)
            time.sleep(0.15)

    log.info(f"═══ 开仓周期结束 {anchor_ts} ═══\n")


def _opened_already(anchor_ts: str, side_label: str) -> bool:
    return len(db.get_open_log_8h_by_anchor_side(anchor_ts, side_label)) > 0


# ── batch 浮盈 & 平仓 ──

def batch_pnl(brows: list[dict], price_map: dict) -> float | None:
    """用记录的 entry_price + 实时标记价算这一组的合计浮盈（税前，做空）。
    价格拉不全返回 None（这轮跳过，不误触发）。"""
    total = 0.0
    for r in brows:
        mark = price_map.get(r["symbol"])
        if not mark:
            return None
        entry = r["entry_price"]
        amt   = r["position_amt"]
        if not entry or not amt:
            continue
        total += (entry - float(mark)) * amt   # 做空：跌了赚
    return total


def _mark_provisional_close(brows: list[dict], reason: str):
    """下平仓单后立即打上临时 close_time，避免监控循环重复触发；真实数值随后回填。"""
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in brows:
        db.update_open_log_8h(r["id"], {"close_time": now_ts, "close_reason": reason})


def close_batch_market(brows: list[dict], symbol_info: dict, reason: str):
    """整组立即市价平（+10U 触发）。只平本 batch 记录的数量（reduceOnly）。"""
    log.info(f"  整组市价平 {len(brows)} 单（{reason}）")
    for r in brows:
        sym = r["symbol"]; amt = r["position_amt"]; info = symbol_info.get(sym)
        if not info or not amt:
            continue
        place_close_market(sym, amt, info)
        time.sleep(0.2)


def close_batch_timed(brows: list[dict], symbol_info: dict, window_end: datetime):
    """窗口末定时平：限价 ladder 到 window_end-1min，再市价兜底。只处理本 batch。"""
    market_dt = window_end - timedelta(minutes=CLOSE_MARKET_MIN)
    pending = {}
    for r in brows:
        sym = r["symbol"]; amt = r["position_amt"]; info = symbol_info.get(sym)
        if not info or not amt:
            continue
        try:
            ref = get_mark_price(sym)
        except Exception as e:
            log.warning(f"  {sym} 取 mark 失败：{e}")
            continue
        res = place_close_limit(sym, amt, info, ref)
        if res:
            res["amt"] = amt
            pending[sym] = res
        time.sleep(0.15)

    attempt = 2
    while pending and datetime.now() < market_dt and attempt <= MAX_LIMIT_ATTEMPTS:
        sleep_sec = min(ATTEMPT_INTERVAL_SEC,
                        max(0, (market_dt - datetime.now()).total_seconds()))
        if sleep_sec > 0:
            time.sleep(sleep_sec)
        try:
            price_map = get_all_mark_prices()
        except Exception:
            price_map = {}
        still = {}
        for sym, data in pending.items():
            try:
                order = get_order(sym, data["orderId"])
            except Exception:
                still[sym] = data
                continue
            status = order.get("status", "UNKNOWN")
            if status == "FILLED":
                continue
            if status == "PARTIALLY_FILLED":
                still[sym] = data
                continue
            cancel_order(sym, data["orderId"])
            time.sleep(0.3)
            if get_order(sym, data["orderId"]).get("status") == "FILLED":
                continue
            ref = price_map.get(sym) or 0
            if not ref:
                try:
                    ref = get_mark_price(sym)
                except Exception:
                    continue
            new_res = place_close_limit(sym, data["amt"], data["info"], ref)
            if new_res:
                new_res["amt"] = data["amt"]
                still[sym] = new_res
            time.sleep(0.15)
        pending = still
        attempt += 1

    # 市价兜底：对本 batch 仍有仓的 symbol
    sleep_sec = max(0, (market_dt - datetime.now()).total_seconds())
    if sleep_sec > 0:
        time.sleep(sleep_sec)
    positions = auth_get("/fapi/v2/positionRisk")
    held = {p["symbol"]: float(p["positionAmt"]) for p in positions if float(p["positionAmt"]) != 0}
    for r in brows:
        sym = r["symbol"]; info = symbol_info.get(sym)
        if not info:
            continue
        if held.get(sym):
            cancel_all_orders(sym)
            time.sleep(0.3)
            place_close_market(sym, r["position_amt"], info)
            time.sleep(0.2)


def close_batch(brows: list[dict], reason: str, market_now: bool, window_end: datetime | None = None):
    """平掉一个 batch 并回填。market_now=True 立即市价（+10U），否则限价 ladder。"""
    if not LIVE:
        pnl_hint = "（观察模式，不下单）"
        log.info(f"  [dry] 平 batch {reason} 共 {len(brows)} 单 {pnl_hint}")
        return
    _, symbol_info = get_exchange_info()
    if market_now:
        close_batch_market(brows, symbol_info, reason)
    else:
        close_batch_timed(brows, symbol_info, window_end)
    _mark_provisional_close(brows, reason)
    log.info(f"  平仓完成，等 {SETTLE_DELAY_SEC}s 回填账单")
    time.sleep(SETTLE_DELAY_SEC)
    writeback_batch(brows, reason)


# ── 回填 ──

def writeback_batch(brows: list[dict], reason: str):
    """对本 batch 每单查 userTrades，回填真实 close_price / pnl / commission / funding。"""
    now_ms = int(time.time() * 1000)
    for r in brows:
        sym = r["symbol"]
        open_dt = datetime.strptime(r["open_time"], "%Y-%m-%d %H:%M:%S")
        open_ms = int(open_dt.timestamp() * 1000)
        try:
            trades = auth_get("/fapi/v1/userTrades", {
                "symbol": sym, "startTime": open_ms - 60_000,
                "endTime": now_ms, "limit": 1000,
            })
        except Exception as e:
            log.warning(f"  {sym}#{r['id']} 查 userTrades 失败：{e}")
            continue
        sell_trades = [t for t in trades if t["side"] == "SELL"]
        buy_trades  = [t for t in trades if t["side"] == "BUY"]
        if not buy_trades:
            log.info(f"  {sym}#{r['id']} 暂无 BUY 成交，跳过（下轮再补）")
            continue

        def weighted_avg(ts):
            qty = sum(float(t["qty"]) for t in ts)
            if qty == 0:
                return 0, 0, 0
            value = sum(float(t["price"]) * float(t["qty"]) for t in ts)
            comm  = sum(float(t["commission"]) for t in ts)
            return value / qty, qty, -abs(comm)

        open_avg, open_qty, open_comm = weighted_avg(sell_trades)
        close_avg, close_qty, close_comm = weighted_avg(buy_trades)
        close_ms = max(int(t["time"]) for t in buy_trades)
        close_time = datetime.fromtimestamp(close_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")

        entry = r["entry_price"] or open_avg or 0
        amt   = abs(r["position_amt"] or close_qty or 0)
        if entry == 0 or amt == 0:
            log.warning(f"  {sym}#{r['id']} entry/amt 为 0，跳过")
            continue
        pnl = (entry - close_avg) * amt           # 做空
        margin = entry * amt / (r["leverage"] or LEVERAGE)
        roe = pnl / margin * 100 if margin else 0
        try:
            funding = query_funding(sym, open_ms, close_ms + 1000)
        except Exception:
            funding = None

        fields = {
            "close_time":       close_time,
            "close_price":      round(close_avg, 8),
            "position_amt":     round(amt, 8),
            "unrealized_pnl":   round(pnl, 4),
            "roe_pct":          round(roe, 2),
            "open_commission":  round(open_comm, 6) if open_comm else None,
            "close_commission": round(close_comm, 6),
            "funding_fee":      round(funding, 6) if funding is not None else None,
            "close_reason":     reason,
        }
        if not r["entry_price"] and open_avg:
            fields["entry_price"] = round(open_avg, 8)
        db.update_open_log_8h(r["id"], fields)
        log.info(f"  {sym}#{r['id']} 回填: close={close_avg:.6f} pnl={pnl:+.4f} "
                 f"roe={roe:+.2f}% funding={funding} [{reason}]")


def monitor_batches():
    """遍历所有未平 batch：+10U 立即市价平；到窗口末定时平。"""
    rows = db.get_open_log_8h_unclosed()
    if not rows:
        return
    batches: dict = {}
    for r in rows:
        batches.setdefault((r["open_anchor"], r["side"]), []).append(r)
    try:
        price_map = get_all_mark_prices()
    except Exception as e:
        log.warning(f"取全量标记价失败：{e}")
        return
    now = datetime.now()
    for (anchor, side), brows in batches.items():
        if not anchor:
            continue
        try:
            anchor_dt = datetime.strptime(anchor, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        window_end = anchor_dt + timedelta(hours=WINDOW_HOURS)
        pnl = batch_pnl(brows, price_map)

        if pnl is not None and pnl >= TARGET_GROUP_PNL:
            log.info(f"★ +10U 触发  {side} @ {anchor}  合计浮盈 {pnl:+.2f}U → 整组市价平")
            close_batch(brows, reason="组内+10u", market_now=True)
            continue
        if now >= window_end - timedelta(minutes=CLOSE_PREP_MIN):
            log.info(f"batch {side} @ {anchor} 到窗口末（浮盈 {pnl}）→ 定时平")
            close_batch(brows, reason="8h_timed", market_now=False, window_end=window_end)


# ── 主循环 ──

def _is_in_open_window(now: datetime) -> bool:
    return (now.hour in OPEN_HOURS
            and OPEN_MINUTE <= now.minute < OPEN_MINUTE + OPEN_WINDOW_MIN)


def _open_anchor_of(now: datetime) -> datetime:
    return now.replace(minute=OPEN_MINUTE, second=0, microsecond=0)


def main():
    db.init_db()
    log.info("8h 实盘策略启动  LIVE=%s" % LIVE)
    if not LIVE:
        log.warning("★ 观察模式（未设 REAL_8H_LIVE=1）：只选币/打印/计算，不下真单、不写库")
    log.info(f"  开仓：每天 {OPEN_HOURS} 点 {OPEN_MINUTE} 分")
    log.info(f"  方向：{[d[0] for d in DIRECTIONS]}，各 TOP{TOP_N}")
    log.info(f"  平仓：组内浮盈 ≥ {TARGET_GROUP_PNL}U 提前市价平，否则跑满 {WINDOW_HOURS}h 定时平")
    log.info(f"  参数：{LEVERAGE}x  {MARGIN_PER_POS}U/单  名义 {MARGIN_PER_POS*LEVERAGE}U")

    last_open_anchor = None   # 观察模式下用于同一 anchor 去重
    while True:
        try:
            now = datetime.now()
            # 1) 开仓窗口 XX:30 ~ XX:34
            if _is_in_open_window(now):
                anchor = _open_anchor_of(now)
                anchor_ts = anchor.strftime("%Y-%m-%d %H:%M:%S")
                if LIVE:
                    do_open = any(not _opened_already(anchor_ts, d[0]) for d in DIRECTIONS)
                else:
                    do_open = (anchor_ts != last_open_anchor)
                if do_open:
                    last_open_anchor = anchor_ts
                    try:
                        run_open_cycle(anchor)
                    except Exception as e:
                        log.error(f"开仓周期异常：{e}", exc_info=True)

            # 2) 监控所有 batch（+10U / 窗口末）
            try:
                monitor_batches()
            except Exception as e:
                log.error(f"监控异常：{e}", exc_info=True)

            # 3) 回填重试：已平但真实数值没填上的（userTrades 结算延迟）
            if LIVE:
                try:
                    pending = db.get_open_log_8h_pending_writeback()
                    if pending:
                        by_reason: dict = {}
                        for r in pending:
                            by_reason.setdefault(r.get("close_reason") or "8h_timed", []).append(r)
                        for reason, rows_r in by_reason.items():
                            writeback_batch(rows_r, reason)
                except Exception as e:
                    log.error(f"回填重试异常：{e}", exc_info=True)

            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            log.info("退出")
            break
        except Exception as e:
            log.error(f"主循环异常：{e}", exc_info=True)
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
