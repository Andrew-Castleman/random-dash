#!/usr/bin/env python3
"""
Smoke test: ensure the site starts and key routes return without crashing.
Uses Flask test client (no server bind). Run from project root: python scripts/smoke_test.py
"""
import os
import sys

# Run from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load env so RENTCAST etc. are optional
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def main():
    from app import app

    client = app.test_client()
    routes = [
        ("GET", "/", "dashboard"),
        ("GET", "/terms", "terms"),
        ("GET", "/privacy", "privacy"),
        ("GET", "/about", "about"),
        ("GET", "/contact", "contact"),
        ("GET", "/api/dashboard", "api dashboard"),
        ("GET", "/api/apartments/portal", "api apartments portal (SF)"),
        ("GET", "/api/apartments/portal/stanford", "api apartments portal (Stanford)"),
    ]
    failed = []
    for method, path, name in routes:
        try:
            if method == "GET":
                r = client.get(path)
            else:
                r = client.post(path)
            if r.status_code != 200:
                failed.append((name, path, r.status_code))
            else:
                print(f"  OK  {method} {path} -> {r.status_code}")
            # Ensure JSON endpoints return valid JSON
            if path.startswith("/api/") and "application/json" in (r.content_type or ""):
                r.get_json()
        except Exception as e:
            failed.append((name, path, str(e)))
            print(f"  FAIL {method} {path} -> {e}")

    if failed:
        print("\nFailed:")
        for name, path, err in failed:
            print(f"  {name}: {path} -> {err}")
        sys.exit(1)
    print("\nAll routes OK. Site should not crash.")
    return 0


if __name__ == "__main__":
    main()
