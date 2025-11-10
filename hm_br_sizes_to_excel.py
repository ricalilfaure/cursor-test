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
PAGES_TO_SCAN = 5
OUTPUT_XLSX = "hm_status.xlsx"
HEADLESS = False
LOG_LEVEL = "INFO"

# Descoberta de PDPs (ligue/desligue conforme necessidade)
USE_SHADOW_SCAN = True
USE_FRAME_SCAN = True
USE_CLICK_FALLBACK = True

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
    "XXP",
    "XP",
    "PP",
    "P",
    "M",
    "G",
    "GG",
    "XG",
    "XXG",
    "XXGG",
    "XXGGG",
]
NUMERIC_ALLOWED = {str(n) for n in range(32, 54, 2)}  # pares 32–52

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

PRODUCT_HINT_SELECTORS = [
    "a[href*='/produto']",
    "a[href*='/productpage']",
    "a[href*='/product/']",
    "[data-product-url]",
    "[data-href*='/produto']",
    "[data-href*='/product']",
    "article[data-fs-product-card-custom='true']",
    "article[data-fs-product-card-custom='true'] a[href]",
]


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


# ------------------ auto-scroll / load more ------------------


async def _auto_scroll(page: Page, max_rounds: int = 60, pause_ms: int = 700):
    prev_h = 0
    stable = 0
    for i in range(max_rounds):
        cur_h = await page.evaluate("document.documentElement.scrollHeight")
        if cur_h <= prev_h:
            stable += 1
        else:
            stable = 0
        if stable >= 3:
            break
        await page.mouse.wheel(0, 2400)
        await page.wait_for_timeout(pause_ms)
        prev_h = cur_h
    log.info("Auto-scroll finalizado (altura=%s, iterações=%s).", prev_h, i + 1)


async def _load_more(page: Page, max_clicks: int = 8):
    for _ in range(max_clicks):
        try:
            btn = page.locator(
                'button:has-text("Carregar mais"), '
                'button:has-text("Mais produtos"), '
                'button:has-text("Load more"), '
                'button:has-text("Ver mais"), '
                'button:has-text("Mostrar mais")'
            )
            if await btn.count() > 0 and await btn.first.is_visible():
                await btn.first.click()
                log.info("Clicado em 'Carregar mais'.")
                await page.wait_for_timeout(1200)
            else:
                break
        except Exception:
            break


# ------------------ PDP discovery helpers ------------------

DISCOVERY_JS = r"""
() => {
  // Busca **em profundidade** (document + shadow roots) por:
  //  - <a href> com /p|produto|product/
  //  - atributos: data-href, data-url, data-product-url, data-link, onclick (com URL)
  //  - JSON-LD com url para produto
  const out = new Set();
  const PDP = /\/(p\b|produto\b|product\b|productpage\b)/i;

  const extractFromRoot = (root) => {
    try {
      // anchors
      root.querySelectorAll('a[href]').forEach(a => {
        if (a.closest('[data-color-selector-hex]')) return;
        if ((a.dataset || {}).testid === 'color-block') return;
        const h = a.getAttribute('href') || '';
        const abs = a.href || '';
        if (PDP.test(h)) out.add(h);
        else if (PDP.test(abs)) out.add(abs);
      });

      // atributos
      root.querySelectorAll('[data-href],[data-url],[data-product-url],[data-link],[onclick]').forEach(el => {
        if (el.closest && el.closest('[data-color-selector-hex]')) return;
        const attrs = ['data-href','data-url','data-product-url','data-link','onclick'];
        for (const k of attrs) {
          const v = el.getAttribute(k);
          if (!v) continue;
          const str = String(v);
          const m = str.match(/['"]((?:https?:)?\/?[^'"]*\/(?:p|produto|product)\/[^'"]+)['"]/i);
          if (m && m[1]) { out.add(m[1]); continue; }
          if (PDP.test(str)) out.add(str);
        }
      });

      // JSON-LD
      root.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
        try {
          const txt = s.textContent || '';
          if (!txt.trim()) return;
          const data = JSON.parse(txt);
          const push = (u) => {
            if (!u) return;
            if (PDP.test(u)) out.add(u);
          };
          const walk = (x) => {
            if (Array.isArray(x)) return x.forEach(walk);
            if (x && typeof x === 'object') {
              if (x.url) push(x.url);
              Object.values(x).forEach(walk);
            }
          };
          walk(data);
        } catch(e){}
      });

      // desce em shadow roots
      root.querySelectorAll('*').forEach(el => {
        if (el && el.shadowRoot) extractFromRoot(el.shadowRoot);
      });
    } catch(e){}
  };

  extractFromRoot(document);
  return Array.from(out);
}
"""

CARD_DISCOVERY_JS = r"""
() => {
  const cards = Array.from(document.querySelectorAll('article[data-fs-product-card-custom="true"]'));
  const PDP = /\/(p\b|produto\b|product\b|productpage\b)/i;
  const out = [];
  const seen = new Set();
  for (const card of cards) {
    let anchor =
      card.querySelector('[data-carousel-image-container] a[href]') ||
      card.querySelector('a[data-product-card-link][href]') ||
      card.querySelector('a[href]');
    if (!anchor) continue;
    if (anchor.closest('[data-color-selector-hex]')) continue;
    const href = anchor.getAttribute('href') || anchor.href || '';
    if (!href) continue;
    if (!PDP.test(href)) continue;
    if (seen.has(href)) continue;
    seen.add(href);
    out.push(href);
  }
  return out;
}
"""


async def _collect_pdp_urls_in(page_or_frame) -> List[str]:
    try:
        urls = await page_or_frame.evaluate(DISCOVERY_JS)
        # normaliza e filtra
        uniq: List[str] = []
        seen: Set[str] = set()
        for u in urls:
            if not u:
                continue
            if not PDP_URL_RE.search(u):
                continue
            # normalização simples (sem resolver URL relativa aqui; faremos em Python)
            if u not in seen:
                uniq.append(u)
                seen.add(u)
        return uniq
    except Exception:
        return []


async def _collect_card_urls(page_or_frame) -> List[str]:
    try:
        urls = await page_or_frame.evaluate(CARD_DISCOVERY_JS)
        uniq: List[str] = []
        seen: Set[str] = set()
        for u in urls:
            if not u:
                continue
            if not PDP_URL_RE.search(u):
                continue
            if u not in seen:
                uniq.append(u)
                seen.add(u)
        return uniq
    except Exception:
        return []


async def _discover_by_click_in(page_or_frame, limit: Optional[int], category_url: str) -> List[str]:
    urls: List[str] = []
    anchors = page_or_frame.locator(
        "article[data-fs-product-card-custom='true'] [data-carousel-image-container] a[href]"
    )
    count = await anchors.count()
    max_candidates = count if limit is None else min(count, max(limit * 6, limit + 6))
    for i in range(max_candidates):
        if i >= count:
            break
        if limit is not None and len(urls) >= limit:
            break
        anchor = anchors.nth(i)
        try:
            href = await anchor.get_attribute("href")
            if not href:
                continue
            norm = _normalize_href(href)
            if not PDP_URL_RE.search(norm):
                continue

            await anchor.scroll_into_view_if_needed()
            await anchor.click(timeout=4000, force=True)

            try:
                await page_or_frame.page.wait_for_url(PDP_URL_RE, timeout=8000)
            except Exception:
                continue

            u = page_or_frame.page.url
            if PDP_URL_RE.search(u) and u not in urls:
                urls.append(u)

            try:
                await page_or_frame.page.go_back(wait_until="domcontentloaded", timeout=15000)
            except Exception:
                await robust_goto(page_or_frame.page, category_url)
                await _maybe_accept_cookies(page_or_frame.page)
                await _close_overlays(page_or_frame.page)
        except Exception:
            continue
    return urls


async def discover_pdp_urls(page: Page, limit: Optional[int], category_url: str) -> List[str]:
    found: List[str] = []
    seen: Set[str] = set()
    seen_keys: Set[str] = set()

    async def wait_for_candidates():
        for sel in PRODUCT_HINT_SELECTORS:
            try:
                await page.wait_for_selector(sel, timeout=6_000)
                return
            except Exception:
                continue
        await page.wait_for_timeout(700)

    await wait_for_candidates()

    async def add_urls(urls: List[str], tag: str):
        nonlocal found, seen, seen_keys
        buf: List[str] = []
        for raw in urls:
            nh = _normalize_href(raw)
            if not PDP_URL_RE.search(nh):
                continue
            key = _product_key(nh)
            if nh in seen or key in seen_keys:
                continue
            buf.append(nh)
            seen.add(nh)
            seen_keys.add(key)
            if limit is not None and len(found) + len(buf) >= limit:
                break
        if buf:
            log.info("  + %s -> %d URLs", tag, len(buf))
            found.extend(buf)

    def quota_reached() -> bool:
        return limit is not None and len(found) >= limit

    # coleta ordenada via cards visíveis
    card_urls = await _collect_card_urls(page)
    await add_urls(card_urls, "cards")

    async def add_from_ctx(ctx, tag: str):
        got = await _collect_pdp_urls_in(ctx)
        await add_urls(got, tag)

    if not found:
        # fallback para DOM completo se nenhum card foi capturado
        await add_from_ctx(page, "document")

    if USE_FRAME_SCAN and not quota_reached() and not found:
        for fr in page.frames:
            if fr == page.main_frame:
                continue
            try:
                await add_from_ctx(fr, f"frame:{fr.url}")
            except Exception:
                continue

    if quota_reached():
        return found[:limit] if limit is not None else found

    # 3) aciona carregamento incremental
    await _load_more(page)
    await _auto_scroll(page)
    await wait_for_candidates()
    # reexecuta coleta ordenada após carregar mais cards
    prev = len(found)
    await add_urls(await _collect_card_urls(page), "cards-scroll")
    if quota_reached():
        return found[:limit] if limit is not None else found

    if len(found) == prev:
        # 4) fallback apenas se nenhuma nova URL foi adicionada via cards
        await add_from_ctx(page, "document-scroll")

    if USE_FRAME_SCAN and not quota_reached():
        for fr in page.frames:
            if fr == page.main_frame:
                continue
            try:
                await add_from_ctx(fr, f"frame-scroll:{fr.url}")
            except Exception:
                continue

    # 4) se ainda insuficiente, fallback por clique (no main e em frames)
    remaining = None if limit is None else max(limit - len(found), 0)
    if USE_CLICK_FALLBACK and limit is not None and (remaining is None or remaining > 0):
        extra = await _discover_by_click_in(page, remaining, category_url)
        if extra:
            new = []
            for u in extra:
                key = _product_key(u)
                if key in seen_keys:
                    continue
                new.append(u)
                seen_keys.add(key)
                seen.add(u)
            if new:
                log.info("  + click(main) -> %d URLs", len(new))
                found.extend(new)

    if USE_CLICK_FALLBACK and limit is not None and len(found) < limit:
        for fr in page.frames:
            if limit is not None and len(found) >= limit:
                break
            if fr == page.main_frame:
                continue
            try:
                extra = await _discover_by_click_in(
                    fr,
                    None if limit is None else max(limit - len(found), 0),
                    category_url,
                )
                if extra:
                    new = []
                    for u in extra:
                        key = _product_key(u)
                        if key in seen_keys:
                            continue
                        new.append(u)
                        seen_keys.add(key)
                        seen.add(u)
                    if new:
                        log.info("  + click(frame) -> %d URLs", len(new))
                        found.extend(new)
            except Exception:
                continue

    log.info("Links detectados — total:%d", len(found))
    return found[:limit] if limit is not None else found


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

  // tenta achar o container de tamanhos mais "rico"
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
    const low  = !sold && (lowStockFlag || hasRedIndicator(el)); // dot vermelho, atributo low-stock ou label associado

    const status = sold ? "Esgotado" : (low ? "Poucas unidades" : "Disponível");

    if (LETTERS.has(label)) L.push({label, status});
    else                    N.push({label, status});
  }

  // escolhe UMA família: a que tiver mais opções
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
    """Extrai (nome, {tamanho: status}) — família única (letras OU pares 32–52),
    'Poucas' somente com dot vermelho no próprio botão; 'Esgotado' por disabled/risco."""
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

    # 2) JS no contexto da página: coleta botões, determina status, separa por família
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
                log.warning("Timeout no goto da categoria (página %d); seguindo.", offset + 1)
                continue

            try:
                await page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass

            await page.wait_for_timeout(600)
            await _maybe_accept_cookies(page)
            await _close_overlays(page)

            log.info("Fazendo scroll e coletando produtos da página...")
            novos = await discover_pdp_urls(page, None, category_url)

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
                try:
                    debug_prefix = f"DEBUG_category_p{page_idx}"
                    await page.screenshot(path=f"{debug_prefix}.png", full_page=True)
                    html = await page.content()
                    with open(f"{debug_prefix}.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    log.info("  → Salvos %s.(html/png) para inspeção.", debug_prefix)
                except Exception as exc:
                    log.warning("  → Falha ao salvar debug da página %d: %s", offset + 1, exc)

        log.info("Total de PDPs únicas detectadas: %d", len(pdp_urls))

        if not pdp_urls:
            await page.screenshot(path="DEBUG_category.png", full_page=True)
            html = await page.content()
            with open("DEBUG_category.html", "w", encoding="utf-8") as f:
                f.write(html)
            log.error("Nenhum produto encontrado. Salvei DEBUG_category.(html/png).")
            await ctx.close()
            await browser.close()
            return

        items: List[Tuple[str, Dict[str, str]]] = []
        for i, url in enumerate(pdp_urls, 1):
            log.info("[%d/%d] Abrindo PDP…", i, len(pdp_urls))
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
            log.info("Produto analisado (%d/%d): %s", i, len(pdp_urls), name)

        await ctx.close()
        await browser.close()

    log.info("Gerando Excel: %s", OUTPUT_XLSX)
    df = build_excel(items)
    df.to_excel(OUTPUT_XLSX, index=False)
    log.info("Concluído. Linhas no Excel: %d", len(df))


if __name__ == "__main__":
    asyncio.run(main())
