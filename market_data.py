"""
Market data with parallel fetching. Safe per-ticker fetch; no delays.
Trending/gainers/losers: try Yahoo screener, fallback to popular tickers.
"""

import math
import logging
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf

logger = logging.getLogger(__name__)

MAX_WORKERS = 10
FALLBACK_POPULAR = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "NFLX", "AMD", "INTC",
]


def _safe_float(x, default=None):
    if x is None:
        return default
    try:
        v = float(x)
        return default if math.isnan(v) else v
    except (TypeError, ValueError):
        return default


def _safe_int(x, default=None):
    if x is None:
        return default
    try:
        v = float(x)
        if math.isnan(v):
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


def _change_pct(current, previous):
    if previous is None or previous == 0:
        return 0.0
    curr = _safe_float(current, 0.0)
    prev = _safe_float(previous, 0.0)
    if prev == 0:
        return 0.0
    pct = (curr - prev) / prev * 100
    return 0.0 if math.isnan(pct) else pct


def fetch_stock_safely(ticker: str) -> Optional[dict]:
    """
    Fetch one ticker with try/finally cleanup.
    Returns dict with ticker, name, price, change_pct, volume or None.
    """
    stock = None
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d", auto_adjust=True)
        if hist is None or hist.empty or len(hist) < 2:
            hist = stock.history(period="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return None
        close = _safe_float(hist["Close"].iloc[-1])
        prev = _safe_float(hist["Close"].iloc[-2]) if len(hist) >= 2 else close
        close = close if close is not None else 0.0
        prev = prev if prev is not None else close
        pct = _change_pct(close, prev)
        vol_val = hist["Volume"].iloc[-1] if "Volume" in hist.columns else None
        vol = _safe_int(vol_val, 0)
        vol = 0 if vol is None else vol
        try:
            info = stock.info
            name = info.get("shortName") or info.get("longName") or ticker
        except Exception:
            name = ticker
        return {
            "ticker": ticker,
            "name": name or ticker,
            "price": round(close, 2),
            "change_pct": round(pct, 2),
            "volume": vol,
        }
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", ticker, e)
        return None
    finally:
        if stock is not None:
            try:
                del stock
            except Exception:
                pass


def fetch_all_stocks_parallel(tickers: list[str], max_workers: int = MAX_WORKERS) -> dict[str, dict]:
    """Fetch multiple stocks in parallel. Returns { ticker: data } for successful fetches."""
    if not tickers:
        return {}
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {executor.submit(fetch_stock_safely, t): t for t in tickers}
        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                data = future.result()
                if data is not None:
                    results[ticker] = data
            except Exception as e:
                logger.warning("Parallel fetch %s: %s", ticker, e)
    return results


def get_stock_data(ticker: str) -> Optional[dict]:
    """Single-ticker wrapper."""
    try:
        return fetch_stock_safely(ticker)
    except Exception as e:
        logger.warning("get_stock_data %s: %s", ticker, e)
        return None


def get_competitor_data(ticker_list: list[str]) -> list[dict]:
    """Fetch all competitors in parallel. Returns list of { ticker, price, change_pct }."""
    if not ticker_list:
        return []
    results = fetch_all_stocks_parallel(ticker_list)
    return [
        {"ticker": t, "price": d["price"], "change_pct": d["change_pct"]}
        for t, d in results.items()
    ]


def _parse_screener_quotes(quotes: list, count: int) -> list[dict]:
    """Parse Yahoo screener 'quotes' list into our list of dicts."""
    out = []
    for q in quotes[:count]:
        if not isinstance(q, dict):
            continue
        sym = q.get("symbol")
        if not sym:
            continue
        close = _safe_float(q.get("regularMarketPrice") or q.get("price"))
        pct = _safe_float(q.get("regularMarketChangePercent") or q.get("changePercent"))
        vol = _safe_int(q.get("regularMarketVolume") or q.get("Volume"))
        name = q.get("shortName") or q.get("longName") or q.get("displayName") or str(sym)
        out.append({
            "ticker": str(sym).strip(),
            "name": str(name).strip() if name else str(sym),
            "price": close if close is not None else 0.0,
            "change_pct": pct if pct is not None else 0.0,
            "volume": vol if vol is not None else 0,
        })
    return out


def _screener_to_list(screener_id: str, count: int) -> list[dict]:
    """Try yf.screen with predefined screener name; return list of dicts or empty on failure."""
    try:
        if not hasattr(yf, "screen"):
            return []
        result = yf.screen(screener_id, count=count)
        if result is None:
            return []
        # yfinance returns dict with 'quotes' list
        if isinstance(result, dict) and "quotes" in result:
            return _parse_screener_quotes(result["quotes"], count)
        # Fallback: DataFrame-style (iloc/columns)
        out = []
        if hasattr(result, "columns") and hasattr(result, "iloc"):
            for i in range(min(len(result), count)):
                try:
                    row = result.iloc[i]
                    sym = row.get("symbol") or row.get("Symbol") or (result.columns[0] if len(result.columns) else None)
                    if not sym:
                        continue
                    close = _safe_float(row.get("Close") or row.get("regularMarketPrice") or row.get("price"))
                    pct = _safe_float(row.get("change_pct") or row.get("regularMarketChangePercent") or row.get("changePercent"))
                    vol = _safe_int(row.get("Volume") or row.get("regularMarketVolume"))
                    out.append({
                        "ticker": str(sym).strip(),
                        "name": str(sym),
                        "price": close,
                        "change_pct": 0.0 if pct is None else pct,
                        "volume": 0 if vol is None else vol,
                    })
                except Exception:
                    continue
        return out
    except Exception as e:
        logger.warning("Screener %s failed: %s", screener_id, e)
        return []


def get_trending_with_fallback() -> tuple[list[dict], bool]:
    """Try Yahoo most_actives screener; fallback to popular tickers in parallel. Returns (data, used_fallback)."""
    rows = _screener_to_list("most_actives", 15)
    if rows:
        return rows, False
    tickers = FALLBACK_POPULAR[:10]
    results = fetch_all_stocks_parallel(tickers)
    out = [results[t] for t in tickers if t in results]
    out.sort(key=lambda x: x.get("volume") or 0, reverse=True)
    return out[:10], True


def get_gainers_with_fallback(limit: int = 5) -> tuple[list[dict], bool]:
    """Try day_gainers screener; fallback to popular tickers sorted by change_pct."""
    rows = _screener_to_list("day_gainers", limit)
    if rows:
        return rows, False
    results = fetch_all_stocks_parallel(FALLBACK_POPULAR)
    out = list(results.values())
    out.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)
    return out[:limit], True


def get_losers_with_fallback(limit: int = 5) -> tuple[list[dict], bool]:
    """Try day_losers screener; fallback to popular tickers sorted by change_pct ascending."""
    rows = _screener_to_list("day_losers", limit)
    if rows:
        return rows, False
    results = fetch_all_stocks_parallel(FALLBACK_POPULAR)
    out = list(results.values())
    out.sort(key=lambda x: x.get("change_pct") or 0)
    return out[:limit], True


def get_yahoo_trending() -> list[dict]:
    """Legacy: return trending data (with fallback)."""
    data, _ = get_trending_with_fallback()
    return data


def get_yahoo_most_active() -> list[dict]:
    """Same as trending for fallback."""
    data, _ = get_trending_with_fallback()
    return data[:10]


def get_yahoo_gainers(limit: int = 10) -> list[dict]:
    data, _ = get_gainers_with_fallback(limit)
    return data


def get_yahoo_losers(limit: int = 10) -> list[dict]:
    data, _ = get_losers_with_fallback(limit)
    return data
