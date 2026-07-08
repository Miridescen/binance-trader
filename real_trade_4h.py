"""
4h 周期实盘策略（精简版）。

规则：
  - 每天 6 个开仓周期：00:30 / 04:30 / 08:30 / 12:30 / 16:30 / 20:30
  - 每个周期开 2 个方向：涨幅榜-空（无过滤）+ 跌幅榜-空（无过滤），各 TOP10
  - 仅筛选：24h 交易量 ≥ 1000 万 USDT
  - 杠杆 3x，每单保证金 10 USDT，名义 30 USDT
  - 全部 4h 定平，没有提前止盈

开仓（10 分钟限价兜底）：
  XX:30:00 拉 24h ticker → 各 TOP10 → 按标记价挂限价 SELL
  XX:32/34/36/38 撤单换价重挂（5 轮限价）
  XX:40:00 仍未成交 → 撤单 → 市价单

平仓（提前 10 分钟限价兜底）：
  XX:20:00 对所有未平仓挂限价 BUY (reduceOnly)
  XX:22/24/26/28 撤单换价重挂
  XX:29:00 强制市价兜底
  XX:30:00 之前账户清空

数据：open_log_4h 表，所有字段（含 commission/funding_fee）等成交后回填，保证真实。
"""
from __future__ import annotations
import math
import time
import logging
from datetime import datetime, timedelta

from binance_client import (
    auth_get, auth_post, auth_delete,
    get_exchange_info, get_ticker_24h, get_mark_price, get_all_mark_prices,
    is_hedge_mode,
)
import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ── 策略参数 ──
LEVERAGE         = 3
MARGIN_PER_POS   = 10
MIN_VOLUME       = 10_000_000
TOP_N            = 10

# 时间表
OPEN_HOURS       = (0, 4, 8, 12, 16, 20)  # 开仓整点
OPEN_MINUTE      = 30
OPEN_WINDOW_MIN  = 5      # 开仓滑动窗口（用于幂等检测）
CLOSE_HOURS      = (0, 4, 8, 12, 16, 20)  # 平仓整点（提前 10 分钟即 :20 开始挂限价）
CLOSE_PREP_MIN   = 20     # 平仓提前分钟（XX:20 开始挂限价）
CLOSE_MARKET_MIN = 29     # 市价兜底分钟（XX:29 强制市价）

# 限价单换价节奏
ATTEMPT_INTERVAL_SEC = 120   # 每 2 分钟检查
MAX_LIMIT_ATTEMPTS   = 5     # 5 次限价（0/2/4/6/8 分钟）→ 第 10 分钟市价兜底

# 主循环
CHECK_INTERVAL  = 15  # 秒
SETTLE_DELAY_SEC = 12  # 平仓完成后等几秒再查 income 账单


# ── 精度工具 ──

def floor_to_step(value: float, step: float) -> float:
    # round 抵消浮点误差（否则 86.3/0.1=862.999… 会被 floor 成 862 → 86.2，平仓少平留尾）
    return math.floor(round(value / step, 8)) * step

def round_to_tick(value: float, tick: float) -> float:
    decimals = max(0, -int(math.floor(math.log10(tick))))
    return round(round(value / tick) * tick, decimals)

def fmt(value: float, step: float) -> str:
    decimals = max(0, -int(math.floor(math.log10(step))))
    return f"{value:.{decimals}f}"


# ── 币安基础工具 ──

def set_leverage(symbol: str) -> bool:
    res = auth_post("/fapi/v1/leverage", {"symbol": symbol, "leverage": LEVERAGE})
    if "leverage" in res:
        return True
    log.error(f"  {symbol} 杠杆设置失败：{res.get('msg', res)}")
    return False

def get_order(symbol: str, order_id: int) -> dict:
    return auth_get("/fapi/v1/order", {"symbol": symbol, "orderId": order_id})

def cancel_order(symbol: str, order_id: int):
    try:
        auth_delete("/fapi/v1/order", {"symbol": symbol, "orderId": order_id})
    except Exception as e:
        log.warning(f"  撤单 {symbol}#{order_id} 异常（可能已成交）：{e}")

def cancel_all_orders(symbol: str):
    try:
        auth_delete("/fapi/v1/allOpenOrders", {"symbol": symbol})
    except Exception as e:
        log.warning(f"  撤所有 {symbol} 异常：{e}")


def query_commission(symbol: str, start_ms: int, end_ms: int) -> float:
    """指定 symbol 在 [start_ms, end_ms] 区间的 commission 总和（负数表示支出）"""
    data = auth_get("/fapi/v1/income", {
        "symbol": symbol, "incomeType": "COMMISSION",
        "startTime": start_ms, "endTime": end_ms, "limit": 1000,
    })
    return sum(float(item["income"]) for item in data)


def query_funding(symbol: str, start_ms: int, end_ms: int) -> float:
    """指定 symbol 在 [start_ms, end_ms] 区间的资金费总和（正=收入，负=支出）"""
    data = auth_get("/fapi/v1/income", {
        "symbol": symbol, "incomeType": "FUNDING_FEE",
        "startTime": start_ms, "endTime": end_ms, "limit": 1000,
    })
    return sum(float(item["income"]) for item in data)


# ── 选币 ──

def select_top10(side_label: str) -> tuple[list, dict]:
    """返回 (TOP10 ticker 列表, exchange_info)。side_label 用来日志输出。"""
    valid_symbols, symbol_info = get_exchange_info()
    tickers = get_ticker_24h(valid_symbols, MIN_VOLUME)
    tickers.sort(key=lambda x: float(x["priceChangePercent"]), reverse=True)
    if "涨幅" in side_label:
        return tickers[:TOP_N], symbol_info
    else:
        return tickers[-TOP_N:][::-1], symbol_info


# ── 开仓核心 ──

def place_open_limit(symbol: str, info: dict, ref_price: float) -> dict | None:
    """挂限价 SELL（开空）。ref_price 是参考价（标记价），按 tick 对齐。"""
    step  = info["step_size"]
    tick  = info["tick_size"]
    min_n = info["min_notional"]

    qty   = floor_to_step(MARGIN_PER_POS * LEVERAGE / ref_price, step)
    price = round_to_tick(ref_price, tick)
    if qty * ref_price < min_n:
        log.warning(f"  {symbol} 名义价值 {qty*ref_price:.2f} < min {min_n}，跳过")
        return None

    params = {
        "symbol": symbol, "side": "SELL", "type": "LIMIT",
        "price": fmt(price, tick), "quantity": fmt(qty, step),
        "timeInForce": "GTC",
    }
    res = auth_post("/fapi/v1/order", params)
    if "orderId" in res:
        log.info(f"  {symbol} 限价 SELL 挂 {fmt(price, tick)} × {fmt(qty, step)}")
        return {"orderId": res["orderId"], "qty": qty, "price": price, "info": info}
    log.error(f"  {symbol} 挂单失败：{res.get('msg', res)}")
    return None


def place_open_market(symbol: str, info: dict) -> dict | None:
    """市价 SELL 兜底"""
    step = info["step_size"]
    mark = get_mark_price(symbol)
    qty  = floor_to_step(MARGIN_PER_POS * LEVERAGE / mark, step)
    if qty * mark < info["min_notional"]:
        log.warning(f"  {symbol} 市价兜底跳过（名义价值不足）")
        return None
    res = auth_post("/fapi/v1/order", {
        "symbol": symbol, "side": "SELL", "type": "MARKET",
        "quantity": fmt(qty, step),
    })
    if "orderId" in res:
        log.info(f"  {symbol} 市价 SELL ✅ 数量 {fmt(qty, step)}")
        return {"orderId": res["orderId"], "qty": qty, "info": info}
    log.error(f"  {symbol} 市价兜底失败：{res.get('msg', res)}")
    return None


def insert_open_record(symbol: str, side_label: str, order_id: int, anchor_ts: str) -> int | None:
    """开仓成交后，按 order 实际成交数据 INSERT open_log_4h，返回新行 id。
    anchor_ts: 该周期的 :30 整点时刻（如 '2026-05-28 04:30:00'），用于稳定分组。"""
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
    update_ms = int(order.get("updateTime", time.time()*1000))
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
    new_id = db.insert_open_log_4h(row)
    log.info(f"  {symbol} INSERT open_log_4h#{new_id}: entry={avg_price} qty={executed} @ {open_time} (anchor {anchor_ts})")
    return new_id


def run_open_cycle(anchor: datetime):
    """完整开仓周期：10 分钟限价 + 最后市价兜底。阻塞执行。"""
    anchor_ts = anchor.strftime("%Y-%m-%d %H:%M:%S")
    log.info(f"═══ 开仓周期开始 {anchor_ts} ═══")

    # ── 第一步：拉两榜 TOP10 ──
    g_tickers, symbol_info = select_top10("涨幅榜")
    l_tickers, _           = select_top10("跌幅榜")
    targets = [(t["symbol"], "涨幅榜-空（无过滤）") for t in g_tickers] + \
              [(t["symbol"], "跌幅榜-空（无过滤）") for t in l_tickers]
    log.info(f"涨幅 TOP{len(g_tickers)}: {[t['symbol'] for t in g_tickers]}")
    log.info(f"跌幅 TOP{len(l_tickers)}: {[t['symbol'] for t in l_tickers]}")

    # ── 第二步：限价单首挂 ──
    pending = {}   # symbol -> {orderId, qty, price, info, side_label}
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

    # ── 第三步：每 2 分钟扫一次（5 轮限价） ──
    for attempt in range(2, MAX_LIMIT_ATTEMPTS + 1):
        if not pending:
            break
        log.info(f"等待 {ATTEMPT_INTERVAL_SEC}s 进入第 {attempt} 轮检查...")
        time.sleep(ATTEMPT_INTERVAL_SEC)

        still = {}
        # 批量拉一次最新价
        try:
            price_map = get_all_mark_prices()
        except Exception:
            price_map = {}

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
                insert_open_record(sym, data["side_label"], data["orderId"], anchor_ts)
                continue
            if status == "PARTIALLY_FILLED":
                log.info(f"  {sym} 部分成交，继续等")
                still[sym] = data
                continue

            # 撤单换价重挂
            log.info(f"  {sym} status={status}，撤单换价（第 {attempt} 轮）")
            cancel_order(sym, data["orderId"])
            time.sleep(0.3)
            recheck = get_order(sym, data["orderId"]).get("status")
            if recheck == "FILLED":
                log.info(f"  {sym} 撤单时已成交")
                insert_open_record(sym, data["side_label"], data["orderId"], anchor_ts)
                continue

            ref = price_map.get(sym) or 0
            if not ref:
                try:
                    ref = get_mark_price(sym)
                except Exception:
                    log.warning(f"  {sym} 取价失败")
                    continue
            new_res = place_open_limit(sym, data["info"], ref)
            if new_res:
                new_res["side_label"] = data["side_label"]
                still[sym] = new_res
            time.sleep(0.15)

        pending = still

    # ── 第四步：市价兜底 ──
    if pending:
        log.warning(f"仍有 {len(pending)} 个未成交，市价兜底")
        positions = auth_get("/fapi/v2/positionRisk")
        held = {p["symbol"] for p in positions if float(p["positionAmt"]) != 0}

        for sym, data in pending.items():
            cancel_order(sym, data["orderId"])
            time.sleep(0.3)
            recheck = get_order(sym, data["orderId"]).get("status")
            if recheck == "FILLED":
                log.info(f"  {sym} 撤单时已成交")
                insert_open_record(sym, data["side_label"], data["orderId"], anchor_ts)
                continue
            if sym in held:
                log.info(f"  {sym} 已有持仓，跳过市价兜底")
                continue
            res = place_open_market(sym, data["info"])
            if res:
                time.sleep(1)  # 等市价单成交
                insert_open_record(sym, data["side_label"], res["orderId"], anchor_ts)
            time.sleep(0.15)

    log.info(f"═══ 开仓周期结束 {anchor_ts} ═══\n")


# ── 平仓核心 ──

def place_close_limit(symbol: str, amt: float, info: dict, ref_price: float) -> dict | None:
    """挂限价 BUY (reduceOnly)，平掉空头 amt 数量"""
    step = info["step_size"]
    tick = info["tick_size"]
    qty   = floor_to_step(abs(amt), step)
    price = round_to_tick(ref_price, tick)
    if qty == 0:
        return None
    params = {
        "symbol": symbol, "side": "BUY", "type": "LIMIT",
        "price": fmt(price, tick), "quantity": fmt(qty, step),
        "timeInForce": "GTC", "reduceOnly": "true",
    }
    res = auth_post("/fapi/v1/order", params)
    if "orderId" in res:
        log.info(f"  {symbol} 限价 BUY 平 挂 {fmt(price, tick)} × {fmt(qty, step)}")
        return {"orderId": res["orderId"], "qty": qty, "price": price, "info": info}
    log.error(f"  {symbol} 平单挂单失败：{res.get('msg', res)}")
    return None


def place_close_market(symbol: str, amt: float, info: dict) -> dict | None:
    step = info["step_size"]
    qty  = floor_to_step(abs(amt), step)
    if qty == 0:
        return None
    res = auth_post("/fapi/v1/order", {
        "symbol": symbol, "side": "BUY", "type": "MARKET",
        "quantity": fmt(qty, step), "reduceOnly": "true",
    })
    if "orderId" in res:
        log.info(f"  {symbol} 市价 BUY 平 ✅ × {fmt(qty, step)}")
        return {"orderId": res["orderId"], "qty": qty, "info": info}
    log.error(f"  {symbol} 市价平失败：{res.get('msg', res)}")
    return None


def run_close_cycle(close_anchor: datetime):
    """完整平仓周期：XX:20 起 10 分钟限价 + XX:29 市价兜底"""
    anchor_ts = close_anchor.strftime("%Y-%m-%d %H:%M:%S")
    log.info(f"═══ 平仓周期开始 {anchor_ts} ═══")

    # 拉账户持仓
    positions = auth_get("/fapi/v2/positionRisk")
    actives = [p for p in positions if float(p["positionAmt"]) != 0]
    if not actives:
        log.info("  无持仓，跳过平仓")
        log.info(f"═══ 平仓周期结束 {anchor_ts} ═══\n")
        return

    log.info(f"待平 {len(actives)} 个持仓")
    _, symbol_info = get_exchange_info()

    # 第一轮限价挂单
    pending = {}
    for p in actives:
        sym = p["symbol"]
        amt = float(p["positionAmt"])
        info = symbol_info.get(sym)
        if not info:
            log.warning(f"  {sym} 无 info，跳过限价直接转市价")
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

    # 4 次换价（XX:22 24 26 28）
    target_market_dt = close_anchor.replace(minute=CLOSE_MARKET_MIN, second=0, microsecond=0)
    for attempt in range(2, MAX_LIMIT_ATTEMPTS + 1):
        if not pending:
            break
        # 计算下一次唤醒时间：anchor + (attempt-1)*2 分钟
        next_wake_dt = close_anchor + timedelta(minutes=(attempt - 1) * 2)
        sleep_sec = max(0, (next_wake_dt - datetime.now()).total_seconds())
        if sleep_sec > 0:
            log.info(f"等待 {sleep_sec:.0f}s 进入第 {attempt} 轮平仓检查...")
            time.sleep(sleep_sec)

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
                log.info(f"  {sym} ✅ 平仓成交")
                continue
            if status == "PARTIALLY_FILLED":
                log.info(f"  {sym} 部分成交，继续等")
                still[sym] = data
                continue

            log.info(f"  {sym} status={status}，撤单换价（第 {attempt} 轮）")
            cancel_order(sym, data["orderId"])
            time.sleep(0.3)
            recheck = get_order(sym, data["orderId"]).get("status")
            if recheck == "FILLED":
                log.info(f"  {sym} 撤单时已成交")
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

    # XX:29 市价兜底
    sleep_sec = max(0, (target_market_dt - datetime.now()).total_seconds())
    if sleep_sec > 0:
        log.info(f"等 {sleep_sec:.0f}s 进入市价兜底（{target_market_dt.strftime('%H:%M')}）")
        time.sleep(sleep_sec)

    # 重新拉一次持仓，对仍未平的市价
    positions = auth_get("/fapi/v2/positionRisk")
    still_open = [p for p in positions if float(p["positionAmt"]) != 0]
    if still_open:
        log.warning(f"市价兜底 {len(still_open)} 个持仓")
        for p in still_open:
            sym = p["symbol"]
            amt = float(p["positionAmt"])
            info = symbol_info.get(sym)
            if not info:
                continue
            # 先撤所有该 symbol 限价单
            cancel_all_orders(sym)
            time.sleep(0.3)
            place_close_market(sym, amt, info)
            time.sleep(0.2)

    log.info(f"═══ 平仓周期结束 {anchor_ts}，等 {SETTLE_DELAY_SEC}s 后回填账单 ═══")
    time.sleep(SETTLE_DELAY_SEC)
    writeback_closes()


# ── 平仓后回填 ──

def writeback_closes():
    """对所有未回填 close_time 的 open_log_4h 记录，查实际平仓信息 + 手续费 + 资金费"""
    unclosed = db.get_open_log_4h_unclosed()
    if not unclosed:
        log.info("  无待回填记录")
        return

    log.info(f"  回填 {len(unclosed)} 条记录的平仓信息")
    now_ms = int(time.time() * 1000)

    for r in unclosed:
        sym  = r["symbol"]
        # 查实际平仓信息：用 /fapi/v1/userTrades 拿 sym 在 open_time 之后的所有交易，
        # 按 isBuyer=True（平空对应买入）取最后一批，加权平均 = close_price
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

        # 卖单（开仓 SELL）+ 买单（平仓 BUY）
        sell_trades = [t for t in trades if t["side"] == "SELL"]  # 开仓
        buy_trades  = [t for t in trades if t["side"] == "BUY"]   # 平仓
        if not buy_trades:
            log.info(f"  {sym}#{r['id']} 暂无 BUY 成交，跳过（可能还没成交完）")
            continue

        # 加权均价
        def weighted_avg(ts):
            qty = sum(float(t["qty"]) for t in ts)
            if qty == 0:
                return 0, 0, 0
            value = sum(float(t["price"]) * float(t["qty"]) for t in ts)
            comm  = sum(float(t["commission"]) for t in ts)
            return value / qty, qty, -abs(comm)

        # 开仓部分（用实际成交校验）
        open_avg, open_qty, open_comm = weighted_avg(sell_trades)
        close_avg, close_qty, close_comm = weighted_avg(buy_trades)

        # 平仓时间 = buy_trades 最后一笔 time
        close_ms = max(int(t["time"]) for t in buy_trades)
        close_time = datetime.fromtimestamp(close_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")

        entry = r["entry_price"] or open_avg or 0
        amt   = abs(r["position_amt"] or close_qty or 0)
        if entry == 0 or amt == 0:
            log.warning(f"  {sym}#{r['id']} entry/amt 为 0，跳过")
            continue

        # 做空 PnL = (entry - close) * amt
        pnl = (entry - close_avg) * amt
        margin = entry * amt / (r["leverage"] or LEVERAGE)
        roe = pnl / margin * 100 if margin else 0

        # 资金费（[open_ms, close_ms+1000]）
        try:
            funding = query_funding(sym, open_ms, close_ms + 1000)
        except Exception as e:
            log.warning(f"  {sym}#{r['id']} 查 funding 失败：{e}")
            funding = None

        # close_reason：如果有 MARKET 类型的 trade（无法直接判断 type，用 commission 比率判断 maker/taker）
        # 简化：所有 trades 都是 maker 标 4h_limit，否则 4h_market
        # 实际 userTrades 的 maker 字段：True = maker，False = taker
        any_taker_close = any(not t.get("maker", False) for t in buy_trades)
        close_reason = "4h_market" if any_taker_close else "4h_limit"

        fields = {
            "close_time":       close_time,
            "close_price":      round(close_avg, 8),
            "position_amt":     round(amt, 8),
            "unrealized_pnl":   round(pnl, 4),
            "roe_pct":          round(roe, 2),
            "open_commission":  round(open_comm, 6) if open_comm else None,
            "close_commission": round(close_comm, 6),
            "funding_fee":      round(funding, 6) if funding is not None else None,
            "close_reason":     close_reason,
        }
        # entry_price 若为 NULL，也用实际开仓均价补上
        if not r["entry_price"] and open_avg:
            fields["entry_price"] = round(open_avg, 8)
        db.update_open_log_4h(r["id"], fields)
        log.info(f"  {sym}#{r['id']} 回填: close={close_avg:.6f} pnl={pnl:+.4f} roe={roe:+.2f}% "
                 f"open_comm={open_comm} close_comm={close_comm} funding={funding} [{close_reason}]")


# ── 主循环 ──

def _is_in_open_window(now: datetime) -> bool:
    return (now.hour in OPEN_HOURS
            and OPEN_MINUTE <= now.minute < OPEN_MINUTE + OPEN_WINDOW_MIN)


def _is_close_anchor(now: datetime) -> bool:
    """XX:20:00 ~ XX:20:30 这一短窗口触发平仓周期（只触发一次）"""
    return now.hour in CLOSE_HOURS and now.minute == CLOSE_PREP_MIN and now.second < 30


def _open_anchor_of(now: datetime) -> datetime:
    return now.replace(minute=OPEN_MINUTE, second=0, microsecond=0)


def _close_anchor_of(now: datetime) -> datetime:
    return now.replace(minute=CLOSE_PREP_MIN, second=0, microsecond=0)


def _opened_already(anchor_ts: str) -> bool:
    """该 anchor 时刻是否已经开过仓（5 分钟容差内 INSERT 过）"""
    return len(db.get_open_log_4h_by_open_time(anchor_ts)) > 0


def main():
    db.init_db()
    log.info("4h 实盘策略启动")
    log.info(f"  开仓时刻：每天 {OPEN_HOURS} 点 {OPEN_MINUTE} 分（{OPEN_WINDOW_MIN} 分钟滑动）")
    log.info(f"  平仓时刻：每天 {CLOSE_HOURS} 点 {CLOSE_PREP_MIN} 分开始挂限价 → {CLOSE_MARKET_MIN} 分市价兜底")
    log.info(f"  方向：涨幅榜-空（无过滤）+ 跌幅榜-空（无过滤），各 TOP{TOP_N}")
    log.info(f"  参数：杠杆 {LEVERAGE}x  保证金 {MARGIN_PER_POS} U/单  名义 {MARGIN_PER_POS*LEVERAGE} U")

    while True:
        try:
            now = datetime.now()

            # 1) 平仓 anchor：XX:20:00 ~ XX:20:30
            if _is_close_anchor(now):
                close_anchor = _close_anchor_of(now)
                try:
                    run_close_cycle(close_anchor)
                except Exception as e:
                    log.error(f"平仓周期异常：{e}", exc_info=True)
                # 平仓周期占用约 9 分钟，结束时通常已过开仓 anchor 之前
                continue

            # 2) 开仓 anchor：XX:30 ~ XX:34（5 分钟容差）
            if _is_in_open_window(now):
                anchor = _open_anchor_of(now)
                anchor_ts = anchor.strftime("%Y-%m-%d %H:%M:%S")
                if not _opened_already(anchor_ts):
                    try:
                        run_open_cycle(anchor)
                    except Exception as e:
                        log.error(f"开仓周期异常：{e}", exc_info=True)
                continue

            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            log.info("退出")
            break
        except Exception as e:
            log.error(f"主循环异常：{e}", exc_info=True)
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
