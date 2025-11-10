# H&M Brasil - Scraper de Disponibilidade de Tamanhos

Script automatizado para extrair informações de disponibilidade de tamanhos de produtos da H&M Brasil.

## 🚀 Início Rápido

```bash
# Instalar dependências
pip install -r requirements.txt
playwright install chromium

# Executar
python hm_br_sizes_to_excel.py
```

## 📋 O que faz

- Acessa a página de categoria da H&M Brasil
- Encontra produtos automaticamente
- Entra em cada produto e verifica disponibilidade de tamanhos
- Detecta 3 estados:
  - ✅ **Disponível** - Produto em estoque
  - ⚠️ **Poucas unidades** - Quadrado vermelho no botão
  - ❌ **Esgotado** - Texto riscado ou botão desabilitado
- Gera planilha Excel com os resultados

## 📊 Resultado

Arquivo `hm_status.xlsx` com colunas:
- Nome do Produto
- Tamanhos disponíveis (PP, P, M, G, GG, XG, etc. ou 32, 34, 36, etc.)

## 🎯 Melhorias v4.9 (OTIMIZADO)

**🚀 Nova versão com otimizações de performance!**

- ⚡ **40-50% mais rápido** que a versão anterior
- 🎯 **Mantém mesma precisão** de detecção
- 🧹 **Código mais limpo** (235 linhas a menos: 753→518)
- 💾 **Cache de URLs** para normalização instantânea
- 🔍 **Seletores específicos** para o site H&M
- ⏱️ **Timeouts otimizados** e wait strategies inteligentes

Veja detalhes em [OTIMIZACOES.md](OTIMIZACOES.md)

### Melhorias v4.8

### Detecção robusta de "Poucas unidades"
- Pseudo-elementos CSS (::before, ::after)
- Dots/badges vermelhos dentro do botão
- SVG com fill vermelho
- Background gradients
- Classes indicadoras

### Detecção robusta de "Esgotado"
- Text-decoration: line-through
- Tags HTML (<s>, <del>, <strike>)
- Atributos disabled
- Opacidade baixa
- Classes e palavras-chave

### Logging melhorado
- Emojis no console
- Debug detalhado
- Screenshots automáticos
- Informações de progresso

## 📖 Documentação completa

Veja [SETUP.md](SETUP.md) para instruções detalhadas de configuração e uso.

## 🔧 Configuração

Edite as constantes no início de `hm_br_sizes_to_excel.py`:

```python
PRODUCT_LIMIT = 5          # Quantos produtos processar
OUTPUT_XLSX   = "hm_status.xlsx"  # Nome do arquivo
HEADLESS      = False      # True = sem visualização
LOG_LEVEL     = "INFO"     # Nível de log
```

## 🛠️ Tecnologias

- Python 3.8+
- Playwright (automação de navegador)
- Pandas (geração de Excel)
- BeautifulSoup implícito via Playwright