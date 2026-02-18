"""
AI-Powered Market Intelligence Dashboard.

Portfolio + competitors, trending/gainers/losers, economic calendar, SF apartments.
Set FLASK_DEBUG=true for dev; PORT and config via environment.
"""

import math
import os
import time
import threading
import logging
from datetime import datetime
try:
    import resource
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (4096, 4096))
    except (ValueError, OSError):
        pass
except ImportError:
    pass

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS

import market_data as md
import agent_brain as brain
from database import init_db, save_portfolio_snapshot
from economic_calendar import get_economic_calendar
from craigslist_scraper import (
    scrape_sf_apartments,
    scrape_stanford_apartments,
    analyze_apartment_deals_cached,
    get_stanford_market_rates,
)
from portal_listings import get_portal_listings_sf, get_portal_listings_stanford

try:
    from config import PORT, FLASK_DEBUG
except ImportError:
    PORT = int(os.environ.get("PORT", "5000"))
    FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "false").strip().lower() in ("1", "true", "yes")

logging.basicConfig(
    level=logging.DEBUG if FLASK_DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_base_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(_base_dir, "templates"),
    static_folder=os.path.join(_base_dir, "static"),
)
CORS(app)

# 7 Silver Lake portfolio companies — max 2 competitors each (11 total)
SILVER_LAKE_PORTFOLIO = [
    ("DELL", "Dell Technologies", "Enterprise IT infrastructure", ["HPE", "IBM"]),
    ("MSGS", "MSG Sports", "Madison Square Garden sports and entertainment", ["LYV", "BATRA"]),
    ("GPN", "Global Payments", "Payment technology and processing", ["PYPL", "FIS"]),
    ("U", "Unity Software", "Gaming and 3D development platform", ["RBLX", "APP"]),
    ("FA", "First Advantage", "Employment screening and background checks", []),
    ("NABL", "N-able", "IT management software for MSPs", []),
    ("EVCM", "EverCommerce", "Business software for service industries", ["TOST"]),
]

# All competitor tickers for one parallel fetch
ALL_COMPETITOR_TICKERS = ["HPE", "IBM", "LYV", "BATRA", "PYPL", "FIS", "RBLX", "APP", "TOST"]

CACHE_TTL_FULL = 300
_cache: dict = {}
_cache_lock = threading.Lock()
NO_COMPETITORS_MSG = "No public competitors available"


def _safe_num(x, default=0.0):
    if x is None:
        return default
    if isinstance(x, float) and math.isnan(x):
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _format_competitors(competitor_data: list) -> str:
    if not competitor_data:
        return NO_COMPETITORS_MSG
    parts = []
    for c in competitor_data:
        pct = _safe_num(c.get("change_pct"), None)
        if pct is not None:
            parts.append(f"{c.get('ticker', '')} {'up' if pct >= 0 else 'down'} {abs(pct):.1f}%")
    return ", ".join(parts) if parts else NO_COMPETITORS_MSG


def _refresh_all() -> tuple[list, list, list, list, list, list, dict]:
    """
    Refresh all data in parallel. No delays.
    Returns (portfolio_list, failed_tickers, trending, gainers, losers, errors, market_fallback).
    """
    errors = []
    market_fallback = {"trending": False, "gainers": False, "losers": False}
    portfolio = []
    failed = []

    # Phase 1: Fetch 7 portfolio tickers in parallel
    portfolio_tickers = [t[0] for t in SILVER_LAKE_PORTFOLIO]
    try:
        portfolio_data = md.fetch_all_stocks_parallel(portfolio_tickers)
    except Exception as e:
        logger.exception("Portfolio fetch: %s", e)
        errors.append(f"Portfolio fetch: {e}")
        portfolio_data = {}

    # Phase 2: Fetch all competitors in parallel
    try:
        competitor_data_all = md.fetch_all_stocks_parallel(ALL_COMPETITOR_TICKERS)
        competitor_by_ticker = {
            t: {"ticker": t, "price": d["price"], "change_pct": d["change_pct"]}
            for t, d in competitor_data_all.items()
        }
    except Exception as e:
        logger.warning("Competitor fetch: %s", e)
        competitor_by_ticker = {}

    # Phase 3: Claude analyses in parallel for stocks we have data for
    analysis_items = []
    for ticker, name, _desc, comp_tickers in SILVER_LAKE_PORTFOLIO:
        price_data = portfolio_data.get(ticker)
        if not price_data:
            failed.append(ticker)
            continue
        comp_list = [competitor_by_ticker[t] for t in comp_tickers if t in competitor_by_ticker]
        analysis_items.append((ticker, price_data, comp_list))

    analyses = {}
    if analysis_items:
        try:
            analyses = brain.analyze_all_stocks_parallel(analysis_items, max_workers=7)
        except Exception as e:
            logger.warning("Analyses: %s", e)
            errors.append(f"Analyses: {e}")

    # Build portfolio list in SILVER_LAKE order
    for ticker, name, _desc, comp_tickers in SILVER_LAKE_PORTFOLIO:
        price_data = portfolio_data.get(ticker)
        if not price_data:
            portfolio.append({
                "ticker": ticker,
                "name": name,
                "price": None,
                "change_pct": None,
                "volume": None,
                "analysis": "Data temporarily unavailable.",
                "competitors": [],
                "competitor_summary": NO_COMPETITORS_MSG if not comp_tickers else "—",
                "major_move": False,
            })
            continue
        comp_list = [competitor_by_ticker[t] for t in comp_tickers if t in competitor_by_ticker]
        comp_summary = _format_competitors(comp_list) if comp_list else NO_COMPETITORS_MSG
        price = _safe_num(price_data.get("price"), None)
        pct = _safe_num(price_data.get("change_pct"), 0.0)
        vol = int(_safe_num(price_data.get("volume"), 0))
        analysis = analyses.get(ticker) or "Analysis temporarily unavailable."
        try:
            save_portfolio_snapshot(ticker, price or 0, pct, vol, analysis, comp_summary)
        except Exception:
            pass
        portfolio.append({
            "ticker": ticker,
            "name": name,
            "price": price,
            "change_pct": pct,
            "volume": vol,
            "analysis": analysis,
            "competitors": comp_list,
            "competitor_summary": comp_summary,
            "major_move": abs(pct) > 3,
        })

    # Phase 4: Market widgets with fallback
    trending = []
    gainers = []
    losers = []
    try:
        trending, market_fallback["trending"] = md.get_trending_with_fallback()
    except Exception as e:
        logger.warning("Trending: %s", e)
        errors.append(f"Trending: {e}")
    try:
        gainers, market_fallback["gainers"] = md.get_gainers_with_fallback(5)
    except Exception as e:
        logger.warning("Gainers: %s", e)
        errors.append(f"Gainers: {e}")
    try:
        losers, market_fallback["losers"] = md.get_losers_with_fallback(5)
    except Exception as e:
        logger.warning("Losers: %s", e)
        errors.append(f"Losers: {e}")

    # Phase 5: AI summaries for trending/gainers/losers (parallel)
    try:
        trend_analyses, gainer_analyses, loser_analyses = brain.analyze_market_widgets_parallel(
            trending, gainers, losers, max_workers=10
        )
        for r in trending:
            r["analysis"] = trend_analyses.get(r.get("ticker"), "")
        for r in gainers:
            r["analysis"] = gainer_analyses.get(r.get("ticker"), "")
        for r in losers:
            r["analysis"] = loser_analyses.get(r.get("ticker"), "")
    except Exception as e:
        logger.warning("Market widget analyses: %s", e)
        fallback = "Analysis temporarily unavailable."
        for r in trending:
            r["analysis"] = r.get("analysis") or fallback
        for r in gainers:
            r["analysis"] = r.get("analysis") or fallback
        for r in losers:
            r["analysis"] = r.get("analysis") or fallback

    return portfolio, failed, trending, gainers, losers, errors, market_fallback


def _build_performance_summary(portfolio_list: list) -> dict:
    valid = [p for p in portfolio_list if p.get("change_pct") is not None]
    if not valid:
        return {"avg_change_pct": None, "best": None, "worst": None, "count": 0}
    avg = sum(p["change_pct"] for p in valid) / len(valid)
    best = max(valid, key=lambda p: p["change_pct"])
    worst = min(valid, key=lambda p: p["change_pct"])
    return {
        "avg_change_pct": round(avg, 2),
        "best": {"ticker": best["ticker"], "name": best["name"], "change_pct": best["change_pct"]},
        "worst": {"ticker": worst["ticker"], "name": worst["name"], "change_pct": worst["change_pct"]},
        "count": len(valid),
    }


def _build_top_movers(portfolio_list: list) -> dict:
    valid = [p for p in portfolio_list if p.get("change_pct") is not None]
    if not valid:
        return {"gainers": [], "losers": []}
    sorted_by_pct = sorted(valid, key=lambda p: p["change_pct"], reverse=True)
    gainers = [{"ticker": p["ticker"], "name": p["name"], "change_pct": p["change_pct"], "price": p.get("price")} for p in sorted_by_pct[:3]]
    losers = [{"ticker": p["ticker"], "name": p["name"], "change_pct": p["change_pct"], "price": p.get("price")} for p in sorted_by_pct[-3:][::-1]]
    return {"gainers": gainers, "losers": losers}


def _build_portfolio_vs_market(portfolio_list: list) -> dict:
    valid = [p for p in portfolio_list if p.get("change_pct") is not None]
    if not valid:
        return {"portfolio_avg_pct": None, "spy_pct": None, "outperformance": None}
    portfolio_avg = sum(p["change_pct"] for p in valid) / len(valid)
    spy_data = md.get_stock_data("SPY")
    spy_pct = _safe_num(spy_data.get("change_pct"), None) if spy_data else None
    outperformance = (portfolio_avg - spy_pct) if spy_pct is not None else None
    return {
        "portfolio_avg_pct": round(portfolio_avg, 2),
        "spy_pct": round(spy_pct, 2) if spy_pct is not None else None,
        "outperformance": round(outperformance, 2) if outperformance is not None else None,
    }


def run_refresh():
    """Run full refresh and update cache. Never raises."""
    logger.info("Refreshing all data (parallel)...")
    start = time.time()
    try:
        portfolio, failed, trending, gainers, losers, errors, market_fallback = _refresh_all()
        updated = time.time()
        summary = _build_performance_summary(portfolio)
        movers = _build_top_movers(portfolio)
        vs_market = _build_portfolio_vs_market(portfolio)
        with _cache_lock:
            _cache["portfolio"] = {"data": portfolio, "updated": updated}
            _cache["performance_summary"] = {"data": summary, "updated": updated}
            _cache["top_movers"] = {"data": movers, "updated": updated}
            _cache["portfolio_vs_market"] = {"data": vs_market, "updated": updated}
            _cache["trending"] = {"data": trending, "updated": updated}
            _cache["gainers"] = {"data": gainers, "updated": updated}
            _cache["losers"] = {"data": losers, "updated": updated}
            _cache["errors"] = {"data": errors, "updated": updated}
            _cache["market_fallback"] = {"data": market_fallback, "updated": updated}
            _cache["last_failed"] = {"data": failed, "updated": updated}
        logger.info("Refresh complete in %.1fs. Succeeded: %s, Failed: %s", updated - start, len(portfolio) - len(failed), len(failed))
    except Exception as e:
        logger.exception("Refresh failed: %s", e)
        with _cache_lock:
            portfolio = _cache.get("portfolio", {}).get("data") or []


# ---------- Routes ----------

@app.route("/", methods=["GET"])
def index():
    return render_template("dashboard.html"), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/api/refresh", methods=["POST"])
def api_manual_refresh():
    """Trigger manual refresh. Never 500. Returns succeeded/failed and duration."""
    start = time.time()
    failed = []
    try:
        run_refresh()
        updated = time.time()
        with _cache_lock:
            portfolio = _cache.get("portfolio", {}).get("data") or []
            failed = _cache.get("last_failed", {}).get("data") or []
        succeeded = len([p for p in portfolio if p.get("price") is not None])
        return jsonify({
            "ok": True,
            "updated": updated,
            "duration_seconds": round(updated - start, 1),
            "succeeded": succeeded,
            "failed": len(failed),
            "failed_tickers": failed,
        })
    except Exception as e:
        logger.exception("Refresh error: %s", e)
        updated = time.time()
        with _cache_lock:
            portfolio = _cache.get("portfolio", {}).get("data") or []
            failed = _cache.get("last_failed", {}).get("data") or []
        return jsonify({
            "ok": True,
            "updated": updated,
            "duration_seconds": round(time.time() - start, 1),
            "succeeded": len([p for p in portfolio if p.get("price") is not None]),
            "failed": len(failed),
            "failed_tickers": failed,
            "warning": str(e),
        })


@app.route("/api/dashboard")
def api_dashboard():
    with _cache_lock:
        portfolio = _cache.get("portfolio", {}).get("data") or []
        summary = _cache.get("performance_summary", {}).get("data") or _build_performance_summary(portfolio)
        movers = _cache.get("top_movers", {}).get("data") or _build_top_movers(portfolio)
        vs_market = _cache.get("portfolio_vs_market", {}).get("data") or _build_portfolio_vs_market(portfolio)
        trending = _cache.get("trending", {}).get("data") or []
        gainers = _cache.get("gainers", {}).get("data") or []
        losers = _cache.get("losers", {}).get("data") or []
        errors = _cache.get("errors", {}).get("data") or []
        market_fallback = _cache.get("market_fallback", {}).get("data") or {}
        updated = _cache.get("portfolio", {}).get("updated", time.time())
    try:
        economic_calendar = get_economic_calendar(days_back_recent=30, days_ahead_upcoming=60)
    except Exception as e:
        logger.warning("Economic calendar failed: %s", e)
        economic_calendar = {"recent_releases": [], "upcoming_releases": []}
    if not isinstance(economic_calendar, dict):
        economic_calendar = {"recent_releases": [], "upcoming_releases": []}
    economic_calendar.setdefault("recent_releases", [])
    economic_calendar.setdefault("upcoming_releases", [])
    return jsonify({
        "portfolio": portfolio,
        "performance_summary": summary,
        "top_movers": movers,
        "portfolio_vs_market": vs_market,
        "trending": trending,
        "gainers": gainers,
        "losers": losers,
        "economic_calendar": economic_calendar,
        "errors": errors,
        "market_fallback": market_fallback,
        "updated": updated,
    })


def _register_debug_routes():
    """Register /api/apartments/debug only when FLASK_DEBUG is set."""
    @app.route("/api/apartments/debug")
    def debug_apartments():
        import requests as req
        from bs4 import BeautifulSoup as BS
        debug_info = {"timestamp": datetime.now().isoformat(), "steps": []}
        try:
            resp = req.get(
                "https://sfbay.craigslist.org/search/sfc/apa?min_price=2000&max_price=5000",
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
                timeout=10,
            )
            debug_info["steps"].append({
                "test": "Craigslist HTTP Request",
                "status": "success",
                "status_code": resp.status_code,
                "response_length": len(resp.text),
            })
            soup = BS(resp.text, "html.parser")
            class_counts = {cn: len(soup.find_all("li", class_=cn)) for cn in ("cl-search-result", "result-row", "cl-static-search-result")}
            listing_links = [a for a in soup.find_all("a", href=True) if "/sfc/apa/" in a.get("href", "") or "/apa/" in a.get("href", "")]
            debug_info["steps"].append({
                "test": "HTML Structure Check",
                "status": "success",
                "class_counts": class_counts,
                "total_li": len(soup.find_all("li")),
                "listing_like_links": len(listing_links),
            })
        except Exception as e:
            debug_info["steps"].append({"test": "Craigslist HTTP Request", "status": "failed", "error": str(e)})
        return jsonify(debug_info)


MAX_APARTMENTS_RETURN = 200
SCRAPE_POOL_SIZE = 400

# Refresh rate limit: per-IP, generous but prevents credit abuse
REFRESH_LIMIT_PER_HOUR = 15
REFRESH_MIN_INTERVAL_SECONDS = 120  # at least 2 min between refreshes
_refresh_timestamps = {}  # ip -> list of timestamps
_refresh_lock = threading.Lock()


def _client_ip(request):
    """Client IP for rate limiting (supports X-Forwarded-For behind proxy)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _check_refresh_rate_limit(ip):
    """
    Return (allowed: bool, retry_after_seconds: int).
    Prune timestamps older than 1 hour; allow if under limit and last refresh was at least MIN_INTERVAL ago.
    """
    now = time.time()
    window_start = now - 3600
    with _refresh_lock:
        timestamps = _refresh_timestamps.get(ip, [])
        timestamps = [t for t in timestamps if t > window_start]
        if len(timestamps) >= REFRESH_LIMIT_PER_HOUR:
            oldest_in_window = min(timestamps) if timestamps else now
            return False, int(3600 - (now - oldest_in_window)) + 1
        if timestamps and (now - max(timestamps)) < REFRESH_MIN_INTERVAL_SECONDS:
            return False, REFRESH_MIN_INTERVAL_SECONDS - int(now - max(timestamps))
        timestamps.append(now)
        _refresh_timestamps[ip] = timestamps
    return True, 0


@app.route("/api/apartments/portal")
def get_apartments_portal():
    """Portal (API) listings for SF. Cached; rate-limited. Same response shape as get_apartments."""
    try:
        apartments = get_portal_listings_sf(min_price=2000, max_price=5000, max_return=MAX_APARTMENTS_RETURN)
        total = len(apartments)
        excellent = len([a for a in apartments if (a.get("deal_score") or 0) >= 80])
        avg_price = round(sum(a["price"] for a in apartments if a.get("price")) / total) if total > 0 else 0
        return jsonify({
            "apartments": apartments,
            "stats": {"total": total, "excellent_deals": excellent, "average_price": avg_price},
            "last_updated": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.exception("Portal SF endpoint: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/apartments/portal/stanford")
def get_apartments_portal_stanford():
    """Portal (API) listings for Stanford area. Cached; rate-limited."""
    try:
        apartments = get_portal_listings_stanford(min_price=1500, max_price=6500, max_return=MAX_APARTMENTS_RETURN)
        total = len(apartments)
        excellent = len([a for a in apartments if (a.get("deal_score") or 0) >= 80])
        avg_price = round(sum(a["price"] for a in apartments if a.get("price")) / total) if total > 0 else 0
        return jsonify({
            "apartments": apartments,
            "stats": {"total": total, "excellent_deals": excellent, "average_price": avg_price},
            "last_updated": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.exception("Portal Stanford endpoint: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/apartments")
def get_apartments():
    """Alternate source: SF apartments in $2K-$5K range. Same response shape."""
    try:
        apartments = scrape_sf_apartments(max_listings=SCRAPE_POOL_SIZE)
        apartments = analyze_apartment_deals_cached(apartments, max_return=MAX_APARTMENTS_RETURN)
        total = len(apartments)
        excellent = len([a for a in apartments if a.get("deal_score", 0) >= 80])
        avg_price = round(sum(a["price"] for a in apartments if a.get("price")) / total) if total > 0 else 0
        return jsonify({
            "apartments": apartments,
            "stats": {
                "total": total,
                "excellent_deals": excellent,
                "average_price": avg_price,
            },
            "last_updated": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.exception("Apartments endpoint: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/apartments/refresh", methods=["POST"])
def refresh_apartments():
    """Manually refresh apartment listings. Returns top 200 by deal score. Rate-limited per IP."""
    ip = _client_ip(request)
    allowed, retry_after = _check_refresh_rate_limit(ip)
    if not allowed:
        return (
            jsonify({
                "success": False,
                "error": "refresh_limit",
                "message": "Too many refreshes. Wait a bit before trying again.",
                "retry_after_seconds": retry_after,
            }),
            429,
            {"Retry-After": str(max(1, retry_after))},
        )
    try:
        apartments = scrape_sf_apartments(max_listings=SCRAPE_POOL_SIZE)
        apartments = analyze_apartment_deals_cached(apartments, max_return=MAX_APARTMENTS_RETURN)
        total = len(apartments)
        excellent = len([a for a in apartments if a.get("deal_score", 0) >= 80])
        avg_price = round(sum(a["price"] for a in apartments if a.get("price")) / total) if total > 0 else 0
        return jsonify({
            "success": True,
            "apartments": apartments,
            "stats": {
                "total": total,
                "excellent_deals": excellent,
                "average_price": avg_price,
            },
        })
    except Exception as e:
        logger.exception("Apartments refresh: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/apartments/stanford")
def get_stanford_apartments():
    """Fetch and analyze Stanford area (peninsula) apartments. Student-friendly $1.5K–$6.5K (incl. 2BR). Returns top 200."""
    try:
        apartments = scrape_stanford_apartments(max_listings=SCRAPE_POOL_SIZE)
        apartments = analyze_apartment_deals_cached(
            apartments, max_return=MAX_APARTMENTS_RETURN, get_market_rates=get_stanford_market_rates
        )
        total = len(apartments)
        excellent = len([a for a in apartments if a.get("deal_score", 0) >= 80])
        avg_price = round(sum(a["price"] for a in apartments if a.get("price")) / total) if total > 0 else 0
        return jsonify({
            "apartments": apartments,
            "stats": {
                "total": total,
                "excellent_deals": excellent,
                "average_price": avg_price,
            },
            "last_updated": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.exception("Stanford apartments endpoint: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/apartments/stanford/refresh", methods=["POST"])
def refresh_stanford_apartments():
    """Manually refresh Stanford area listings. Rate-limited per IP (same as SF refresh)."""
    ip = _client_ip(request)
    allowed, retry_after = _check_refresh_rate_limit(ip)
    if not allowed:
        return (
            jsonify({
                "success": False,
                "error": "refresh_limit",
                "message": "Too many refreshes. Wait a bit before trying again.",
                "retry_after_seconds": retry_after,
            }),
            429,
            {"Retry-After": str(max(1, retry_after))},
        )
    try:
        apartments = scrape_stanford_apartments(max_listings=SCRAPE_POOL_SIZE)
        apartments = analyze_apartment_deals_cached(
            apartments, max_return=MAX_APARTMENTS_RETURN, get_market_rates=get_stanford_market_rates
        )
        total = len(apartments)
        excellent = len([a for a in apartments if a.get("deal_score", 0) >= 80])
        avg_price = round(sum(a["price"] for a in apartments if a.get("price")) / total) if total > 0 else 0
        return jsonify({
            "success": True,
            "apartments": apartments,
            "stats": {
                "total": total,
                "excellent_deals": excellent,
                "average_price": avg_price,
            },
        })
    except Exception as e:
        logger.exception("Stanford apartments refresh: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
