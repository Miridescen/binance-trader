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

def get_funding_income(start_ms: int, end_ms: int) -> float:
    """获取指定时间段内的资金费率收支（正=收入，负=支出）"""
    data = auth_get("/fapi/v1/income", {
        "incomeType": "FUNDING_FEE",
        "startTime":  start_ms,
        "endTime":    end_ms,
        "limit":      1000,
    })
    return sum(float(item["income"]) for item in data)

def get_btc_change_pct() -> float:
    """获取 BTC 当前 24h 涨跌幅（%）"""
    data = public_get("/fapi/v1/ticker/24hr", {"symbol": "BTCUSDT"})
    return float(data["priceChangePercent"])

def get_all_funding_rates() -> dict:
    """获取所有合约当前资金费率，返回 {symbol: lastFundingRate}"""
    data = public_get("/fapi/v1/premiumIndex")
    return {item["symbol"]: float(item["lastFundingRate"]) for item in data}

def get_oi_changes(symbols: list) -> dict:
    """
    批量获取各币种近1小时持仓量变化率（%）
    返回: {symbol: oi_change_pct}，取不到的币种不在返回值中
    """
    result = {}
    for sym in symbols:
        try:
            data = public_get("/futures/data/openInterestHist",
                              {"symbol": sym, "period": "1h", "limit": 2})
            if len(data) >= 2:
                prev = float(data[0]["sumOpenInterest"])
                curr = float(data[1]["sumOpenInterest"])
                if prev:
                    result[sym] = (curr - prev) / prev * 100
        except Exception:
            pass
        time.sleep(0.1)
    return result

def get_long_short_ratios(symbols: list) -> dict:
    """
    批量获取各币种全球账户多空比（>1 多头占优，<1 空头占优）
    返回: {symbol: ratio}，取不到的币种不在返回值中
    """
    result = {}
    for sym in symbols:
        try:
            data = public_get("/futures/data/globalLongShortAccountRatio",
                              {"symbol": sym, "period": "5m", "limit": 1})
            if data:
                result[sym] = float(data[0]["longShortRatio"])
        except Exception:
            pass
        time.sleep(0.1)
    return result

def get_commissions_by_symbol(start_ms: int, end_ms: int) -> dict:
    """获取时间段内各币种手续费合计，返回 {symbol: usdt}（负数=支出）"""
    data = auth_get("/fapi/v1/income", {
        "incomeType": "COMMISSION",
        "startTime":  start_ms,
        "endTime":    end_ms,
        "limit":      1000,
    })
    result = {}
    for item in data:
        sym = item.get("symbol", "")
        result[sym] = result.get(sym, 0.0) + float(item["income"])
    return result


# ── BTC 趋势指标 ─────────────────────────────────────────

def get_klines(symbol: str, interval: str, limit: int = 200) -> list:
    """获取 K 线数据，返回 [{open_time, open, high, low, close, volume}, ...]"""
    data = public_get("/fapi/v1/klines", {
        "symbol": symbol, "interval": interval, "limit": limit,
    })
    return [
        {
            "open_time": item[0],
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5]),
        }
        for item in data
    ]


def calc_sma(closes: list, period: int) -> float:
    """计算简单移动平均线"""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def calc_rsi(closes: list, period: int = 14) -> float:
    """计算 RSI"""
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def get_fear_greed_index() -> dict:
    """获取恐惧贪婪指数（Alternative.me 免费 API）"""
    resp = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
    resp.raise_for_status()
    item = resp.json()["data"][0]
    return {
        "value": int(item["value"]),
        "label": item["value_classification"],
    }


def get_funding_rate(symbol: str = "BTCUSDT") -> float:
    """获取单个合约的当前资金费率"""
    data = public_get("/fapi/v1/premiumIndex", {"symbol": symbol})
    return float(data["lastFundingRate"])


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
        for attempt in range(3):   # 429 限速最多重试 3 次
            try:
                resp = requests.get(
                    f"{COINGECKO_URL}/coins/markets",
                    params={"vs_currency": "usd", "per_page": 250, "page": page,
                            "order": "market_cap_desc"},
                    timeout=15,
                )
                if resp.status_code == 429:
                    wait = 30 * (attempt + 1)
                    print(f"[CoinGecko] page {page} 限速，等待 {wait}s 后重试...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                break
            except Exception as e:
                if attempt == 2:
                    print(f"[CoinGecko] page {page} 请求失败，跳过：{e}")
                time.sleep(5)
        else:
            break   # 3 次均失败，终止

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
        time.sleep(1.5)   # 避免触发 CoinGecko 频率限制

    return result
