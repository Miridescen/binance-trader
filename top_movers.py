"""
获取币安 U本位永续合约 24h 涨幅榜 / 跌幅榜 前10
"""

from binance_client import get_exchange_info, get_ticker_24h

MIN_VOLUME = 10_000_000


def print_table(title: str, rows: list):
    print("=" * 58)
    print(f"{title:^48}")
    print("=" * 58)
    print(f"{'排名':<4} {'交易对':<15} {'涨跌幅':>8}  {'最新价':>12}  {'24h成交额':>12}")
    print("-" * 58)
    for i, t in enumerate(rows, 1):
        pct   = float(t["priceChangePercent"])
        price = float(t["lastPrice"])
        vol   = float(t["quoteVolume"]) / 1_000_000
        print(f"{i:<4} {t['symbol']:<15} {pct:>+7.2f}%  {price:>12.4f}  {vol:>9.1f}M")


def main():
    print("正在获取数据...")
    valid_symbols, _ = get_exchange_info()
    tickers = get_ticker_24h(valid_symbols, MIN_VOLUME)
    tickers.sort(key=lambda x: float(x["priceChangePercent"]), reverse=True)

    print_table("涨幅榜 TOP 10", tickers[:10])
    print()
    print_table("跌幅榜 TOP 10", tickers[-10:][::-1])
    print(f"\n共统计 {len(tickers)} 个合约（已过滤成交额 < {MIN_VOLUME/1e6:.0f}M 的交易对）")


if __name__ == "__main__":
    main()
