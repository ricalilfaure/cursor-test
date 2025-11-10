# H&M Brasil - Scraper de Disponibilidade de Tamanhos

Script Python que faz scraping da H&M Brasil para verificar a disponibilidade de tamanhos de produtos e gera um arquivo Excel com os resultados.

## Funcionalidades

- **Descoberta automática de produtos**: Varre a página de categoria usando múltiplas estratégias:
  - Análise de links no DOM principal
  - Busca em Shadow DOM
  - Análise de iframes
  - Fallback por clique em elementos de produto

- **Detecção inteligente de disponibilidade**:
  - **Esgotado**: Detecta botões desabilitados, texto riscado (line-through), e classes/metadados indicando indisponibilidade
  - **Poucas unidades**: Detecta indicadores vermelhos (quadrados/bolinhas) no botão do tamanho
  - **Disponível**: Tamanhos sem indicadores de problema

- **Suporte a múltiplas famílias de tamanhos**:
  - Letras: XXP, XP, PP, P, M, G, GG, XG, XXG, XXGG, XXGGG
  - Numéricos: 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52

## Instalação

1. Instale as dependências:
```bash
pip install -r requirements.txt
```

2. Instale os navegadores do Playwright:
```bash
playwright install chromium
```

## Configuração

Edite as constantes no início do arquivo `hm_br_sizes_to_excel.py`:

- `CATEGORY_URL`: URL da categoria a ser analisada
- `PRODUCT_LIMIT`: Número máximo de produtos a processar (padrão: 5)
- `OUTPUT_XLSX`: Nome do arquivo Excel de saída (padrão: "hm_status.xlsx")
- `HEADLESS`: `False` para ver o navegador, `True` para modo headless
- `LOG_LEVEL`: Nível de log ("DEBUG", "INFO", "WARNING", "ERROR")

## Uso

Execute o script:

```bash
python hm_br_sizes_to_excel.py
```

O script irá:
1. Abrir a página de categoria da H&M
2. Coletar links de produtos
3. Visitar cada produto e extrair informações de tamanhos
4. Gerar o arquivo Excel `hm_status.xlsx`

## Saída

O arquivo Excel gerado contém:
- Coluna "Nome do Produto"
- Colunas para cada tamanho encontrado (ordenadas)
- Valores nas células:
  - **"Disponível"**: Tamanho disponível
  - **"Poucas unidades"**: Tamanho com baixa disponibilidade (indicador vermelho)
  - **"Esgotado"**: Tamanho esgotado (botão desabilitado/riscado)
  - **"-"**: Tamanho que não pertence à grade do produto

## Melhorias Implementadas

### Detecção de Esgotado
- Verifica `disabled` e `aria-disabled`
- Detecta texto riscado (line-through) no elemento e filhos
- Verifica classes/metadados com palavras-chave de indisponibilidade
- Verifica opacidade reduzida e pointer-events

### Detecção de Poucas Unidades
- Busca por elementos pequenos vermelhos (≤20px) dentro do botão
- Verifica pseudo-elementos `::before` e `::after` com cores vermelhas
- Detecta indicadores posicionados no canto superior direito ou centralizados
- Verifica bordas e backgrounds vermelhos

### Robustez
- Múltiplas estratégias de descoberta de produtos
- Tratamento de cookies e overlays
- Auto-scroll e carregamento de mais produtos
- Timeouts configuráveis
- Logs detalhados para debug

## Troubleshooting

Se nenhum produto for encontrado, o script salvará:
- `DEBUG_category.png`: Screenshot da página
- `DEBUG_category.html`: HTML da página

Use esses arquivos para investigar problemas de detecção.
