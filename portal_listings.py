"""
Portal (API) rental listings for SF and Stanford area.
Minimizes API calls: 7-day cache, persistent cache file, 2 cities for Stanford, serve stale when at limit.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import requests

from database import get_monthly_api_call_count, increment_api_call_count, reset_monthly_api_counter_if_needed

logger = logging.getLogger(__name__)

API_KEY = os.environ.get("RENTCAST_API_KEY", "").strip()
BASE_URL = "https://api.rentcast.io/v1"
# 7-day default cache to minimize API calls (50/month budget)
CACHE_TTL = int(os.environ.get("PORTAL_CACHE_TTL", "604800"))
MIN_REQUEST_INTERVAL = int(os.environ.get("PORTAL_MIN_REQUEST_INTERVAL", "120"))
REQUEST_TIMEOUT = 25
MAX_RESULTS = 100
MAX_MONTHLY_CALLS = 50

# Persistent cache path (survives restarts so deploys don't burn calls)
_CACHE_FILE = os.environ.get("PORTAL_CACHE_FILE", "").strip() or (Path(__file__).resolve().parent / "data" / "portal_listings_cache.json")

# Initialize cache structures BEFORE loading persistent cache
_cache: dict[str, tuple[list[dict], float]] = {}
_cache_lock = threading.Lock()
_last_request: dict[str, float] = {}
_request_lock = threading.Lock()

# Initialize: reset counter if new month
reset_monthly_api_counter_if_needed()


def _load_persistent_cache() -> None:
    """Load cache from file so restarts don't burn API calls."""
    global _cache
    path = Path(_CACHE_FILE) if isinstance(_CACHE_FILE, str) else _CACHE_FILE
    if not path.exists():
        return
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        with _cache_lock:
            for k, v in data.items():
                if isinstance(v, dict) and "entries" in v and "ts" in v:
                    _cache[k] = (v["entries"], float(v["ts"]))
        logger.info("Loaded portal listings cache from %s (%s keys)", path, len(_cache))
    except Exception as e:
        logger.warning("Could not load portal cache file %s: %s", path, e)


def _save_persistent_cache() -> None:
    """Write in-memory cache to file."""
    path = Path(_CACHE_FILE) if isinstance(_CACHE_FILE, str) else _CACHE_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _cache_lock:
            data = {k: {"entries": entries, "ts": ts} for k, (entries, ts) in _cache.items()}
        with open(path, "w") as f:
            json.dump(data, f, separators=(",", ":"))
    except Exception as e:
        logger.warning("Could not save portal cache file %s: %s", path, e)


# Load persistent cache on import (so restarts reuse data)
_load_persistent_cache()


def get_api_usage_info() -> dict[str, Any]:
    """Get current API usage info for monitoring."""
    count = get_monthly_api_call_count()
    return {
        "current_month_calls": count,
        "monthly_limit": MAX_MONTHLY_CALLS,
        "remaining_calls": max(0, MAX_MONTHLY_CALLS - count),
        "limit_reached": count >= MAX_MONTHLY_CALLS,
    }


def _rate_limit(region: str) -> None:
    with _request_lock:
        last = _last_request.get(region, 0)
        if time.time() - last < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - (time.time() - last))
        _last_request[region] = time.time()


def _is_publicly_listed(item: dict[str, Any]) -> bool:
    """Only include listings that are currently active and publicly listed."""
    status = (item.get("status") or "").strip()
    if status.lower() != "active":
        return False
    # Exclude if listing has been removed (no longer current)
    if item.get("removedDate"):
        return False
    return True


def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    """Map API fields to our card shape. API data is structured—minimal coercion."""
    # API returns numbers; coerce price in case it's a string
    try:
        price = item.get("price")
        price = int(price) if isinstance(price, (int, float)) else (int(float(price)) if price else None)
    except (TypeError, ValueError):
        price = None
    try:
        b, s = item.get("bedrooms"), item.get("squareFootage")
        bedrooms = int(b) if b is not None else None
        sqft = int(s) if s is not None else None
    except (TypeError, ValueError):
        bedrooms = sqft = None
    bathrooms = item.get("bathrooms")

    agent = item.get("listingAgent") or {}
    office = item.get("listingOffice") or {}
    url = agent.get("website") or office.get("website") or ""
    if not url and (agent.get("email") or office.get("email")):
        url = "mailto:" + (agent.get("email") or office.get("email"))

    return {
        "title": item.get("formattedAddress") or item.get("addressLine1") or "Rental listing",
        "url": url or "#",
        "price": price,
        "neighborhood": item.get("city") or "Unknown",
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "sqft": sqft,
        "price_per_sqft": round(price / sqft, 2) if price and sqft else None,
        "price_per_bedroom": round(price / bedrooms, 2) if price and bedrooms else None,
        "posted_date": (item.get("listedDate") or "")[:10] or None,
        "deal_score": None,
        "deal_analysis": "Listed via portal. Contact agent for details.",
        "discount_pct": None,
        "laundry_type": None,
        "parking": None,
        "thumbnail_url": None,
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "source": "portal",
    }


def _fetch(city: str, state: str, min_price: int, max_price: int, limit: int) -> list[dict]:
    """Fetch from API. Checks monthly limit first; increments counter only on success."""
    if not API_KEY:
        logger.warning("RENTCAST_API_KEY not set; portal listings disabled")
        return []
    
    # Check monthly limit BEFORE making API call
    current_count = get_monthly_api_call_count()
    if current_count >= MAX_MONTHLY_CALLS:
        logger.error(
            f"RentCast API monthly limit reached: {current_count}/{MAX_MONTHLY_CALLS} calls. "
            "No more API calls will be made this month. Using cached data only."
        )
        return []
    
    try:
        r = requests.get(
            f"{BASE_URL}/listings/rental/long-term",
            params={
                "city": city,
                "state": state,
                "price": f"{min_price}:{max_price}",
                "status": "Active",
                "limit": min(limit, 500),
            },
            headers={"X-Api-Key": API_KEY},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        raw_list = data if isinstance(data, list) else []
        # Only include currently active, publicly listed (not removed)
        result = [it for it in raw_list if _is_publicly_listed(it)]
        
        # Only increment counter on successful API call
        if increment_api_call_count():
            new_count = get_monthly_api_call_count()
            logger.info(f"RentCast API call successful. Monthly usage: {new_count}/{MAX_MONTHLY_CALLS}")
        else:
            logger.error("Failed to increment API call counter (limit may have been reached during call)")
        
        return result
    except Exception as e:
        logger.warning("Portal API request failed: %s", e)
        return []


def get_portal_listings_sf(
    min_price: int = 2000,
    max_price: int = 5000,
    max_return: int = 200,
) -> list[dict[str, Any]]:
    """Get SF listings. Long-lived cache; persistent file; stale served when at limit."""
    cache_key = f"sf_{min_price}_{max_price}"
    now = time.time()
    with _cache_lock:
        if cache_key in _cache:
            entries, ts = _cache[cache_key]
            if now - ts < CACHE_TTL:
                logger.debug("Returning cached SF listings (age: %ss)", int(now - ts))
                return entries[:max_return]
            stale_entries, stale_ts = entries, ts  # keep for limit fallback
        else:
            stale_entries, stale_ts = [], 0.0

    if get_monthly_api_call_count() >= MAX_MONTHLY_CALLS:
        if stale_entries:
            logger.info("Monthly limit reached; serving stale SF cache (age: %ss)", int(now - stale_ts))
            return stale_entries[:max_return]
        logger.warning("Monthly API limit reached. No stale cache. Returning empty.")
        return []

    _rate_limit("sf")
    raw = _fetch("San Francisco", "CA", min_price, max_price, max_return)
    entries = [_normalize(it) for it in raw if _is_publicly_listed(it)]
    with _cache_lock:
        _cache[cache_key] = (entries, time.time())
    _save_persistent_cache()
    return entries[:max_return]


def get_portal_listings_stanford(
    min_price: int = 1500,
    max_price: int = 6500,
    max_return: int = 200,
) -> list[dict[str, Any]]:
    """Get Stanford area listings. Long-lived cache; persistent file; 2 cities only; stale when at limit."""
    cache_key = f"stanford_{min_price}_{max_price}"
    now = time.time()
    with _cache_lock:
        if cache_key in _cache:
            entries, ts = _cache[cache_key]
            if now - ts < CACHE_TTL:
                logger.debug("Returning cached Stanford listings (age: %ss)", int(now - ts))
                return entries[:max_return]
            stale_entries, stale_ts = entries, ts
        else:
            stale_entries, stale_ts = [], 0.0

    if get_monthly_api_call_count() >= MAX_MONTHLY_CALLS:
        if stale_entries:
            logger.info("Monthly limit reached; serving stale Stanford cache (age: %ss)", int(now - stale_ts))
            return stale_entries[:max_return]
        logger.warning("Monthly API limit reached. No stale cache. Returning empty.")
        return []

    _rate_limit("stanford")
    # Two cities only: 2 API calls per full refresh when cache misses
    cities = [("Palo Alto", "CA"), ("Menlo Park", "CA")]
    per_city = max(50, (max_return + len(cities) - 1) // len(cities))
    seen: set[str] = set()
    all_entries: list[dict] = []
    for city, state in cities:
        if get_monthly_api_call_count() >= MAX_MONTHLY_CALLS:
            logger.warning("Monthly limit reached while fetching %s. Stopping.", city)
            break
        for it in _fetch(city, state, min_price, max_price, per_city):
            if not _is_publicly_listed(it):
                continue
            lid = it.get("id")
            if lid and lid in seen:
                continue
            if lid:
                seen.add(lid)
            all_entries.append(_normalize(it))
    all_entries.sort(key=lambda x: x.get("price") or 0)
    with _cache_lock:
        _cache[cache_key] = (all_entries, time.time())
    _save_persistent_cache()
    return all_entries[:max_return]
