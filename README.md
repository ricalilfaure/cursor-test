# H&M Product Availability Scraper

Script para coletar informações de disponibilidade e tamanhos de produtos do site da H&M Brasil.

## Status: ✅ FIXED

**Problema resolvido:** O script estava coletando apenas 16 produtos por página ao invés de ~64 produtos esperados.

**Solução aplicada:** Interceptação de API GraphQL com deduplicação adequada de variantes de tamanho.

## Uso Rápido

\`\`\`bash
python3 hm_scraper.py
\`\`\`

## Resultados

- **~69-72 produtos únicos por página** (de 73-75 SKUs)
- Arquivo de saída: `hm_status(29/11).xlsx`
- Formato: Nome do produto + colunas de tamanho com status de disponibilidade

## Documentação

- **`QUICK_START.md`** - Guia rápido de uso
- **`FIXES_APPLIED.md`** - Detalhes técnicos das correções

## Dependências

\`\`\`bash
pip install playwright pandas openpyxl
playwright install chromium
\`\`\`

## Configuração

Edite as variáveis no início de `hm_scraper.py`:
- `START_PAGE` - Página inicial
- `PAGES_TO_SCAN` - Número de páginas para varrer
- `OUTPUT_XLSX` - Nome do arquivo de saída
