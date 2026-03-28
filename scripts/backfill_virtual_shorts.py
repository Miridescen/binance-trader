"""
一次性脚本：将实盘空单历史数据复制到虚拟盘作为「模拟空」记录。
实盘空单参数（涨幅>=5% + 市值过滤 + TOP10）与模拟空完全一致，
所以可以直接复制。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db

def main():
    all_open = db.get_open_log_all()
    shorts = [r for r in all_open if r.get("side") == "空"]

    if not shorts:
        print("没有实盘空单数据")
        return

    rows = []
    for r in shorts:
        rows.append({
            "open_time":           r.get("open_time"),
            "close_time":          r.get("close_time"),
            "symbol":              r.get("symbol"),
            "side":                "模拟空",
            "change_pct":          r.get("change_pct"),
            "market_cap_usd":      r.get("market_cap_usd"),
            "circulating_supply":  r.get("circulating_supply"),
            "has_mcap":            1,
            "btc_change_pct":      r.get("btc_change_pct"),
            "symbol_funding_rate": r.get("symbol_funding_rate"),
            "oi_change_pct":       r.get("oi_change_pct"),
            "long_short_ratio":    r.get("long_short_ratio"),
            "entry_price":         r.get("entry_price"),
            "close_price":         r.get("close_price"),
            "unrealized_pnl":      r.get("unrealized_pnl"),
            "roe_pct":             r.get("roe_pct"),
        })

    db.insert_virtual_log(rows)
    print(f"已补录 {len(rows)} 条模拟空记录到 virtual_log")


if __name__ == "__main__":
    main()
