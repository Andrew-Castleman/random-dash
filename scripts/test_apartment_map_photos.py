#!/usr/bin/env python3
"""
Test why only some map photos show: inspect thumbnail_url, lat/lon, and OSM embed URL.
Run from repo root: python scripts/test_apartment_map_photos.py
Or with live API: APARTMENTS_URL=http://localhost:5000/api/apartments python scripts/test_apartment_map_photos.py
"""
import json
import os
import sys

# Prefer live API if URL set; else use scraper sample
def get_apartments():
    url = os.environ.get("APARTMENTS_URL")
    if url:
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.loads(r.read().decode())
                return data.get("apartments", data.get("apartment_list", []))
        except Exception as e:
            print("API fetch failed:", e, file=sys.stderr)
    # Fallback: minimal sample from scraper
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from craigslist_scraper import scrape_sf_apartments
    return scrape_sf_apartments(max_listings=30)


def main():
    apartments = get_apartments()
    n = len(apartments)
    with_thumb = sum(1 for a in apartments if a.get("thumbnail_url"))
    with_latlon = sum(1 for a in apartments if a.get("latitude") is not None and a.get("longitude") is not None)
    neighborhoods = set((a.get("neighborhood") or "").strip() or "San Francisco" for a in apartments)

    print("Apartment map/photo test")
    print("  Total listings:", n)
    print("  With thumbnail_url (show photo):", with_thumb)
    print("  With lat/lon (exact map):", with_latlon)
    print("  Unique neighborhoods:", len(neighborhoods), sorted(neighborhoods)[:15], "..." if len(neighborhoods) > 15 else "")

    # Sample OSM embed URL (like dashboard.js)
    sample = next((a for a in apartments if a.get("latitude") is not None and a.get("longitude") is not None), apartments[0] if apartments else None)
    if sample:
        lat = float(sample.get("latitude") or 37.7849)
        lon = float(sample.get("longitude") or -122.4094)
        from urllib.parse import quote
        bbox = f"{lon - 0.015:.4f},{lat - 0.01:.4f},{lon + 0.015:.4f},{lat + 0.01:.4f}"
        base = "https://www.openstreetmap.org/export/embed.html"
        url_encoded = f"{base}?bbox={quote(bbox)}&layer=mapnik&marker={quote(f'{lat},{lon}')}"
        print("  Sample OSM embed (encoded):", url_encoded[:110] + "...")

    # Why some don't show map: no thumbnail -> need lat/lon or neighborhood fallback
    no_thumb = [a for a in apartments if not a.get("thumbnail_url")]
    no_coords = [a for a in no_thumb if a.get("latitude") is None or a.get("longitude") is None]
    print("  Without thumbnail:", len(no_thumb), "| of those without lat/lon (need fallback):", len(no_coords))
    if no_coords:
        print("  Example neighborhoods missing coords:", list(set((a.get("neighborhood") or "?") for a in no_coords[:5])))


if __name__ == "__main__":
    main()
