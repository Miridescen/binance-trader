"""
批量将币安合约账户所有交易对的杠杆倍率设置为指定倍数
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import time
from binance_client import auth_post, get_exchange_info

TARGET_LEVERAGE = 3


def set_leverage(symbol: str, leverage: int) -> dict:
    return auth_post("/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})


def main():
    print(f"目标杠杆：{TARGET_LEVERAGE}x\n正在获取所有合约交易对...")
    valid_symbols, _ = get_exchange_info()
    symbols = sorted(valid_symbols)
    print(f"共找到 {len(symbols)} 个永续合约交易对\n")

    success, failed = [], []

    for i, symbol in enumerate(symbols, 1):
        result = set_leverage(symbol, TARGET_LEVERAGE)
        if "leverage" in result:
            print(f"[{i:>4}/{len(symbols)}] ✓ {symbol:>12}  →  {result['leverage']}x")
            success.append(symbol)
        else:
            code = result.get("code", "?")
            msg  = result.get("msg", str(result))
            print(f"[{i:>4}/{len(symbols)}] ✗ {symbol:>12}  code={code}  {msg}")
            failed.append((symbol, msg))
        time.sleep(0.1)

    print(f"\n完成！成功 {len(success)} 个，失败 {len(failed)} 个")
    if failed:
        print("\n失败列表：")
        for sym, msg in failed:
            print(f"  {sym}: {msg}")


if __name__ == "__main__":
    main()
