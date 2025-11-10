# hm_br_sizes_to_excel.py  (v4.9 – OTIMIZADO)
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
from typing import Dict, List, Tuple, Set

import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PWTimeout, Page

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

# Timeouts otimizados
NAV_TIMEOUT_MS  = 60_000  # Reduzido de 90s
STEP_TIMEOUT_MS = 30_000  # Reduzido de 45s

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
NUMERIC_ALLOWED = {str(n) for n in range(32, 54, 2)}

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("hm")

# Cache para URLs normalizadas
_url_cache: Dict[str, str] = {}

# ---------------------- utils (OTIMIZADOS) ----------------------

def _order_sizes(all_sizes: List[str]) -> List[str]:
    """Ordena tamanhos: letras -> números -> outros"""
    letters, nums, other = [], [], []
    for s in all_sizes:
        if s.isalpha(): letters.append(s)
        elif s.isdigit(): nums.append(s)
        else: other.append(s)
    
    letters.sort(key=lambda x: (LETTER_SIZES.index(x) if x in LETTER_SIZES else 999, x))
    nums.sort(key=int)
    other.sort()
    return letters + nums + other

def _normalize_href(href: str) -> str:
    """Normaliza href com cache"""
    if href in _url_cache:
        return _url_cache[href]
    
    if href.startswith("/"):
        result = HM_BASE + href
    elif not href.startswith("http"):
        result = f"{HM_BASE.rstrip('/')}/{href.lstrip('/')}"
    else:
        result = href
    
    _url_cache[href] = result
    return result

async def _handle_popups(page: Page):
    """Unificado: aceita cookies e fecha overlays em uma função"""
    # Cookies
    cookie_sels = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Aceitar')",
        "button:has-text('Accept')"
    ]
    for sel in cookie_sels:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1000):
                await btn.click(timeout=2000)
                log.info("Cookie aceito.")
                break
        except Exception:
            continue
    
    # Overlays
    overlay_sels = [
        "button[aria-label='Fechar']",
        "button:has-text('Fechar')",
        "[data-testid='modal-close']"
    ]
    for sel in overlay_sels:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1000):
                await btn.click(timeout=2000)
                log.info("Overlay fechado.")
                break
        except Exception:
            continue

# ------------------ PDP discovery (OTIMIZADO) ------------------

# JS otimizado - foca apenas em anchors e atributos data-* da H&M
DISCOVERY_JS = r"""
() => {
  const out = new Set();
  const PDP = /\/(p|produto|product)\//i;
  
  // 1. Anchors diretos (método mais comum na H&M)
  document.querySelectorAll('a[href]').forEach(a => {
    const h = a.getAttribute('href');
    if (h && PDP.test(h)) out.add(h);
  });
  
  // 2. Atributos data-* (usado em cards de produto)
  document.querySelectorAll('[data-href],[data-product-url],[data-url]').forEach(el => {
    ['data-href','data-product-url','data-url'].forEach(k => {
      const v = el.getAttribute(k);
      if (v && PDP.test(v)) out.add(v);
    });
  });
  
  // 3. JSON-LD (structured data)
  document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
    try {
      const data = JSON.parse(s.textContent || '');
      if (data.url && PDP.test(data.url)) out.add(data.url);
      if (Array.isArray(data)) {
        data.forEach(item => {
          if (item.url && PDP.test(item.url)) out.add(item.url);
        });
      }
    } catch(e){}
  });
  
  return Array.from(out);
}
"""

async def _smart_scroll(page: Page) -> None:
    """Auto-scroll inteligente: para quando não há mais mudanças"""
    prev_count = 0
    stable = 0
    max_rounds = 20  # Reduzido de 60
    
    for i in range(max_rounds):
        # Conta produtos ao invés de altura (mais confiável)
        count = await page.locator('article, [class*="product"], a[href*="/p/"]').count()
        
        if count == prev_count:
            stable += 1
            if stable >= 2:  # Para após 2 iterações sem mudança
                break
        else:
            stable = 0
        
        prev_count = count
        await page.mouse.wheel(0, 3000)
        await page.wait_for_timeout(600)  # Reduzido de 900ms
    
    log.info("Auto-scroll: %d produtos detectados em %d iterações", prev_count, i + 1)

async def _load_more_button(page: Page) -> None:
    """Clica em 'Carregar mais' se existir"""
    try:
        btn = page.locator('button:has-text("Carregar mais"), button:has-text("Load more")').first
        if await btn.is_visible(timeout=2000):
            await btn.click()
            log.info("'Carregar mais' clicado")
            await page.wait_for_timeout(1500)
    except Exception:
        pass

async def discover_pdp_urls(page: Page, limit: int) -> List[str]:
    """Descobre URLs de produtos de forma otimizada"""
    # Passo 1: Load more + scroll
    await _load_more_button()
    await _smart_scroll(page)
    
    # Passo 2: Extrai URLs via JS otimizado
    try:
        urls = await page.evaluate(DISCOVERY_JS)
    except Exception:
        urls = []
    
    # Passo 3: Normaliza e filtra
    found: Set[str] = set()
    for u in urls:
        if not u or not PDP_URL_RE.search(u):
            continue
        normalized = _normalize_href(u)
        if PDP_URL_RE.search(normalized):
            found.add(normalized)
    
    result = list(found)[:limit]
    log.info("URLs de produtos detectadas: %d", len(result))
    return result

# ------------------ PDP parsing (OTIMIZADO) ------------------

# JavaScript OTIMIZADO para detecção de tamanhos
SIZE_DETECTION_JS = r"""
(() => {
  const LETTERS = new Set(["XXP","XP","PP","P","M","G","GG","XG","XXG","XXGG","XXGGG"]);
  const NUMERIC = new Set(["32","34","36","38","40","42","44","46","48","50","52"]);
  const SYN = {"XS":"XP","S":"P","L":"G","XL":"XG","XXL":"XXG"};
  
  // Limpa e normaliza texto
  const clean = (txt) => {
    if (!txt) return "";
    let t = txt.trim().toUpperCase().split(/[\s–·|\-]/)[0].replace(/[^A-Z0-9]/g, "");
    return SYN[t] || t;
  };
  
  // Verifica se cor é vermelha (otimizado)
  const isRed = (c) => {
    if (!c) return false;
    const m = c.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/i);
    if (!m) return false;
    const [r, g, b] = [+m[1], +m[2], +m[3]];
    return r >= 120 && g <= 120 && b <= 120 && r > g && r > b;
  };
  
  // Verifica indicador vermelho (OTIMIZADO - early returns)
  const hasRedIndicator = (el) => {
    // 1. Pseudo-elementos
    const aft = getComputedStyle(el, '::after');
    if (isRed(aft.backgroundColor) || isRed(aft.borderColor)) return true;
    
    const bef = getComputedStyle(el, '::before');
    if (isRed(bef.backgroundColor) || isRed(bef.borderColor)) return true;
    
    // 2. Filhos pequenos com cor vermelha
    const rect = el.getBoundingClientRect();
    for (const k of el.querySelectorAll('*')) {
      const r = k.getBoundingClientRect();
      if (r.width <= 20 && r.height <= 20) {
        const cs = getComputedStyle(k);
        const inside = r.left >= rect.left-2 && r.right <= rect.right+2 &&
                       r.top >= rect.top-2 && r.bottom <= rect.bottom+2;
        if (inside && (isRed(cs.backgroundColor) || isRed(cs.borderColor))) {
          return true;
        }
      }
    }
    
    // 3. SVG com fill vermelho
    for (const svg of el.querySelectorAll('svg, svg *')) {
      const fill = svg.getAttribute('fill');
      if (fill && isRed(fill)) return true;
    }
    
    return false;
  };
  
  // Verifica se está esgotado (OTIMIZADO)
  const isSoldOut = (el) => {
    // Disabled
    if (el.disabled || el.getAttribute("aria-disabled") === "true") return true;
    
    // Text decoration
    const cs = getComputedStyle(el);
    if ((cs.textDecoration || '').includes('line-through')) return true;
    if (cs.pointerEvents === 'none') return true;
    if (parseFloat(cs.opacity) < 0.4) return true;
    
    // Classes e atributos
    const meta = `${el.className} ${el.getAttribute('aria-label')||''} ${el.getAttribute('title')||''}`.toLowerCase();
    if (/(soldout|sold-out|unavailable|esgotad|indispon)/.test(meta)) return true;
    
    // Tags de risco
    if (el.querySelector('s, del, strike')) return true;
    
    return false;
  };
  
  // Encontra container de tamanhos (H&M específico)
  let scope = document.querySelector('[class*="size" i], fieldset, [role="radiogroup"]') || document;
  
  // Busca botões de tamanho (seletores específicos da H&M)
  const nodes = scope.querySelectorAll(
    'button[data-size], button[class*="size" i], [role="radio"], ' +
    'input[type="radio"]+label, button, label'
  );
  
  const L = [], N = [];
  const seen = new Set();
  
  for (const el of nodes) {
    // Extrai label
    const candidates = [
      clean(el.textContent),
      clean(el.getAttribute("data-size")),
      clean(el.getAttribute("aria-label")),
      clean(el.getAttribute("title"))
    ];
    
    let label = "";
    for (const t of candidates) {
      if (LETTERS.has(t) || NUMERIC.has(t)) {
        label = t;
        break;
      }
    }
    
    if (!label || seen.has(label)) continue;
    seen.add(label);
    
    // Determina status
    const sold = isSoldOut(el);
    const low = !sold && hasRedIndicator(el);
    const status = sold ? "Esgotado" : (low ? "Poucas unidades" : "Disponível");
    
    if (LETTERS.has(label)) L.push({label, status});
    else N.push({label, status});
  }
  
  // Escolhe família predominante
  const chosen = N.length > L.length ? N : L;
  const result = {};
  const rank = s => s==='Esgotado'?2:(s==='Poucas unidades'?1:0);
  
  for (const {label, status} of chosen) {
    if (!result[label] || rank(status) > rank(result[label])) {
      result[label] = status;
    }
  }
  
  return result;
})()
"""

async def parse_pdp(page: Page) -> Tuple[str, Dict[str, str]]:
    """Extrai nome e tamanhos do produto"""
    # 1. Nome do produto (tenta h1 primeiro - mais rápido)
    name = ""
    try:
        h1 = page.locator("h1").first
        if await h1.is_visible(timeout=2000):
            name = (await h1.inner_text()).strip()
    except Exception:
        pass
    
    if not name:
        try:
            meta = await page.locator('meta[property="og:title"]').first.get_attribute("content")
            name = meta.strip() if meta else ""
        except Exception:
            pass
    
    if not name:
        name = "Produto H&M"
    
    # 2. Extrai tamanhos via JS otimizado
    try:
        data = await page.evaluate(SIZE_DETECTION_JS)
    except Exception as e:
        log.error("Erro ao extrair tamanhos: %s", e)
        data = {}
    
    # 3. Filtra tamanhos válidos
    sizes_map: Dict[str, str] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if (k.isalpha() and k in LETTER_SIZES) or (k.isdigit() and k in NUMERIC_ALLOWED):
                sizes_map[k] = v
    
    # Debug se vazio
    if not sizes_map:
        log.warning("⚠️  Nenhum tamanho detectado para: %s", name)
        try:
            await page.screenshot(path=f"DEBUG_{name[:20].replace(' ','_')}.png")
        except Exception:
            pass
    
    return name, sizes_map

# ------------------ Excel ------------------

def build_excel(items: List[Tuple[str, Dict[str, str]]]) -> pd.DataFrame:
    """Gera DataFrame do Excel"""
    # Coleta todos os tamanhos únicos
    all_sizes: Set[str] = set()
    for _, mp in items:
        all_sizes.update(mp.keys())
    
    # Filtra e ordena
    valid_sizes = [s for s in all_sizes 
                   if (s.isalpha() and s in LETTER_SIZES) or (s.isdigit() and s in NUMERIC_ALLOWED)]
    size_cols = _order_sizes(valid_sizes)
    
    # Cria linhas
    rows = []
    for name, mp in items:
        row = {"Nome do Produto": name}
        row.update({s: mp.get(s, LABEL_HYPHEN) for s in size_cols})
        rows.append(row)
    
    return pd.DataFrame(rows, columns=["Nome do Produto"] + size_cols)

# ------------------ MAIN ------------------

async def main():
    log.info("=" * 80)
    log.info("H&M Brasil - Scraper de Tamanhos v4.9 (OTIMIZADO)")
    log.info("=" * 80)
    log.info("URL: %s", CATEGORY_URL)
    
    async with async_playwright() as p:
        # Browser otimizado
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=['--disable-blink-features=AutomationControlled']  # Menos detectável
        )
        
        ctx = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 1400},
            locale="pt-BR",
            java_script_enabled=True
        )
        ctx.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        ctx.set_default_timeout(STEP_TIMEOUT_MS)
        
        page = await ctx.new_page()
        
        # Abre categoria
        try:
            await page.goto(CATEGORY_URL, wait_until="domcontentloaded")
        except PWTimeout:
            log.warning("Timeout na navegação inicial")
        
        await page.wait_for_timeout(800)  # Reduzido de 1500ms
        await _handle_popups(page)
        
        # Descobre produtos
        log.info("Buscando produtos (limite=%d)...", PRODUCT_LIMIT)
        pdp_urls = await discover_pdp_urls(page, PRODUCT_LIMIT)
        
        if not pdp_urls:
            log.error("❌ Nenhum produto encontrado!")
            await page.screenshot(path="DEBUG_category.png", full_page=True)
            await ctx.close()
            await browser.close()
            return
        
        log.info("Produtos encontrados:")
        for i, u in enumerate(pdp_urls, 1):
            log.info("  [%d] %s", i, u)
        
        # Processa cada produto
        items: List[Tuple[str, Dict[str, str]]] = []
        for i, url in enumerate(pdp_urls, 1):
            log.info("\n" + "=" * 80)
            log.info("[%d/%d] Processando: %s", i, len(pdp_urls), url)
            log.info("=" * 80)
            
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            except PWTimeout:
                log.warning("Timeout ao abrir produto")
                continue
            
            # Espera conteúdo carregar (otimizado)
            try:
                await page.wait_for_selector('h1, [class*="product"]', timeout=5000)
            except Exception:
                pass
            
            await page.wait_for_timeout(800)  # Reduzido de 1200ms
            await _handle_popups(page)
            
            # Extrai dados
            name, sizes = await parse_pdp(page)
            
            if sizes:
                log.info("✅ %s", name)
                for k, v in sorted(sizes.items()):
                    emoji = "🔴" if v == LABEL_SOLDOUT else ("🟡" if v == LABEL_LOW else "🟢")
                    log.info("   %s %s: %s", emoji, k, v)
            else:
                log.warning("⚠️  %s - Sem tamanhos", name)
            
            items.append((name, sizes))
        
        await ctx.close()
        await browser.close()
    
    # Gera Excel
    log.info("\n" + "=" * 80)
    log.info("Gerando arquivo: %s", OUTPUT_XLSX)
    df = build_excel(items)
    df.to_excel(OUTPUT_XLSX, index=False)
    log.info("✅ Concluído! %d produtos processados", len(df))
    log.info("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
