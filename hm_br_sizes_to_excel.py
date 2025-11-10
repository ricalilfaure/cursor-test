# hm_br_sizes_to_excel.py  (v4.7 – PDP discovery com shadow DOM + iframes + clique; tamanhos por botão)
# -----------------------------------------------------------------------------------------------------
# Saída: hm_status.xlsx
#  - "Nome do Produto"
#  - colunas de tamanho (PP..XXGGG e pares 32–52)
#  - células: "Disponível" | "Poucas unidades" | "Esgotado"
#  - "-" para tamanhos que não pertencem à grade do produto
# -----------------------------------------------------------------------------------------------------

import asyncio
import logging
import re
from typing import Dict, List, Tuple

import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PWTimeout, Page, Frame

# ======= CONFIG =======
CATEGORY_URL = (
    "https://www.hm.com.br/feminino/vestuario"
    "?category-1=feminino&category-2=vestuario&fuzzy=0&operator=and"
    "&facets=category-1%2Ccategory-2%2Cfuzzy%2Coperator&sort=score_desc&page=0"
)
PRODUCT_LIMIT = 5
OUTPUT_XLSX   = "hm_status.xlsx"
HEADLESS      = False
LOG_LEVEL     = "INFO"

# Descoberta de PDPs (ligue/desligue conforme necessidade)
USE_SHADOW_SCAN   = True
USE_FRAME_SCAN    = True
USE_CLICK_FALLBACK= True

# Timeouts
NAV_TIMEOUT_MS  = 90_000
STEP_TIMEOUT_MS = 45_000

# ======================
HM_BASE = "https://www.hm.com.br"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

PDP_URL_RE = re.compile(r"/(p|produto|product)/", re.I)

LABEL_SOLDOUT = "Esgotado"
LABEL_LOW     = "Poucas unidades"
LABEL_AVAIL   = "Disponível"
LABEL_HYPHEN  = "-"

LETTER_SIZES = ["XXP","XP","PP","P","M","G","GG","XG","XXG","XXGG","XXGGG"]
NUMERIC_ALLOWED = {str(n) for n in range(32, 54, 2)}  # pares 32–52

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("hm")

# ---------------------- utils ----------------------

def _order_sizes(all_sizes: List[str]) -> List[str]:
    letters = [s for s in all_sizes if s.isalpha()]
    nums    = [s for s in all_sizes if s.isdigit()]
    other   = [s for s in all_sizes if s not in letters and s not in nums]
    ordered_letters = sorted(letters, key=lambda x: (LETTER_SIZES.index(x) if x in LETTER_SIZES else 999, x))
    ordered_nums    = sorted(nums, key=lambda x: int(x))
    ordered_other   = sorted(other)
    return ordered_letters + ordered_nums + ordered_other

def _normalize_href(href: str) -> str:
    if href.startswith("/"):
        return HM_BASE + href
    if not href.startswith("http"):
        return HM_BASE.rstrip("/") + "/" + href.lstrip("/")
    return href

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
    for sel in [
        "#onetrust-accept-btn-handler",
        "button#onetrust-accept-btn-handler",
        "button:has-text('Aceitar todos')",
        "button:has-text('Aceitar')",
        "button:has-text('Accept all')",
        "button:has-text('Accept')",
    ]:
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
    for sel in [
        "button[aria-label='Fechar']",
        "button:has-text('Fechar')",
        "button:has-text('Close')",
        "[data-testid='modal-close']",
        "button[aria-label*='close' i]",
    ]:
        try:
            el = page.locator(sel)
            if await el.count() > 0:
                await el.first.click()
                log.info("Overlay fechado (%s).", sel)
                await page.wait_for_timeout(250)
        except Exception:
            pass

# ------------------ auto-scroll / load more ------------------

async def _auto_scroll(page: Page, max_rounds: int = 60, pause_ms: int = 900):
    prev_h = 0
    stable = 0
    for i in range(max_rounds):
        cur_h = await page.evaluate("document.documentElement.scrollHeight")
        if cur_h <= prev_h: stable += 1
        else: stable = 0
        if stable >= 3: break
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
                await page.wait_for_timeout(1800)
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
  const PDP = /\/(p|produto|product)\//i;

  const extractFromRoot = (root) => {
    try {
      // anchors
      root.querySelectorAll('a[href]').forEach(a => {
        const h = a.getAttribute('href') || '';
        const abs = a.href || '';
        if (PDP.test(h)) out.add(h);
        else if (PDP.test(abs)) out.add(abs);
      });

      // atributos
      root.querySelectorAll('[data-href],[data-url],[data-product-url],[data-link],[onclick]').forEach(el => {
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

async def _collect_pdp_urls_in(page_or_frame) -> List[str]:
    try:
        urls = await page_or_frame.evaluate(DISCOVERY_JS)
        # normaliza e filtra
        uniq = []
        for u in urls:
            if not u: continue
            if not PDP_URL_RE.search(u): continue
            # normalização simples (sem resolver URL relativa aqui; faremos em Python)
            if u not in uniq: uniq.append(u)
        return uniq
    except Exception:
        return []

async def _discover_by_click_in(page_or_frame, limit: int) -> List[str]:
    urls: List[str] = []
    candidates = page_or_frame.locator(
        '[data-testid*="product"], [class*="product-card"], [class*="ProductCard"], ' +
        'article, li, a[role], div[role="link"]'
    )
    count = await candidates.count()
    for i in range(min(count, limit * 4)):
        if len(urls) >= limit: break
        el = candidates.nth(i)
        try:
            await el.scroll_into_view_if_needed()
            clicked = False
            for sel in ["a", "button", "img", "*"]:
                try:
                    target = el.locator(sel).first if sel != "*" else el
                    await target.click(timeout=3000, force=True)
                    clicked = True
                    break
                except Exception:
                    continue
            if not clicked: continue

            # espera SPA mudar para PDP
            try:
                await page_or_frame.page.wait_for_url(PDP_URL_RE, timeout=8000)
            except Exception:
                continue

            u = page_or_frame.page.url
            if PDP_URL_RE.search(u) and u not in urls:
                urls.append(u)

            # volta para a categoria
            try:
                await page_or_frame.page.go_back(wait_until="domcontentloaded", timeout=15000)
            except Exception:
                # recarrega categoria se necessário
                await robust_goto(page_or_frame.page, CATEGORY_URL)
                await _maybe_accept_cookies(page_or_frame.page)
                await _close_overlays(page_or_frame.page)
        except Exception:
            continue
    return urls

async def discover_pdp_urls(page: Page, limit: int) -> List[str]:
    found: List[str] = []

    async def add_from_ctx(ctx, tag: str):
        nonlocal found
        got = await _collect_pdp_urls_in(ctx)
        # normaliza e agrega
        buf = []
        for h in got:
            nh = _normalize_href(h)
            if PDP_URL_RE.search(nh) and nh not in found and nh not in buf:
                buf.append(nh)
        if buf:
            log.info("  + %s -> %d URLs", tag, len(buf))
            found.extend(buf)

    # 1) no documento principal
    await add_from_ctx(page, "document")

    # 2) shadow/atributos/anchors varridos pelo JS (já incluso no passo 1)
    # 3) frames (se existirem)
    if USE_FRAME_SCAN:
        for fr in page.frames:
            if fr == page.main_frame: continue
            try:
                await add_from_ctx(fr, f"frame:{fr.url}")
            except Exception:
                continue

    await _load_more(page)
    await _auto_scroll(page)

    # 4) se ainda insuficiente, fallback por clique (no main e em frames)
    if USE_CLICK_FALLBACK and len(found) < limit:
        extra = await _discover_by_click_in(page, limit - len(found))
        if extra:
            log.info("  + click(main) -> %d URLs", len(extra))
            found.extend(extra)

    if USE_CLICK_FALLBACK and len(found) < limit:
        for fr in page.frames:
            if len(found) >= limit: break
            if fr == page.main_frame: continue
            try:
                extra = await _discover_by_click_in(fr, limit - len(found))
                if extra:
                    log.info("  + click(frame) -> %d URLs", len(extra))
                    found.extend(extra)
            except Exception:
                continue

    log.info("Links detectados — total:%d", len(found))
    return found[:limit]

# ------------------ PDP -> nome + tamanhos ------------------

async def parse_pdp(page: Page) -> Tuple[str, Dict[str, str]]:
    """Extrai (nome, {tamanho: status}) — família única (letras OU pares 32–52),
       'Poucas' somente com quadrado vermelho no próprio botão; 'Esgotado' por disabled/risco."""
    # 1) Nome
    name = ""
    for sel in ["h1", 'meta[property="og:title"]', "title"]:
        try:
            loc = page.locator(sel)
            if await loc.count() > 0:
                v = await (loc.first.get_attribute("content") if sel.startswith("meta") else loc.first.inner_text())
                if v and v.strip(): name = v.strip(); break
        except Exception:
            pass
    if not name: name = "Produto H&M"

    # 2) JS no contexto da página: coleta botões, determina status, separa por família
    js = r"""
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

  function hasRedSquare(el){
    // Procura por quadrado vermelho no botão (indicador de poucas unidades)
    // Pode ser um elemento filho pequeno ou pseudo-elemento
    const rect = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    
    // Verifica pseudo-elementos ::before e ::after
    try {
      const aft = window.getComputedStyle(el, '::after');
      const bef = window.getComputedStyle(el, '::before');
      if (isRed(aft.backgroundColor) || isRed(aft.borderColor)) return true;
      if (isRed(bef.backgroundColor) || isRed(bef.borderColor)) return true;
    } catch(e) {}
    
    // Verifica elementos filhos pequenos (quadrados/indicadores)
    for (const child of el.querySelectorAll('*')) {
      const childRect = child.getBoundingClientRect();
      const childStyle = getComputedStyle(child);
      
      // Quadrado pequeno (até 20x20px) dentro do botão, preferencialmente no canto superior direito
      const isSmall = childRect.width <= 20 && childRect.height <= 20;
      const isInside = childRect.left >= rect.left && childRect.right <= rect.right &&
                       childRect.top >= rect.top && childRect.bottom <= rect.bottom;
      const isNearTopRight = (childRect.left >= rect.left + rect.width * 0.5) &&
                             (childRect.top <= rect.top + rect.height * 0.5);
      
      if (isSmall && isInside && (isNearTopRight || true)) { // aceita em qualquer posição dentro
        const bg = childStyle.backgroundColor;
        const border = childStyle.borderColor;
        const color = childStyle.color;
        if (isRed(bg) || isRed(border) || isRed(color)) {
          return true;
        }
      }
    }
    
    // Verifica se o próprio elemento tem fundo/borda vermelha (mas não completamente vermelho)
    if (isRed(cs.borderColor) && cs.borderWidth && parseFloat(cs.borderWidth) > 0) {
      return true;
    }
    
    return false;
  }

  function hasLineThrough(el){
    // Detecta risco/texto riscado (indicador de esgotado)
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

    // Esgotado: botão desabilitado OU tem risco/texto riscado
    const disabled = !!el.disabled || el.getAttribute("aria-disabled") === "true" || 
                     getComputedStyle(el).pointerEvents === "none" ||
                     getComputedStyle(el).opacity === "0.5" || 
                     getComputedStyle(el).cursor === "not-allowed";
    const meta = ((el.className||"") + " " + (el.getAttribute("aria-label")||"") + " " + (el.getAttribute("title")||"")).toLowerCase();
    const sold = disabled || hasLineThrough(el) || /(soldout|sold-out|out-of-stock|unavailable|esgotad)/.test(meta);
    
    // Poucas unidades: botão funciona mas tem quadrado vermelho
    const low  = !sold && hasRedSquare(el);

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
    try:
        data = await page.evaluate(js)
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
    all_sizes: List[str] = []
    for _, mp in items:
        all_sizes.extend(list(mp.keys()))
    all_sizes = [s for s in set(all_sizes)
                 if (s.isalpha() and s in LETTER_SIZES) or (s.isdigit() and s in NUMERIC_ALLOWED)]
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
    log.info("Abrindo categoria: %s", CATEGORY_URL)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 1400},
            locale="pt-BR"
        )
        ctx.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        ctx.set_default_timeout(STEP_TIMEOUT_MS)

        page = await ctx.new_page()

        try:
            await page.goto(CATEGORY_URL, wait_until="domcontentloaded")
        except PWTimeout:
            log.warning("Timeout no goto da categoria; seguindo.")

        await page.wait_for_timeout(1500)
        await _maybe_accept_cookies(page)
        await _close_overlays(page)

        log.info("Fazendo scroll e coletando produtos (limite=%d)...", PRODUCT_LIMIT)
        pdp_urls = await discover_pdp_urls(page, PRODUCT_LIMIT)
        log.info("Total de PDPs detectadas: %d", len(pdp_urls))
        for i, u in enumerate(pdp_urls, 1):
            log.info("  [%d] %s", i, u)

        if not pdp_urls:
            await page.screenshot(path="DEBUG_category.png", full_page=True)
            html = await page.content()
            with open("DEBUG_category.html", "w", encoding="utf-8") as f:
                f.write(html)
            log.error("Nenhum produto encontrado. Salvei DEBUG_category.(html/png).")
            await ctx.close(); await browser.close()
            return

        items: List[Tuple[str, Dict[str, str]]] = []
        for i, url in enumerate(pdp_urls[:PRODUCT_LIMIT], 1):
            log.info("[%d/%d] Abrindo PDP…", i, min(PRODUCT_LIMIT, len(pdp_urls)))
            try:
                await page.goto(url, wait_until="domcontentloaded")
            except PWTimeout:
                log.warning("Timeout no goto do PDP; continuando.")
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            await page.wait_for_timeout(1200)
            await _maybe_accept_cookies(page)
            await _close_overlays(page)

            name, sizes = await parse_pdp(page)
            log.info(" → %s | tamanhos: %s", name, ", ".join(f"{k}:{v}" for k,v in sorted(sizes.items())))
            items.append((name, sizes))

        await ctx.close(); await browser.close()

    log.info("Gerando Excel: %s", OUTPUT_XLSX)
    df = build_excel(items)
    df.to_excel(OUTPUT_XLSX, index=False)
    log.info("Concluído. Linhas no Excel: %d", len(df))

if __name__ == "__main__":
    asyncio.run(main())
