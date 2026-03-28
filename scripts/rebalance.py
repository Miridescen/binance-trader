"""
一次性调仓脚本：
  1. 平掉当前所有持仓
  2. 重新开仓：空单 TOP10（保证金 20 USDT），多单不变（保证金 10 USDT）
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import time
import logging
from open_top_shorts import (
    cancel_all_open_orders, close_all_positions,
    get_exchange_info, get_ticker_24h,
    set_leverage_verified, place_limit_order, place_market_order,
    get_order_status, cancel_order,
    is_hedge_mode, get_coin_market_data, get_mark_price,
    floor_to_step, round_to_tick, fmt,
    print_open_summary,
    LEVERAGE, MIN_VOLUME, MIN_CHANGE_SHORT, MIN_CHANGE_LONG,
    CANDIDATE_BUFFER, ORDER_CHECK_INTERVAL, MAX_RETRIES,
)
from binance_client import auth_post, auth_get

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── 调仓参数 ──────────────────────────────────────────
TOP_N_SHORT    = 10        # 空单 10 个
TOP_N_LONG     = 10        # 多单 10 个
MARGIN_SHORT   = 20        # 空单保证金翻倍 → 20 USDT
MARGIN_LONG    = 10        # 多单保证金不变 → 10 USDT


def place_limit_order_with_margin(symbol, info, side, hedge, attempt, margin):
    """按指定保证金下限价单"""
    step  = info["step_size"]
    tick  = info["tick_size"]
    min_n = info["min_notional"]

    mark_price = get_mark_price(symbol)
    qty   = floor_to_step(margin * LEVERAGE / mark_price, step)
    price = round_to_tick(mark_price, tick)

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
        log.info(f"  {symbol} 第{attempt}次{direction} ✅ 数量 {fmt(qty, step)} 限价 {fmt(price, tick)} 保证金 {margin} USDT")
        return {"orderId": order["orderId"], "info": info}
    else:
        log.error(f"  {symbol} 第{attempt}次下单失败 code={order.get('code')} {order.get('msg', order)}")
        return None


def place_market_order_with_margin(symbol, info, side, hedge, margin):
    """按指定保证金市价兜底"""
    step       = info["step_size"]
    mark_price = get_mark_price(symbol)
    qty        = floor_to_step(margin * LEVERAGE / mark_price, step)
    params     = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": fmt(qty, step)}
    if hedge:
        params["positionSide"] = "SHORT" if side == "SELL" else "LONG"
    result    = auth_post("/fapi/v1/order", params)
    direction = "空" if side == "SELL" else "多"
    if "orderId" in result:
        log.info(f"  {symbol} 市价开{direction}成功 数量 {fmt(qty, step)} 保证金 {margin} USDT ✅")
    else:
        log.error(f"  {symbol} 市价开{direction}失败：{result.get('msg', result)}")


def run_batch(label, tickers, side, symbol_info, hedge, margin):
    """批量下单（支持自定义保证金）"""
    direction = "涨幅" if side == "SELL" else "跌幅"
    log.info(f"── {label}（保证金 {margin} USDT） ──")
    log.info(f"{direction}榜 TOP{len(tickers)}：{[t['symbol'] for t in tickers]}")

    pending = {}
    for i, ticker in enumerate(tickers, 1):
        symbol = ticker["symbol"]
        pct    = float(ticker["priceChangePercent"])
        info   = symbol_info.get(symbol)
        if not info:
            log.warning(f"[{i}/{len(tickers)}] {symbol} 无交易对信息，跳过")
            continue

        log.info(f"[{i:>2}/{len(tickers)}] {symbol} {direction}幅 {pct:>+.2f}%")
        if not set_leverage_verified(symbol):
            log.warning(f"  {symbol} 杠杆设置失败，跳过此币种")
            continue

        result = place_limit_order_with_margin(symbol, info, side, hedge, attempt=1, margin=margin)
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
                log.info(f"  {symbol} 部分成交，继续等待...")
                still_pending[symbol] = data
            elif status in ("CANCELED", "EXPIRED", "REJECTED"):
                log.warning(f"  {symbol} 状态 {status}，重新下单")
                result = place_limit_order_with_margin(symbol, data["info"], side, hedge, attempt, margin)
                if result:
                    still_pending[symbol] = result
                time.sleep(0.15)
            else:
                log.info(f"  {symbol} 未成交（{status}），换价重下（第{attempt}次）")
                cancel_order(symbol, data["orderId"])
                time.sleep(0.3)
                result = place_limit_order_with_margin(symbol, data["info"], side, hedge, attempt, margin)
                if result:
                    still_pending[symbol] = result
                time.sleep(0.15)

        pending = still_pending

    # 市价兜底
    if pending:
        log.warning(f"仍有 {len(pending)} 个 {label} 未成交，改用市价单...")
        for symbol, data in pending.items():
            cancel_order(symbol, data["orderId"])
            time.sleep(0.3)
            place_market_order_with_margin(symbol, data["info"], side, hedge, margin)
            time.sleep(0.15)


def main():
    log.info("=" * 50)
    log.info("【调仓脚本】空单 10 个 × 20 USDT / 多单 10 个 × 10 USDT")
    log.info("=" * 50)

    hedge = is_hedge_mode()

    # ── 第一步：平掉所有持仓 ──
    log.info("【第一步】撤销挂单 + 平掉所有持仓")
    cancel_all_open_orders()
    close_all_positions(hedge)

    # ── 第二步：筛选标的 ──
    log.info("【第二步】筛选开仓标的")
    valid_symbols, symbol_info = get_exchange_info()
    tickers = get_ticker_24h(valid_symbols, MIN_VOLUME)
    tickers.sort(key=lambda x: float(x["priceChangePercent"]), reverse=True)

    n_short = TOP_N_SHORT * CANDIDATE_BUFFER
    n_long  = TOP_N_LONG  * CANDIDATE_BUFFER
    gainer_pool = tickers[:n_short]
    loser_pool  = tickers[-n_long:][::-1]

    log.info("正在从 CoinGecko 获取市值数据...")
    try:
        market_data = get_coin_market_data([t["symbol"] for t in gainer_pool + loser_pool])
    except Exception as e:
        log.warning(f"CoinGecko 数据获取失败，不过滤市值：{e}")
        market_data = {}

    def has_mcap(t):
        return bool(market_data.get(t["symbol"], {}).get("market_cap"))

    if market_data:
        top_gainers = [t for t in gainer_pool
                       if has_mcap(t) and float(t["priceChangePercent"]) >= MIN_CHANGE_SHORT
                       ][:TOP_N_SHORT]
        top_losers  = [t for t in loser_pool
                       if has_mcap(t) and float(t["priceChangePercent"]) <= -MIN_CHANGE_LONG
                       ][:TOP_N_LONG]
    else:
        top_gainers = [t for t in gainer_pool
                       if float(t["priceChangePercent"]) >= MIN_CHANGE_SHORT][:TOP_N_SHORT]
        top_losers  = [t for t in loser_pool
                       if float(t["priceChangePercent"]) <= -MIN_CHANGE_LONG][:TOP_N_LONG]

    log.info(f"空单候选：{len(top_gainers)} 个（涨幅 >= {MIN_CHANGE_SHORT}%，上限 {TOP_N_SHORT}）")
    log.info(f"多单候选：{len(top_losers)} 个（跌幅 >= {MIN_CHANGE_LONG}%，上限 {TOP_N_LONG}）")

    # ── 第三步：开仓 ──
    log.info("【第三步】开仓")
    run_batch("空单（涨幅榜）", top_gainers, "SELL", symbol_info, hedge, margin=MARGIN_SHORT)
    run_batch("多单（跌幅榜）", top_losers,  "BUY",  symbol_info, hedge, margin=MARGIN_LONG)

    log.info("=" * 50)
    log.info("【调仓完成】")
    log.info(f"  空单：{len(top_gainers)} 个 × {MARGIN_SHORT} USDT = {len(top_gainers) * MARGIN_SHORT} USDT 保证金")
    log.info(f"  多单：{len(top_losers)} 个 × {MARGIN_LONG} USDT = {len(top_losers) * MARGIN_LONG} USDT 保证金")
    log.info(f"  总保证金：{len(top_gainers) * MARGIN_SHORT + len(top_losers) * MARGIN_LONG} USDT")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
