# 🚀 Guia Rápido - Solução de Captcha SHEIN Brasil

## 📋 Passo a Passo

### 1. Instalação

```bash
# Instale as dependências
pip install -r requirements.txt

# Instale o Playwright (opcional, mas recomendado)
playwright install chromium
```

### 2. Uso Básico (Modo Manual)

A forma mais simples de começar é usar o modo manual, onde o código abre o navegador e você resolve o captcha manualmente:

```bash
python example_simple.py
```

Ou use diretamente:

```python
from captcha_solver import CaptchaSolver

solver = CaptchaSolver(headless=False)
solver.solve_shein_captcha("https://br.shein.com")
# O navegador abrirá e você resolve o captcha
# O código aguardará automaticamente
solver.close()
```

### 3. Uso Automático (Requer API Key)

Para resolução automática, você precisa de um serviço de captcha:

#### Opção A: 2Captcha (Recomendado para começar)

1. Crie uma conta em: https://2captcha.com/
2. Adicione créditos (mínimo ~$3)
3. Copie sua API key
4. Crie o arquivo `.env`:

```bash
cp .env.example .env
```

5. Edite o `.env`:

```
CAPTCHA_SERVICE=2captcha
CAPTCHA_API_KEY=sua_chave_aqui
```

6. Execute:

```bash
python example_simple.py
```

#### Opção B: AntiCaptcha

1. Crie uma conta em: https://anti-captcha.com/
2. Adicione créditos
3. Configure no `.env`:

```
CAPTCHA_SERVICE=anticaptcha
CAPTCHA_API_KEY=sua_chave_aqui
```

## 🔍 Tipos de Captcha Suportados

- ✅ **reCAPTCHA v2** - Suportado (automático e manual)
- ✅ **hCaptcha** - Suportado (automático e manual)
- ⚠️ **Captcha de Imagem** - Apenas modo manual

## 💡 Dicas

### Evitar Detecção

O código já inclui várias técnicas para evitar detecção:
- User-agent realista
- Ocultação de propriedades de automação
- Configurações de navegador otimizadas

### Se o Captcha Não For Detectado

1. Verifique manualmente se há captcha na página
2. A SHEIN pode ter mudado a estrutura
3. Ajuste os seletores CSS em `detect_captcha_type()` se necessário

### Economizar Créditos de API

- Use o modo manual quando possível
- Configure timeouts menores se o captcha resolver rápido
- Monitore seu uso na dashboard do serviço

## 🐛 Problemas Comuns

### "ChromeDriver não encontrado"
```bash
# O webdriver-manager deve instalar automaticamente
# Se falhar, instale manualmente:
pip install --upgrade webdriver-manager
```

### "Navegador não abre"
- Verifique se o Chrome está instalado
- Tente com `headless=False` explicitamente
- No Linux, pode precisar de: `apt-get install chromium-browser`

### "API key inválida"
- Verifique se copiou a chave corretamente
- Confirme que tem créditos no serviço
- Teste a API key no site do serviço

## 📞 Precisa de Ajuda?

1. Verifique os logs de erro
2. Teste primeiro em modo manual
3. Confirme que o tipo de captcha é suportado
4. Verifique se a estrutura da página da SHEIN mudou

## ⚖️ Lembrete Legal

- Use apenas para fins legítimos
- Respeite os termos de serviço da SHEIN
- Não faça scraping em larga escala
- Este código é para fins educacionais
