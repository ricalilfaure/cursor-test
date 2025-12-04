import asyncio
from playwright.async_api import async_playwright
import re
from urllib.parse import urlparse

HM_BASE = "https://www.hm.com.br"

def _product_key(url: str) -> str:
    """Extract unique product identifier from URL"""
    try:
        path = urlparse(url).path
    except Exception:
        path = url
    if not path:
        return url
    path = path.split("?", 1)[0]
    # Extract the base product code (before the SKU suffix)
    codes = re.findall(r"-(\d{10,})-", path)
    if codes:
        return codes[0]
    digits = re.findall(r"\d{6,}", path)
    if digits:
        return digits[0]
    slug = path.rstrip("/").split("/")[-1]
    slug = slug.split(".", 1)[0]
    slug_clean = re.sub(r"-\d+$", "", slug)
    return slug_clean or url

async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1280, 'height': 1400})
        
        products = {}  # key -> full_url
        seen_skus = set()
        
        async def handle_response(response):
            try:
                url = response.url
                if 'graphql' not in url:
                    return
                if 'ClientManyProductsQuery' not in url and 'ClientProductGalleryQuery' not in url:
                    return
                
                data = await response.json()
                if 'data' not in data:
                    return
                
                search = data['data'].get('search', {})
                products_wrapper = search.get('products', {})
                edges = products_wrapper.get('edges', [])
                
                for edge in edges:
                    node = edge.get('node', {})
                    slug = node.get('slug')
                    sku = node.get('sku')
                    
                    if not slug or not sku:
                        continue
                    
                    if sku in seen_skus:
                        continue
                    seen_skus.add(sku)
                    
                    full_url = f"{HM_BASE}/{slug}/p"
                    key = _product_key(full_url)
                    
                    if key not in products:
                        products[key] = full_url
            
            except Exception:
                pass
        
        page.on('response', handle_response)
        
        url = 'https://www.hm.com.br/feminino/vestuario?category-1=feminino&category-2=vestuario&fuzzy=0&operator=and&facets=category-1%2Ccategory-2%2Cfuzzy%2Coperator&sort=score_desc&page=0'
        await page.goto(url, wait_until='networkidle')
        
        try:
            await page.click('button:has-text("Aceitar todos")', timeout=5000)
            await page.wait_for_timeout(500)
        except:
            pass
        
        await page.wait_for_timeout(1000)
        
        print("Scrolling to trigger GraphQL API calls...")
        
        prev_count = 0
        stable = 0
        
        for i in range(150):
            await page.evaluate('window.scrollBy(0, 450)')
            await page.wait_for_timeout(600)
            
            current_count = len(products)
            
            if current_count > prev_count:
                if i % 10 == 0:
                    print(f"Round {i+1}: {current_count} unique products (SKUs: {len(seen_skus)})")
                prev_count = current_count
                stable = 0
            else:
                stable += 1
            
            if stable >= 10:
                print(f"Stable at {current_count} products for {stable} rounds")
                break
        
        print(f"\nFinal: {len(products)} unique products from {len(seen_skus)} SKUs")
        print(f"\nFirst 10 products:")
        for i, url in enumerate(list(products.values())[:10], 1):
            print(f"  {i}. {url}")
        
        await browser.close()

asyncio.run(test())
