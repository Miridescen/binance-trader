"""
一次性查询：当前持仓币对的市值、流通量、24h涨跌幅
输出终端表格 + 写入数据库
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import os
from datetime import datetime
from binance_client import auth_get, get_ticker_24h, get_exchange_info, get_coin_market_data
import db


def fmt_large(n: float) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.2f}B"
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    if n > 0:
        return f"{n:.0f}"
    return "N/A"


def get_positions() -> list:
    data = auth_get("/fapi/v2/positionRisk")
    return [p for p in data if float(p["positionAmt"]) != 0]


def main():
    print("获取当前持仓...")
    positions = get_positions()
    if not positions:
        print("当前无持仓")
        return

    symbols = [p["symbol"] for p in positions]
    print(f"持仓币对：{symbols}")

    print("获取 24h 行情...")
    valid_symbols, _ = get_exchange_info()
    all_tickers      = get_ticker_24h(valid_symbols, min_volume=0)
    ticker_map       = {t["symbol"]: t for t in all_tickers}

    print("从 CoinGecko 获取市值/流通量...")
    market_data = get_coin_market_data(symbols)

    now = datetime.now()

    C = {"symbol": 14, "side": 4, "pct": 10, "mcap": 13, "supply": 18}
    divider = "-" * (sum(C.values()) + len(C) * 3 + 1)

    print("=" * len(divider))
    print(f"  持仓行情观察  {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(divider)
    print(
        f"| {'交易对':<{C['symbol']}} | {'方向':<{C['side']}} "
        f"| {'24h涨跌':>{C['pct']}} | {'市值(USD)':>{C['mcap']}} "
        f"| {'流通量':>{C['supply']}} |"
    )
    print(divider)

    positions_sorted = sorted(
        positions,
        key=lambda p: float(ticker_map.get(p["symbol"], {}).get("priceChangePercent", 0)),
        reverse=True,
    )

    db_rows = []
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    for p in positions_sorted:
        sym      = p["symbol"]
        amt      = float(p["positionAmt"])
        side_str = "多" if amt > 0 else "空"
        ticker   = ticker_map.get(sym, {})
        pct      = float(ticker.get("priceChangePercent", 0))
        md       = market_data.get(sym, {})
        mc       = md.get("market_cap", 0)
        cs       = md.get("circulating_supply", 0)

        print(
            f"| {sym:<{C['symbol']}} | {side_str:<{C['side']}} "
            f"| {pct:>+{C['pct']}.2f}% | {fmt_large(mc):>{C['mcap']}} "
            f"| {fmt_large(cs):>{C['supply']}} |"
        )
        db_rows.append({
            "open_time":           ts,
            "close_time":          None,
            "symbol":              sym,
            "side":                side_str,
            "change_pct":          pct,
            "market_cap_usd":      fmt_large(mc) if mc else None,
            "circulating_supply":  fmt_large(cs) if cs else None,
            "btc_change_pct":      None,
            "symbol_funding_rate": None,
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

    print("=" * len(divider))

    db.insert_open_log(db_rows)
    print(f"已写入数据库（{len(db_rows)} 条）")


if __name__ == "__main__":
    main()
