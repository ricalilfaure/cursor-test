# hm_br_sizes_to_excel.py  (v4.8 – PDP discovery com shadow DOM + iframes + clique; tamanhos por botão)
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

# Cache para ordenação de tamanhos
_LETTER_SIZES_DICT = {size: idx for idx, size in enumerate(LETTER_SIZES)}

def _order_sizes(all_sizes: List[str]) -> List[str]:
    letters = []
    nums = []
    other = []
    seen = set()
    for s in all_sizes:
        if s in seen:
            continue
        seen.add(s)
        if s.isalpha():
            letters.append(s)
        elif s.isdigit():
            nums.append(s)
        else:
            other.append(s)
    ordered_letters = sorted(letters, key=lambda x: (_LETTER_SIZES_DICT.get(x, 999), x))
    ordered_nums = sorted(nums, key=int)
    ordered_other = sorted(other)
    return ordered_letters + ordered_nums + ordered_other

def _normalize_href(href: str) -> str:
    if not href:
        return href
    if href.startswith("/"):
        return HM_BASE + href
    if href.startswith("http"):
        return href
    return f"{HM_BASE.rstrip('/')}/{href.lstrip('/')}"

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

_COOKIE_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "button#onetrust-accept-btn-handler",
    "button:has-text('Aceitar todos')",
    "button:has-text('Aceitar')",
    "button:has-text('Accept all')",
    "button:has-text('Accept')",
]

async def _maybe_accept_cookies(page: Page):
    for sel in _COOKIE_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=500):
                await btn.click()
                log.info("Cookie banner aceito (%s).", sel)
                await page.wait_for_timeout(400)
                return
        except Exception:
            continue

_OVERLAY_SELECTORS = [
    "button[aria-label='Fechar']",
    "button:has-text('Fechar')",
    "button:has-text('Close')",
    "[data-testid='modal-close']",
    "button[aria-label*='close' i]",
]

async def _close_overlays(page: Page):
    for sel in _OVERLAY_SELECTORS:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=300):
                await el.click()
                log.info("Overlay fechado (%s).", sel)
                await page.wait_for_timeout(250)
        except Exception:
            continue

# ------------------ auto-scroll / load more ------------------

async def _auto_scroll(page: Page, max_rounds: int = 60, pause_ms: int = 900):
    prev_h = 0
    stable = 0
    scroll_js = "document.documentElement.scrollHeight"
    for i in range(max_rounds):
        cur_h = await page.evaluate(scroll_js)
        if cur_h <= prev_h:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
        await page.mouse.wheel(0, 2400)
        await page.wait_for_timeout(pause_ms)
        prev_h = cur_h
    log.info("Auto-scroll finalizado (altura=%s, iterações=%s).", prev_h, i + 1)

_LOAD_MORE_SELECTOR = (
    'button:has-text("Carregar mais"), '
    'button:has-text("Mais produtos"), '
    'button:has-text("Load more"), '
    'button:has-text("Ver mais"), '
    'button:has-text("Mostrar mais")'
)

async def _load_more(page: Page, max_clicks: int = 8):
    for _ in range(max_clicks):
        try:
            btn = page.locator(_LOAD_MORE_SELECTOR).first
            if await btn.is_visible(timeout=500):
                await btn.click()
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
        if not urls:
            return []
        # normaliza e filtra usando set para deduplicação rápida
        seen = set()
        uniq = []
        for u in urls:
            if not u or u in seen:
                continue
            if PDP_URL_RE.search(u):
                seen.add(u)
                uniq.append(u)
        return uniq
    except Exception:
        return []

_CLICK_SELECTORS = ["a", "button", "img", "*"]
_PRODUCT_CANDIDATE_SELECTOR = (
    '[data-testid*="product"], [class*="product-card"], [class*="ProductCard"], ' +
    'article, li, a[role], div[role="link"]'
)

async def _discover_by_click_in(page_or_frame, limit: int) -> List[str]:
    urls: List[str] = []
    seen_urls = set()
    candidates = page_or_frame.locator(_PRODUCT_CANDIDATE_SELECTOR)
    count = await candidates.count()
    max_iter = min(count, limit * 4)
    
    for i in range(max_iter):
        if len(urls) >= limit:
            break
        el = candidates.nth(i)
        try:
            await el.scroll_into_view_if_needed()
            clicked = False
            for sel in _CLICK_SELECTORS:
                try:
                    target = el.locator(sel).first if sel != "*" else el
                    await target.click(timeout=3000, force=True)
                    clicked = True
                    break
                except Exception:
                    continue
            if not clicked:
                continue

            # espera SPA mudar para PDP
            try:
                await page_or_frame.page.wait_for_url(PDP_URL_RE, timeout=8000)
            except Exception:
                continue

            u = page_or_frame.page.url
            if PDP_URL_RE.search(u) and u not in seen_urls:
                seen_urls.add(u)
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
    seen = set()

    async def add_from_ctx(ctx, tag: str):
        nonlocal found, seen
        got = await _collect_pdp_urls_in(ctx)
        if not got:
            return
        # normaliza e agrega
        buf = []
        for h in got:
            nh = _normalize_href(h)
            if nh not in seen and PDP_URL_RE.search(nh):
                seen.add(nh)
                buf.append(nh)
        if buf:
            log.info("  + %s -> %d URLs", tag, len(buf))
            found.extend(buf)

    # 1) no documento principal
    await add_from_ctx(page, "document")

    # 2) shadow/atributos/anchors varridos pelo JS (já incluso no passo 1)
    # 3) frames (se existirem)
    if USE_FRAME_SCAN:
        frames = [fr for fr in page.frames if fr != page.main_frame]
        for fr in frames:
            if len(found) >= limit:
                break
            try:
                await add_from_ctx(fr, f"frame:{fr.url}")
            except Exception:
                continue

    if len(found) < limit:
        await _load_more(page)
        await _auto_scroll(page)

    # 4) se ainda insuficiente, fallback por clique (no main e em frames)
    if USE_CLICK_FALLBACK and len(found) < limit:
        extra = await _discover_by_click_in(page, limit - len(found))
        if extra:
            log.info("  + click(main) -> %d URLs", len(extra))
            found.extend(extra)

    if USE_CLICK_FALLBACK and len(found) < limit:
        frames = [fr for fr in page.frames if fr != page.main_frame]
        for fr in frames:
            if len(found) >= limit:
                break
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

_NAME_SELECTORS = [
    ("h1", False),
    ('meta[property="og:title"]', True),
    ("title", False),
]

async def parse_pdp(page: Page) -> Tuple[str, Dict[str, str]]:
    """Extrai (nome, {tamanho: status}) — família única (letras OU pares 32–52),
       'Poucas' somente com quadrado vermelho no próprio botão; 'Esgotado' por disabled/risco."""
    # 1) Nome - cache de locators
    name = ""
    for sel, is_meta in _NAME_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                v = await (loc.get_attribute("content") if is_meta else loc.inner_text())
                if v and (v := v.strip()):
                    name = v
                    break
        except Exception:
            continue
    if not name:
        name = "Produto H&M"

    # 2) JS no contexto da página: coleta botões, determina status, separa por família
    js = r"""
(() => {
  const LETTERS = new Set(["XXP","XP","PP","P","M","G","GG","XG","XXG","XXGG","XXGGG"]);
  const NUMERIC = new Set(["32","34","36","38","40","42","44","46","48","50","52"]);
  const SYN = { "XS":"XP", "S":"P", "L":"G", "XL":"XG", "XXL":"XXG" };
  const splitRe = /\s|–|-|·|\|/;
  const cleanRe = /[^A-Z0-9]/g;

  function clean(txt){
    if(!txt) return "";
    let t = txt.trim().toUpperCase();
    t = t.split(splitRe)[0];
    t = t.replace(cleanRe, "");
    if (SYN[t]) t = SYN[t];
    return t;
  }

  function isRed(c){
    if(!c) return false;
    const m = c.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*[\d.]+)?\)/i);
    if(!m) return false;
    const r = +m[1], g = +m[2], b = +m[3];
    // Vermelho: R alto, G e B baixos
    return (r >= 150 && g <= 110 && b <= 110);
  }

  function hasRedSquareIndicator(el){
    // Busca por elementos pequenos vermelhos (quadrados/indicadores) dentro ou sobrepostos ao botão
    const rect = el.getBoundingClientRect();
    const elCenterX = rect.left + rect.width / 2;
    const elCenterY = rect.top + rect.height / 2;
    const elStyle = getComputedStyle(el);
    
    // Verifica pseudo-elementos ::before e ::after
    try {
      const bef = getComputedStyle(el, '::before');
      const aft = getComputedStyle(el, '::after');
      
      // Verifica se há um elemento ::before ou ::after vermelho
      if (bef.content && bef.content !== 'none' && bef.content !== '""') {
        if (isRed(bef.backgroundColor) || isRed(bef.borderColor) || isRed(bef.color)) {
          return true;
        }
      }
      if (aft.content && aft.content !== 'none' && aft.content !== '""') {
        if (isRed(aft.backgroundColor) || isRed(aft.borderColor) || isRed(aft.color)) {
          return true;
        }
      }
    } catch(e) {}

    // Verifica também o próprio elemento se tiver borda vermelha (cache de elStyle)
    if (isRed(elStyle.borderColor) || isRed(elStyle.borderTopColor) || 
        isRed(elStyle.borderRightColor) || isRed(elStyle.borderBottomColor) || 
        isRed(elStyle.borderLeftColor)) {
      return true;
    }

    // Busca elementos filhos pequenos que possam ser indicadores vermelhos
    // Especialmente no canto superior direito ou centralizado
    const children = el.querySelectorAll('*');
    const bgImgRe = /rgb\(255,\s*0,\s*0\)|rgba\(255,\s*0,\s*0|#ff0000|#f00/i;
    const halfWidth = rect.width * 0.5;
    const halfHeight = rect.height * 0.5;
    
    for (let i = 0; i < children.length; i++) {
      const child = children[i];
      const childRect = child.getBoundingClientRect();
      
      // Verifica se é um elemento pequeno (quadrado/indicador)
      if (childRect.width > 20 || childRect.height > 20) continue;
      
      // Verifica posicionamento otimizado
      const isTopRight = (childRect.left >= rect.left + halfWidth) && 
                         (childRect.top <= rect.top + halfHeight);
      const childCenterX = childRect.left + childRect.width / 2;
      const childCenterY = childRect.top + childRect.height / 2;
      const isCentered = Math.abs(childCenterX - elCenterX) < 5 &&
                         Math.abs(childCenterY - elCenterY) < 5;
      
      if (isTopRight || isCentered) {
        const cs = getComputedStyle(child);
        // Verifica se tem cor vermelha
        if (isRed(cs.backgroundColor) || isRed(cs.borderColor) || isRed(cs.color)) {
          return true;
        }
        
        // Verifica se tem background-image com vermelho
        const bgImg = cs.backgroundImage;
        if (bgImg && bgImg !== 'none' && bgImgRe.test(bgImg)) {
          return true;
        }
      }
    }
    
    return false;
  }

  function hasLineThrough(el){
    // Verifica se o elemento ou seus filhos têm texto riscado
    const check = (n) => {
      const cs = getComputedStyle(n);
      const td = (cs.textDecorationLine || cs.textDecoration || "").toLowerCase();
      if (td.includes("line-through")) return true;
      
      const cl = (n.className || "").toLowerCase();
      if (cl.includes("strike") || cl.includes("line-through") || cl.includes("cross") || 
          cl.includes("soldout") || cl.includes("unavailable")) return true;
      
      // Verifica elementos semânticos de riscado (cache da query)
      if (n.querySelector("s, del, strike")) return true;
      
      return false;
    };
    
    if (check(el)) return true;
    
    // Verifica filhos recursivamente (otimizado: para na primeira ocorrência)
    const children = el.querySelectorAll("*");
    for (let i = 0; i < children.length; i++) {
      if (check(children[i])) return true;
    }
    
    return false;
  }

  // Tenta achar o container de tamanhos mais "rico"
  const sizeContainerSel = '[id*="size" i], [class*="size" i], [data-test*="size" i], section, fieldset, div';
  const sizeTextRe = /escolha o tamanho|tamanho|size|selecione/i;
  const allContainers = document.querySelectorAll(sizeContainerSel);
  const containers = Array.from(allContainers).filter(el => {
    return sizeTextRe.test((el.textContent || "").toLowerCase());
  });

  const sizeNodeSel = 'button, label, [role="option"], [role="radio"], input[type="radio"]+label, ' +
                      '[data-size], [data-testid*="size" i], li, a, span, div';
  
  let scope = document;
  let best = -1;
  const candidates = containers.length ? containers : [document];
  for (let i = 0; i < candidates.length; i++) {
    const el = candidates[i];
    const count = el.querySelectorAll(sizeNodeSel).length;
    if (count > best) { best = count; scope = el; }
  }

  const nodes = scope.querySelectorAll(sizeNodeSel);

  const L = [];
  const N = [];
  const rank = s => s==='Esgotado' ? 2 : (s==='Poucas unidades' ? 1 : 0);

  const soldoutRe = /(soldout|sold-out|out-of-stock|unavailable|esgotad|indispon|não disponível)/;
  
  for (let i = 0; i < nodes.length; i++) {
    const el = nodes[i];
    const textContent = el.textContent || "";
    const dataSize = el.getAttribute("data-size") || "";
    const dataSkuSize = el.getAttribute("data-sku-size") || "";
    const ariaLabel = el.getAttribute("aria-label") || "";
    const title = el.getAttribute("title") || "";
    
    const cand = [
      clean(textContent),
      clean(dataSize),
      clean(dataSkuSize),
      clean(ariaLabel),
      clean(title)
    ].filter(Boolean);

    let label = "";
    for (let j = 0; j < cand.length; j++) {
      const t = cand[j];
      if (LETTERS.has(t) || NUMERIC.has(t)) { label = t; break; }
    }
    if (!label) continue;

    // Cache de computed style
    const cs = getComputedStyle(el);
    
    // Verifica se está desabilitado
    const disabled = !!el.disabled || 
                     el.getAttribute("aria-disabled") === "true" || 
                     cs.pointerEvents === "none" ||
                     cs.opacity === "0.5" ||
                     el.classList.contains("disabled") ||
                     el.hasAttribute("disabled");

    // Verifica metadados para esgotado (concatenação otimizada)
    const className = el.className || "";
    const dataStatus = el.getAttribute("data-status") || "";
    const meta = `${className} ${ariaLabel} ${title} ${dataStatus}`.toLowerCase();
    const sold = disabled || 
                 hasLineThrough(el) || 
                 soldoutRe.test(meta);

    // Verifica indicador vermelho (quadrado) para baixa disponibilidade
    // Só marca como "Poucas unidades" se NÃO estiver esgotado E tiver indicador vermelho
    const low = !sold && hasRedSquareIndicator(el);

    const status = sold ? "Esgotado" : (low ? "Poucas unidades" : "Disponível");

    if (LETTERS.has(label)) L.push({label, status});
    else                    N.push({label, status});
  }

  // Escolhe UMA família: a que tiver mais opções
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
    except Exception as e:
        log.warning("Erro ao avaliar JS de parsing: %s", e)
        data = {}

    sizes_map: Dict[str, str] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if (k.isalpha() and k in LETTER_SIZES) or (k.isdigit() and k in NUMERIC_ALLOWED):
                sizes_map[k] = v

    return name, sizes_map

# ------------------ Excel ------------------

def build_excel(items: List[Tuple[str, Dict[str, str]]]) -> pd.DataFrame:
    if not items:
        return pd.DataFrame(columns=["Nome do Produto"])
    
    # Coleta tamanhos únicos de forma otimizada
    all_sizes_set = set()
    for _, mp in items:
        all_sizes_set.update(mp.keys())
    
    # Filtra tamanhos válidos
    all_sizes = [
        s for s in all_sizes_set
        if (s.isalpha() and s in LETTER_SIZES) or (s.isdigit() and s in NUMERIC_ALLOWED)
    ]
    size_cols = _order_sizes(all_sizes)

    # Constrói rows de forma otimizada
    rows = []
    columns = ["Nome do Produto"] + size_cols
    for name, mp in items:
        row = {"Nome do Produto": name}
        # Usa dict comprehension para melhor performance
        row.update({s: mp.get(s, LABEL_HYPHEN) for s in size_cols})
        rows.append(row)
    
    return pd.DataFrame(rows, columns=columns)

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
        limit = min(PRODUCT_LIMIT, len(pdp_urls))
        for i, url in enumerate(pdp_urls[:limit], 1):
            log.info("[%d/%d] Abrindo PDP…", i, limit)
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
            if sizes:
                sizes_str = ", ".join(f"{k}:{v}" for k, v in sorted(sizes.items()))
                log.info(" → %s | tamanhos: %s", name, sizes_str)
            else:
                log.info(" → %s | nenhum tamanho detectado", name)
            items.append((name, sizes))

        await ctx.close(); await browser.close()

    log.info("Gerando Excel: %s", OUTPUT_XLSX)
    df = build_excel(items)
    df.to_excel(OUTPUT_XLSX, index=False)
    log.info("Concluído. Linhas no Excel: %d", len(df))

if __name__ == "__main__":
    asyncio.run(main())
