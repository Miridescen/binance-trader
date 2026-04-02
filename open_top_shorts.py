"""
每天定时策略：
  08:50 → 撤销所有未成交限价单 + 市价平掉所有持仓
  09:00 → 涨幅榜 TOP20（涨幅 >= 5%）开 3 倍限价空单，每单保证金 10 USDT
         跌幅榜 TOP10（跌幅 >= 8%）开 3 倍限价多单，每单保证金 10 USDT
  未成交则每 60 秒换价重下，最多 10 次，超过后改市价单
"""

import math
import os
import time
import logging
from datetime import datetime, timedelta
from binance_client import (
    auth_get, auth_post, auth_delete,
    get_exchange_info, get_ticker_24h, get_mark_price, is_hedge_mode,
    get_coin_market_data, get_btc_change_pct, get_all_funding_rates,
    get_commissions_by_symbol, get_oi_changes, get_long_short_ratios,
)
import db
import notify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

LEVERAGE             = 3
MARGIN_PER_POS       = 60
TOP_N_SHORT          = 10       # 空单最多开仓数
TOP_N_LONG           = 10       # 多单最多开仓数
TOP_N                = max(TOP_N_SHORT, TOP_N_LONG)  # 兼容旧引用
MIN_CHANGE_SHORT     = 5.0      # 空单入场最低涨幅（%）
MAX_CHANGE_SHORT     = 35.0     # 空单入场最高涨幅（%），超过的波动太大容易反噬
MIN_CHANGE_LONG      = 8.0      # 多单入场最低跌幅（%）
CANDIDATE_BUFFER     = 6        # 候选池倍数，过滤无市值后取前 TOP_N_SHORT/LONG
MIN_VOLUME           = 10_000_000
ORDER_CHECK_INTERVAL = 60
MAX_RETRIES          = 10
LIMIT_CLOSE_HOUR, LIMIT_CLOSE_MINUTE = 8, 30   # 限价平仓开始时间
MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE = 8, 50 # 市价兜底平仓时间
OPEN_HOUR, OPEN_MINUTE = 9, 1
CLOSE_CHECK_INTERVAL = 60                       # 限价平仓检查间隔（秒）


# ── 格式工具 ───────────────────────────────────────────

def fmt_large(n: float) -> str:
    """将大数字格式化为 B / M 单位"""
    if n >= 1e9:
        return f"{n / 1e9:.2f}B"
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    if n > 0:
        return f"{n:.0f}"
    return "N/A"


# ── 精度工具 ───────────────────────────────────────────

def floor_to_step(value: float, step: float) -> float:
    return math.floor(value / step) * step

def round_to_tick(value: float, tick: float) -> float:
    return round(round(value / tick) * tick, max(0, -int(math.floor(math.log10(tick)))))

def fmt(value: float, step: float) -> str:
    return f"{value:.{max(0, -int(math.floor(math.log10(step))))}f}"


# ── 平仓逻辑 ───────────────────────────────────────────

def cancel_all_open_orders():
    open_orders = auth_get("/fapi/v1/openOrders")
    symbols = set(o["symbol"] for o in open_orders)
    for symbol in symbols:
        result = auth_delete("/fapi/v1/allOpenOrders", {"symbol": symbol})
        status = "✅" if result.get("code") == 200 else f"❌ {result.get('msg', result)}"
        log.info(f"撤单 {symbol} {status}")
        time.sleep(0.1)
    log.info(f"共撤销 {len(symbols)} 个交易对的挂单")

def close_all_positions_market(hedge: bool):
    """市价平掉所有持仓（兜底用）"""
    positions = auth_get("/fapi/v2/positionRisk")
    active    = [p for p in positions if float(p["positionAmt"]) != 0]
    if not active:
        log.info("当前无持仓，无需平仓")
        return
    closed = 0
    for p in active:
        symbol = p["symbol"]
        amt    = float(p["positionAmt"])
        side   = "BUY" if amt < 0 else "SELL"
        params = {"symbol": symbol, "side": side, "type": "MARKET",
                  "quantity": abs(amt), "reduceOnly": "true"}
        if hedge:
            params.pop("reduceOnly")
            params["positionSide"] = "SHORT" if amt < 0 else "LONG"
        result = auth_post("/fapi/v1/order", params)
        if "orderId" in result:
            log.info(f"市价平仓 {symbol} {'空→买' if side=='BUY' else '多→卖'} 数量 {abs(amt)} ✅")
            closed += 1
        else:
            log.error(f"市价平仓 {symbol} 失败：{result.get('msg', result)}")
        time.sleep(0.15)
    log.info(f"共市价平仓 {closed}/{len(active)} 个持仓")


def close_all_positions_limit(hedge: bool, symbol_info: dict) -> dict:
    """限价平掉所有持仓，返回 {symbol: orderId} 等待成交"""
    positions = auth_get("/fapi/v2/positionRisk")
    active    = [p for p in positions if float(p["positionAmt"]) != 0]
    if not active:
        log.info("当前无持仓，无需平仓")
        return {}

    pending = {}
    for p in active:
        symbol = p["symbol"]
        amt    = float(p["positionAmt"])
        mark   = float(p["markPrice"])
        side   = "BUY" if amt < 0 else "SELL"
        info   = symbol_info.get(symbol)
        if not info:
            log.warning(f"  {symbol} 无交易对信息，跳过限价平仓")
            continue

        tick = info["tick_size"]
        step = info["step_size"]
        price = round_to_tick(mark, tick)

        params = {
            "symbol": symbol, "side": side, "type": "LIMIT",
            "price": fmt(price, tick), "quantity": fmt(abs(amt), step),
            "timeInForce": "GTC", "reduceOnly": "true",
        }
        if hedge:
            params.pop("reduceOnly")
            params["positionSide"] = "SHORT" if amt < 0 else "LONG"

        result = auth_post("/fapi/v1/order", params)
        if "orderId" in result:
            log.info(f"限价平仓 {symbol} {'空→买' if side=='BUY' else '多→卖'} 数量 {fmt(abs(amt), step)} 限价 {fmt(price, tick)} ✅")
            pending[symbol] = {"orderId": result["orderId"], "amt": abs(amt), "info": info, "side": side, "hedge_side": "SHORT" if amt < 0 else "LONG"}
        else:
            log.error(f"限价平仓 {symbol} 失败：{result.get('msg', result)}")
        time.sleep(0.15)

    log.info(f"共挂限价平仓单 {len(pending)} 个")
    return pending

def save_close_log(positions: list, now: datetime):
    """平仓前把收益数据回填到数据库对应的开仓行；无匹配行则新增一行"""
    ts = now.strftime("%Y-%m-%d %H:%M:%S")

    for p in positions:
        amt      = float(p["positionAmt"])
        entry    = float(p["entryPrice"])
        mark     = float(p["markPrice"])
        pnl      = float(p["unRealizedProfit"])
        leverage = int(p["leverage"])
        margin   = entry * abs(amt) / leverage if leverage and entry else 0
        roe      = pnl / margin * 100 if margin else 0
        sym      = p["symbol"]

        close_data = {
            "close_time":     ts,
            "entry_price":    entry,
            "close_price":    mark,
            "position_amt":   abs(amt),
            "unrealized_pnl": pnl,
            "roe_pct":        roe,
            "leverage":       leverage,
            "close_reason":   "定时平仓",
        }

        db.update_close_data(sym, "", close_data)

    log.info(f"上周期收益已回填到数据库（{len(positions)} 条）")


def _patch_close_commissions(commissions: dict):
    """平仓后将手续费回填到数据库"""
    today = datetime.now().strftime("%Y-%m-%d")
    db.patch_close_commissions(commissions, today)


def print_close_summary(positions: list):
    """平仓前打印本批次多单/空单盈亏汇总"""
    longs  = [p for p in positions if float(p["positionAmt"]) > 0]
    shorts = [p for p in positions if float(p["positionAmt"]) < 0]

    def calc(ps):
        total_pnl = sum(float(p["unRealizedProfit"]) for p in ps)
        details = []
        for p in sorted(ps, key=lambda x: float(x["unRealizedProfit"]), reverse=True):
            amt    = float(p["positionAmt"])
            entry  = float(p["entryPrice"])
            mark   = float(p["markPrice"])
            pnl    = float(p["unRealizedProfit"])
            lev    = int(p["leverage"])
            margin = entry * abs(amt) / lev if lev and entry else 0
            roe    = pnl / margin * 100 if margin else 0
            details.append((p["symbol"], pnl, roe))
        return total_pnl, details

    long_total,  long_details  = calc(longs)
    short_total, short_details = calc(shorts)
    grand_total = long_total + short_total

    sep = "=" * 60
    print(sep)
    print(f"  【本批次收益汇总】{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(sep)
    print(f"  多单（{len(longs):>2} 笔）总盈亏：{long_total:>+10.2f} USDT")
    for sym, pnl, roe in long_details:
        print(f"    {sym:<16} {pnl:>+8.2f} USDT   ROE {roe:>+7.1f}%")
    print(f"  空单（{len(shorts):>2} 笔）总盈亏：{short_total:>+10.2f} USDT")
    for sym, pnl, roe in short_details:
        print(f"    {sym:<16} {pnl:>+8.2f} USDT   ROE {roe:>+7.1f}%")
    print(sep)
    print(f"  本批次总盈亏：{grand_total:>+.2f} USDT")
    print(sep)


def save_close_summary_csv(positions: list, now: datetime):
    """将本批次多空汇总写入数据库（每批次一行）"""
    longs  = [p for p in positions if float(p["positionAmt"]) > 0]
    shorts = [p for p in positions if float(p["positionAmt"]) < 0]
    long_pnl  = sum(float(p["unRealizedProfit"]) for p in longs)
    short_pnl = sum(float(p["unRealizedProfit"]) for p in shorts)

    db.insert_batch_summary({
        "close_time":  now.strftime("%Y-%m-%d %H:%M:%S"),
        "long_count":  len(longs),
        "long_pnl":    long_pnl,
        "short_count": len(shorts),
        "short_pnl":   short_pnl,
        "total_pnl":   long_pnl + short_pnl,
    })
    log.info("批次盈亏已写入数据库")


def run_limit_close():
    """08:30 第一阶段：限价平仓"""
    log.info("=" * 50)
    log.info("【限价平仓开始】08:30")
    close_start_ms = int(time.time() * 1000)
    hedge = is_hedge_mode()
    positions = auth_get("/fapi/v2/positionRisk")
    active = [p for p in positions if float(p["positionAmt"]) != 0]
    if active:
        print_close_summary(active)
        save_close_summary_csv(active, datetime.now())
        save_close_log(active, datetime.now())
        # 日报推送
        try:
            balance = next(
                (float(a["marginBalance"]) for a in auth_get("/fapi/v2/account").get("assets", []) if a["asset"] == "USDT"), 0
            )
            notify.send_daily_report(active, balance)
        except Exception as e:
            log.warning(f"日报推送失败：{e}")

    log.info("撤销所有挂单...")
    cancel_all_open_orders()

    log.info("获取交易对信息...")
    _, symbol_info = get_exchange_info()

    log.info("挂限价平仓单...")
    pending = close_all_positions_limit(hedge, symbol_info)

    # 每 60 秒检查一次，未成交的换价重挂，直到 08:50
    while pending:
        now = datetime.now()
        if now.hour == MARKET_CLOSE_HOUR and now.minute >= MARKET_CLOSE_MINUTE:
            break

        log.info(f"等待 {CLOSE_CHECK_INTERVAL}s 后检查限价平仓单（剩余 {len(pending)} 个）...")
        time.sleep(CLOSE_CHECK_INTERVAL)

        still_pending = {}
        for symbol, data in pending.items():
            status = get_order_status(symbol, data["orderId"])
            if status == "FILLED":
                log.info(f"  {symbol} 限价平仓已成交 ✅")
            elif status == "PARTIALLY_FILLED":
                log.info(f"  {symbol} 部分成交，继续等待...")
                still_pending[symbol] = data
            else:
                # 未成交，换价重挂
                cancel_order(symbol, data["orderId"])
                time.sleep(0.3)
                mark = get_mark_price(symbol)
                info = data["info"]
                tick = info["tick_size"]
                step = info["step_size"]
                price = round_to_tick(mark, tick)
                params = {
                    "symbol": symbol, "side": data["side"], "type": "LIMIT",
                    "price": fmt(price, tick), "quantity": fmt(data["amt"], step),
                    "timeInForce": "GTC", "reduceOnly": "true",
                }
                if hedge:
                    params.pop("reduceOnly")
                    params["positionSide"] = data["hedge_side"]
                result = auth_post("/fapi/v1/order", params)
                if "orderId" in result:
                    log.info(f"  {symbol} 换价重挂 限价 {fmt(price, tick)} ✅")
                    still_pending[symbol] = {**data, "orderId": result["orderId"]}
                else:
                    log.error(f"  {symbol} 换价失败：{result.get('msg', result)}")
                    still_pending[symbol] = data
                time.sleep(0.15)

        pending = still_pending

    log.info(f"【限价平仓阶段结束】剩余未成交：{len(pending)} 个")
    return pending, close_start_ms


def run_market_close(remaining: dict, close_start_ms: int = 0):
    """08:50 第二阶段：市价兜底"""
    log.info("=" * 50)
    log.info("【市价兜底平仓】08:50")
    if not close_start_ms:
        close_start_ms = int(time.time() * 1000)
    hedge = is_hedge_mode()

    # 先撤掉所有未成交的限价单
    if remaining:
        log.info(f"撤销 {len(remaining)} 个未成交限价平仓单...")
        for symbol, data in remaining.items():
            cancel_order(symbol, data["orderId"])
            time.sleep(0.15)

    # 市价清掉剩余持仓
    close_all_positions_market(hedge)
    close_end_ms = int(time.time() * 1000)

    try:
        close_commissions = get_commissions_by_symbol(close_start_ms, close_end_ms)
        total_comm = sum(close_commissions.values())
        log.info(f"本批平仓手续费合计：{total_comm:.4f} USDT（{len(close_commissions)} 个币种）")
        if close_commissions:
            _patch_close_commissions(close_commissions)
    except Exception as e:
        log.warning(f"获取平仓手续费失败：{e}")

    log.info("【平仓全部完成】")


# ── 开单工具 ───────────────────────────────────────────

def set_leverage_verified(symbol: str) -> bool:
    """设置杠杆并验证成功，失败返回 False"""
    result = auth_post("/fapi/v1/leverage", {"symbol": symbol, "leverage": LEVERAGE})
    if "leverage" in result:
        return True
    log.error(f"  {symbol} 杠杆设置失败：{result.get('msg', result)}")
    return False

def get_order_status(symbol: str, order_id: int) -> str:
    result = auth_get("/fapi/v1/order", {"symbol": symbol, "orderId": order_id})
    return result.get("status", "UNKNOWN")

def cancel_order(symbol: str, order_id: int):
    auth_delete("/fapi/v1/order", {"symbol": symbol, "orderId": order_id})

def place_limit_order(symbol: str, info: dict, side: str, hedge: bool, attempt: int):
    """下限价单，返回 {orderId, info} 或 None"""
    step  = info["step_size"]
    tick  = info["tick_size"]
    min_n = info["min_notional"]

    mark_price = get_mark_price(symbol)
    qty        = floor_to_step(MARGIN_PER_POS * LEVERAGE / mark_price, step)
    price      = round_to_tick(mark_price, tick)

    if qty * mark_price < min_n:
        log.warning(f"  {symbol} 跳过（名义价值 {qty * mark_price:.2f} < 最低 {min_n:.2f} USDT）")
        return None

    params = {
        "symbol": symbol, "side": side, "type": "LIMIT",
        "price": fmt(price, tick), "quantity": fmt(qty, step), "timeInForce": "GTC",
    }
    if hedge:
        params["positionSide"] = "SHORT" if side == "SELL" else "LONG"

    order = auth_post("/fapi/v1/order", params)
    direction = "开空" if side == "SELL" else "开多"
    if "orderId" in order:
        log.info(f"  {symbol} 第{attempt}次{direction} ✅ 数量 {fmt(qty, step)} 限价 {fmt(price, tick)} 标记价 {mark_price}")
        return {"orderId": order["orderId"], "info": info}
    else:
        log.error(f"  {symbol} 第{attempt}次下单失败 code={order.get('code')} {order.get('msg', order)}")
        return None

def place_market_order(symbol: str, info: dict, side: str, hedge: bool):
    """市价兜底开仓"""
    step       = info["step_size"]
    mark_price = get_mark_price(symbol)
    qty        = floor_to_step(MARGIN_PER_POS * LEVERAGE / mark_price, step)
    params     = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": fmt(qty, step)}
    if hedge:
        params["positionSide"] = "SHORT" if side == "SELL" else "LONG"
    result    = auth_post("/fapi/v1/order", params)
    direction = "空" if side == "SELL" else "多"
    if "orderId" in result:
        log.info(f"  {symbol} 市价开{direction}成功 数量 {fmt(qty, step)} ✅")
    else:
        log.error(f"  {symbol} 市价开{direction}失败：{result.get('msg', result)}")


def run_batch_orders(label: str, tickers: list, side: str, symbol_info: dict, hedge: bool,
                     funding_rates: dict = None):
    direction = "涨幅" if side == "SELL" else "跌幅"
    funding_rates = funding_rates or {}
    log.info(f"── {label} ──")
    log.info(f"{direction}榜 TOP{len(tickers)}：{[t['symbol'] for t in tickers]}")

    # 第一轮下单
    pending = {}
    for i, ticker in enumerate(tickers, 1):
        symbol = ticker["symbol"]
        pct    = float(ticker["priceChangePercent"])
        info   = symbol_info.get(symbol)
        if not info:
            log.warning(f"[{i}/{TOP_N}] {symbol} 无交易对信息，跳过")
            continue

        fr = funding_rates.get(symbol)
        fr_str = f"  资金费率 {fr*100:+.4f}%" if fr is not None else ""
        log.info(f"[{i:>2}/{len(tickers)}] {symbol} {direction}幅 {pct:>+.2f}%{fr_str}")
        if not set_leverage_verified(symbol):
            log.warning(f"  {symbol} 杠杆设置失败，跳过此币种")
            continue

        result = place_limit_order(symbol, info, side, hedge, attempt=1)
        if result:
            pending[symbol] = result
        time.sleep(0.15)

    # 重试循环
    for attempt in range(2, MAX_RETRIES + 2):
        if not pending:
            break
        log.info(f"等待 {ORDER_CHECK_INTERVAL}s 后检查未成交订单（{label}）...")
        time.sleep(ORDER_CHECK_INTERVAL)

        still_pending = {}
        for symbol, data in pending.items():
            status = get_order_status(symbol, data["orderId"])

            if status == "FILLED":
                log.info(f"  {symbol} ✅ 已成交")

            elif status == "PARTIALLY_FILLED":
                # 部分成交：保留原单继续等，不撤不补
                log.info(f"  {symbol} 部分成交，继续等待...")
                still_pending[symbol] = data

            elif status in ("CANCELED", "EXPIRED", "REJECTED"):
                log.warning(f"  {symbol} 状态 {status}，重新下单")
                result = place_limit_order(symbol, data["info"], side, hedge, attempt)
                if result:
                    still_pending[symbol] = result
                time.sleep(0.15)

            else:  # NEW — 未成交，换价重下
                log.info(f"  {symbol} 未成交（{status}），换价重下（第{attempt}次）")
                cancel_order(symbol, data["orderId"])
                time.sleep(0.3)   # 等待撤单生效
                # 撤单后再查一次，确认不是刚好成交了
                recheck = get_order_status(symbol, data["orderId"])
                if recheck == "FILLED":
                    log.info(f"  {symbol} 撤单时已成交 ✅")
                    continue
                result = place_limit_order(symbol, data["info"], side, hedge, attempt)
                if result:
                    still_pending[symbol] = result
                time.sleep(0.15)

        pending = still_pending

    # 市价兜底
    if pending:
        log.warning(f"仍有 {len(pending)} 个 {label} 未成交，改用市价单...")
        # 先获取当前持仓，避免对已有持仓的币重复下单
        positions = auth_get("/fapi/v2/positionRisk")
        held_symbols = {p["symbol"] for p in positions if float(p["positionAmt"]) != 0}

        for symbol, data in pending.items():
            cancel_order(symbol, data["orderId"])
            time.sleep(0.3)
            # 检查撤单后是否已成交
            recheck = get_order_status(symbol, data["orderId"])
            if recheck == "FILLED":
                log.info(f"  {symbol} 撤单时已成交 ✅")
                continue
            if symbol in held_symbols:
                log.info(f"  {symbol} 已有持仓，跳过市价兜底")
                continue
            place_market_order(symbol, data["info"], side, hedge)
            time.sleep(0.15)


def log_event(event: str, detail: str):
    """向 events_log 表追加一条策略事件记录"""
    db.insert_event(event, detail)


def save_open_csv(rows: list, now: datetime):
    """将开单观察数据写入数据库（平仓字段留空待填）"""
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    db_rows = []
    for row in rows:
        db_rows.append({
            "open_time":           ts,
            "close_time":          None,
            "symbol":              row["symbol"],
            "side":                row["side"],
            "change_pct":          float(row["change_pct"]) if row.get("change_pct") else None,
            "market_cap_usd":      row.get("market_cap_usd"),
            "circulating_supply":  row.get("circulating_supply"),
            "btc_change_pct":      float(row["btc_change_pct"]) if row.get("btc_change_pct") else None,
            "symbol_funding_rate": float(row["symbol_funding_rate"]) if row.get("symbol_funding_rate") else None,
            "oi_change_pct":       float(row["oi_change_pct"]) if row.get("oi_change_pct") else None,
            "long_short_ratio":    float(row["long_short_ratio"]) if row.get("long_short_ratio") else None,
            "open_commission":     float(row["open_commission"]) if row.get("open_commission") else None,
            "entry_price":         None,
            "close_price":         None,
            "position_amt":        None,
            "unrealized_pnl":      None,
            "roe_pct":             None,
            "leverage":            None,
            "close_commission":    None,
        })
    db.insert_open_log(db_rows)
    log.info(f"开单观察数据已写入数据库（{len(db_rows)} 条）")


def print_open_summary(top_gainers: list, top_losers: list, market_data: dict = None,
                       btc_pct: float = None, funding_rates: dict = None,
                       commissions: dict = None, oi_changes: dict = None,
                       long_short_ratios: dict = None):
    """开单完成后输出标的行情观察表，并保存 CSV"""
    if market_data is None:
        symbols = [t["symbol"] for t in top_gainers + top_losers]
        log.info("正在从 CoinGecko 获取市值/流通量数据...")
        try:
            market_data = get_coin_market_data(symbols)
        except Exception as e:
            log.warning(f"CoinGecko 数据获取失败，跳过观察表：{e}")
            return

    funding_rates    = funding_rates    or {}
    commissions      = commissions      or {}
    oi_changes       = oi_changes       or {}
    long_short_ratios = long_short_ratios or {}
    btc_str = f"{btc_pct:+.2f}%" if btc_pct is not None else "N/A"

    C = {"symbol": 14, "side": 4, "pct": 10, "fr": 10, "oi": 10, "ls": 8, "comm": 10, "mcap": 13, "supply": 18}
    divider = "-" * (sum(C.values()) + len(C) * 3 + 1)
    header  = "=" * len(divider)

    print(header)
    print(f"  开单标的行情观察    BTC 24h涨跌：{btc_str}")
    print(divider)
    print(
        f"| {'交易对':<{C['symbol']}} | {'方向':<{C['side']}} "
        f"| {'24h涨跌':>{C['pct']}} | {'资金费率':>{C['fr']}} "
        f"| {'OI变化':>{C['oi']}} | {'多空比':>{C['ls']}} "
        f"| {'开仓手续费':>{C['comm']}} | {'市值(USD)':>{C['mcap']}} "
        f"| {'流通量':>{C['supply']}} |"
    )
    print(divider)

    csv_rows = []
    for label, tickers, side_str in [
        ("空单（涨幅榜）", top_gainers, "空"),
        ("多单（跌幅榜）", top_losers,  "多"),
    ]:
        print(f"  {label}")
        for t in tickers:
            sym  = t["symbol"]
            pct  = float(t["priceChangePercent"])
            md   = market_data.get(sym, {})
            mc   = md.get("market_cap", 0)
            cs   = md.get("circulating_supply", 0)
            fr   = funding_rates.get(sym)
            oi   = oi_changes.get(sym)
            ls   = long_short_ratios.get(sym)
            comm = commissions.get(sym, 0.0)
            fr_str = f"{fr*100:+.4f}%" if fr is not None else "N/A"
            oi_str = f"{oi:+.2f}%"     if oi is not None else "N/A"
            ls_str = f"{ls:.3f}"        if ls is not None else "N/A"
            comm_str = f"{comm:.4f}"
            print(
                f"| {sym:<{C['symbol']}} | {side_str:<{C['side']}} "
                f"| {pct:>+{C['pct']}.2f}% | {fr_str:>{C['fr']}} "
                f"| {oi_str:>{C['oi']}} | {ls_str:>{C['ls']}} "
                f"| {comm_str:>{C['comm']}} | {fmt_large(mc):>{C['mcap']}} "
                f"| {fmt_large(cs):>{C['supply']}} |"
            )
            csv_rows.append({
                "symbol":              sym,
                "side":                side_str,
                "change_pct":          f"{pct:.4f}",
                "market_cap_usd":      fmt_large(mc) if mc else "",
                "circulating_supply":  fmt_large(cs) if cs else "",
                "btc_change_pct":      f"{btc_pct:.4f}" if btc_pct is not None else "",
                "symbol_funding_rate": f"{fr:.6f}"      if fr is not None else "",
                "oi_change_pct":       f"{oi:.4f}"      if oi is not None else "",
                "long_short_ratio":    f"{ls:.4f}"      if ls is not None else "",
                "open_commission":     f"{comm:.6f}",
            })
        print(divider)

    print(header)
    save_open_csv(csv_rows, datetime.now())


def run_open():
    log.info("=" * 50)
    log.info(f"【开单开始】杠杆 {LEVERAGE}x  保证金 {MARGIN_PER_POS} USDT  名义 {MARGIN_PER_POS * LEVERAGE} USDT")

    valid_symbols, symbol_info = get_exchange_info()
    tickers = get_ticker_24h(valid_symbols, MIN_VOLUME)
    tickers.sort(key=lambda x: float(x["priceChangePercent"]), reverse=True)
    hedge = is_hedge_mode()

    # 候选池：取最大 TOP_N * CANDIDATE_BUFFER 倍，提前拉市值用于过滤无市值币
    n_short = TOP_N_SHORT * CANDIDATE_BUFFER
    n_long  = TOP_N_LONG  * CANDIDATE_BUFFER
    gainer_pool = tickers[:n_short]
    loser_pool  = tickers[-n_long:][::-1]

    log.info("正在从 CoinGecko 获取市值/流通量数据（过滤无市值币）...")
    try:
        market_data = get_coin_market_data([t["symbol"] for t in gainer_pool + loser_pool])
    except Exception as e:
        log.warning(f"CoinGecko 数据获取失败，不过滤市值：{e}")
        market_data = {}

    def has_mcap(t):
        return bool(market_data.get(t["symbol"], {}).get("market_cap"))

    if market_data:
        # 过滤无市值，再按涨跌幅阈值筛选，最后取前 N 个
        top_gainers = [t for t in gainer_pool
                       if has_mcap(t) and MIN_CHANGE_SHORT <= float(t["priceChangePercent"]) <= MAX_CHANGE_SHORT
                       ][:TOP_N_SHORT]
        top_losers  = [t for t in loser_pool
                       if has_mcap(t) and float(t["priceChangePercent"]) <= -MIN_CHANGE_LONG
                       ][:TOP_N_LONG]

        skipped = [t["symbol"] for t in gainer_pool + loser_pool if not has_mcap(t)]
        if skipped:
            detail = f"跳过无市值币 {len(skipped)} 个: {skipped}"
            log.info(detail)
            log_event("FILTER_NO_MCAP", detail)
    else:
        top_gainers = [t for t in gainer_pool
                       if MIN_CHANGE_SHORT <= float(t["priceChangePercent"]) <= MAX_CHANGE_SHORT][:TOP_N_SHORT]
        top_losers  = [t for t in loser_pool
                       if float(t["priceChangePercent"]) <= -MIN_CHANGE_LONG][:TOP_N_LONG]

    log.info(f"空单候选：{len(top_gainers)} 个（涨幅 {MIN_CHANGE_SHORT}%~{MAX_CHANGE_SHORT}%，上限 {TOP_N_SHORT}）")
    log.info(f"多单候选：{len(top_losers)} 个（跌幅 >= {MIN_CHANGE_LONG}%，上限 {TOP_N_LONG}）")

    log.info(f"持仓模式：{'双向（对冲）' if hedge else '单向'}")

    try:
        funding_rates = get_all_funding_rates()
    except Exception as e:
        log.warning(f"获取资金费率失败：{e}")
        funding_rates = {}

    open_start_ms = int(time.time() * 1000)
    run_batch_orders("空单（涨幅榜）", top_gainers, "SELL", symbol_info, hedge, funding_rates)
    log.info(f"多单已转为模拟盘观察，不实盘开仓（{len(top_losers)} 个标的）")
    open_end_ms = int(time.time() * 1000)

    # 开单完成后采集辅助指标
    try:
        btc_pct = get_btc_change_pct()
        log.info(f"BTC 24h涨跌幅：{btc_pct:+.2f}%")
    except Exception as e:
        log.warning(f"获取 BTC 涨跌幅失败：{e}")
        btc_pct = None

    all_symbols = [t["symbol"] for t in top_gainers + top_losers]

    log.info("正在获取持仓量变化（OI）...")
    try:
        oi_changes = get_oi_changes(all_symbols)
    except Exception as e:
        log.warning(f"获取OI变化失败：{e}")
        oi_changes = {}

    log.info("正在获取多空持仓比...")
    try:
        long_short_ratios = get_long_short_ratios(all_symbols)
    except Exception as e:
        log.warning(f"获取多空比失败：{e}")
        long_short_ratios = {}

    try:
        commissions = get_commissions_by_symbol(open_start_ms, open_end_ms)
        total_comm  = sum(commissions.values())
        log.info(f"本批开仓手续费合计：{total_comm:.4f} USDT（{len(commissions)} 个币种）")
    except Exception as e:
        log.warning(f"获取开仓手续费失败：{e}")
        commissions = {}

    print_open_summary(top_gainers, [], market_data, btc_pct,
                       funding_rates, commissions, oi_changes, long_short_ratios)
    log.info("【开单全部完成】")


# ── 定时工具 ───────────────────────────────────────────

def wait_until(hour: int, minute: int):
    now      = datetime.now()
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    wait_sec = (next_run - now).total_seconds()
    log.info(f"等待中 → 下次执行：{next_run.strftime('%Y-%m-%d %H:%M:%S')}（约 {wait_sec/3600:.1f} 小时后）")
    time.sleep(wait_sec)


# ── 主循环 ─────────────────────────────────────────────

def main():
    log.info("策略定时器启动")
    log.info(f"  每天 {LIMIT_CLOSE_HOUR:02d}:{LIMIT_CLOSE_MINUTE:02d} 限价平仓")
    log.info(f"  每天 {MARKET_CLOSE_HOUR:02d}:{MARKET_CLOSE_MINUTE:02d} 市价兜底")
    log.info(f"  每天 {OPEN_HOUR:02d}:{OPEN_MINUTE:02d} 开单（空单 TOP{TOP_N_SHORT} 涨幅{MIN_CHANGE_SHORT}%~{MAX_CHANGE_SHORT}%）")

    while True:
        # 08:30 限价平仓
        wait_until(LIMIT_CLOSE_HOUR, LIMIT_CLOSE_MINUTE)
        remaining = {}
        close_start_ms = 0
        try:
            remaining, close_start_ms = run_limit_close()
        except Exception as e:
            log.error(f"限价平仓出错：{e}", exc_info=True)

        # 08:50 市价兜底
        wait_until(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)
        try:
            run_market_close(remaining, close_start_ms)
        except Exception as e:
            log.error(f"市价平仓出错：{e}", exc_info=True)

        # 09:05 开仓
        wait_until(OPEN_HOUR, OPEN_MINUTE)
        try:
            run_open()
        except Exception as e:
            log.error(f"开单出错：{e}", exc_info=True)


if __name__ == "__main__":
    main()
