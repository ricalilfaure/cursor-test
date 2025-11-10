# Configuração do H&M Size Scraper

## Instalação

### 1. Instalar dependências Python

```bash
pip install -r requirements.txt
```

### 2. Instalar navegadores do Playwright

```bash
playwright install chromium
```

## Como usar

### Execução básica

```bash
python hm_br_sizes_to_excel.py
```

### Configurações disponíveis

Edite o início do arquivo `hm_br_sizes_to_excel.py` para ajustar:

```python
PRODUCT_LIMIT = 5          # Número de produtos a processar
OUTPUT_XLSX   = "hm_status.xlsx"  # Nome do arquivo de saída
HEADLESS      = False      # True = sem interface visual
LOG_LEVEL     = "INFO"     # INFO, DEBUG, WARNING, ERROR
```

## Saída

O script gera um arquivo Excel (`hm_status.xlsx`) com:
- Coluna "Nome do Produto"
- Colunas para cada tamanho encontrado (PP, P, M, G, GG, etc. e/ou 32, 34, 36, etc.)
- Células com status:
  - **"Disponível"** ✅ - Tamanho em estoque
  - **"Poucas unidades"** ⚠️ - Tamanho com baixo estoque (quadrado vermelho)
  - **"Esgotado"** ❌ - Tamanho indisponível (texto riscado/botão desabilitado)
  - **"-"** - Tamanho não pertence à grade do produto

## Melhorias da v4.8

### 🎯 Detecção de "Poucas unidades" (quadrado vermelho)

O script agora detecta o indicador vermelho de múltiplas formas:

1. **Pseudo-elementos**: `::before` e `::after` com cores vermelhas
2. **Elementos filhos pequenos**: Dots/badges até 20x20px com cor vermelha
3. **Classes indicadoras**: `indicator`, `badge`, `dot`, `alert` com cores vermelhas
4. **SVG**: Elementos SVG ou caminhos com `fill` vermelho
5. **Background gradients**: Gradientes com tons vermelhos

**Critério de cor vermelha**: R ≥ 120, G ≤ 120, B ≤ 120

### 🚫 Detecção de "Esgotado" (texto riscado)

Detecta produtos esgotados através de:

1. **CSS**: `text-decoration: line-through`
2. **Classes CSS**: `strike`, `line-through`, `cross`, `unavailable`, `sold-out`, `soldout`
3. **Tags HTML**: `<s>`, `<del>`, `<strike>`
4. **Atributos**: `disabled`, `aria-disabled="true"`, `pointer-events: none`
5. **Opacidade**: Elementos com opacidade < 0.4
6. **Palavras-chave**: "soldout", "sold-out", "out-of-stock", "unavailable", "esgotado"

### 📊 Logging detalhado

O script agora exibe:
- Emojis no console (🟢 Disponível, 🟡 Poucas unidades, 🔴 Esgotado)
- Debug detalhado no console do navegador (visível com F12)
- Screenshots automáticos quando não detecta tamanhos

### 🔍 Busca melhorada de containers

Busca por containers de tamanho usando múltiplos seletores:
- `[class*="size"]`, `[id*="size"]`
- `[data-testid*="size"]`, `[data-test*="size"]`
- `fieldset`, `[role="radiogroup"]`
- `.product-size-selector`, `.size-selector`

## Debug

Se o script não detectar tamanhos corretamente:

1. **Verifique os logs do console** - o script mostra debug detalhado
2. **Confira os screenshots** - gerados automaticamente em `DEBUG_*.png`
3. **Execute com HEADLESS=False** - para ver o navegador em ação
4. **Ative LOG_LEVEL="DEBUG"** - para mais informações

## Estrutura do código

- `parse_pdp()`: Extrai nome e tamanhos da página do produto
- `hasRedIndicator()`: Detecta quadrado vermelho (JS executado no navegador)
- `hasLineThrough()`: Detecta texto riscado (JS executado no navegador)
- `discover_pdp_urls()`: Encontra URLs de produtos na categoria
- `build_excel()`: Gera planilha Excel com os dados

## Notas

- O script usa **Playwright** para automação do navegador
- Aceita cookies automaticamente
- Fecha overlays/modals automaticamente
- Faz scroll automático para carregar todos os produtos
- Normaliza tamanhos (XS→XP, S→P, L→G, XL→XG, XXL→XXG)
