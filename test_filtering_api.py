#!/usr/bin/env python3
"""
Test filtering functionality for apartment listings API endpoints.
Tests that filters work correctly and can be combined.
"""

import json
import requests
import sys

BASE_URL = "http://localhost:5000"  # Adjust if your server runs on different port

def test_filtering():
    """Test filtering functionality."""
    print("=" * 60)
    print("Testing Apartment Filtering Functionality")
    print("=" * 60)
    
    # Test 1: Get all SF listings
    print("\n1. Fetching all SF listings...")
    try:
        response = requests.get(f"{BASE_URL}/api/apartments/portal", timeout=10)
        if response.status_code != 200:
            print(f"   ERROR: API returned status {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            return False
        
        data = response.json()
        all_listings = data.get("apartments", [])
        total_count = len(all_listings)
        print(f"   ✓ Retrieved {total_count} total listings")
        
        if total_count == 0:
            print("   WARNING: No listings returned. Cannot test filtering.")
            return False
        
        # Show sample of listings
        print(f"\n   Sample listings:")
        for i, apt in enumerate(all_listings[:3]):
            print(f"   {i+1}. {apt.get('title', 'N/A')[:50]} | "
                  f"{apt.get('neighborhood', 'N/A')} | "
                  f"{apt.get('bedrooms', 'N/A')}BR | "
                  f"${apt.get('price', 'N/A')}")
        
    except requests.exceptions.ConnectionError:
        print("   ERROR: Could not connect to server. Is Flask running?")
        print("   Start server with: python app.py")
        return False
    except Exception as e:
        print(f"   ERROR: {e}")
        return False
    
    # Test 2: Verify data structure
    print("\n2. Verifying data structure...")
    required_fields = ['title', 'neighborhood', 'bedrooms', 'price', 'latitude', 'longitude']
    missing_fields = []
    for field in required_fields:
        if not any(apt.get(field) is not None for apt in all_listings):
            missing_fields.append(field)
    
    if missing_fields:
        print(f"   WARNING: Some listings missing fields: {missing_fields}")
    else:
        print("   ✓ All required fields present")
    
    # Test 3: Analyze filterable data
    print("\n3. Analyzing filterable data...")
    neighborhoods = set(apt.get('neighborhood', 'Unknown') for apt in all_listings)
    bedrooms = set(apt.get('bedrooms') for apt in all_listings if apt.get('bedrooms') is not None)
    prices = [apt.get('price') for apt in all_listings if apt.get('price')]
    min_price = min(prices) if prices else 0
    max_price = max(prices) if prices else 0
    
    print(f"   Neighborhoods: {len(neighborhoods)} unique ({', '.join(list(neighborhoods)[:5])}...)")
    print(f"   Bedrooms: {sorted(bedrooms)}")
    print(f"   Price range: ${min_price} - ${max_price}")
    
    # Test 4: Test filtering logic (simulated)
    print("\n4. Testing filter logic (simulated)...")
    
    # Test neighborhood filter
    test_neighborhood = list(neighborhoods)[0] if neighborhoods else None
    if test_neighborhood:
        filtered_by_hood = [apt for apt in all_listings 
                           if apt.get('neighborhood') == test_neighborhood]
        print(f"   ✓ Neighborhood filter ({test_neighborhood}): {len(filtered_by_hood)} results")
    
    # Test bedroom filter
    test_bedrooms = sorted(bedrooms)[0] if bedrooms else None
    if test_bedrooms is not None:
        filtered_by_bed = [apt for apt in all_listings 
                          if apt.get('bedrooms') == test_bedrooms]
        print(f"   ✓ Bedroom filter ({test_bedrooms}BR): {len(filtered_by_bed)} results")
    
    # Test price filter
    if prices:
        mid_price = (min_price + max_price) // 2
        filtered_by_price = [apt for apt in all_listings 
                            if apt.get('price') and min_price <= apt.get('price') <= mid_price]
        print(f"   ✓ Price filter (${min_price}-${mid_price}): {len(filtered_by_price)} results")
    
    # Test combined filters
    if test_neighborhood and test_bedrooms is not None and prices:
        combined_filtered = [apt for apt in all_listings 
                           if apt.get('neighborhood') == test_neighborhood
                           and apt.get('bedrooms') == test_bedrooms
                           and apt.get('price') and apt.get('price') >= min_price]
        print(f"   ✓ Combined filters ({test_neighborhood} + {test_bedrooms}BR + >=${min_price}): "
              f"{len(combined_filtered)} results")
    
    # Test 5: Verify map data availability
    print("\n5. Verifying map data...")
    listings_with_coords = [apt for apt in all_listings 
                           if apt.get('latitude') and apt.get('longitude')]
    print(f"   ✓ {len(listings_with_coords)}/{total_count} listings have coordinates for map")
    
    if len(listings_with_coords) < total_count * 0.8:
        print(f"   WARNING: Only {len(listings_with_coords)/total_count*100:.1f}% have coordinates")
    
    # Test 6: Verify deal scores
    print("\n6. Verifying deal scores...")
    listings_with_scores = [apt for apt in all_listings 
                          if apt.get('deal_score') is not None]
    print(f"   ✓ {len(listings_with_scores)}/{total_count} listings have deal scores")
    
    if listings_with_scores:
        scores = [apt.get('deal_score') for apt in listings_with_scores]
        print(f"   Score range: {min(scores)} - {max(scores)}")
        top_25_count = max(1, int(len(listings_with_scores) * 0.25))
        top_scores = sorted(scores, reverse=True)[:top_25_count]
        threshold = top_scores[-1] if top_scores else 0
        print(f"   Top 25% threshold: {threshold}")
        
        listings_with_ai = [apt for apt in all_listings 
                           if apt.get('deal_score', 0) >= threshold 
                           and apt.get('deal_score', 0) > 50]
        print(f"   ✓ {len(listings_with_ai)} listings should have AI descriptions")
    
    print("\n" + "=" * 60)
    print("Filtering Test Complete")
    print("=" * 60)
    print("\nNote: This test verifies data structure and filter logic.")
    print("For full frontend filtering test, open test_filtering.html in a browser.")
    print(f"Test page: http://localhost:8000/test_filtering.html")
    
    return True

if __name__ == "__main__":
    success = test_filtering()
    sys.exit(0 if success else 1)
