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
    # Otimização: usar sets para classificação mais rápida
    size_set = set(all_sizes)
    letters = [s for s in all_sizes if s.isalpha()]
    nums    = [s for s in all_sizes if s.isdigit()]
    other   = [s for s in size_set if s not in letters and s not in nums]
    # Cache do índice para evitar múltiplas buscas
    letter_index_map = {s: i for i, s in enumerate(LETTER_SIZES)}
    ordered_letters = sorted(letters, key=lambda x: (letter_index_map.get(x, 999), x))
    ordered_nums    = sorted(nums, key=int)
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
    # CORREÇÃO: Guardar URL antes de clicar para verificar se mudou
    url_before = page.url
    # Otimização: verificar visibilidade antes de count (mais rápido)
    for sel in [
        "#onetrust-accept-btn-handler",
        "button#onetrust-accept-btn-handler",
        "button:has-text('Aceitar todos')",
        "button:has-text('Aceitar')",
        "button:has-text('Accept all')",
        "button:has-text('Accept')",
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=500):
                await btn.click()
                log.info("Cookie banner aceito (%s).", sel)
                await page.wait_for_timeout(300)
                # CORREÇÃO: Verificar se o clique causou navegação indesejada
                url_after = page.url
                if url_before != url_after and not PDP_URL_RE.search(url_after):
                    category_base = CATEGORY_URL.split('?')[0]
                    if category_base not in url_after:
                        log.warning("Cookie click causou navegação indesejada. Voltando: %s", url_after)
                        await robust_goto(page, CATEGORY_URL)
                break
        except Exception:
            pass

async def _close_overlays(page: Page):
    # CORREÇÃO: Guardar URL antes de clicar para verificar se mudou
    url_before = page.url
    # Otimização: verificar visibilidade antes de count
    for sel in [
        "button[aria-label='Fechar']",
        "button:has-text('Fechar')",
        "button:has-text('Close')",
        "[data-testid='modal-close']",
        "button[aria-label*='close' i]",
    ]:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=300):
                await el.click()
                log.info("Overlay fechado (%s).", sel)
                await page.wait_for_timeout(200)
                # CORREÇÃO: Verificar se o clique causou navegação indesejada
                url_after = page.url
                if url_before != url_after and not PDP_URL_RE.search(url_after):
                    category_base = CATEGORY_URL.split('?')[0]
                    if category_base not in url_after:
                        log.warning("Overlay click causou navegação indesejada. Voltando: %s", url_after)
                        await robust_goto(page, CATEGORY_URL)
                break
        except Exception:
            pass

# ------------------ auto-scroll / load more ------------------

async def _auto_scroll(page: Page, max_rounds: int = 60, pause_ms: int = 700):
    # Otimização: reduzir pause_ms e usar evaluate_once para scrollHeight
    prev_h = 0
    stable = 0
    scroll_script = "document.documentElement.scrollHeight"
    for i in range(max_rounds):
        cur_h = await page.evaluate(scroll_script)
        if cur_h <= prev_h: 
            stable += 1
            if stable >= 3: break
        else: 
            stable = 0
        await page.mouse.wheel(0, 2400)
        await page.wait_for_timeout(pause_ms)
        prev_h = cur_h
    log.info("Auto-scroll finalizado (altura=%s, iterações=%s).", prev_h, i + 1)

async def _load_more(page: Page, max_clicks: int = 8):
    # CORREÇÃO: Guardar URL base para verificar navegação
    category_base = CATEGORY_URL.split('?')[0]
    # Otimização: verificar visibilidade primeiro (mais rápido que count)
    btn_selector = (
        'button:has-text("Carregar mais"), '
        'button:has-text("Mais produtos"), '
        'button:has-text("Load more"), '
        'button:has-text("Ver mais"), '
        'button:has-text("Mostrar mais")'
    )
    for _ in range(max_clicks):
        # CORREÇÃO: Verificar URL antes de cada clique
        current_url = page.url
        if category_base not in current_url and not PDP_URL_RE.search(current_url):
            log.warning("URL incorreta durante load_more. Parando: %s", current_url)
            break
        try:
            btn = page.locator(btn_selector).first
            if await btn.is_visible(timeout=1000):
                await btn.click()
                log.info("Clicado em 'Carregar mais'.")
                await page.wait_for_timeout(1500)
                # CORREÇÃO: Verificar URL após clique
                new_url = page.url
                if category_base not in new_url and not PDP_URL_RE.search(new_url):
                    log.warning("Navegação indesejada após load_more. Parando: %s", new_url)
                    break
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
  // CORREÇÃO: Filtrar links de navegação
  const NAV_EXCLUDE = /(\/homem|\/casa|\/masculino)(\/|$)/i;

  const extractFromRoot = (root) => {
    try {
      // anchors
      root.querySelectorAll('a[href]').forEach(a => {
        const h = a.getAttribute('href') || '';
        const abs = a.href || '';
        // CORREÇÃO: Filtrar links de navegação antes de adicionar
        if (PDP.test(h) && !NAV_EXCLUDE.test(h)) out.add(h);
        else if (PDP.test(abs) && !NAV_EXCLUDE.test(abs)) out.add(abs);
      });

      // atributos
      root.querySelectorAll('[data-href],[data-url],[data-product-url],[data-link],[onclick]').forEach(el => {
        const attrs = ['data-href','data-url','data-product-url','data-link','onclick'];
        for (const k of attrs) {
          const v = el.getAttribute(k);
          if (!v) continue;
          const str = String(v);
          const m = str.match(/['"]((?:https?:)?\/?[^'"]*\/(?:p|produto|product)\/[^'"]+)['"]/i);
          if (m && m[1] && !NAV_EXCLUDE.test(m[1])) { out.add(m[1]); continue; }
          if (PDP.test(str) && !NAV_EXCLUDE.test(str)) out.add(str);
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
            // CORREÇÃO: Filtrar links de navegação
            if (PDP.test(u) && !NAV_EXCLUDE.test(u)) out.add(u);
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
        # Otimização: usar set para deduplicação mais eficiente
        seen = set()
        uniq = []
        for u in urls:
            if not u or u in seen: continue
            if not PDP_URL_RE.search(u): continue
            seen.add(u)
            uniq.append(u)
        return uniq
    except Exception:
        return []

async def _discover_by_click_in(page_or_frame, limit: int) -> List[str]:
    # Otimização: usar set para URLs e reduzir verificações
    urls: List[str] = []
    seen_urls = set()
    
    # CORREÇÃO: Seletores mais específicos para evitar cliques em links de navegação
    # Excluir explicitamente links de navegação (homem, casa, etc.)
    candidates = page_or_frame.locator(
        '[data-testid*="product"]:not([href*="/homem"]):not([href*="/casa"]):not([href*="/masculino"]), '
        '[class*="product-card"]:not([href*="/homem"]):not([href*="/casa"]):not([href*="/masculino"]), '
        '[class*="ProductCard"]:not([href*="/homem"]):not([href*="/casa"]):not([href*="/masculino"])'
    )
    count = await candidates.count()
    max_iter = min(count, limit * 4)
    
    # CORREÇÃO: Guardar URL inicial para verificar se ainda estamos na página correta
    initial_url = page_or_frame.page.url
    
    for i in range(max_iter):
        if len(urls) >= limit: break
        
        # CORREÇÃO: Verificar se ainda estamos na URL correta antes de continuar
        current_url = page_or_frame.page.url
        if not CATEGORY_URL.split('?')[0] in current_url and not PDP_URL_RE.search(current_url):
            log.warning("Navegação inesperada detectada. Voltando para categoria: %s", current_url)
            try:
                await robust_goto(page_or_frame.page, CATEGORY_URL)
                await page_or_frame.page.wait_for_timeout(1000)
                await _maybe_accept_cookies(page_or_frame.page)
                await _close_overlays(page_or_frame.page)
            except Exception:
                pass
        
        el = candidates.nth(i)
        try:
            # CORREÇÃO: Verificar se o elemento contém link de produto antes de clicar
            href = None
            try:
                link_el = el.locator('a[href]').first
                if await link_el.count() > 0:
                    href = await link_el.get_attribute('href')
                    # Filtrar links de navegação
                    if href and ('/homem' in href or '/casa' in href or '/masculino' in href or 
                                 '/feminino/vestuario' not in href and not PDP_URL_RE.search(href)):
                        continue
            except Exception:
                pass
            
            await el.scroll_into_view_if_needed()
            clicked = False
            # Otimização: tentar cliques mais específicos primeiro
            for sel in ["a[href*='/p/'], a[href*='/produto/'], a[href*='/product/'], a", "button", "img", "*"]:
                try:
                    target = el.locator(sel).first if sel != "*" else el
                    if await target.is_visible(timeout=500):
                        await target.click(timeout=2000, force=True)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked: continue

            # espera SPA mudar para PDP
            try:
                await page_or_frame.page.wait_for_url(PDP_URL_RE, timeout=6000)
            except Exception:
                # CORREÇÃO: Se não mudou para PDP, voltar para categoria
                if not PDP_URL_RE.search(page_or_frame.page.url):
                    try:
                        await robust_goto(page_or_frame.page, CATEGORY_URL)
                        await page_or_frame.page.wait_for_timeout(1000)
                        await _maybe_accept_cookies(page_or_frame.page)
                        await _close_overlays(page_or_frame.page)
                    except Exception:
                        pass
                continue

            u = page_or_frame.page.url
            if PDP_URL_RE.search(u) and u not in seen_urls:
                seen_urls.add(u)
                urls.append(u)

            # volta para a categoria
            try:
                await page_or_frame.page.go_back(wait_until="domcontentloaded", timeout=12000)
                # CORREÇÃO: Verificar se voltou para a categoria correta
                await page_or_frame.page.wait_for_timeout(1000)
                final_url = page_or_frame.page.url
                if not CATEGORY_URL.split('?')[0] in final_url:
                    log.warning("Não voltou para categoria correta após go_back. Recarregando...")
                    await robust_goto(page_or_frame.page, CATEGORY_URL)
                    await _maybe_accept_cookies(page_or_frame.page)
                    await _close_overlays(page_or_frame.page)
            except Exception:
                # recarrega categoria se necessário
                await robust_goto(page_or_frame.page, CATEGORY_URL)
                await _maybe_accept_cookies(page_or_frame.page)
                await _close_overlays(page_or_frame.page)
        except Exception:
            continue
    return urls

async def discover_pdp_urls(page: Page, limit: int) -> List[str]:
    # Otimização: usar set para deduplicação mais eficiente
    found: List[str] = []
    seen = set()
    
    # CORREÇÃO: Guardar URL da categoria para verificar se ainda estamos nela
    category_base = CATEGORY_URL.split('?')[0]

    async def add_from_ctx(ctx, tag: str):
        nonlocal found, seen
        got = await _collect_pdp_urls_in(ctx)
        # CORREÇÃO: Filtrar URLs que não são da categoria correta
        buf = []
        for h in got:
            nh = _normalize_href(h)
            # Filtrar links de navegação (homem, casa, etc.)
            if '/homem' in nh or '/casa' in nh or '/masculino' in nh:
                continue
            if PDP_URL_RE.search(nh) and nh not in seen:
                seen.add(nh)
                buf.append(nh)
        if buf:
            log.info("  + %s -> %d URLs", tag, len(buf))
            found.extend(buf)

    # CORREÇÃO: Verificar se estamos na URL correta antes de começar
    current_url = page.url
    if category_base not in current_url:
        log.warning("URL atual não corresponde à categoria. Recarregando: %s", current_url)
        await robust_goto(page, CATEGORY_URL)
        await page.wait_for_timeout(1000)
        await _maybe_accept_cookies(page)
        await _close_overlays(page)

    # 1) no documento principal
    await add_from_ctx(page, "document")

    # 2) shadow/atributos/anchors varridos pelo JS (já incluso no passo 1)
    # 3) frames (se existirem)
    if USE_FRAME_SCAN:
        frames = [fr for fr in page.frames if fr != page.main_frame]
        for fr in frames:
            try:
                await add_from_ctx(fr, f"frame:{fr.url}")
            except Exception:
                continue

    # CORREÇÃO: Verificar URL após scroll e load_more
    await _load_more(page)
    current_url = page.url
    if category_base not in current_url and not PDP_URL_RE.search(current_url):
        log.warning("Navegação inesperada após load_more. Voltando para categoria.")
        await robust_goto(page, CATEGORY_URL)
        await page.wait_for_timeout(1000)
        await _maybe_accept_cookies(page)
        await _close_overlays(page)
    
    await _auto_scroll(page)
    current_url = page.url
    if category_base not in current_url and not PDP_URL_RE.search(current_url):
        log.warning("Navegação inesperada após scroll. Voltando para categoria.")
        await robust_goto(page, CATEGORY_URL)
        await page.wait_for_timeout(1000)
        await _maybe_accept_cookies(page)
        await _close_overlays(page)

    # 4) se ainda insuficiente, fallback por clique (no main e em frames)
    if USE_CLICK_FALLBACK and len(found) < limit:
        # CORREÇÃO: Verificar URL antes de cliques
        current_url = page.url
        if category_base not in current_url:
            log.warning("URL incorreta antes de cliques. Recarregando categoria.")
            await robust_goto(page, CATEGORY_URL)
            await page.wait_for_timeout(1000)
            await _maybe_accept_cookies(page)
            await _close_overlays(page)
        
        extra = await _discover_by_click_in(page, limit - len(found))
        if extra:
            log.info("  + click(main) -> %d URLs", len(extra))
            found.extend(extra)

    if USE_CLICK_FALLBACK and len(found) < limit:
        frames = [fr for fr in page.frames if fr != page.main_frame]
        for fr in frames:
            if len(found) >= limit: break
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
    # 1) Nome - Otimização: verificar visibilidade antes de count
    name = ""
    for sel in ["h1", 'meta[property="og:title"]', "title"]:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=500) or sel.startswith("meta"):
                v = await (loc.get_attribute("content") if sel.startswith("meta") else loc.inner_text())
                if v and v.strip(): 
                    name = v.strip()
                    break
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
    // Otimização: verificar primeiro o elemento, depois filhos apenas se necessário
    const check = (n) => {
      const cs = getComputedStyle(n);
      const td = (cs.textDecorationLine || cs.textDecoration || "").toLowerCase();
      if (td.includes("line-through")) return true;
      const cl = (n.className || "").toLowerCase();
      if (cl.includes("strike") || cl.includes("line-through") || cl.includes("cross")) return true;
      // Otimização: verificar apenas uma vez se há elementos s, del, strike
      if (n.querySelector("s, del, strike")) return true;
      return false;
    };
    if (check(el)) return true;
    // Otimização: limitar busca em filhos (evitar verificar todos os descendentes)
    const children = el.querySelectorAll("s, del, strike, [class*='strike'], [class*='line-through']");
    if (children.length > 0) return true;
    // Verificar apenas filhos diretos para performance
    for (const k of el.children) if (check(k)) return true;
    return false;
  }

  // Otimização: tenta achar o container de tamanhos mais "rico" de forma mais eficiente
  const sizeSelector = '[id*="size" i], [class*="size" i], [data-test*="size" i]';
  const containers = Array.from(document.querySelectorAll(sizeSelector))
    .filter(el => {
      const txt = el.textContent || "";
      return /ESCOLHA O TAMANHO|TAMANHO|SIZE/i.test(txt);
    });

  let scope = document;
  let best = -1;
  const sizeButtonSelector = 'button, label, [role="option"], [role="radio"], input[type="radio"]+label, ' +
    '[data-size], [data-testid*="size" i]';
  
  // Otimização: verificar containers primeiro, depois document
  const candidates = containers.length ? containers : [document];
  for (const el of candidates) {
    const count = el.querySelectorAll(sizeButtonSelector).length;
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
    // Otimização: cachear getComputedStyle para evitar múltiplas chamadas
    const cs = getComputedStyle(el);
    const disabled = !!el.disabled || el.getAttribute("aria-disabled") === "true" || 
                     cs.pointerEvents === "none" ||
                     cs.opacity === "0.5" || 
                     cs.cursor === "not-allowed";
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
    # Otimização: usar set comprehension e evitar múltiplas iterações
    all_sizes_set = set()
    for _, mp in items:
        all_sizes_set.update(mp.keys())
    all_sizes = [s for s in all_sizes_set
                 if (s.isalpha() and s in LETTER_SIZES) or (s.isdigit() and s in NUMERIC_ALLOWED)]
    size_cols = _order_sizes(all_sizes)

    # Otimização: construir rows de forma mais eficiente
    rows = []
    for name, mp in items:
        row = {"Nome do Produto": name}
        row.update({s: mp.get(s, LABEL_HYPHEN) for s in size_cols})
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

        # CORREÇÃO: Verificar se realmente carregou a URL correta
        await page.wait_for_timeout(1000)
        current_url = page.url
        category_base = CATEGORY_URL.split('?')[0]
        if category_base not in current_url:
            log.warning("URL após goto não corresponde à categoria esperada. Tentando novamente...")
            log.warning("  Esperado: %s", category_base)
            log.warning("  Obtido: %s", current_url)
            try:
                await page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                await page.wait_for_timeout(1500)
            except Exception as e:
                log.error("Erro ao recarregar categoria: %s", e)
        
        await _maybe_accept_cookies(page)
        await _close_overlays(page)
        
        # CORREÇÃO: Verificar URL final após cookies/overlays
        final_url = page.url
        if category_base not in final_url:
            log.warning("URL mudou após cookies/overlays. Recarregando categoria: %s", final_url)
            await robust_goto(page, CATEGORY_URL)
            await page.wait_for_timeout(1000)
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
            # Otimização: usar domcontentloaded primeiro (mais rápido), depois networkidle se necessário
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
                await page.wait_for_load_state("networkidle", timeout=8000)  # Reduzido de 10s
            except Exception:
                pass
            await page.wait_for_timeout(800)  # Reduzido de 1200ms
            await _maybe_accept_cookies(page)
            await _close_overlays(page)

            name, sizes = await parse_pdp(page)
            # Otimização: formatar log apenas se houver tamanhos
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
