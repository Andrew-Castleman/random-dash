#!/usr/bin/env python3
"""
Test script for Rentcast portal endpoints.
Tests both SF and Stanford endpoints, shows API usage, and checks for errors.
"""

import os
import sys
import json
import requests
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Import portal functions
from portal_listings import get_portal_listings_sf, get_portal_listings_stanford, get_api_usage_info

def test_api_key():
    """Check if API key is set."""
    api_key = os.environ.get("RENTCAST_API_KEY", "").strip()
    if not api_key:
        print("❌ ERROR: RENTCAST_API_KEY not found in environment")
        return False
    print(f"✅ API Key found: {api_key[:10]}...{api_key[-4:]}")
    return True

def test_api_usage():
    """Show current API usage."""
    try:
        usage = get_api_usage_info()
        print(f"\n📊 API Usage:")
        print(f"   Current month calls: {usage['current_month_calls']}")
        print(f"   Monthly limit: {usage['monthly_limit']}")
        print(f"   Remaining calls: {usage['remaining_calls']}")
        if usage['limit_reached']:
            print("   ⚠️  LIMIT REACHED - API calls will use cached data")
        else:
            print(f"   ✅ {usage['remaining_calls']} calls remaining")
    except Exception as e:
        print(f"⚠️  Could not get API usage: {e}")

def test_sf_endpoint():
    """Test SF portal endpoint."""
    print("\n" + "="*60)
    print("Testing SF Portal Endpoint (/api/apartments/portal)")
    print("="*60)
    
    try:
        apartments = get_portal_listings_sf(min_price=2000, max_price=5000, max_return=200)
        print(f"✅ Function returned {len(apartments)} apartments")
        
        if apartments:
            sample = apartments[0]
            print(f"\n📋 Sample listing:")
            print(f"   Title: {sample.get('title', 'N/A')}")
            print(f"   Price: ${sample.get('price', 'N/A')}")
            print(f"   Neighborhood: {sample.get('neighborhood', 'N/A')}")
            print(f"   Bedrooms: {sample.get('bedrooms', 'N/A')}")
            print(f"   URL: {sample.get('url', 'N/A')[:80]}...")
            print(f"   Has coordinates: {sample.get('latitude') is not None}")
        else:
            print("⚠️  No apartments returned")
            
        return len(apartments)
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 0

def test_stanford_endpoint():
    """Test Stanford portal endpoint."""
    print("\n" + "="*60)
    print("Testing Stanford Portal Endpoint (/api/apartments/portal/stanford)")
    print("="*60)
    
    try:
        apartments = get_portal_listings_stanford(min_price=1500, max_price=6500, max_return=200)
        print(f"✅ Function returned {len(apartments)} apartments")
        
        if apartments:
            sample = apartments[0]
            print(f"\n📋 Sample listing:")
            print(f"   Title: {sample.get('title', 'N/A')}")
            print(f"   Price: ${sample.get('price', 'N/A')}")
            print(f"   Neighborhood: {sample.get('neighborhood', 'N/A')}")
            print(f"   Bedrooms: {sample.get('bedrooms', 'N/A')}")
            print(f"   URL: {sample.get('url', 'N/A')[:80]}...")
            print(f"   Has coordinates: {sample.get('latitude') is not None}")
        else:
            print("⚠️  No apartments returned")
            
        return len(apartments)
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 0

def test_http_endpoints(base_url="http://localhost:5000"):
    """Test HTTP endpoints if server is running."""
    print("\n" + "="*60)
    print("Testing HTTP Endpoints (if server is running)")
    print("="*60)
    
    endpoints = [
        "/api/apartments/portal",
        "/api/apartments/portal/stanford"
    ]
    
    for endpoint in endpoints:
        url = base_url + endpoint
        print(f"\n🌐 Testing {endpoint}...")
        try:
            response = requests.get(url, timeout=10)
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                apt_count = len(data.get("apartments", []))
                stats = data.get("stats", {})
                print(f"   ✅ Success: {apt_count} apartments")
                print(f"   Stats: {stats}")
            else:
                print(f"   ❌ Error: {response.text[:200]}")
        except requests.exceptions.ConnectionError:
            print(f"   ⚠️  Server not running at {base_url}")
        except Exception as e:
            print(f"   ❌ Error: {e}")

def main():
    print("🧪 Rentcast Portal Endpoint Test")
    print("="*60)
    
    # Check API key
    if not test_api_key():
        print("\n💡 Tip: Set RENTCAST_API_KEY in .env file")
        return 1
    
    # Show API usage
    test_api_usage()
    
    # Test SF endpoint
    sf_count = test_sf_endpoint()
    
    # Test Stanford endpoint
    stanford_count = test_stanford_endpoint()
    
    # Test HTTP endpoints if server running
    test_http_endpoints()
    
    # Summary
    print("\n" + "="*60)
    print("📊 Summary")
    print("="*60)
    print(f"SF listings: {sf_count}")
    print(f"Stanford listings: {stanford_count}")
    
    if sf_count == 0 and stanford_count == 0:
        print("\n⚠️  WARNING: No listings returned. Possible issues:")
        print("   1. API key invalid or expired")
        print("   2. Monthly API limit reached (check usage above)")
        print("   3. No listings match the price filters")
        print("   4. Network/API error (check error messages above)")
        return 1
    else:
        print("\n✅ Tests completed successfully!")
        return 0

if __name__ == "__main__":
    sys.exit(main())
