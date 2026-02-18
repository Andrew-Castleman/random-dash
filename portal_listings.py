"""
Portal (API) rental listings for SF and Stanford area.
Minimizes API calls: 7-day cache, persistent cache file, 2 cities for Stanford, serve stale when at limit.
"""

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests

from database import get_monthly_api_call_count, increment_api_call_count, reset_monthly_api_counter_if_needed

try:
    from craigslist_scraper import get_neighborhood_market_rates, get_stanford_market_rates
except ImportError:
    get_neighborhood_market_rates = None
    get_stanford_market_rates = None

logger = logging.getLogger(__name__)

API_KEY = os.environ.get("RENTCAST_API_KEY", "").strip()
BASE_URL = "https://api.rentcast.io/v1"
# 7-day default cache to minimize API calls (50/month budget)
CACHE_TTL = int(os.environ.get("PORTAL_CACHE_TTL", "604800"))
MIN_REQUEST_INTERVAL = int(os.environ.get("PORTAL_MIN_REQUEST_INTERVAL", "5"))  # Reduced from 120s to 5s
REQUEST_TIMEOUT = 25
MAX_RESULTS = 100
MAX_MONTHLY_CALLS = 50

# Persistent cache path (survives restarts so deploys don't burn calls)
_CACHE_FILE = os.environ.get("PORTAL_CACHE_FILE", "").strip() or (Path(__file__).resolve().parent / "data" / "portal_listings_cache.json")

# Optional: static map image URL for card thumbnails. Use {lat} and {lon} placeholders.
# Example (Mapbox): https://api.mapbox.com/styles/v1/mapbox/streets-v11/static/pin-l+ff0000({lon},{lat})/{lon},{lat},14,0/400x200@2x?access_token=YOUR_TOKEN
STATIC_MAP_URL_TEMPLATE = os.environ.get("STATIC_MAP_URL_TEMPLATE", "").strip()

# Initialize cache structures BEFORE loading persistent cache
_cache: dict[str, tuple[list[dict], float]] = {}
_cache_lock = threading.Lock()
_last_request: dict[str, float] = {}
_request_lock = threading.Lock()
# Cache API count for 5 seconds to avoid repeated DB queries
_api_count_cache: tuple[int, float] = (0, 0.0)
_api_count_cache_lock = threading.Lock()

# Initialize: reset counter if new month (no-op if DB/table not ready)
try:
    reset_monthly_api_counter_if_needed()
except Exception as e:
    logger.warning("Portal listings: could not reset monthly API counter at startup: %s", e)


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
                    ent = v["entries"]
                    if isinstance(ent, list) and ent:
                        _cache[k] = (ent, float(v["ts"]))
        logger.info("Loaded portal listings cache from %s (%s keys)", path, len(_cache))
    except Exception as e:
        logger.warning("Could not load portal cache file %s: %s", path, e)


def _save_persistent_cache() -> None:
    """Write in-memory cache to file. Non-blocking: runs in background thread."""
    path = Path(_CACHE_FILE) if isinstance(_CACHE_FILE, str) else _CACHE_FILE
    
    def _write():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with _cache_lock:
                data = {k: {"entries": entries, "ts": ts} for k, (entries, ts) in _cache.items()}
            with open(path, "w") as f:
                json.dump(data, f, separators=(",", ":"))
        except Exception as e:
            logger.warning("Could not save portal cache file %s: %s", path, e)
    
    # Write asynchronously to avoid blocking API response
    threading.Thread(target=_write, daemon=True).start()


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
    """Rate limit: only sleep if last request was very recent (< 5s). Prevents rapid-fire calls."""
    with _request_lock:
        last = _last_request.get(region, 0)
        elapsed = time.time() - last
        if elapsed < MIN_REQUEST_INTERVAL:
            sleep_time = MIN_REQUEST_INTERVAL - elapsed
            if sleep_time > 0:
                logger.debug("Rate limiting %s: sleeping %.1fs", region, sleep_time)
                time.sleep(sleep_time)
        _last_request[region] = time.time()


def _is_publicly_listed(item: dict[str, Any]) -> bool:
    """Include listings that are active and not removed. Include when status missing (API may omit)."""
    status = (item.get("status") or "").strip().lower()
    if status and status != "active":
        return False
    if item.get("removedDate"):
        return False
    return True


def _listing_url(item: dict[str, Any], address: str) -> str:
    """Use link from API when available; else agent/office/builder site, mailto, Google only as last resort."""
    # 1. Prefer any direct listing URL from the API (if they add url/link/listingUrl etc.)
    for key in ("url", "link", "listingUrl", "listingLink", "sourceUrl", "propertyUrl", "listing_url"):
        u = (item.get(key) or "").strip()
        if u and (u.startswith("http://") or u.startswith("https://")):
            return u
    # 2. Agent, office, or builder website (from API)
    agent = item.get("listingAgent") or {}
    office = item.get("listingOffice") or {}
    builder = item.get("builder") or {}
    url = (
        (agent.get("website") or "").strip()
        or (office.get("website") or "").strip()
        or (builder.get("website") or "").strip()
    )
    if url and (url.startswith("http://") or url.startswith("https://")):
        return url
    # 3. Contact email
    email = (agent.get("email") or office.get("email") or "").strip()
    if email:
        return "mailto:" + email
    # 4. Only then fall back to Google search
    query = quote_plus((address or item.get("city") or "rental") + " rental listing")
    return "https://www.google.com/search?q=" + query


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

    address = item.get("formattedAddress") or item.get("addressLine1") or ""
    url = _listing_url(item, address)

    lat = item.get("latitude")
    lon = item.get("longitude")
    thumbnail_url = None
    if STATIC_MAP_URL_TEMPLATE and lat is not None and lon is not None:
        try:
            thumbnail_url = STATIC_MAP_URL_TEMPLATE.format(lat=float(lat), lon=float(lon))
        except (KeyError, ValueError):
            pass
    # If no template: Rentcast does not provide listing photos; frontend shows interactive map

    return {
        "title": address or "Rental listing",
        "url": url,
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
        "thumbnail_url": thumbnail_url,
        "latitude": lat,
        "longitude": lon,
        "source": "portal",
    }


def _score_portal_listing(apt: dict[str, Any], market_rates: dict[str, Any]) -> None:
    """
    Set deal_score (0-100), discount_pct, and deal_analysis from listing details vs neighborhood.
    Uses: bedrooms, bathrooms, br:bath ratio, laundry, parking, sqft, price vs neighborhood expectations.
    """
    if not apt.get("price"):
        apt["deal_score"] = 0
        apt["deal_analysis"] = "Price information missing."
        apt["discount_pct"] = None
        return
    bedrooms = apt.get("bedrooms")
    if bedrooms is None:
        apt["deal_score"] = 40
        apt["deal_analysis"] = "Bedroom count not specified — difficult to evaluate value."
        apt["discount_pct"] = None
        return

    neighborhood = (apt.get("neighborhood") or "").strip()
    hood_key = neighborhood.lower().replace(" ", "-") if neighborhood else "default"
    if hood_key not in (market_rates or {}):
        hood_key = hood_key.replace("-", " ")
    rates = (market_rates or {}).get(hood_key, (market_rates or {}).get("default", {}))
    bed_key = "studio" if bedrooms == 0 else f"{min(bedrooms, 3)}br"
    market_rate = rates.get(bed_key, rates.get("1br", 3000))
    discount_pct = round((market_rate - apt["price"]) / market_rate * 100, 1) if market_rate else 0
    apt["discount_pct"] = discount_pct

    base = 50 + int(discount_pct)
    if apt.get("laundry_type") == "in_unit":
        base += 6
    elif apt.get("laundry_type") == "in_building":
        base += 2
    if apt.get("parking"):
        base += 4
    baths = apt.get("bathrooms")
    if baths is not None and bedrooms is not None and bedrooms > 0:
        if baths / bedrooms >= 1.0:
            base += 3
        elif baths / bedrooms >= 0.75:
            base += 1
    sqft = apt.get("sqft")
    if sqft and bedrooms and bedrooms > 0:
        sqft_per_bed = sqft / bedrooms
        if sqft_per_bed >= 600:
            base += 2
        elif sqft_per_bed >= 500:
            base += 1

    apt["deal_score"] = min(100, max(0, base))
    parts = []
    if discount_pct > 5:
        parts.append(f"~{discount_pct:.0f}% below market for {bed_key} in {neighborhood or 'area'}.")
    elif discount_pct < -5:
        parts.append(f"~{abs(discount_pct):.0f}% above typical for {bed_key} in {neighborhood or 'area'}.")
    else:
        parts.append(f"Roughly at market for {bed_key} in {neighborhood or 'area'}.")
    if apt.get("laundry_type") == "in_unit":
        parts.append("In-unit laundry.")
    elif apt.get("laundry_type") == "in_building":
        parts.append("Laundry in building.")
    if apt.get("parking"):
        parts.append("Parking.")
    if baths is not None and bedrooms and baths >= bedrooms:
        parts.append("Full bath per bedroom.")
    if sqft and bedrooms and bedrooms > 0 and sqft / bedrooms >= 550:
        parts.append("Good sqft for bedroom count.")
    apt["deal_analysis"] = " ".join(parts).strip() or "Listed via portal. Contact agent for details."


def _apply_portal_scores(entries: list[dict[str, Any]], get_market_rates: Any) -> None:
    """Apply deal scores to portal entries using neighborhood market rates."""
    if not get_market_rates:
        return
    try:
        market_rates = get_market_rates()
    except Exception as e:
        logger.warning("Portal scoring: could not get market rates: %s", e)
        return
    for apt in entries:
        try:
            _score_portal_listing(apt, market_rates)
        except Exception as e:
            logger.debug("Portal score one listing: %s", e)
            apt["deal_score"] = 50
            apt["deal_analysis"] = "Listed via portal. Contact agent for details."
            apt["discount_pct"] = None


def _get_cached_api_count() -> int:
    """Get API count with 5-second cache to avoid repeated DB queries."""
    global _api_count_cache
    now = time.time()
    with _api_count_cache_lock:
        cached_count, cached_ts = _api_count_cache
        if now - cached_ts < 5.0:
            return cached_count
        count = get_monthly_api_call_count()
        _api_count_cache = (count, now)
        return count


def _fetch(city: str, state: str, min_price: int, max_price: int, limit: int) -> list[dict]:
    """Fetch from API. Checks monthly limit first; increments counter only on success."""
    if not API_KEY:
        logger.warning("RENTCAST_API_KEY not set; portal listings disabled")
        return []
    
    # Check monthly limit BEFORE making API call (with cache)
    current_count = _get_cached_api_count()
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
        if isinstance(data, list):
            raw_list = data
        elif isinstance(data, dict):
            raw_list = data.get("data") or data.get("results") or data.get("listings") or []
            if not isinstance(raw_list, list):
                raw_list = []
        else:
            raw_list = []
        result = [it for it in raw_list if isinstance(it, dict) and _is_publicly_listed(it)]
        
        # Only increment counter on successful API call
        if increment_api_call_count():
            # Invalidate cache and get fresh count
            with _api_count_cache_lock:
                new_count = get_monthly_api_call_count()
                _api_count_cache = (new_count, time.time())
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
            if now - ts < CACHE_TTL and entries:
                logger.debug("Returning cached SF listings (age: %ss)", int(now - ts))
                _apply_portal_scores(entries, get_neighborhood_market_rates)
                return entries[:max_return]
            stale_entries, stale_ts = entries, ts  # keep for limit fallback
        else:
            stale_entries, stale_ts = [], 0.0

    if _get_cached_api_count() >= MAX_MONTHLY_CALLS:
        if stale_entries:
            logger.info("Monthly limit reached; serving stale SF cache (age: %ss)", int(now - stale_ts))
            _apply_portal_scores(stale_entries, get_neighborhood_market_rates)
            return stale_entries[:max_return]
        logger.warning("Monthly API limit reached. No stale cache. Returning empty.")
        return []

    _rate_limit("sf")
    raw = _fetch("San Francisco", "CA", min_price, max_price, max_return)
    entries = [_normalize(it) for it in raw if _is_publicly_listed(it)]
    _apply_portal_scores(entries, get_neighborhood_market_rates)
    with _cache_lock:
        if entries or cache_key not in _cache:
            _cache[cache_key] = (entries, time.time())
            _save_persistent_cache()
        elif cache_key in _cache:
            entries, _ = _cache[cache_key]
    _apply_portal_scores(entries, get_neighborhood_market_rates)
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
            if now - ts < CACHE_TTL and entries:
                logger.debug("Returning cached Stanford listings (age: %ss)", int(now - ts))
                _apply_portal_scores(entries, get_stanford_market_rates)
                return entries[:max_return]
            stale_entries, stale_ts = entries, ts
        else:
            stale_entries, stale_ts = [], 0.0

    if _get_cached_api_count() >= MAX_MONTHLY_CALLS:
        if stale_entries:
            logger.info("Monthly limit reached; serving stale Stanford cache (age: %ss)", int(now - stale_ts))
            _apply_portal_scores(stale_entries, get_stanford_market_rates)
            return stale_entries[:max_return]
        logger.warning("Monthly API limit reached. No stale cache. Returning empty.")
        return []

    _rate_limit("stanford")
    # Two cities only: 2 API calls per full refresh when cache misses - fetch in parallel
    cities = [("Palo Alto", "CA"), ("Menlo Park", "CA")]
    per_city = max(50, (max_return + len(cities) - 1) // len(cities))
    seen: set[str] = set()
    all_entries: list[dict] = []
    
    # Check limit once before parallel fetch
    if _get_cached_api_count() >= MAX_MONTHLY_CALLS:
        logger.warning("Monthly limit reached before Stanford fetch")
    else:
        # Fetch both cities in parallel
        def fetch_city(city_state):
            city, state = city_state
            if _get_cached_api_count() >= MAX_MONTHLY_CALLS:
                logger.warning("Monthly limit reached while fetching %s. Skipping.", city)
                return []
            return _fetch(city, state, min_price, max_price, per_city)
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {executor.submit(fetch_city, cs): cs for cs in cities}
            for future in as_completed(futures):
                city, state = futures[future]
                try:
                    for it in future.result():
                        if not _is_publicly_listed(it):
                            continue
                        lid = it.get("id")
                        if lid and lid in seen:
                            continue
                        if lid:
                            seen.add(lid)
                        all_entries.append(_normalize(it))
                except Exception as e:
                    logger.warning("Error fetching %s: %s", city, e)
    all_entries.sort(key=lambda x: x.get("price") or 0)
    _apply_portal_scores(all_entries, get_stanford_market_rates)
    with _cache_lock:
        if all_entries or cache_key not in _cache:
            _cache[cache_key] = (all_entries, time.time())
            _save_persistent_cache()
        elif cache_key in _cache:
            all_entries, _ = _cache[cache_key]
    _apply_portal_scores(all_entries, get_stanford_market_rates)
    return all_entries[:max_return]
