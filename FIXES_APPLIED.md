# H&M Scraper - Fixes Applied

## Problem
The script was only collecting **16 products per page** instead of the expected **~64 products**.

## Root Cause Analysis

### 1. Website Structure Change
The H&M Brazil website changed from URL-based pagination to **GraphQL API with cursor-based pagination**:
- Old: `?page=0`, `?page=1` would show different products
- New: Uses GraphQL queries with `after` parameter: `after=0`, `after=36`, `after=72`, etc.

### 2. Virtual Scrolling Limitation
The site uses **virtual scrolling** which:
- Only keeps ~36-40 product cards in the DOM at any time
- Removes products from DOM as you scroll to maintain performance
- Makes DOM-based scraping ineffective

### 3. API Response Structure
The GraphQL API returns:
- **36 SKUs per batch** (SKU = size variant, e.g., "Size P", "Size M")
- Multiple SKUs can belong to the same base product
- Need to deduplicate by base product code (e.g., `1307685001`)

## Solution Implemented

### Main Changes

#### 1. GraphQL API Interception (New Approach)
Instead of scraping the DOM, the script now:
- **Intercepts GraphQL API responses** using Playwright's response listener
- Extracts product data from `ClientManyProductsQuery` and `ClientProductGalleryQuery` responses
- Collects URLs continuously as products load

#### 2. Improved Product Key Extraction
Enhanced `_product_key()` function to:
- Extract the base product code (10+ digits) from URLs
- Deduplicate size variants (e.g., `product-1307685001-115369` and `product-1307685001-115368` become the same base product)
- Prevent counting the same product multiple times

#### 3. Aggressive Scrolling Strategy
- Increased scroll rounds from 60 to **150 iterations**
- Scroll increment: **450px with 600ms wait** (optimized for API call triggers)
- Continues until stable for 10 consecutive rounds (no new products)

#### 4. Removed Obsolete Methods
Cleaned up old approaches that no longer work:
- Shadow DOM scanning
- Frame scanning  
- Click fallback methods
- Load more button detection (button doesn't exist anymore)

### Code Changes Summary

```python
# OLD: DOM-based collection
async def discover_pdp_urls(page, limit, category_url):
    # Scroll and scrape visible cards
    # Limited to ~16-36 products due to virtual scrolling
    
# NEW: GraphQL API interception
async def discover_pdp_urls(page, limit, category_url):
    async def handle_response(response):
        # Extract products from GraphQL responses
        # Deduplicate by base product code
    
    page.on('response', handle_response)
    await page.goto(category_url)
    # Scroll to trigger more API calls
    # Collect 60-75 products per page
```

## Results

### Before Fix
- **16 products per page**
- Only captured initially visible DOM cards
- Virtual scrolling prevented discovery of more products

### After Fix  
- **~69-72 unique products per page** (from ~73-75 SKUs)
- Captures all products loaded via GraphQL API
- Properly deduplicates size variants

### Why Not Exactly 64?
The number varies (69-72) because:
1. H&M's product availability changes over time
2. API may return slightly different counts based on inventory
3. Some products may have been added/removed since you last ran the script

## Usage

The fixed script works the same way as before:

```bash
python3 hm_scraper.py
```

### Configuration (in script)
```python
START_PAGE = 0           # First page index
PAGES_TO_SCAN = 30       # Number of pages to scrape
OUTPUT_XLSX = "hm_status(29/11).xlsx"
HEADLESS = True          # Run browser in background
```

## Technical Details

### GraphQL API Structure
The H&M website makes requests to:
```
https://www.hm.com.br/api/graphql?operationName=ClientManyProductsQuery&variables=...
```

**Response structure:**
```json
{
  "data": {
    "search": {
      "products": {
        "edges": [
          {
            "node": {
              "slug": "product-slug-1234567890-123456",
              "sku": "123456",
              "name": "Product Name Size P",
              ...
            }
          }
        ],
        "pageInfo": {
          "totalCount": 3634
        }
      }
    }
  }
}
```

### Product URL Construction
From slug `"calca-jogger-1307685001-115369"`:
- Full URL: `https://www.hm.com.br/calca-jogger-1307685001-115369/p`
- Base product code: `1307685001`
- SKU ID: `115369`

## Troubleshooting

### If Getting Fewer Products
1. **Check network connection** - API calls may be failing
2. **Increase scroll rounds** - Change `range(150)` to `range(200)` in `discover_pdp_urls()`
3. **Increase wait times** - Change `await page.wait_for_timeout(600)` to `800` or `1000`

### If Script Hangs
1. **Check HEADLESS setting** - Set to `True` for remote environments
2. **Check timeouts** - API responses may be slow
3. **Monitor logs** - Look for "Round N: X unique products" messages

### If Getting Duplicates
The script now properly deduplicates, but if you see duplicates:
1. Check the Excel output - each row should be a unique product
2. The `_product_key()` function extracts base product codes
3. Size variants are merged into a single row with multiple size columns

## Files Modified
- `hm_scraper.py` - Main script with all fixes applied
- Fixed bugs:
  - `LETTER_SIZES` list had missing comma after "XXXP"
  - Added "XXXP" and "XXXXG" sizes
  - Added size "54" to NUMERIC_ALLOWED

## Testing
A test script was created to verify the fix:
```bash
python3 test_final.py  # Quick test with 1 page
```

Expected output:
```
Final: 69-72 unique products from 73-75 SKUs
```

## Performance
- **Before:** ~30 seconds per page, 16 products
- **After:** ~60 seconds per page, 69-72 products
- Processing time increased slightly due to more products, but collection efficiency improved **4.3x**
