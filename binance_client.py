"""
币安合约 API 公共客户端
所有需要签名的请求统一走这里，避免各文件重复代码
"""

import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

API_KEY    = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
BASE_URL   = "https://fapi.binance.com"

if not API_KEY or not API_SECRET:
    raise ValueError("请在 .env 文件中配置 BINANCE_API_KEY 和 BINANCE_API_SECRET")


def _sign(params: dict) -> str:
    query = urlencode(params)
    return hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

def _headers() -> dict:
    return {"X-MBX-APIKEY": API_KEY}

def auth_get(path: str, extra: dict = None):
    params = {"timestamp": int(time.time() * 1000), **(extra or {})}
    params["signature"] = _sign(params)
    resp = requests.get(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()

def auth_post(path: str, params: dict):
    params = dict(params)   # 避免修改调用方的 dict
    params["timestamp"] = int(time.time() * 1000)
    params["signature"] = _sign(params)
    resp = requests.post(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=10)
    return resp.json()

def auth_delete(path: str, params: dict):
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    params["signature"] = _sign(params)
    resp = requests.delete(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=10)
    return resp.json()

def public_get(path: str, params: dict = None):
    resp = requests.get(f"{BASE_URL}{path}", params=params or {}, timeout=10)
    resp.raise_for_status()
    return resp.json()


# ── 公共行情接口 ───────────────────────────────────────

def get_exchange_info() -> tuple:
    """
    一次请求同时返回：
      valid_symbols: set[str]  — 所有正在交易的 USDT 永续合约 symbol
      symbol_info:   dict      — {symbol: {tick_size, step_size, min_notional}}
    """
    data = public_get("/fapi/v1/exchangeInfo")
    valid_symbols = set()
    symbol_info   = {}

    for s in data["symbols"]:
        if not (s["symbol"].endswith("USDT")
                and s["contractType"] == "PERPETUAL"
                and s["status"] == "TRADING"):
            continue
        valid_symbols.add(s["symbol"])

        tick_size = step_size = min_notional = None
        for f in s["filters"]:
            if f["filterType"] == "PRICE_FILTER":
                tick_size = float(f["tickSize"])
            elif f["filterType"] == "LOT_SIZE":
                step_size = float(f["stepSize"])
            elif f["filterType"] == "MIN_NOTIONAL":
                min_notional = float(f["notional"])
        symbol_info[s["symbol"]] = {
            "tick_size":    tick_size    or 0.01,
            "step_size":    step_size    or 0.001,
            "min_notional": min_notional or 0,
        }

    return valid_symbols, symbol_info

def get_mark_price(symbol: str) -> float:
    data = public_get("/fapi/v1/premiumIndex", {"symbol": symbol})
    return float(data["markPrice"])

def get_ticker_24h(valid_symbols: set, min_volume: float) -> list:
    data = public_get("/fapi/v1/ticker/24hr")
    return [
        t for t in data
        if t["symbol"] in valid_symbols
        and float(t["quoteVolume"]) >= min_volume
    ]

def is_hedge_mode() -> bool:
    return auth_get("/fapi/v1/positionSide/dual").get("dualSidePosition", False)


# ── CoinGecko 行情补充 ─────────────────────────────────

COINGECKO_URL = "https://api.coingecko.com/api/v3"

def get_coin_market_data(usdt_symbols: list) -> dict:
    """
    从 CoinGecko 获取指定合约币种的市值和流通量
    输入: ['BTCUSDT', 'ETHUSDT', ...]
    返回: {symbol: {'market_cap': float, 'circulating_supply': float}}
    未查到的币种不在返回值中
    """
    remaining = {s[:-4].lower(): s for s in usdt_symbols}   # {base_lower: full_symbol}
    result = {}

    for page in range(1, 5):   # 最多覆盖前 1000 名
        try:
            resp = requests.get(
                f"{COINGECKO_URL}/coins/markets",
                params={"vs_currency": "usd", "per_page": 250, "page": page,
                        "order": "market_cap_desc"},
                timeout=15,
            )
            resp.raise_for_status()
        except Exception:
            break

        for coin in resp.json():
            sym = coin["symbol"].lower()
            if sym in remaining:
                full = remaining.pop(sym)
                result[full] = {
                    "market_cap":         coin.get("market_cap") or 0,
                    "circulating_supply": coin.get("circulating_supply") or 0,
                }

        if not remaining:
            break
        time.sleep(0.5)   # 避免触发 CoinGecko 频率限制

    return result
