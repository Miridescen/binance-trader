"""
一次性脚本：将调仓脚本开的仓位补录到 open_log.csv
从当前持仓中读取数据，补全开仓记录。
"""

import csv
import os
import logging
from datetime import datetime
from binance_client import (
    auth_get, get_ticker_24h, get_exchange_info,
    get_coin_market_data, get_btc_change_pct, get_all_funding_rates,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

OPEN_LOG_FILE = os.path.join(os.path.dirname(__file__), "open_log.csv")
LOG_FIELDS = [
    "open_time", "close_time", "symbol", "side",
    "change_pct", "market_cap_usd", "circulating_supply",
    "btc_change_pct", "symbol_funding_rate", "oi_change_pct",
    "long_short_ratio", "open_commission",
    "entry_price", "close_price", "position_amt",
    "unrealized_pnl", "roe_pct", "leverage", "close_commission",
]


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

    # 获取 BTC 涨跌幅
    try:
        btc_pct = get_btc_change_pct()
    except Exception:
        btc_pct = None

    # 获取资金费率
    try:
        funding_rates = get_all_funding_rates()
    except Exception:
        funding_rates = {}

    # 读取现有记录
    existing = []
    if os.path.exists(OPEN_LOG_FILE) and os.path.getsize(OPEN_LOG_FILE) > 0:
        with open(OPEN_LOG_FILE, "r", newline="", encoding="utf-8") as f:
            existing = list(csv.DictReader(f))

    # 用 updateTime 作为开仓时间（持仓的最后更新时间，即开仓时间）
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
        change_pct = ticker_map.get(sym, "")

        row = {
            "open_time":           open_time,
            "close_time":          "",
            "symbol":              sym,
            "side":                side,
            "change_pct":          f"{change_pct:.4f}" if isinstance(change_pct, float) else "",
            "market_cap_usd":      fmt_large(mc) if mc else "",
            "circulating_supply":  fmt_large(cs) if cs else "",
            "btc_change_pct":      f"{btc_pct:.4f}" if btc_pct is not None else "",
            "symbol_funding_rate": f"{fr:.6f}" if fr is not None else "",
            "oi_change_pct":       "",
            "long_short_ratio":    "",
            "open_commission":     "",
            "entry_price":         "",
            "close_price":         "",
            "position_amt":        "",
            "unrealized_pnl":      "",
            "roe_pct":             "",
            "leverage":            "",
            "close_commission":    "",
        }
        new_rows.append(row)
        log.info(f"  {sym} {side} 涨跌 {change_pct:+.2f}% 开仓时间 {open_time}")

    existing.extend(new_rows)

    with open(OPEN_LOG_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(existing)

    log.info(f"补录完成，共新增 {len(new_rows)} 条记录到 {OPEN_LOG_FILE}")


if __name__ == "__main__":
    main()
