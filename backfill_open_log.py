"""
一次性脚本：将调仓脚本开的仓位补录到数据库
从当前持仓中读取数据，补全开仓记录。
"""

import logging
from datetime import datetime
from binance_client import (
    auth_get, get_ticker_24h, get_exchange_info,
    get_coin_market_data, get_btc_change_pct, get_all_funding_rates,
)
import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def fmt_large(n: float) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.2f}B"
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    if n > 0:
        return f"{n:.0f}"
    return ""


def main():
    # 获取当前持仓
    positions = auth_get("/fapi/v2/positionRisk")
    active = [p for p in positions if float(p["positionAmt"]) != 0]

    if not active:
        log.info("当前无持仓，无需补录")
        return

    log.info(f"当前持仓 {len(active)} 个，开始补录...")

    # 获取 24h 涨跌幅
    valid_symbols, _ = get_exchange_info()
    tickers = get_ticker_24h(valid_symbols, 0)
    ticker_map = {t["symbol"]: float(t["priceChangePercent"]) for t in tickers}

    # 获取市值数据
    symbols = [p["symbol"] for p in active]
    try:
        market_data = get_coin_market_data(symbols)
    except Exception as e:
        log.warning(f"CoinGecko 获取失败：{e}")
        market_data = {}

    try:
        btc_pct = get_btc_change_pct()
    except Exception:
        btc_pct = None

    try:
        funding_rates = get_all_funding_rates()
    except Exception:
        funding_rates = {}

    new_rows = []
    for p in active:
        sym = p["symbol"]
        amt = float(p["positionAmt"])
        side = "空" if amt < 0 else "多"
        update_ms = int(p.get("updateTime", 0))
        open_time = datetime.fromtimestamp(update_ms / 1000).strftime("%Y-%m-%d %H:%M:%S") if update_ms else ""

        md = market_data.get(sym, {})
        mc = md.get("market_cap", 0)
        cs = md.get("circulating_supply", 0)
        fr = funding_rates.get(sym)
        change_pct = ticker_map.get(sym)

        new_rows.append({
            "open_time":           open_time,
            "close_time":          None,
            "symbol":              sym,
            "side":                side,
            "change_pct":          change_pct,
            "market_cap_usd":      fmt_large(mc) if mc else None,
            "circulating_supply":  fmt_large(cs) if cs else None,
            "btc_change_pct":      btc_pct,
            "symbol_funding_rate": fr,
            "oi_change_pct":       None,
            "long_short_ratio":    None,
            "open_commission":     None,
            "entry_price":         None,
            "close_price":         None,
            "position_amt":        None,
            "unrealized_pnl":      None,
            "roe_pct":             None,
            "leverage":            None,
            "close_commission":    None,
        })
        log.info(f"  {sym} {side} 涨跌 {change_pct:+.2f}% 开仓时间 {open_time}")

    db.insert_open_log(new_rows)
    log.info(f"补录完成，共新增 {len(new_rows)} 条记录到数据库")


if __name__ == "__main__":
    main()
