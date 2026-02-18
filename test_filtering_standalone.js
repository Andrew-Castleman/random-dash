#!/usr/bin/env node
/**
 * Standalone test for filtering functionality.
 * Tests the filtering logic without needing a server.
 * Run with: node test_filtering_standalone.js
 */

// Mock DOM elements (simplified for Node.js testing)
function createMockDOM() {
  const elements = {};
  
  return {
    getElementById: (id) => {
      if (!elements[id]) {
        elements[id] = {
          value: id === 'neighborhoodFilter' ? 'all' : 
                 id === 'bedroomFilter' ? 'all' :
                 id === 'minPriceFilter' ? '' :
                 id === 'maxPriceFilter' ? '' :
                 id === 'sortBy' ? 'best-deal' : '',
          textContent: '',
          innerHTML: ''
        };
      }
      return elements[id];
    },
    setValue: (id, value) => {
      if (!elements[id]) {
        elements[id] = { value: '', textContent: '', innerHTML: '' };
      }
      elements[id].value = value;
    },
    getValue: (id) => {
      return elements[id] ? elements[id].value : '';
    }
  };
}

const mockDOM = createMockDOM();

// Sample apartment data
const sampleApartmentsData = [
  { title: "123 Main St", neighborhood: "Mission", bedrooms: 1, price: 2500, latitude: 37.7599, longitude: -122.4148, deal_score: 65 },
  { title: "456 Market St", neighborhood: "SoMa", bedrooms: 2, price: 3500, latitude: 37.7786, longitude: -122.4056, deal_score: 70 },
  { title: "789 Castro St", neighborhood: "Castro", bedrooms: 1, price: 2800, latitude: 37.7609, longitude: -122.4350, deal_score: 55 },
  { title: "321 Nob Hill", neighborhood: "Nob Hill", bedrooms: 2, price: 4000, latitude: 37.7928, longitude: -122.4155, deal_score: 60 },
  { title: "654 Marina Blvd", neighborhood: "Marina", bedrooms: 0, price: 2200, latitude: 37.8025, longitude: -122.4364, deal_score: 75 },
  { title: "987 Sunset Ave", neighborhood: "Sunset", bedrooms: 3, price: 4500, latitude: 37.7540, longitude: -122.5042, deal_score: 68 },
];

let apartmentsData = [];

function neighborhoodSlug(name) {
  if (!name) return "";
  return name.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "");
}

function getFilteredAndSortedApartments() {
  if (!apartmentsData || !apartmentsData.length) {
    return [];
  }
  const hoodFilter = mockDOM.getElementById("neighborhoodFilter");
  const bedFilter = mockDOM.getElementById("bedroomFilter");
  const minPriceFilter = mockDOM.getElementById("minPriceFilter");
  const maxPriceFilter = mockDOM.getElementById("maxPriceFilter");
  const sortBy = mockDOM.getElementById("sortBy");
  let list = [...apartmentsData];
  const hoodVal = hoodFilter ? hoodFilter.value : "all";
  const bedVal = bedFilter ? bedFilter.value : "all";
  let minPrice = minPriceFilter && minPriceFilter.value && minPriceFilter.value.trim() ? parseInt(minPriceFilter.value.trim(), 10) : null;
  let maxPrice = maxPriceFilter && maxPriceFilter.value && maxPriceFilter.value.trim() ? parseInt(maxPriceFilter.value.trim(), 10) : null;
  const sortVal = sortBy ? sortBy.value : "best-deal";
  
  // Validate price inputs
  if (minPrice !== null && isNaN(minPrice)) minPrice = null;
  if (maxPrice !== null && isNaN(maxPrice)) maxPrice = null;

  // Apply all filters simultaneously
  list = list.filter(function (apt) {
    // Neighborhood filter
    if (hoodVal !== "all") {
      const slug = neighborhoodSlug(apt.neighborhood);
      let matchesHood = false;
      if (hoodVal === "pac-heights") {
        matchesHood = slug === "pacific-heights" || slug === "pac-heights";
      } else {
        matchesHood = slug === hoodVal || slug.indexOf(hoodVal) !== -1 || (apt.neighborhood || "").toLowerCase().indexOf(hoodVal.replace(/-/g, " ")) !== -1;
      }
      if (!matchesHood) return false;
    }
    
    // Bedroom filter
    if (bedVal !== "all") {
      const b = apt.bedrooms;
      let matchesBed = false;
      if (bedVal === "studio") {
        matchesBed = b === 0;
      } else if (bedVal === "3") {
        matchesBed = b >= 3;
      } else {
        matchesBed = b === parseInt(bedVal, 10);
      }
      if (!matchesBed) return false;
    }
    
    // Price filters
    const price = apt.price || 0;
    if (minPrice !== null && price < minPrice) return false;
    if (maxPrice !== null && price > maxPrice) return false;
    
    return true;
  });
  
  // Sort
  if (sortVal === "best-deal") list.sort(function (a, b) { return (b.deal_score || 0) - (a.deal_score || 0); });
  else if (sortVal === "price-low") list.sort(function (a, b) { return (a.price || 0) - (b.price || 0); });
  else if (sortVal === "price-sqft") list.sort(function (a, b) { return (a.price_per_sqft || 999) - (b.price_per_sqft || 999); });
  else if (sortVal === "newest") list.sort(function (a, b) { return (b.posted_date || "").localeCompare(a.posted_date || ""); });
  return list;
}

// Test runner
function runTests() {
  apartmentsData = sampleApartmentsData;
  let passCount = 0;
  let failCount = 0;
  
  console.log("=".repeat(60));
  console.log("Filtering Functionality Test");
  console.log("=".repeat(60));
  
  // Test 1: No filters
  console.log("\n1. Testing: No filters (should return all)");
  mockDOM.setValue("neighborhoodFilter", "all");
  mockDOM.setValue("bedroomFilter", "all");
  mockDOM.setValue("minPriceFilter", "");
  mockDOM.setValue("maxPriceFilter", "");
  const result1 = getFilteredAndSortedApartments();
  if (result1.length === apartmentsData.length) {
    console.log("   ✓ PASS: Returns all", result1.length, "apartments");
    passCount++;
  } else {
    console.log("   ✗ FAIL: Expected", apartmentsData.length, "got", result1.length);
    failCount++;
  }
  
  // Test 2: Neighborhood filter
  console.log("\n2. Testing: Neighborhood filter (Mission)");
  mockDOM.setValue("neighborhoodFilter", "mission");
  mockDOM.setValue("bedroomFilter", "all");
  mockDOM.setValue("minPriceFilter", "");
  mockDOM.setValue("maxPriceFilter", "");
  const result2 = getFilteredAndSortedApartments();
  const expected2 = apartmentsData.filter(a => a.neighborhood.toLowerCase().includes("mission"));
  if (result2.length === expected2.length && result2.every(a => a.neighborhood.toLowerCase().includes("mission"))) {
    console.log("   ✓ PASS: Returns", result2.length, "Mission apartments");
    passCount++;
  } else {
    console.log("   ✗ FAIL: Expected", expected2.length, "got", result2.length);
    failCount++;
  }
  
  // Test 3: Bedroom filter
  console.log("\n3. Testing: Bedroom filter (2 bedrooms)");
  mockDOM.setValue("neighborhoodFilter", "all");
  mockDOM.setValue("bedroomFilter", "2");
  mockDOM.setValue("minPriceFilter", "");
  mockDOM.setValue("maxPriceFilter", "");
  const result3 = getFilteredAndSortedApartments();
  const expected3 = apartmentsData.filter(a => a.bedrooms === 2);
  if (result3.length === expected3.length && result3.every(a => a.bedrooms === 2)) {
    console.log("   ✓ PASS: Returns", result3.length, "2-bedroom apartments");
    passCount++;
  } else {
    console.log("   ✗ FAIL: Expected", expected3.length, "got", result3.length);
    failCount++;
  }
  
  // Test 4: Studio filter
  console.log("\n4. Testing: Studio filter");
  mockDOM.setValue("neighborhoodFilter", "all");
  mockDOM.setValue("bedroomFilter", "studio");
  mockDOM.setValue("minPriceFilter", "");
  mockDOM.setValue("maxPriceFilter", "");
  const result4 = getFilteredAndSortedApartments();
  const expected4 = apartmentsData.filter(a => a.bedrooms === 0);
  if (result4.length === expected4.length && result4.every(a => a.bedrooms === 0)) {
    console.log("   ✓ PASS: Returns", result4.length, "studio apartments");
    passCount++;
  } else {
    console.log("   ✗ FAIL: Expected", expected4.length, "got", result4.length);
    failCount++;
  }
  
  // Test 5: Price filter (min)
  console.log("\n5. Testing: Min price filter ($3000)");
  mockDOM.setValue("neighborhoodFilter", "all");
  mockDOM.setValue("bedroomFilter", "all");
  mockDOM.setValue("minPriceFilter", "3000");
  mockDOM.setValue("maxPriceFilter", "");
  const result5 = getFilteredAndSortedApartments();
  const expected5 = apartmentsData.filter(a => a.price >= 3000);
  if (result5.length === expected5.length && result5.every(a => a.price >= 3000)) {
    console.log("   ✓ PASS: Returns", result5.length, "apartments >= $3000");
    passCount++;
  } else {
    console.log("   ✗ FAIL: Expected", expected5.length, "got", result5.length);
    failCount++;
  }
  
  // Test 6: Price filter (max)
  console.log("\n6. Testing: Max price filter ($3000)");
  mockDOM.setValue("neighborhoodFilter", "all");
  mockDOM.setValue("bedroomFilter", "all");
  mockDOM.setValue("minPriceFilter", "");
  mockDOM.setValue("maxPriceFilter", "3000");
  const result6 = getFilteredAndSortedApartments();
  const expected6 = apartmentsData.filter(a => a.price <= 3000);
  if (result6.length === expected6.length && result6.every(a => a.price <= 3000)) {
    console.log("   ✓ PASS: Returns", result6.length, "apartments <= $3000");
    passCount++;
  } else {
    console.log("   ✗ FAIL: Expected", expected6.length, "got", result6.length);
    failCount++;
  }
  
  // Test 7: Multiple filters combined
  console.log("\n7. Testing: Multiple filters (Mission + 1BR + $2000-$3000)");
  mockDOM.setValue("neighborhoodFilter", "mission");
  mockDOM.setValue("bedroomFilter", "1");
  mockDOM.setValue("minPriceFilter", "2000");
  mockDOM.setValue("maxPriceFilter", "3000");
  const result7 = getFilteredAndSortedApartments();
  const expected7 = apartmentsData.filter(a => 
    a.neighborhood.toLowerCase().includes("mission") && 
    a.bedrooms === 1 && 
    a.price >= 2000 && 
    a.price <= 3000
  );
  const allMatch = result7.every(a => 
    a.neighborhood.toLowerCase().includes("mission") && 
    a.bedrooms === 1 && 
    a.price >= 2000 && 
    a.price <= 3000
  );
  if (result7.length === expected7.length && allMatch) {
    console.log("   ✓ PASS: Returns", result7.length, "matching apartments");
    passCount++;
  } else {
    console.log("   ✗ FAIL: Expected", expected7.length, "got", result7.length);
    console.log("   Results:", result7.map(a => `${a.title} (${a.neighborhood}, ${a.bedrooms}BR, $${a.price})`));
    failCount++;
  }
  
  // Test 8: Price range
  console.log("\n8. Testing: Price range ($2500-$3500)");
  mockDOM.setValue("neighborhoodFilter", "all");
  mockDOM.setValue("bedroomFilter", "all");
  mockDOM.setValue("minPriceFilter", "2500");
  mockDOM.setValue("maxPriceFilter", "3500");
  const result8 = getFilteredAndSortedApartments();
  const expected8 = apartmentsData.filter(a => a.price >= 2500 && a.price <= 3500);
  if (result8.length === expected8.length && result8.every(a => a.price >= 2500 && a.price <= 3500)) {
    console.log("   ✓ PASS: Returns", result8.length, "apartments in price range");
    passCount++;
  } else {
    console.log("   ✗ FAIL: Expected", expected8.length, "got", result8.length);
    failCount++;
  }
  
  // Test 9: Empty result
  console.log("\n9. Testing: Filters that return no results");
  mockDOM.setValue("neighborhoodFilter", "mission");
  mockDOM.setValue("bedroomFilter", "3");
  mockDOM.setValue("minPriceFilter", "5000");
  mockDOM.setValue("maxPriceFilter", "6000");
  const result9 = getFilteredAndSortedApartments();
  if (result9.length === 0) {
    console.log("   ✓ PASS: Correctly returns empty array");
    passCount++;
  } else {
    console.log("   ✗ FAIL: Expected 0 results, got", result9.length);
    failCount++;
  }
  
  // Summary
  console.log("\n" + "=".repeat(60));
  console.log("Test Summary");
  console.log("=".repeat(60));
  console.log(`Passed: ${passCount}`);
  console.log(`Failed: ${failCount}`);
  console.log(`Total:  ${passCount + failCount} tests`);
  console.log("=".repeat(60));
  
  return failCount === 0;
}

// Run tests
if (require.main === module) {
  const success = runTests();
  process.exit(success ? 0 : 1);
}

module.exports = { runTests, getFilteredAndSortedApartments, sampleApartmentsData };
