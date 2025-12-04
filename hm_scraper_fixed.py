import asyncio
import logging
import re
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PWTimeout, Page

# ======= CONFIG =======
CATEGORY_URL_TEMPLATE = (
    "https://www.hm.com.br/feminino/vestuario"
    "?category-1=feminino&category-2=vestuario&fuzzy=0&operator=and"
    "&facets=category-1%2Ccategory-2%2Cfuzzy%2Coperator&sort=score_desc&page={page}"
)
START_PAGE = 0
PAGES_TO_SCAN = 30
PAGE_RETRIES = 5
OUTPUT_XLSX = "hm_status(29/11).xlsx"
HEADLESS = True
LOG_LEVEL = "INFO"

# Timeouts
NAV_TIMEOUT_MS = 90_000
STEP_TIMEOUT_MS = 45_000

# ======================
HM_BASE = "https://www.hm.com.br"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

PDP_URL_RE = re.compile(r"/(?:p\b|produto\b|product\b|productpage\b)", re.I)

LABEL_SOLDOUT = "Esgotado"
LABEL_LOW = "Poucas unidades"
LABEL_AVAIL = "Disponível"
LABEL_HYPHEN = "-"

LETTER_SIZES = [
    "XXXP",
    "XXP",
    "XP",
    "PP",
    "P",
    "M",
    "G",
    "GG",
    "XG",
    "XXG",
    "XXXG",
    "XXXXG",
]
NUMERIC_ALLOWED = {str(n) for n in range(30, 56, 2)}  # pares 30–56

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("hm")

COOKIE_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "button#onetrust-accept-btn-handler",
    "button:has-text('Aceitar todos')",
    "button:has-text('Aceitar')",
    "button:has-text('Accept all')",
    "button:has-text('Accept')",
]

OVERLAY_SELECTORS = [
    "button[aria-label='Fechar']",
    "button:has-text('Fechar')",
    "button:has-text('Close')",
    "[data-testid='modal-close']",
    "button[aria-label*='close' i]",
]

CARD_SELECTOR = "article[data-fs-product-card-custom='true']"


# ---------------------- utils ----------------------


def _order_sizes(all_sizes: List[str]) -> List[str]:
    letters = [s for s in all_sizes if s.isalpha()]
    nums = [s for s in all_sizes if s.isdigit()]
    other = [s for s in all_sizes if s not in letters and s not in nums]
    ordered_letters = sorted(
        letters, key=lambda x: (LETTER_SIZES.index(x) if x in LETTER_SIZES else 999, x)
    )
    ordered_nums = sorted(nums, key=lambda x: int(x))
    ordered_other = sorted(other)
    return ordered_letters + ordered_nums + ordered_other


def _normalize_href(href: str) -> str:
    if href.startswith("/"):
        return HM_BASE + href
    if not href.startswith("http"):
        return HM_BASE.rstrip("/") + "/" + href.lstrip("/")
    return href


def _product_key(url: str) -> str:
    try:
        path = urlparse(url).path
    except Exception:
        path = url
    if not path:
        return url
    path = path.split("?", 1)[0]
    digits = re.findall(r"\d{6,}", path)
    if digits:
        return digits[0]
    slug = path.rstrip("/").split("/")[-1]
    slug = slug.split(".", 1)[0]
    return slug or url


async def robust_goto(page: Page, url: str):
    last = None
    for wait in ("domcontentloaded", "networkidle", "load"):
        try:
            await page.goto(url, wait_until=wait, timeout=NAV_TIMEOUT_MS)
            return
        except Exception as e:
            last = e
    raise last


# ------------------ cookies/overlays ------------------


async def _maybe_accept_cookies(page: Page):
    for sel in COOKIE_SELECTORS:
        try:
            btn = page.locator(sel)
            if await btn.count() > 0:
                await btn.first.click()
                log.info("Cookie banner aceito (%s).", sel)
                await page.wait_for_timeout(400)
                break
        except Exception:
            pass


async def _close_overlays(page: Page):
    for sel in OVERLAY_SELECTORS:
        try:
            el = page.locator(sel)
            if await el.count() > 0:
                await el.first.click()
                log.info("Overlay fechado (%s).", sel)
                await page.wait_for_timeout(250)
        except Exception:
            pass


# ------------------ Enhanced PDP discovery with continuous collection ------------------


COLLECT_URLS_JS = r"""
() => {
    const cards = document.querySelectorAll('article[data-fs-product-card-custom="true"]');
    const urls = new Set();
    const PDP = /\/(p\b|produto\b|product\b|productpage\b)/i;
    
    cards.forEach(card => {
        const anchor =
            card.querySelector('[data-carousel-image-container] a[href]') ||
            card.querySelector('a[data-product-card-link][href]') ||
            card.querySelector('a[href]');
        
        if (anchor && !anchor.closest('[data-color-selector-hex]')) {
            const href = anchor.getAttribute('href') || anchor.href || '';
            if (href && PDP.test(href)) {
                urls.add(href);
            }
        }
    });
    
    return Array.from(urls);
}
"""


async def discover_pdp_urls_with_continuous_collection(page: Page, category_url: str) -> List[str]:
    """
    Collects product URLs while scrolling continuously to handle virtual scrolling.
    The site uses virtual scrolling which removes products from DOM as you scroll,
    so we need to collect URLs during the scroll process, not after.
    """
    found: Set[str] = set()
    seen_keys: Set[str] = set()
    
    # Helper to collect and store URLs
    async def collect_current_urls():
        try:
            urls = await page.evaluate(COLLECT_URLS_JS)
            new_count = 0
            for raw_url in urls:
                norm = _normalize_href(raw_url)
                if not PDP_URL_RE.search(norm):
                    continue
                key = _product_key(norm)
                if norm not in found and key not in seen_keys:
                    found.add(norm)
                    seen_keys.add(key)
                    new_count += 1
            return new_count
        except Exception as e:
            log.warning(f"Error collecting URLs: {e}")
            return 0
    
    # Initial collection
    await page.wait_for_selector(CARD_SELECTOR, timeout=10_000)
    await collect_current_urls()
    log.info(f"  Initial collection: {len(found)} URLs")
    
    # Scroll with continuous collection
    # The site uses virtual scrolling, so we need to collect as we go
    prev_count = len(found)
    stable_rounds = 0
    max_scroll_rounds = 100  # Increased from 60
    
    for i in range(max_scroll_rounds):
        # Scroll incrementally
        await page.evaluate('window.scrollBy(0, 400)')
        await page.wait_for_timeout(500)  # Wait for content to load
        
        # Collect URLs at current scroll position
        new_urls = await collect_current_urls()
        
        current_count = len(found)
        
        # Check if we're still finding new products
        if current_count > prev_count:
            if i % 5 == 0:  # Log every 5 rounds
                log.info(f"  Scroll round {i+1}: {current_count} URLs collected (+{current_count - prev_count} new)")
            prev_count = current_count
            stable_rounds = 0
        else:
            stable_rounds += 1
        
        # Stop if no new products found for 8 consecutive rounds
        if stable_rounds >= 8:
            log.info(f"  Stable at {current_count} URLs for {stable_rounds} rounds")
            break
        
        # Check if we've reached the bottom
        at_bottom = await page.evaluate('''
            () => (window.innerHeight + window.pageYOffset) >= document.documentElement.scrollHeight - 50
        ''')
        
        if at_bottom and stable_rounds >= 3:
            log.info(f"  Reached bottom at round {i+1}")
            # Do a final collection after a short wait
            await page.wait_for_timeout(1000)
            await collect_current_urls()
            break
    
    # Scroll back to top and collect again (in case virtual scrolling showed different products)
    await page.evaluate('window.scrollTo(0, 0)')
    await page.wait_for_timeout(800)
    final_new = await collect_current_urls()
    if final_new > 0:
        log.info(f"  Collected {final_new} more URLs after scrolling back to top")
    
    # Scroll to middle and collect
    await page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight / 2)')
    await page.wait_for_timeout(800)
    middle_new = await collect_current_urls()
    if middle_new > 0:
        log.info(f"  Collected {middle_new} more URLs from middle section")
    
    result = sorted(list(found))
    log.info(f"Links detectados — total: {len(result)}")
    return result


async def _ensure_cards_loaded(page: Page, category_url: str, page_number: int) -> bool:
    for attempt in range(1, PAGE_RETRIES + 1):
        try:
            await page.wait_for_selector(CARD_SELECTOR, timeout=20_000)
            count = await page.locator(CARD_SELECTOR).count()
            if count > 0:
                return True
            log.warning(
                "Cards ainda não visíveis na página %d (tentativa %d/%d); aguardando mais.",
                page_number,
                attempt,
                PAGE_RETRIES,
            )
        except Exception as exc:
            log.warning(
                "Ainda sem cards visíveis na página %d (tentativa %d/%d): %s",
                page_number,
                attempt,
                PAGE_RETRIES,
                exc,
            )
        await page.wait_for_timeout(5_000)
    return False


# ------------------ PDP -> nome + tamanhos ------------------


PARSE_SIZES_JS = r"""
(() => {
  const LETTERS = new Set(["XXP","XP","PP","P","M","G","GG","XG","XXG","XXGG","XXGGG"]);
  const NUMERIC = new Set(["32","34","36","38","40","42","44","46","48","50","52"]);
  const SYN = { "XS":"XP", "S":"P", "L":"G", "XL":"XG", "XXL":"XXG" };

  function clean(txt){
    if(!txt) return "";
    let t = txt.trim().toUpperCase();
    t = t.split(/\s|–|-|·|\|/)[0];
    t = t.replace(/[^A-Z0-9]/g, "");
    if (SYN[t]) t = SYN[t];
    return t;
  }

  function isRed(c){
    if(!c) return false;
    const m = c.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/i);
    if(!m) return false;
    const r = +m[1], g = +m[2], b = +m[3];
    return (r >= 150 && g <= 110 && b <= 110);
  }

  function hasRedIndicator(el){
    const aft = getComputedStyle(el, '::after');
    const bef = getComputedStyle(el, '::before');
    if (isRed(aft.backgroundColor) || isRed(aft.borderColor)) return true;
    if (isRed(bef.backgroundColor) || isRed(bef.borderColor)) return true;

    const rect = el.getBoundingClientRect();
    for (const k of el.querySelectorAll('*')) {
      const r = k.getBoundingClientRect();
      if (r.width <= 22 && r.height <= 22) {
        const cs = getComputedStyle(k);
        const inBounds = r.left >= rect.left - 2 && r.right <= rect.right + 2 &&
                         r.top  >= rect.top - 2  && r.bottom <= rect.bottom + 2;
        if (!inBounds) continue;
        if (isRed(cs.backgroundColor) || isRed(cs.borderColor) || isRed(cs.color)) {
          return true;
        }
      }
    }
    return false;
  }

  function hasLineThrough(el){
    const check = (n) => {
      const cs = getComputedStyle(n);
      const td = (cs.textDecorationLine || cs.textDecoration || "").toLowerCase();
      if (td.includes("line-through")) return true;
      const cl = (n.className || "").toLowerCase();
      if (cl.includes("strike") || cl.includes("line-through") || cl.includes("cross")) return true;
      if (n.querySelector("s, del, strike")) return true;
      return false;
    };
    if (check(el)) return true;
    for (const k of el.querySelectorAll("*")) if (check(k)) return true;
    return false;
  }

  const containers = Array.from(document.querySelectorAll(
    '[id*="size" i], [class*="size" i], [data-test*="size" i], section, fieldset, div'
  )).filter(el => /ESCOLHA O TAMANHO|TAMANHO|SIZE/i.test(el.textContent || ""));

  let scope = document;
  let best = -1;
  for (const el of (containers.length ? containers : [document])) {
    const count = el.querySelectorAll(
      'button, label, [role="option"], [role="radio"], input[type="radio"]+label, ' +
      '[data-size], [data-testid*="size" i], li, a, span, div'
    ).length;
    if (count > best) { best = count; scope = el; }
  }

  const nodes = scope.querySelectorAll(
    'button, label, [role="option"], [role="radio"], input[type="radio"]+label, ' +
    '[data-size], [data-testid*="size" i], li, a, span, div'
  );

  const L = [];
  const N = [];
  const rank = s => s==='Esgotado' ? 2 : (s==='Poucas unidades' ? 1 : 0);

  for (const el of nodes) {
    const cand = [
      clean(el.textContent || ""),
      clean(el.getAttribute("data-size") || ""),
      clean(el.getAttribute("data-sku-size") || ""),
      clean(el.getAttribute("aria-label") || ""),
      clean(el.getAttribute("title") || "")
    ].filter(Boolean);

    let label = "";
    for (const t of cand) {
      if (LETTERS.has(t) || NUMERIC.has(t)) { label = t; break; }
    }
    if (!label) continue;

    const carrier = el.closest('[data-fs-sku-selector-option]') || el;
    const disabledAttr = carrier.getAttribute("data-fs-sku-selector-disabled");
    const stockStatus = (carrier.getAttribute("data-fs-stock-status") || "").toLowerCase();
    const lowAttr = carrier.getAttribute("data-fs-sku-selector-low-stock") === "true";
    const lowClosest = !!carrier.closest('[data-fs-sku-selector-low-stock="true"]');
    const aria = (carrier.getAttribute("aria-label") || el.getAttribute("aria-label") || "").toLowerCase();
    const titleAttr = (carrier.getAttribute("title") || el.getAttribute("title") || "").toLowerCase();
    const disabled = disabledAttr === "true" || !!carrier.disabled || carrier.getAttribute("aria-disabled") === "true" || getComputedStyle(carrier).pointerEvents === "none";
    const meta = ((carrier.className||"") + " " + (el.className||"") + " " + aria + " " + titleAttr + " " + stockStatus).toLowerCase();
    const sold = disabled || hasLineThrough(carrier) || hasLineThrough(el) || /(soldout|sold-out|out-of-stock|unavailable|esgotad)/.test(meta);
    const lowStockFlag = stockStatus.includes("low") || lowAttr || lowClosest || aria.includes("poucas") || titleAttr.includes("poucas");
    const low  = !sold && (lowStockFlag || hasRedIndicator(el));

    const status = sold ? "Esgotado" : (low ? "Poucas unidades" : "Disponível");

    if (LETTERS.has(label)) L.push({label, status});
    else                    N.push({label, status});
  }

  const chosen = (N.length > L.length) ? N : L;
  const bestMap = {};
  for (const it of chosen) {
    const prev = bestMap[it.label];
    if (!prev || rank(it.status) > rank(prev)) bestMap[it.label] = it.status;
  }
  return bestMap;
})()
"""


async def parse_pdp(page: Page) -> Tuple[str, Dict[str, str]]:
    """Extrai (nome, {tamanho: status})"""
    # 1) Nome
    name = ""
    for sel in ["h1", 'meta[property="og:title"]', "title"]:
        try:
            loc = page.locator(sel)
            if await loc.count() > 0:
                if sel.startswith("meta"):
                    v = await loc.first.get_attribute("content")
                else:
                    v = await loc.first.inner_text()
                if v and v.strip():
                    name = v.strip()
                    break
        except Exception:
            pass
    if not name:
        name = "Produto H&M"

    # 2) Sizes
    try:
        data = await page.evaluate(PARSE_SIZES_JS)
    except Exception:
        data = {}

    sizes_map: Dict[str, str] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if (k.isalpha() and k in LETTER_SIZES) or (k.isdigit() and k in NUMERIC_ALLOWED):
                sizes_map[k] = v

    return name, sizes_map


# ------------------ Excel ------------------


def build_excel(items: List[Tuple[str, Dict[str, str]]]) -> pd.DataFrame:
    all_sizes = {
        size
        for _, mp in items
        for size in mp.keys()
    }
    all_sizes = [
        s
        for s in all_sizes
        if (s.isalpha() and s in LETTER_SIZES) or (s.isdigit() and s in NUMERIC_ALLOWED)
    ]
    size_cols = _order_sizes(all_sizes)

    rows = []
    for name, mp in items:
        row = {"Nome do Produto": name}
        for s in size_cols:
            row[s] = mp.get(s, LABEL_HYPHEN)
        rows.append(row)
    return pd.DataFrame(rows, columns=["Nome do Produto"] + size_cols)


# ------------------ MAIN ------------------


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 1400},
            locale="pt-BR",
        )
        ctx.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        ctx.set_default_timeout(STEP_TIMEOUT_MS)

        page = await ctx.new_page()

        pdp_urls: List[str] = []
        seen_product_keys: Set[str] = set()

        for offset in range(PAGES_TO_SCAN):
            page_idx = START_PAGE + offset
            category_url = CATEGORY_URL_TEMPLATE.format(page=page_idx)
            log.info(
                "Abrindo categoria (página %d/%d): %s",
                offset + 1,
                PAGES_TO_SCAN,
                category_url,
            )
            try:
                await page.goto(category_url, wait_until="domcontentloaded")
            except PWTimeout:
                log.warning("Timeout inicial ao carregar página %d; aguardando mais tempo.", offset + 1)
            try:
                await page.wait_for_load_state("networkidle", timeout=60_000)
            except Exception:
                log.warning("Estado 'networkidle' não atingido na página %d; seguindo mesmo assim.", offset + 1)
            await page.wait_for_timeout(2_500)

            await page.wait_for_timeout(1_200)
            await _maybe_accept_cookies(page)
            await _close_overlays(page)

            cards_ready = await _ensure_cards_loaded(page, category_url, offset + 1)
            if not cards_ready:
                log.error("Cards não carregaram na página %d; pulando.", offset + 1)
                continue

            log.info("Coletando produtos da página com scroll contínuo...")
            novos = await discover_pdp_urls_with_continuous_collection(page, category_url)

            filtrados = []
            for url in novos:
                key = _product_key(url)
                if key in seen_product_keys:
                    continue
                seen_product_keys.add(key)
                filtrados.append(url)

            total_pagina = len(filtrados)
            if total_pagina:
                pdp_urls.extend(filtrados)
                base_idx = len(pdp_urls) - total_pagina + 1
                for idx, u in enumerate(filtrados, base_idx):
                    log.info("  [%d] %s", idx, u)
                log.info("Página %d: %d produtos novos coletados (total acumulado=%d).", offset + 1, total_pagina, len(pdp_urls))
            else:
                log.info("Nenhum novo produto único encontrado nesta página.")

        log.info("Total de PDPs únicas detectadas: %d", len(pdp_urls))

        if not pdp_urls:
            log.error("Nenhum produto encontrado.")
            await ctx.close()
            await browser.close()
            return

        items: List[Tuple[str, Dict[str, str]]] = []
        for i, url in enumerate(pdp_urls, 1):
            log.info("[%d/%d] Abrindo PDP: %s", i, len(pdp_urls), url)
            try:
                await page.goto(url, wait_until="domcontentloaded")
            except PWTimeout:
                log.warning("Timeout no goto do PDP; continuando.")
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            await page.wait_for_timeout(600)
            await _maybe_accept_cookies(page)
            await _close_overlays(page)

            name, sizes = await parse_pdp(page)
            log.info(
                " → %s | tamanhos: %s",
                name,
                ", ".join(f"{k}:{v}" for k, v in sorted(sizes.items())),
            )
            items.append((name, sizes))

        await ctx.close()
        await browser.close()

    log.info("Gerando Excel: %s", OUTPUT_XLSX)
    df = build_excel(items)
    df.to_excel(OUTPUT_XLSX, index=False)
    log.info("Concluído. Linhas no Excel: %d", len(df))


if __name__ == "__main__":
    asyncio.run(main())
