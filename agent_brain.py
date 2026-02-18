"""
AI-powered market analysis using Claude. Inline 2-3 sentence reasoning for each ticker.
Cache analyses for 5 minutes to limit API usage.
"""

import math
import os
import time
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

logger = logging.getLogger(__name__)

# Single reusable client at startup to avoid too many open connections
_key = os.getenv("ANTHROPIC_API_KEY")
anthropic_client: Optional[Anthropic] = Anthropic(api_key=_key) if _key else None

SYSTEM_PROMPT = """You are a financial analyst specializing in Silver Lake portfolio companies and market intelligence. Provide concise 2-3 sentence analysis for each stock. For portfolio companies always compare performance to competitors and identify if movement is company-specific or sector-wide. Focus on actionable insights. Output plain text only, 2-3 sentences maximum, no markdown or bullet points."""

ANALYSIS_CACHE_TTL = 300  # 5 minutes
_cache: dict[str, tuple[str, float]] = {}
_cache_lock = threading.Lock()


def _cached_key(prefix: str, ticker: str, extra: str = "") -> str:
    return f"{prefix}:{ticker}:{extra}"


def _get_cached(key: str) -> Optional[str]:
    with _cache_lock:
        entry = _cache.get(key)
        if entry:
            text, ts = entry
            if time.time() - ts < ANALYSIS_CACHE_TTL:
                return text
    return None


def _set_cached(key: str, text: str) -> None:
    with _cache_lock:
        _cache[key] = (text, time.time())


def _safe_num(x, default=0.0):
    """Return a number or default if None/NaN."""
    if x is None:
        return default
    try:
        v = float(x)
        return default if math.isnan(v) else v
    except (TypeError, ValueError):
        return default


def _call_claude(user_text: str, max_tokens: int = 300) -> str:
    if anthropic_client is None:
        raise ValueError("ANTHROPIC_API_KEY not set")
    try:
        resp = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_text}],
        )
        return (resp.content[0].text or "").strip()
    except Exception as e:
        logger.exception("Claude API error: %s", e)
        raise


def analyze_portfolio_stock(
    ticker: str,
    price_data: dict,
    competitor_data: list[dict],
) -> str:
    """2-3 sentence analysis comparing portfolio company to competitors; company-specific vs sector-wide."""
    key = _cached_key("portfolio", ticker, str(sorted([c.get("ticker") for c in competitor_data])))
    cached = _get_cached(key)
    if cached:
        return cached
    comp_summary = ", ".join(
        f"{c.get('ticker', '')} {'up' if _safe_num(c.get('change_pct')) >= 0 else 'down'} {abs(_safe_num(c.get('change_pct'))):.1f}%"
        for c in competitor_data[:6]
    )
    price = _safe_num(price_data.get("price"), 0.0)
    pct = _safe_num(price_data.get("change_pct"), 0.0)
    vol = price_data.get("volume")
    vol = int(_safe_num(vol, 0)) if vol is not None else None
    vol_str = f" Volume {vol/1e6:.1f}M" if vol else ""
    user = (
        f"Portfolio company {ticker}: ${price:.2f} {'up' if pct >= 0 else 'down'} {abs(pct):.1f}%{vol_str}. "
        f"Competitors: {comp_summary}. "
        "In 2-3 sentences: is this company outperforming or underperforming peers? Is the move company-specific or sector-wide? Any level to watch?"
    )
    try:
        out = _call_claude(user)
        _set_cached(key, out)
        return out
    except Exception:
        return "Analysis temporarily unavailable."


def analyze_all_stocks_parallel(
    items: list[tuple[str, dict, list[dict]]],
    max_workers: int = 7,
) -> dict[str, str]:
    """
    Get Claude analysis for multiple portfolio stocks in parallel.
    items: list of (ticker, price_data, competitor_data).
    Returns { ticker: analysis_text }.
    """
    analyses: dict[str, str] = {}

    def task(ticker: str, price_data: dict, competitor_data: list[dict]) -> tuple[str, str]:
        try:
            text = analyze_portfolio_stock(ticker, price_data, competitor_data)
            return (ticker, text)
        except Exception as e:
            logger.warning("Analysis failed for %s: %s", ticker, e)
            return (ticker, "Analysis temporarily unavailable.")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {
            executor.submit(task, ticker, price_data, comp_data): ticker
            for ticker, price_data, comp_data in items
        }
        for future in as_completed(future_to_ticker):
            try:
                ticker, text = future.result()
                analyses[ticker] = text
            except Exception as e:
                ticker = future_to_ticker[future]
                logger.warning("Analysis future %s: %s", ticker, e)
                analyses[ticker] = "Analysis temporarily unavailable."
    return analyses


def analyze_market_widgets_parallel(
    trending: list[dict],
    gainers: list[dict],
    losers: list[dict],
    max_workers: int = 10,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """
    Get Claude analysis for all trending, gainers, and losers in parallel.
    Returns (trending_analyses, gainer_analyses, loser_analyses) each { ticker: analysis }.
    """
    def trend_task(item: dict) -> tuple[str, str]:
        t = item.get("ticker", "")
        try:
            return (t, analyze_trending_stock(t, item, ""))
        except Exception as e:
            logger.warning("Trending analysis %s: %s", t, e)
            return (t, "Analysis temporarily unavailable.")

    def gainer_task(item: dict) -> tuple[str, str]:
        t = item.get("ticker", "")
        try:
            return (t, analyze_gainer_stock(t, item))
        except Exception as e:
            logger.warning("Gainer analysis %s: %s", t, e)
            return (t, "Analysis temporarily unavailable.")

    def loser_task(item: dict) -> tuple[str, str]:
        t = item.get("ticker", "")
        try:
            return (t, analyze_loser_stock(t, item))
        except Exception as e:
            logger.warning("Loser analysis %s: %s", t, e)
            return (t, "Analysis temporarily unavailable.")

    trend_analyses: dict[str, str] = {}
    gainer_analyses: dict[str, str] = {}
    loser_analyses: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for item in trending:
            futures.append(("trend", executor.submit(trend_task, item)))
        for item in gainers:
            futures.append(("gain", executor.submit(gainer_task, item)))
        for item in losers:
            futures.append(("loss", executor.submit(loser_task, item)))
        for kind, fut in futures:
            try:
                ticker, text = fut.result()
                if kind == "trend":
                    trend_analyses[ticker] = text
                elif kind == "gain":
                    gainer_analyses[ticker] = text
                else:
                    loser_analyses[ticker] = text
            except Exception as e:
                logger.warning("Market widget analysis future: %s", e)
    return trend_analyses, gainer_analyses, loser_analyses


def analyze_trending_stock(ticker: str, price_data: dict, trending_context: str = "") -> str:
    """Explain why this stock is trending today - volume spike, news catalyst, or sector move. 2 sentences max."""
    key = _cached_key("trending", ticker, (trending_context or "")[:80])
    cached = _get_cached(key)
    if cached:
        return cached
    price = _safe_num(price_data.get("price"), 0.0)
    pct = _safe_num(price_data.get("change_pct"), 0.0)
    vol = price_data.get("volume")
    vol = int(_safe_num(vol, 0)) if vol is not None else None
    vol_str = f" Volume {vol/1e6:.1f}M" if vol else ""
    user = (
        f"Trending stock {ticker}: ${price:.2f} {'up' if pct >= 0 else 'down'} {abs(pct):.1f}%{vol_str}. "
        "Explain why this stock is trending today - volume spike, news catalyst, or sector move. 2 sentences max. Plain text only."
    )
    try:
        out = _call_claude(user, max_tokens=150)
        _set_cached(key, out)
        return out
    except Exception:
        return "Analysis temporarily unavailable."


def analyze_gainer_stock(ticker: str, price_data: dict) -> str:
    """Explain the catalyst for this gain and whether it is sustainable. 2 sentences max."""
    key = _cached_key("gainer", ticker, str(_safe_num(price_data.get("change_pct"))))
    cached = _get_cached(key)
    if cached:
        return cached
    price = _safe_num(price_data.get("price"), 0.0)
    pct = _safe_num(price_data.get("change_pct"), 0.0)
    user = (
        f"Top gainer {ticker}: ${price:.2f} up {pct:.1f}%. "
        "Explain the catalyst for this gain - earnings, upgrade, sector momentum. Is it sustainable? 2 sentences max. Plain text only."
    )
    try:
        out = _call_claude(user, max_tokens=150)
        _set_cached(key, out)
        return out
    except Exception:
        return "Analysis temporarily unavailable."


def analyze_loser_stock(ticker: str, price_data: dict) -> str:
    """Explain this decline - company-specific or sector-wide. Note support levels. 2 sentences max."""
    key = _cached_key("loser", ticker, str(_safe_num(price_data.get("change_pct"))))
    cached = _get_cached(key)
    if cached:
        return cached
    price = _safe_num(price_data.get("price"), 0.0)
    pct = _safe_num(price_data.get("change_pct"), 0.0)
    user = (
        f"Top loser {ticker}: ${price:.2f} down {abs(pct):.1f}%. "
        "Explain this decline - company-specific or sector-wide. Note support levels. 2 sentences max. Plain text only."
    )
    try:
        out = _call_claude(user, max_tokens=150)
        _set_cached(key, out)
        return out
    except Exception:
        return "Analysis temporarily unavailable."


def analyze_volume_spike(ticker: str, price_data: dict, volume_data: dict) -> str:
    """Explain reason for elevated volume; strength vs distribution."""
    key = _cached_key("volume", ticker, str(volume_data.get("volume")))
    cached = _get_cached(key)
    if cached:
        return cached
    price = _safe_num(price_data.get("price"), 0.0)
    pct = _safe_num(price_data.get("change_pct"), 0.0)
    vol = volume_data.get("volume") or price_data.get("volume")
    vol = int(_safe_num(vol, 0)) if vol is not None else 0
    avg = volume_data.get("avg_volume")
    avg = _safe_num(avg, 0) if avg is not None else 0
    vol_note = f" Volume {vol/1e6:.1f}M" + (f" ({vol/avg:.1f}x average)" if avg and avg > 0 else "") if vol else ""
    user = (
        f"Most active {ticker}: ${price:.2f} {'up' if pct >= 0 else 'down'} {abs(pct):.1f}%{vol_note}. "
        "In 2-3 sentences: why is volume elevated—institutional, retail, news, technical? Does high volume signal strength or distribution?"
    )
    try:
        out = _call_claude(user)
        _set_cached(key, out)
        return out
    except Exception:
        return "Analysis temporarily unavailable."


def analyze_big_mover(
    ticker: str, price_data: dict, percent_change: float, direction: str
) -> str:
    """Explain catalyst for major gain or loss; sustainable or reversal."""
    key = _cached_key("mover", ticker, f"{direction}_{percent_change:.1f}")
    cached = _get_cached(key)
    if cached:
        return cached
    price = _safe_num(price_data.get("price"), 0.0)
    percent_change = _safe_num(percent_change, 0.0)
    user = (
        f"Biggest {direction} {ticker}: ${price:.2f} {percent_change:+.1f}%. "
        "In 2-3 sentences: what is the catalyst (earnings, upgrade, sector, short squeeze, news)? Is the move sustainable or likely to reverse? Any level to watch?"
    )
    try:
        out = _call_claude(user)
        _set_cached(key, out)
        return out
    except Exception:
        return "Analysis temporarily unavailable."


def batch_analyze_stocks(
    items: list[dict],
    analysis_type: str,
    build_prompt: Callable[[dict, int], str],
) -> list[str]:
    """Efficiently analyze multiple stocks in one Claude call. build_prompt(item, index) -> str per item."""
    # For simplicity we do one API call per item to keep responses aligned; could batch into single message with numbered items
    results = []
    for i, item in enumerate(items):
        ticker = item.get("ticker") or item.get("symbol", "")
        key = _cached_key(f"batch_{analysis_type}", ticker, str(i))
        cached = _get_cached(key)
        if cached:
            results.append(cached)
            continue
        try:
            user = build_prompt(item, i)
            out = _call_claude(user, max_tokens=200)
            _set_cached(key, out)
            results.append(out)
        except Exception:
            results.append("Analysis temporarily unavailable.")
    return results
