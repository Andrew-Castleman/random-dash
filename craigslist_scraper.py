"""
Craigslist SF apartment scraper ($2000-$5000/mo) with optional Claude AI deal scoring.

Scrapes sfbay.craigslist.org/sfc/apa with price filter; parses JSON-LD and HTML fallbacks.
Set SCRAPER_DEBUG=1 for verbose logs and /tmp HTML dump. Set ANTHROPIC_API_KEY for AI summaries.
"""

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Price range (USD/month)
MIN_PRICE = 2000
MAX_PRICE = 5000

# Request timeout and optional debug (dump HTML to /tmp)
try:
    from config import REQUEST_TIMEOUT, SCRAPER_DEBUG
except ImportError:
    REQUEST_TIMEOUT = int(os.environ.get("SCRAPER_TIMEOUT", "15"))
    SCRAPER_DEBUG = os.environ.get("SCRAPER_DEBUG", "").strip().lower() in ("1", "true", "yes")

CL_LISTING_BASE = "https://sfbay.craigslist.org"
CL_SEARCH_URL = f"{CL_LISTING_BASE}/search/sfc/apa"
# Peninsula (Palo Alto, Menlo Park, Stanford area) for student housing
CL_SEARCH_URL_PEN = f"{CL_LISTING_BASE}/search/pen/apa"
STANFORD_MIN_PRICE = 1500
STANFORD_MAX_PRICE = 6500

# Only show Stanford-area listings in these cities (near campus/hospital). Lowercase, allow partial match.
STANFORD_ALLOWED_NEIGHBORHOODS = frozenset([
    "palo alto", "menlo park", "east palo alto", "stanford", "redwood city", "mountain view",
    "palo alto / downtown", "downtown palo alto", "palo alto downtown", "old palo alto",
    "south palo alto", "north palo alto", "college terrace", "crescent park", "duveneck",
    "menlo park / downtown", "downtown menlo park", "willow", "belle haven", "shoreline",
    "redwood shores", "woodside", "atherton", "portola valley", "los altos", "los altos hills",
])


def _normalize_listing_url(url: Optional[str]) -> str:
    """Ensure listing URL is a direct sfbay.craigslist.org listing link (no redirects)."""
    if not url or not isinstance(url, str):
        return ""
    url = url.strip()
    if not url:
        return ""
    # Relative path -> direct sfbay link
    if url.startswith("/"):
        path = url.split("?")[0]
        if "/apa/" in path and (".html" in path or "/d/" in path):
            return CL_LISTING_BASE + path
        return CL_LISTING_BASE + url
    if not url.startswith("http://") and not url.startswith("https://"):
        path = url.split("?")[0]
        if "/apa/" in path:
            return CL_LISTING_BASE + "/" + path
        return CL_LISTING_BASE + "/" + url
    # Full URL: force direct sfbay.craigslist.org link (strip redirect/tracking)
    if "craigslist.org" in url:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            path = (parsed.path or "").strip()
            if path and path.startswith("/") and "/apa/" in path:
                return CL_LISTING_BASE + path.split("?")[0]
            if parsed.netloc and "sfbay.craigslist.org" in parsed.netloc:
                return url.split("?")[0]
        except Exception:
            pass
        return url
    return ""

# Claude client (optional; falls back to score-only when missing)
try:
    from anthropic import Anthropic
    _anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")) if os.getenv("ANTHROPIC_API_KEY") else None
except Exception:
    _anthropic = None


def inspect_craigslist_structure():
    """
    Debug function to examine current Craigslist HTML structure.
    Finds and prints all price-related elements to determine correct selectors.
    """
    url = f"{CL_SEARCH_URL}?min_price={MIN_PRICE}&max_price={MAX_PRICE}&availabilityMode=0"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        print(f"Status Code: {response.status_code}")
        print(f"Response Length: {len(response.text)} characters")
        if SCRAPER_DEBUG:
            try:
                with open("/tmp/craigslist_full.html", "w", encoding="utf-8") as f:
                    f.write(response.text)
                print("\nSaved full HTML to: /tmp/craigslist_full.html")
            except OSError:
                pass
        soup = BeautifulSoup(response.text, "html.parser")
        print("\n" + "=" * 60)
        print("SEARCHING FOR PRICE ELEMENTS")
        print("=" * 60)
        price_classes = ["price", "priceinfo", "result-price", "meta", "price-tag", "result-meta"]
        for class_name in price_classes:
            elements = soup.find_all(class_=class_name)
            print(f"\nClass '{class_name}': {len(elements)} found")
            if elements:
                print(f"  First example text: {elements[0].get_text().strip()[:50]}")
                print(f"  First example HTML: {str(elements[0])[:150]}")
        all_spans = soup.find_all("span")
        price_spans = [s for s in all_spans if "$" in (s.get_text() or "")]
        print(f"\n<span> elements with '$': {len(price_spans)} found")
        if price_spans:
            for span in price_spans[:3]:
                print(f"    - Class: {span.get('class')} | Text: {span.get_text().strip()}")
        all_divs = soup.find_all("div")
        price_divs = [d for d in all_divs if "$" in (d.get_text() or "") and len(d.get_text() or "") < 30]
        print(f"\n<div> elements with '$' (short text): {len(price_divs)} found")
        if price_divs:
            for div in price_divs[:3]:
                print(f"    - Class: {div.get('class')} | Text: {(div.get_text() or '').strip()}")
        print("\n" + "=" * 60)
        print("SEARCHING FOR LISTING CONTAINERS")
        print("=" * 60)
        container_classes = ["result-row", "cl-search-result", "cl-static-search-result", "result", "gallery-card"]
        for class_name in container_classes:
            containers = soup.find_all("li", class_=class_name)
            print(f"\nClass 'li.{class_name}': {len(containers)} found")
            if containers:
                print(f"  First listing preview (first 400 chars):")
                print(f"  {str(containers[0])[:400]}")
        print("\n" + "=" * 60)
        print("FIRST COMPLETE LISTING EXAMPLE")
        print("=" * 60)
        first_listing = (
            soup.find("li", class_="result-row")
            or soup.find("li", class_="cl-search-result")
            or soup.find("li", class_=lambda x: x and ("result" in str(x).lower() or "search" in str(x).lower()))
        )
        if first_listing:
            print(f"\nFull HTML of first listing (first 1000 chars):\n")
            print(first_listing.prettify()[:1000])
        else:
            print("\nNo listing found - Craigslist structure may have changed significantly")
        return response.text
    except Exception as e:
        print(f"\nError during inspection: {e}")
        import traceback
        traceback.print_exc()
        return None


def debug_first_listing():
    """
    Debug price extraction on the very first listing.
    Shows exactly what elements exist and which extraction method works.
    """
    url = f"{CL_SEARCH_URL}?min_price={MIN_PRICE}&max_price={MAX_PRICE}&availabilityMode=0"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    soup = BeautifulSoup(response.text, "html.parser")
    listing = (
        soup.find("li", class_="result-row")
        or soup.find("li", class_="cl-search-result")
        or soup.find("li", class_="cl-static-search-result")
        or soup.find("li", class_=lambda x: x and "result" in str(x).lower())
    )
    if not listing:
        print("ERROR: Could not find any listing container")
        return
    print("=" * 60)
    print("FIRST LISTING - PRICE EXTRACTION DEBUG")
    print("=" * 60)
    print(f"\nListing container class: {listing.get('class')}")
    print("\n--- Strategy 1: span.priceinfo ---")
    elem = listing.find("span", class_="priceinfo")
    print(f"Found: {elem}")
    if elem:
        print(f"Text: {elem.get_text()}")
    print("\n--- Strategy 2: span.result-price ---")
    elem = listing.find("span", class_="result-price")
    print(f"Found: {elem}")
    if elem:
        print(f"Text: {elem.get_text()}")
    print("\n--- Strategy 3: div.price or span.price ---")
    elem = listing.find("div", class_="price") or listing.find("span", class_="price")
    print(f"Found: {elem}")
    if elem:
        print(f"Text: {elem.get_text()}")
    print("\n--- Strategy 4: span.meta ---")
    elem = listing.find("span", class_="meta")
    print(f"Found: {elem}")
    if elem:
        print(f"Text: {elem.get_text()}")
    print("\n--- Strategy 5: Any element with 'price' in class name ---")
    elem = listing.find(class_=lambda x: x and "price" in str(x).lower())
    print(f"Found: {elem}")
    if elem:
        print(f"Text: {elem.get_text()}")
    print("\n--- Strategy 6: data-price attribute ---")
    print(f"data-price attribute: {listing.get('data-price')}")
    print("\n--- Strategy 7: All text content (first 300 chars) ---")
    print((listing.get_text() or "")[:300])
    print("\n--- Strategy 8: All dollar amounts in text ---")
    dollar_amounts = re.findall(r"\$\s*([\d,]+)", listing.get_text() or "")
    print(f"Found dollar amounts: {dollar_amounts}")
    print("\n" + "=" * 60)
    print("FULL LISTING HTML")
    print("=" * 60)
    print(listing.prettify())


def _area_from_search_url(search_url: str) -> str:
    """Extract area code from search URL e.g. .../search/pen/apa -> pen."""
    m = re.search(r"/search/([a-z]+)/apa", search_url or "")
    return m.group(1) if m else "sfc"


def scrape_sf_apartments(max_listings: int = 50) -> list[dict[str, Any]]:
    """Fetch SF apartments in price range. Tries JSON API, then HTML; returns sample on failure."""
    apartments = scrape_via_json_api()
    if apartments:
        logger.info("Scraped %s listings via JSON API", len(apartments))
        return apartments[:max_listings]

    apartments = scrape_via_html(max_listings)
    if apartments:
        logger.info("Scraped %s listings via HTML", len(apartments))
        return apartments[:max_listings]

    logger.warning("Scrape failed; returning sample data")
    return get_sample_apartments()


def _is_stanford_area_neighborhood(neighborhood: Optional[str]) -> bool:
    """True if the listing is in an allowed city/area near Stanford (school/hospital)."""
    if not neighborhood or not isinstance(neighborhood, str):
        return False
    n = neighborhood.lower().strip()
    if not n:
        return False
    n_clean = re.sub(r"[^\w\s/-]", "", n).strip()
    for allowed in STANFORD_ALLOWED_NEIGHBORHOODS:
        if allowed in n_clean or n_clean in allowed:
            return True
    if any(term in n for term in ("palo alto", "menlo park", "east palo alto", "stanford", "redwood city", "mountain view", "redwood shores", "los altos", "woodside", "atherton", "portola valley")):
        return True
    return False


def scrape_stanford_apartments(max_listings: int = 50) -> list[dict[str, Any]]:
    """Fetch peninsula apartments near Stanford (Palo Alto, Menlo Park, etc.). Filter to allowed areas only."""
    apartments = scrape_via_json_api(CL_SEARCH_URL_PEN, STANFORD_MIN_PRICE, STANFORD_MAX_PRICE)
    if apartments:
        apartments = [a for a in apartments if _is_stanford_area_neighborhood(a.get("neighborhood"))]
        logger.info("Scraped %s Stanford-area listings via JSON API (after neighborhood filter)", len(apartments))
        return apartments[:max_listings]

    apartments = scrape_via_html(
        max_listings * 2, search_url=CL_SEARCH_URL_PEN, min_price=STANFORD_MIN_PRICE, max_price=STANFORD_MAX_PRICE
    )
    if apartments:
        apartments = [a for a in apartments if _is_stanford_area_neighborhood(a.get("neighborhood"))]
        logger.info("Scraped %s Stanford-area listings via HTML (after neighborhood filter)", len(apartments))
        return apartments[:max_listings]

    logger.warning("Stanford area scrape failed; returning sample data")
    return get_sample_apartments_stanford()


def scrape_via_json_api(
    search_url: Optional[str] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Try Craigslist JSON-style response. Returns [] when not available."""
    search_url = search_url or CL_SEARCH_URL
    min_price = min_price if min_price is not None else MIN_PRICE
    max_price = max_price if max_price is not None else MAX_PRICE
    apartments = []
    try:
        json_url = f"{search_url}?format=json&min_price={min_price}&max_price={max_price}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        response = requests.get(json_url, headers=headers, timeout=REQUEST_TIMEOUT)
        logger.debug("JSON API status=%s", response.status_code)
        if response.status_code != 200:
            return []
        try:
            data = response.json()
            items = []
            if isinstance(data, dict):
                items = data.get("data", {}).get("items", []) or data.get("items", [])
            elif isinstance(data, list):
                items = data
            logger.debug("JSON API items=%s", len(items))
            for item in items[:50]:
                try:
                    price = item.get("ask") or item.get("price")
                    if not price:
                        continue
                    price = int(price)
                    if not (min_price <= price <= max_price):
                        continue
                    headline = item.get("headline", item.get("title", "Apartment"))
                    default_hood = "San Francisco" if "sfc" in search_url else "Palo Alto"
                    apartments.append({
                        "title": headline,
                        "url": _normalize_listing_url(item.get("url", "")),
                        "price": price,
                        "neighborhood": item.get("neighborhood", item.get("location", default_hood)),
                        "bedrooms": item.get("bedrooms") if item.get("bedrooms") is not None else extract_bedrooms(str(headline)),
                        "bathrooms": item.get("bathrooms") if item.get("bathrooms") is not None else extract_bathrooms(str(headline)),
                        "sqft": item.get("sqft") if item.get("sqft") is not None else extract_sqft(str(headline)),
                        "price_per_sqft": None,
                        "price_per_bedroom": None,
                        "posted_date": item.get("date"),
                        "deal_score": None,
                        "deal_analysis": None,
                        "discount_pct": None,
                        "laundry_type": extract_laundry(str(headline)),
                        "parking": extract_parking(str(headline)),
                        "thumbnail_url": None,
                        "latitude": None,
                        "longitude": None,
                    })
                except Exception as e:
                    logger.debug("JSON item parse error: %s", e)
        except ValueError:
            logger.debug("JSON API response is not valid JSON")
    except Exception as e:
        logger.debug("JSON API error: %s", e)
    return apartments


def _normalize_image_from_schema(image_field):
    """Return first image URL from schema.org image (string, list of URLs, or ImageObjects)."""
    if not image_field:
        return None
    if isinstance(image_field, str) and image_field.startswith("http"):
        return image_field.strip()
    if isinstance(image_field, list) and image_field:
        first = image_field[0]
        if isinstance(first, str) and first.startswith("http"):
            return first.strip()
        if isinstance(first, dict) and first.get("url"):
            return (first.get("url") or "").strip()
    if isinstance(image_field, dict) and image_field.get("url"):
        return (image_field.get("url") or "").strip()
    return None


def _extract_thumbnail_from_listing(listing):
    """Extract first thumbnail URL from a listing element (data-ids or img src)."""
    # Craigslist: data-ids on anchor e.g. "3:123,3:456" -> https://images.craigslist.org/123_300x300.jpg
    for tag in listing.find_all(["a", "span", "div"], attrs={"data-ids": True}):
        raw = tag.get("data-ids", "")
        if not raw:
            continue
        ids = [p.strip().replace("3:", "").strip() for p in raw.split(",") if p.strip()]
        if ids and ids[0].isdigit():
            return f"https://images.craigslist.org/{ids[0]}_300x300.jpg"
    for img in listing.find_all("img", src=True):
        src = (img.get("src") or "").strip()
        if "craigslist.org" in src or "images.craigslist" in src:
            return src
    return None


def scrape_via_ldjson(html_text, min_price: Optional[int] = None, max_price: Optional[int] = None):
    """
    Parse Craigslist JSON-LD from script#ld_searchpage_results.
    Returns list of apartment dicts in price range, or [] if not found/invalid.
    """
    min_price = min_price if min_price is not None else MIN_PRICE
    max_price = max_price if max_price is not None else MAX_PRICE
    apartments = []
    try:
        soup = BeautifulSoup(html_text, "html.parser")
        script = soup.find("script", type="application/ld+json", id="ld_searchpage_results")
        if not script or not script.string:
            return []
        data = json.loads(script.string.strip())
        items = data.get("itemListElement") or data.get("itemListElements") or []
        if not isinstance(items, list):
            return []
        logger.debug("JSON-LD itemListElement count=%s", len(items))
        for entry in items:
            try:
                item = entry.get("item") or entry
                if not isinstance(item, dict):
                    continue
                name = (item.get("name") or "").strip()
                if not name:
                    continue
                url = item.get("url") or item.get("mainEntityOfPage")
                if isinstance(url, dict):
                    url = url.get("url") or url.get("@id") or ""
                url = (url or "").strip()
                url = _normalize_listing_url(url)
                if not url:
                    continue
                price = None
                offers = item.get("offers")
                if isinstance(offers, dict):
                    price = offers.get("price")
                elif isinstance(offers, list) and offers:
                    price = offers[0].get("price") if isinstance(offers[0], dict) else None
                if price is None:
                    price = item.get("price")
                if price is not None:
                    try:
                        if isinstance(price, str):
                            price = int(re.sub(r"[^\d]", "", price)) if re.search(r"\d", price) else None
                        else:
                            price = int(float(price))
                    except (TypeError, ValueError):
                        price = None
                if price is None and name:
                    price = extract_price_from_text(name)
                if not price or not (min_price <= price <= max_price):
                    continue
                bedrooms = item.get("numberOfRooms")
                if bedrooms is not None:
                    try:
                        bedrooms = int(float(bedrooms))
                    except (TypeError, ValueError):
                        bedrooms = extract_bedrooms(name)
                else:
                    bedrooms = extract_bedrooms(name)
                bathrooms = item.get("numberOfBathroomsTotal")
                if bathrooms is not None:
                    try:
                        bathrooms = float(bathrooms)
                    except (TypeError, ValueError):
                        bathrooms = extract_bathrooms(name)
                else:
                    bathrooms = extract_bathrooms(name)
                sqft = None
                floor = item.get("floorSize")
                if isinstance(floor, dict):
                    sqft = floor.get("value")
                    if sqft is not None:
                        try:
                            sqft = int(float(sqft))
                        except (TypeError, ValueError):
                            sqft = extract_sqft(name)
                else:
                    sqft = extract_sqft(name)
                price_per_sqft = round(price / sqft, 2) if price and sqft else None
                price_per_bedroom = round(price / bedrooms, 2) if price and bedrooms and bedrooms > 0 else None
                addr = item.get("address")
                if isinstance(addr, dict):
                    neighborhood = addr.get("addressLocality") or addr.get("name") or "San Francisco"
                else:
                    neighborhood = addr if isinstance(addr, str) else "San Francisco"
                thumbnail_url = _normalize_image_from_schema(item.get("image"))
                lat = item.get("latitude")
                lon = item.get("longitude")
                if lat is not None:
                    try:
                        lat = float(lat)
                    except (TypeError, ValueError):
                        lat = None
                if lon is not None:
                    try:
                        lon = float(lon)
                    except (TypeError, ValueError):
                        lon = None
                apartments.append({
                    "title": name,
                    "url": url or CL_LISTING_BASE + "/search/sfc/apa",
                    "price": price,
                    "neighborhood": neighborhood,
                    "bedrooms": bedrooms,
                    "bathrooms": bathrooms,
                    "sqft": sqft,
                    "price_per_sqft": price_per_sqft,
                    "price_per_bedroom": price_per_bedroom,
                    "posted_date": item.get("datePosted"),
                    "deal_score": None,
                    "deal_analysis": None,
                    "discount_pct": None,
                    "laundry_type": extract_laundry(name),
                    "parking": extract_parking(name),
                    "thumbnail_url": thumbnail_url,
                    "latitude": lat,
                    "longitude": lon,
                })
            except Exception as e:
                logger.debug("JSON-LD item parse: %s", e)
                continue
        for apt in apartments:
            if isinstance(apt.get("neighborhood"), dict):
                apt["neighborhood"] = apt["neighborhood"].get("addressLocality") or apt["neighborhood"].get("name") or "San Francisco"
            elif not apt.get("neighborhood"):
                apt["neighborhood"] = "San Francisco"
        logger.debug("JSON-LD parsed %s in range", len(apartments))
    except json.JSONDecodeError as e:
        logger.warning("JSON-LD decode error: %s", e)
    except Exception as e:
        logger.warning("JSON-LD parse error: %s", e)
    return apartments


def scrape_via_html(
    max_listings: int = 50,
    search_url: Optional[str] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Scrape Craigslist HTML search page; try JSON-LD first, then list/link parsing."""
    search_url = search_url or CL_SEARCH_URL
    min_price = min_price if min_price is not None else MIN_PRICE
    max_price = max_price if max_price is not None else MAX_PRICE
    area = _area_from_search_url(search_url)
    apartments = []
    base_url = f"{search_url}?min_price={min_price}&max_price={max_price}&availabilityMode=0"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(base_url, headers=headers, timeout=REQUEST_TIMEOUT)
        if SCRAPER_DEBUG:
            try:
                with open("/tmp/craigslist_debug.html", "w") as f:
                    f.write(response.text)
                logger.debug("Wrote /tmp/craigslist_debug.html")
            except OSError:
                pass
        response.raise_for_status()

        apartments = scrape_via_ldjson(response.text, min_price=min_price, max_price=max_price)
        if len(apartments) >= 20:
            return apartments[:max_listings]
        if apartments:
            logger.debug("JSON-LD returned %s; trying HTML parsing", len(apartments))

        soup = BeautifulSoup(response.text, "html.parser")
        all_links = soup.find_all("a", href=True)
        listing_links = [a for a in all_links if f"/{area}/apa/" in a.get("href", "") or "/apa/" in a.get("href", "")]

        listings = (
            soup.find_all("li", class_="cl-search-result")
            or soup.find_all("li", class_="result-row")
            or soup.find_all("li", class_="cl-static-search-result")
            or soup.select(".result-row")
            or soup.select("[data-pid]")
            or soup.select(".cl-search-result")
        )
        logger.debug("Listings count=%s", len(listings))

        if not listings:
            logger.debug("No list items; trying link-based parsing")
            # Any link to a listing page: /pen/apa/... or /sfc/apa/...
            apt_links = soup.select(f'a[href*="/{area}/apa/"]')
            # Dedupe by href (same listing can appear multiple times)
            seen = set()
            unique_links = []
            for a in apt_links:
                h = a.get("href", "")
                if h and h not in seen and re.search(r"/" + re.escape(area) + r"/apa/(?:d/)?[^/]+/\d+\.html", h):
                    seen.add(h)
                    unique_links.append(a)
            logger.debug("Unique listing links=%s", len(unique_links))
            if unique_links:
                for link in unique_links[: max_listings * 2]:  # fetch extra, filter by price
                    try:
                        url = _normalize_listing_url(link.get("href", ""))
                        if not url:
                            continue
                        raw_title = (link.get_text() or "").strip()
                        if not raw_title:
                            continue
                        parent = link.parent
                        combined_text = (parent.get_text() if parent else "") or raw_title
                        if parent and parent.parent and not re.search(r"\d\s*br|\d\s*bed|studio", combined_text, re.I):
                            combined_text = (parent.parent.get_text() or "") + " " + combined_text
                        price = extract_price_from_text(combined_text) or extract_price_from_text(raw_title)
                        if not price:
                            price_elem = parent.find(class_=re.compile(r"result-price|priceinfo|price", re.I)) if parent else None
                            if price_elem:
                                m = re.search(r"\$?([\d,]+)", (price_elem.get_text() or ""))
                                if m:
                                    price = int(m.group(1).replace(",", ""))
                        if not price or not (min_price <= price <= max_price):
                            continue
                        # Neighborhood often at end of link text: "Title$2,695 noe valley"
                        parts = raw_title.rsplit("$", 1)
                        title = parts[0].strip() if len(parts) > 1 else raw_title
                        neighborhood = "Palo Alto" if area == "pen" else "San Francisco"
                        if parent:
                            hood_span = parent.find(class_=re.compile(r"hood|supertitle|meta|location", re.I))
                            if hood_span:
                                neighborhood = (hood_span.get_text() or "").strip("() \n") or neighborhood
                        apartments.append({
                            "title": title or raw_title[:80],
                            "url": url,
                            "price": price,
                            "neighborhood": neighborhood,
                            "bedrooms": extract_bedrooms(combined_text) or extract_bedrooms(title),
                            "bathrooms": extract_bathrooms(combined_text) or extract_bathrooms(title),
                            "sqft": extract_sqft(combined_text) or extract_sqft(title),
                            "price_per_sqft": None,
                            "price_per_bedroom": None,
                            "posted_date": None,
                            "deal_score": None,
                            "deal_analysis": None,
                            "discount_pct": None,
                        "laundry_type": extract_laundry(combined_text),
                        "parking": extract_parking(combined_text),
                        "thumbnail_url": None,
                        "latitude": None,
                        "longitude": None,
                    })
                    except Exception as e:
                        logger.debug("Link parse error: %s", e)
                if apartments:
                    logger.debug("Built %s from link-based parsing", len(apartments))
                    return apartments[:max_listings]
            return []

        for listing in listings[:max_listings]:
            try:
                apt = parse_listing(listing)
                if apt and apt.get("price"):
                    if min_price <= apt["price"] <= max_price:
                        apartments.append(apt)
                    else:
                        logger.debug("Price $%s outside range %s-%s", apt["price"], min_price, max_price)
            except Exception as e:
                logger.debug("Error parsing listing: %s", e)

        # If list items didn't parse (wrong DOM), fall back to link-based parsing
        detail_links = [a for a in listing_links if re.search(r"/" + re.escape(area) + r"/apa/.+\d+\.html", a.get("href", ""))]
        if not apartments and detail_links:
            logger.debug("0 from list items; link fallback (%s links)", len(detail_links))
            seen = set()
            for link in detail_links[: max_listings * 2]:
                try:
                    url = _normalize_listing_url(link.get("href", ""))
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    raw_title = (link.get_text() or "").strip()
                    if not raw_title:
                        continue
                    parent = link.parent
                    combined_text = (parent.get_text() if parent else "") or raw_title
                    if parent and parent.parent and not re.search(r"\d\s*br|\d\s*bed|studio", combined_text, re.I):
                        combined_text = (parent.parent.get_text() or "") + " " + combined_text
                    price = extract_price_from_text(combined_text) or extract_price_from_text(raw_title)
                    if not price and parent:
                        price_elem = parent.find(class_=re.compile(r"result-price|priceinfo|price", re.I))
                        if price_elem:
                            m = re.search(r"\$?([\d,]+)", (price_elem.get_text() or ""))
                            if m:
                                price = int(m.group(1).replace(",", ""))
                    if not price or not (min_price <= price <= max_price):
                        continue
                    parts = raw_title.rsplit("$", 1)
                    title = (parts[0].strip() if len(parts) > 1 else raw_title) or raw_title[:80]
                    neighborhood = "Palo Alto" if area == "pen" else "San Francisco"
                    if parent:
                        hood_span = parent.find(class_=re.compile(r"hood|supertitle|meta|location", re.I))
                        if hood_span:
                            neighborhood = (hood_span.get_text() or "").strip("() \n") or neighborhood
                    apartments.append({
                        "title": title,
                        "url": url,
                        "price": price,
                        "neighborhood": neighborhood,
                        "bedrooms": extract_bedrooms(combined_text) or extract_bedrooms(title),
                        "bathrooms": extract_bathrooms(combined_text) or extract_bathrooms(title),
                        "sqft": extract_sqft(combined_text) or extract_sqft(title),
                        "price_per_sqft": None,
                        "price_per_bedroom": None,
                        "posted_date": None,
                        "deal_score": None,
                        "deal_analysis": None,
                        "discount_pct": None,
                        "laundry_type": extract_laundry(combined_text),
                        "parking": extract_parking(combined_text),
                        "thumbnail_url": None,
                        "latitude": None,
                        "longitude": None,
                    })
                except Exception as e:
                    logger.debug("Link parse error: %s", e)
            if apartments:
                apartments = apartments[:max_listings]
                logger.debug("Link fallback: %s apartments", len(apartments))

        logger.debug("Parsed %s in price range", len(apartments))
    except requests.exceptions.RequestException as e:
        logger.warning("Scraper network error: %s", e)
        return []
    except Exception as e:
        logger.exception("Scraper error: %s", e)
        return []
    return apartments


def parse_listing(listing):
    """
    Parse individual Craigslist listing with robust multi-strategy price extraction.
    Tries 7 different methods to find price from actual HTML elements, then text fallback.
    """
    try:
        apt = {
            "title": None,
            "url": None,
            "price": None,
            "neighborhood": None,
            "bedrooms": None,
            "bathrooms": None,
            "sqft": None,
            "price_per_sqft": None,
            "price_per_bedroom": None,
            "posted_date": None,
            "deal_score": None,
            "deal_analysis": None,
            "discount_pct": None,
            "laundry_type": None,
            "parking": False,
            "thumbnail_url": None,
            "latitude": None,
            "longitude": None,
        }
        # ----- Title and URL -----
        title_elem = (
            listing.find("a", class_="titlestring")
            or listing.find("a", class_="result-title")
            or listing.find("div", class_="title")
            or listing.find("a", class_="posting-title")
            or listing.find("a", class_="cl-app-anchor")
            or listing.find("a", href=re.compile(r"/sfc/apa/.+\d+\.html"))
            or listing.find("a", href=lambda x: x and "/apa/" in (x or ""))
        )
        if not title_elem:
            logger.debug("Could not find title element")
            return None
        apt["title"] = (title_elem.get_text() or "").strip()
        apt["url"] = _normalize_listing_url(title_elem.get("href", ""))

        # ----- Price: multi-strategy from actual elements first -----
        price = None
        price_source = None

        # Strategy 1: span.priceinfo
        if not price:
            price_elem = listing.find("span", class_="priceinfo")
            if price_elem:
                m = re.search(r"\$\s*([\d,]+)", price_elem.get_text() or "")
                if m:
                    price = int(m.group(1).replace(",", ""))
                    price_source = "span.priceinfo"

        # Strategy 2: span.result-price
        if not price:
            price_elem = listing.find("span", class_="result-price")
            if price_elem:
                m = re.search(r"\$\s*([\d,]+)", price_elem.get_text() or "")
                if m:
                    price = int(m.group(1).replace(",", ""))
                    price_source = "span.result-price"

        # Strategy 3: div.price or span.price
        if not price:
            price_elem = listing.find("div", class_="price") or listing.find("span", class_="price")
            if price_elem and "$" in (price_elem.get_text() or ""):
                m = re.search(r"\$\s*([\d,]+)", price_elem.get_text() or "")
                if m:
                    price = int(m.group(1).replace(",", ""))
                    price_source = "div/span.price"

        # Strategy 4: span.meta
        if not price:
            meta_elem = listing.find("span", class_="meta")
            if meta_elem and "$" in (meta_elem.get_text() or ""):
                m = re.search(r"\$\s*([\d,]+)", meta_elem.get_text() or "")
                if m:
                    price = int(m.group(1).replace(",", ""))
                    price_source = "span.meta"

        # Strategy 5: any element with 'price' in class
        if not price:
            price_elem = listing.find(class_=lambda x: x and "price" in str(x).lower())
            if price_elem and "$" in (price_elem.get_text() or ""):
                m = re.search(r"\$\s*([\d,]+)", price_elem.get_text() or "")
                if m:
                    price = int(m.group(1).replace(",", ""))
                    price_source = "class containing 'price'"

        # Strategy 6: data-price attribute
        if not price:
            price_attr = listing.get("data-price")
            if price_attr:
                try:
                    price = int(price_attr)
                    price_source = "data-price attribute"
                except (TypeError, ValueError):
                    pass

        # Strategy 7: first reasonable dollar amount in listing text (4–6 digits)
        if not price:
            listing_text = listing.get_text() or ""
            m = re.search(r"\$\s*([\d,]{4,6})(?!\d)", listing_text)
            if m:
                extracted = int(m.group(1).replace(",", ""))
                if 500 <= extracted <= 15000:
                    price = extracted
                    price_source = "text search"
        if not price:
            price = extract_price_from_text(listing.get_text() or "") or extract_price_from_text(apt["title"] or "")
            if price:
                price_source = "extract_price_from_text"

        if not price:
            logger.debug("Could not extract price from listing: %s", (apt["title"] or "")[:60])
            return None
        if price < 500 or price > 15000:
            logger.debug("Unrealistic price $%s for listing: %s", price, (apt["title"] or "")[:60])
            return None
        apt["price"] = price
        logger.debug("Extracted price $%s using %s", price, price_source or "fallback")

        # ----- Neighborhood -----
        hood_elem = (
            listing.find("span", class_="supertitle")
            or listing.find("span", class_="result-hood")
            or listing.find("span", class_="meta")
            or listing.find("span", class_="nearby")
            or listing.find(class_=re.compile(r"hood|neighborhood|location", re.I))
        )
        if hood_elem:
            hood_text = (hood_elem.get_text() or "").strip("() \n")
            hood_match = re.match(r"^([^0-9]+)", hood_text)
            apt["neighborhood"] = hood_match.group(1).strip() if hood_match else hood_text[:30]
        else:
            title_lower = (apt["title"] or "").lower()
            for hood in ("mission", "soma", "nob hill", "marina", "sunset", "richmond", "castro", "haight", "pac heights", "inner sunset", "outer sunset"):
                if hood in title_lower:
                    apt["neighborhood"] = hood.title()
                    break
            if not apt["neighborhood"]:
                apt["neighborhood"] = "San Francisco"

        # ----- Bedrooms, bathrooms, sqft (try housing span, then any attr-like element, then full listing) -----
        housing_elem = (
            listing.find("span", class_="housing")
            or listing.find(class_=re.compile(r"housing|attr|posting-details|postingbody", re.I))
            or listing.find("span", class_=lambda c: c and "housing" in str(c).lower())
        )
        listing_full_text = (listing.get_text() or "") + " " + (apt["title"] or "")
        search_text = (housing_elem.get_text() if housing_elem else "") + " " + (apt["title"] or "")
        # Prefer housing block, then fall back to full listing text (helps peninsula/different DOM)
        apt["bedrooms"] = (
            extract_bedrooms(search_text)
            or extract_bedrooms(listing_full_text)
            or extract_bedrooms(apt["title"])
        )
        apt["bathrooms"] = (
            extract_bathrooms(search_text)
            or extract_bathrooms(listing_full_text)
            or extract_bathrooms(apt["title"])
        )
        apt["sqft"] = (
            extract_sqft(search_text)
            or extract_sqft(listing_full_text)
            or extract_sqft(apt["title"])
        )

        # ----- Laundry, parking, thumbnail -----
        full_text = (listing.get_text() or "") + " " + (apt["title"] or "")
        apt["laundry_type"] = extract_laundry(full_text)
        apt["parking"] = extract_parking(full_text)
        apt["thumbnail_url"] = _extract_thumbnail_from_listing(listing)

        # ----- Posted date -----
        time_elem = listing.find("time", class_="result-date") or listing.find("time")
        if time_elem:
            apt["posted_date"] = time_elem.get("datetime") or (time_elem.get_text() or "").strip()

        # ----- Derived metrics -----
        if apt["price"] and apt["sqft"]:
            apt["price_per_sqft"] = round(apt["price"] / apt["sqft"], 2)
        if apt["price"] and apt.get("bedrooms") and apt["bedrooms"] > 0:
            apt["price_per_bedroom"] = round(apt["price"] / apt["bedrooms"], 2)

        return apt
    except Exception as e:
        logger.debug("parse_listing error: %s", e)
        return None


def extract_bedrooms(text):
    """Extract bedroom count from listing text. Handles 2br, 2 br, 2-bed, 2 bd, studio, etc."""
    if not text:
        return None
    text = text.lower()
    # Studio / 0 BR
    if re.search(r"\bstudio\b", text) or re.search(r"\b0\s*br\b", text) or "0br" in text or "0-bed" in text:
        return 0
    # Explicit N br / N bed / N bedroom (with optional hyphen, optional s)
    match = re.search(
        r"(?:^|[\s/\-])(\d+)\s*[-]?\s*(?:br|bed|bedroom|bd)s?\b",
        text,
        re.IGNORECASE,
    )
    if match:
        n = int(match.group(1))
        if 0 <= n <= 6:
            return n
    # Compact form: 1br, 2br, 3br (no space)
    match = re.search(r"\b([1-6])br\b", text)
    if match:
        return int(match.group(1))
    return None


def extract_bathrooms(text):
    if not text:
        return None
    match = re.search(r"([\d.]+)\s*(?:ba|bath|bathroom)s?", text.lower())
    if match:
        return float(match.group(1))
    return None


def extract_sqft(text):
    if not text:
        return None
    match = re.search(r"(\d+)\s*(?:sqft|sq\.?\s*ft\.?|sf|ft²)", text.lower())
    if match:
        return int(match.group(1))
    return None


def extract_price_from_text(text):
    """Extract first rent-like price ($1,000-$10,000) from text. Returns int or None."""
    if not text:
        return None
    # Match $1,234 or $1234
    for m in re.finditer(r"\$[\s]*([\d,]+)", text):
        try:
            val = int(m.group(1).replace(",", ""))
            if 500 <= val <= 15000:  # plausible rent
                return val
        except (ValueError, IndexError):
            continue
    return None


def extract_laundry(text):
    """Extract laundry: 'in_unit', 'in_building', or None. In-unit is best."""
    if not text:
        return None
    t = text.lower()
    # In-unit / W/D in unit / washer dryer in unit
    if re.search(r"in[- ]?unit\s*(?:w/?d|washer|laundry)|w/?d\s*in\s*unit|washer\s*(?:&|and)\s*dryer\s*in\s*unit|in-unit\s*laundry", t):
        return "in_unit"
    if re.search(r"laundry\s*(?:in\s*building|on[- ]?site|in\s*building)|in\s*building\s*laundry|on[- ]?site\s*laundry|shared\s*laundry|laundry\s*on\s*site", t):
        return "in_building"
    if re.search(r"washer|dryer|w/d|w&d|laundry", t):
        # Generic mention: assume in-building if not in-unit
        return "in_building"
    return None


def extract_parking(text):
    """True if parking mentioned (included, available, garage, etc.)."""
    if not text:
        return False
    t = text.lower()
    return bool(
        re.search(r"parking|garage|car\s*space|pkg\s*(?:incl|avail)|parking\s*(?:incl|avail|included)", t)
    )


def get_neighborhood_market_rates():
    """SF neighborhood market rates by bedroom (approximate)."""
    return {
        "mission": {"studio": 2300, "1br": 2900, "2br": 3900, "3br": 4800},
        "soma": {"studio": 2500, "1br": 3200, "2br": 4400, "3br": 5200},
        "nob hill": {"studio": 2400, "1br": 3000, "2br": 4100, "3br": 5000},
        "nob-hill": {"studio": 2400, "1br": 3000, "2br": 4100, "3br": 5000},
        "marina": {"studio": 2600, "1br": 3300, "2br": 4600, "3br": 5500},
        "sunset": {"studio": 2000, "1br": 2500, "2br": 3400, "3br": 4300},
        "richmond": {"studio": 2000, "1br": 2500, "2br": 3400, "3br": 4400},
        "castro": {"studio": 2400, "1br": 2900, "2br": 4000, "3br": 4900},
        "haight": {"studio": 2200, "1br": 2800, "2br": 3700, "3br": 4700},
        "haight-ashbury": {"studio": 2200, "1br": 2800, "2br": 3700, "3br": 4700},
        "pac heights": {"studio": 2700, "1br": 3400, "2br": 4700, "3br": 5800},
        "pacific heights": {"studio": 2700, "1br": 3400, "2br": 4700, "3br": 5800},
        "inner sunset": {"studio": 2100, "1br": 2600, "2br": 3500, "3br": 4400},
        "default": {"studio": 2300, "1br": 2900, "2br": 3900, "3br": 4900},
    }


def get_stanford_market_rates():
    """Peninsula / Stanford area market rates (Palo Alto, Menlo Park, etc.) for student housing."""
    return {
        "palo alto": {"studio": 2200, "1br": 2800, "2br": 3800, "3br": 4800},
        "palo-alto": {"studio": 2200, "1br": 2800, "2br": 3800, "3br": 4800},
        "menlo park": {"studio": 2100, "1br": 2700, "2br": 3600, "3br": 4500},
        "menlo-park": {"studio": 2100, "1br": 2700, "2br": 3600, "3br": 4500},
        "redwood city": {"studio": 1900, "1br": 2500, "2br": 3300, "3br": 4200},
        "redwood-city": {"studio": 1900, "1br": 2500, "2br": 3300, "3br": 4200},
        "mountain view": {"studio": 2100, "1br": 2700, "2br": 3500, "3br": 4400},
        "mountain-view": {"studio": 2100, "1br": 2700, "2br": 3500, "3br": 4400},
        "stanford": {"studio": 2300, "1br": 2900, "2br": 3900, "3br": 4900},
        "east palo alto": {"studio": 1700, "1br": 2200, "2br": 2900, "3br": 3700},
        "east-palo-alto": {"studio": 1700, "1br": 2200, "2br": 2900, "3br": 3700},
        "default": {"studio": 2100, "1br": 2700, "2br": 3600, "3br": 4500},
    }


# Only run Claude AI summary for the top N by market discount (saves API cost)
AI_ANALYSIS_TOP_N = 20
# Parallel workers for scoring pass and for Claude API calls
SCORE_MAX_WORKERS = 16
AI_MAX_WORKERS = 10

# Cache analyzed results to avoid repeated Claude API calls (key=listing url, value=analysis data)
# TTL in seconds; configurable via APARTMENT_ANALYSIS_CACHE_TTL (default 1 hour)
try:
    from config import APARTMENT_ANALYSIS_CACHE_TTL
except ImportError:
    APARTMENT_ANALYSIS_CACHE_TTL = int(os.environ.get("APARTMENT_ANALYSIS_CACHE_TTL", "3600"))

_analysis_cache: dict[str, dict] = {}
_analysis_cache_lock = threading.Lock()


def _cache_key(url: Optional[str]) -> Optional[str]:
    """Normalize listing URL for cache key (strip fragment)."""
    if not url or not isinstance(url, str):
        return None
    return url.split("#")[0].rstrip("/") or url


def _get_cached_analysis(url: Optional[str]):
    """Return cached {deal_score, deal_analysis, discount_pct} or None if miss/expired."""
    key = _cache_key(url)
    if not key:
        return None
    now = time.time()
    with _analysis_cache_lock:
        entry = _analysis_cache.get(key)
    if not entry:
        return None
    if (now - entry["cached_at"]) > APARTMENT_ANALYSIS_CACHE_TTL:
        with _analysis_cache_lock:
            _analysis_cache.pop(key, None)
        return None
    return {
        "deal_score": entry.get("deal_score"),
        "deal_analysis": entry.get("deal_analysis"),
        "discount_pct": entry.get("discount_pct"),
    }


def _set_cached_analysis(url: Optional[str], deal_score: Any, deal_analysis: Any, discount_pct: Any) -> None:
    """Store analysis in cache."""
    key = _cache_key(url)
    if not key:
        return
    with _analysis_cache_lock:
        _analysis_cache[key] = {
            "deal_score": deal_score,
            "deal_analysis": deal_analysis,
            "discount_pct": discount_pct,
            "cached_at": time.time(),
        }


def _compute_discount_and_score(apt, market_rates):
    """Set discount_pct and a simple deal_score for ranking. Returns True if apt is valid.

    Semantics: discount_pct = (market_rate - price) / market_rate * 100
    - Positive discount_pct = price BELOW market = good deal
    - Negative discount_pct = price ABOVE market = bad deal (overpriced)
    """
    if not apt.get("price"):
        apt["deal_score"] = 0
        apt["deal_analysis"] = "Price information missing."
        apt["discount_pct"] = None
        return False
    if apt.get("bedrooms") is None:
        apt["deal_score"] = 40
        apt["deal_analysis"] = "Bedroom count not specified — difficult to evaluate value."
        apt["discount_pct"] = None
        return False
    neighborhood = apt.get("neighborhood") or ""
    hood_key = neighborhood.lower().strip().replace(" ", "-") if isinstance(neighborhood, str) else "default"
    if hood_key not in market_rates:
        hood_key = hood_key.replace("-", " ")
    hood_rates = market_rates.get(hood_key, market_rates["default"])
    bed_key = "studio" if apt["bedrooms"] == 0 else f"{min(apt['bedrooms'], 3)}br"
    market_rate = hood_rates.get(bed_key, hood_rates.get("1br"))
    # Below market → positive % (good); above market → negative % (bad)
    discount_pct = round((market_rate - apt["price"]) / market_rate * 100, 1) if market_rate else 0
    apt["discount_pct"] = discount_pct
    base = 50 + int(discount_pct)
    # Bonuses: in-unit laundry (+3), in-building laundry (+1), parking (+2)
    if apt.get("laundry_type") == "in_unit":
        base += 3
    elif apt.get("laundry_type") == "in_building":
        base += 1
    if apt.get("parking"):
        base += 2
    apt["deal_score"] = min(100, max(0, base))
    apt["deal_analysis"] = None  # filled by AI for top N, or placeholder for rest
    return True


def _call_claude_for_apartment(apt, market_rate):
    """Call Claude once for this apartment; set apt['deal_score'] and apt['deal_analysis']."""
    discount_pct = apt.get("discount_pct", 0)
    bed_str = "Studio" if apt["bedrooms"] == 0 else f"{apt['bedrooms']} bedroom"
    bath_str = f"{apt['bathrooms']} bath" if apt.get("bathrooms") else "bath unknown"
    sqft_str = f"{apt['sqft']} sqft" if apt.get("sqft") else "size unknown"
    price_sqft_str = f"${apt['price_per_sqft']}/sqft" if apt.get("price_per_sqft") else "N/A"
    laundry_str = apt.get("laundry_type") == "in_unit" and "In-unit washer/dryer" or (apt.get("laundry_type") == "in_building" and "Laundry in building" or "Laundry not specified")
    parking_str = "Parking mentioned (incl. or available)" if apt.get("parking") else "Parking not mentioned"
    context = (
        f"Apartment: ${apt['price']}/month, {bed_str}, {bath_str}, {sqft_str}\n"
        f"Location: {apt['neighborhood']}\n"
        f"Price per sqft: {price_sqft_str}\n"
        f"Market rate for this unit type: ${market_rate}\n"
        f"Price vs market: {discount_pct:+.1f}% (positive = below market / good; negative = above market / overpriced)\n"
        f"Laundry: {laundry_str}. Parking: {parking_str}.\n"
        f"Title: {apt['title']}"
    )
    if not _anthropic:
        if discount_pct and discount_pct > 0:
            apt["deal_analysis"] = f"About {discount_pct:.0f}% below market (good). Set ANTHROPIC_API_KEY for AI analysis."
        elif discount_pct and discount_pct < 0:
            apt["deal_analysis"] = f"About {abs(discount_pct):.0f}% above market (overpriced). Set ANTHROPIC_API_KEY for AI analysis."
        else:
            apt["deal_analysis"] = "Roughly at market. Set ANTHROPIC_API_KEY for AI analysis."
        return
    try:
        response = _anthropic.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=280,
            messages=[
                {
                    "role": "user",
                    "content": f"""{context}

Give a short overview of this apartment and rate it as a deal (0-100). Be specific about why it stands out vs similar listings—or why it doesn't.

What to consider:
- Price vs market: below market = better deal; above = overpriced.
- Laundry: in-unit washer/dryer is a major plus; in-building is a plus; none is a drawback.
- Space: higher sqft for the price (or per bedroom) is better; call out if it's roomy or tight for the bed count.
- Bedrooms: more beds at this price band can mean better value.
- Bed:bath ratio: 1:1 (e.g. each bedroom with its own bath) is a strong plus; shared baths are normal but note if ratio is worse than typical.
- Parking: included or available is a plus in SF.
- Neighborhood: desirable areas can justify a premium; mention if the area adds or subtracts value.

Scoring:
- 80-100: Excellent (well below market and/or standout amenities: in-unit laundry, 1:1 bed:bath, parking, more space).
- 65-79: Good deal (below market or clear perks vs comparable units).
- 50-64: Fair (at market; no major pros or cons).
- 35-49: Overpriced (above market or weak amenities for the price).
- 0-34: Poor deal (well above market or missing basics for the price).

In your analysis, say concretely what makes this a better or worse deal than other similar units (e.g. "In-unit laundry and 1:1 bed:bath are rare at this price" or "No laundry and shared bath make it weaker than comparable 2BRs").

Format your response as:
SCORE: [number 0-100]
ANALYSIS: [2-3 sentences: brief overview of the unit, then specific reasons it's a better or worse deal than similar listings]""",
                }
            ],
        )
        text = response.content[0].text
        score_match = re.search(r"SCORE:\s*(\d+)", text)
        analysis_match = re.search(r"ANALYSIS:\s*(.+)", text, re.DOTALL)
        apt["deal_score"] = int(score_match.group(1)) if score_match else apt.get("deal_score", 50)
        if analysis_match:
            analysis_text = analysis_match.group(1).strip()
            sentences = [s.strip() for s in analysis_text.split(".") if s.strip()][:3]
            apt["deal_analysis"] = ". ".join(sentences).strip() + ("." if sentences else "")
        else:
            apt["deal_analysis"] = "Reasonable option in this price range."
    except Exception as e:
        logger.warning("Claude analysis failed: %s", e)
        apt["deal_analysis"] = "AI analysis unavailable — manual review recommended."
        apt["deal_score"] = apt.get("deal_score", 50)


def analyze_apartment_deals(apartments, max_return=None, get_market_rates=None):
    """
    Compute discount for all; run Claude only for top 20 among the listings we will return.
    If max_return is set (e.g. 200), trim to top max_return by score before any API calls.
    get_market_rates: optional callable() -> dict; if None, uses SF neighborhood rates.
    """
    if not apartments:
        return []
    market_rates = (get_market_rates or get_neighborhood_market_rates)()

    # First pass (parallel): set discount_pct and simple score for everyone (no API calls)
    def _score_one(args):
        apt, rates = args
        return (apt, _compute_discount_and_score(apt, rates))

    with ThreadPoolExecutor(max_workers=SCORE_MAX_WORKERS) as executor:
        scored = list(executor.map(_score_one, [(apt, market_rates) for apt in apartments]))
    valid = [apt for apt, ok in scored if ok]

    # Sort by deal_score and trim to max_return before any expensive API calls
    valid.sort(key=lambda x: x.get("deal_score", 0), reverse=True)
    if max_return is not None and len(valid) > max_return:
        valid = valid[:max_return]

    # Among the ones we'll return, take top N by discount for Claude
    valid.sort(key=lambda x: (x.get("discount_pct") or -999), reverse=True)
    top_for_ai = valid[:AI_ANALYSIS_TOP_N]

    # Build (apt, market_rate) for each; then run Claude in parallel
    def _market_rate_for(apt):
        hood_key = apt["neighborhood"].lower().strip().replace(" ", "-")
        if hood_key not in market_rates:
            hood_key = hood_key.replace("-", " ")
        hood_rates = market_rates.get(hood_key, market_rates["default"])
        bed_key = "studio" if apt["bedrooms"] == 0 else f"{min(apt['bedrooms'], 3)}br"
        return hood_rates.get(bed_key, hood_rates.get("1br"))

    def _call_claude_task(args):
        apt, rate = args
        _call_claude_for_apartment(apt, rate)

    with ThreadPoolExecutor(max_workers=AI_MAX_WORKERS) as executor:
        tasks = [(apt, _market_rate_for(apt)) for apt in top_for_ai]
        list(executor.map(_call_claude_task, tasks))

    # Rest get a short placeholder (no AI call)
    for apt in valid[AI_ANALYSIS_TOP_N:]:
        apt["deal_analysis"] = "Not in top 20 — no AI summary. See price vs market % above."

    # Final order by deal_score (AI-scored top 20 first, then rest by simple score)
    valid.sort(key=lambda x: x.get("deal_score", 0), reverse=True)
    return valid


def analyze_apartment_deals_cached(
    apartments: list[dict], max_return: Optional[int] = None, get_market_rates=None
) -> list[dict]:
    """
    Like analyze_apartment_deals, but use a cache keyed by listing URL so we only call Claude
    for listings that are new or whose cache entry has expired. Reduces API cost on refresh/page load.
    """
    if not apartments:
        return []
    uncached = []
    for apt in apartments:
        cached = _get_cached_analysis(apt.get("url"))
        if cached is not None:
            apt["deal_score"] = cached.get("deal_score")
            apt["deal_analysis"] = cached.get("deal_analysis")
            apt["discount_pct"] = cached.get("discount_pct")
        else:
            uncached.append(apt)

    if uncached:
        analyzed = analyze_apartment_deals(uncached, max_return=None, get_market_rates=get_market_rates)
        for apt in analyzed:
            _set_cached_analysis(
                apt.get("url"),
                apt.get("deal_score"),
                apt.get("deal_analysis"),
                apt.get("discount_pct"),
            )
        logger.info("Analyzed %s uncached listings (Claude used for top 20 of those); %s served from cache", len(uncached), len(apartments) - len(uncached))
    else:
        logger.info("All %s listings served from cache (no Claude calls)", len(apartments))

    # Full list: cached entries already updated in place; uncached were mutated by analyze_apartment_deals
    apartments_sorted = sorted(apartments, key=lambda x: (x.get("deal_score") is None, -(x.get("deal_score") or 0)))
    if max_return is not None:
        apartments_sorted = apartments_sorted[:max_return]
    return apartments_sorted


def get_sample_apartments():
    """Sample data when scraping fails or for demo."""
    return [
        {
            "title": "Spacious 2BR in Mission - Newly Renovated, Hardwood Floors",
            "url": f"{CL_LISTING_BASE}/sfc/apa/",
            "price": 3400,
            "neighborhood": "Mission",
            "bedrooms": 2,
            "bathrooms": 1.0,
            "sqft": 950,
            "price_per_sqft": 3.58,
            "price_per_bedroom": 1700,
            "posted_date": "2026-02-16",
            "deal_score": None,
            "deal_analysis": None,
            "discount_pct": None,
        },
        {
            "title": "Charming Studio near Golden Gate Park - Perfect for Singles",
            "url": f"{CL_LISTING_BASE}/sfc/apa/",
            "price": 2100,
            "neighborhood": "Inner Sunset",
            "bedrooms": 0,
            "bathrooms": 1.0,
            "sqft": 450,
            "price_per_sqft": 4.67,
            "price_per_bedroom": None,
            "posted_date": "2026-02-15",
            "deal_score": None,
            "deal_analysis": None,
            "discount_pct": None,
        },
        {
            "title": "Modern 1BR in SoMa - Walk to Tech Companies",
            "url": f"{CL_LISTING_BASE}/sfc/apa/",
            "price": 2950,
            "neighborhood": "SoMa",
            "bedrooms": 1,
            "bathrooms": 1.0,
            "sqft": 700,
            "price_per_sqft": 4.21,
            "price_per_bedroom": 2950,
            "posted_date": "2026-02-14",
            "deal_score": None,
            "deal_analysis": None,
            "discount_pct": None,
        },
    ]


def get_sample_apartments_stanford():
    """Sample peninsula listings when Stanford area scrape fails."""
    return [
        {
            "title": "Studio near Stanford - Walk to Campus",
            "url": f"{CL_LISTING_BASE}/pen/apa/",
            "price": 1950,
            "neighborhood": "Palo Alto",
            "bedrooms": 0,
            "bathrooms": 1.0,
            "sqft": 450,
            "price_per_sqft": 4.33,
            "price_per_bedroom": None,
            "posted_date": None,
            "deal_score": None,
            "deal_analysis": None,
            "discount_pct": None,
        },
        {
            "title": "1BR in Menlo Park - Near Caltrain",
            "url": f"{CL_LISTING_BASE}/pen/apa/",
            "price": 2400,
            "neighborhood": "Menlo Park",
            "bedrooms": 1,
            "bathrooms": 1.0,
            "sqft": 650,
            "price_per_sqft": 3.69,
            "price_per_bedroom": 2400,
            "posted_date": None,
            "deal_score": None,
            "deal_analysis": None,
            "discount_pct": None,
        },
        {
            "title": "2BR Shared - Redwood City, Student Friendly",
            "url": f"{CL_LISTING_BASE}/pen/apa/",
            "price": 3200,
            "neighborhood": "Redwood City",
            "bedrooms": 2,
            "bathrooms": 2.0,
            "sqft": 950,
            "price_per_sqft": 3.37,
            "price_per_bedroom": 1600,
            "posted_date": None,
            "deal_score": None,
            "deal_analysis": None,
            "discount_pct": None,
        },
    ]


if __name__ == "__main__":
    print("=" * 70)
    print("CRAIGSLIST SCRAPER DEBUG MODE")
    print("=" * 70)
    print("\n1. Running HTML structure inspector...")
    inspect_craigslist_structure()
    print("\n2. Running detailed first listing debugger...")
    debug_first_listing()
    print("\n3. Running full scrape test...")
    apartments = scrape_sf_apartments(max_listings=10)
    print(f"\n{'=' * 70}")
    print(f"RESULTS: Found {len(apartments)} valid apartments")
    print(f"{'=' * 70}")
    if apartments:
        print("\nFirst 3 apartments:")
        for i, apt in enumerate(apartments[:3], 1):
            print(f"\n{i}. {(apt.get('title') or '')[:60]}")
            print(f"   Price: ${apt.get('price')}")
            print(f"   Neighborhood: {apt.get('neighborhood')}")
            print(f"   Beds: {apt.get('bedrooms')}, Baths: {apt.get('bathrooms')}, Sqft: {apt.get('sqft')}")
    else:
        print("\nNO APARTMENTS FOUND - Check debug output above")
