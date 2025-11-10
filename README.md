# Solução para Captcha da SHEIN Brasil

Este projeto fornece ferramentas para ajudar a passar pelo captcha da SHEIN Brasil de forma legítima.

## ⚠️ Aviso Legal

Este código é fornecido apenas para fins educacionais e de automação pessoal. Certifique-se de:
- Respeitar os termos de serviço da SHEIN
- Usar apenas para fins legítimos
- Não realizar scraping em larga escala ou atividades que possam sobrecarregar os servidores

## 🚀 Instalação

1. Instale as dependências:
```bash
pip install -r requirements.txt
```

2. Instale o Playwright (opcional, para melhor suporte):
```bash
playwright install chromium
```

3. Configure as variáveis de ambiente (opcional):
```bash
cp .env.example .env
# Edite o .env com suas configurações
```

## 📋 Uso Básico

### Modo Manual (Recomendado para começar)

```python
from captcha_solver import CaptchaSolver

solver = CaptchaSolver(headless=False)
try:
    solver.solve_shein_captcha("https://br.shein.com")
    # O navegador abrirá e você pode resolver o captcha manualmente
    # O código aguardará até que você resolva
finally:
    solver.close()
```

### Modo Automático (Requer serviço de resolução de captcha)

Para resolução automática, você precisará de um serviço como:
- [2Captcha](https://2captcha.com/)
- [AntiCaptcha](https://anti-captcha.com/)
- [CapSolver](https://www.capsolver.com/)

Configure sua API key no arquivo `.env`:
```
CAPTCHA_API_KEY=sua_chave_aqui
```

## 🔧 Funcionalidades

- ✅ Detecção automática do tipo de captcha (reCAPTCHA, hCaptcha, imagem)
- ✅ Suporte para resolução manual (aguarda você resolver)
- ✅ Preparado para integração com serviços de resolução automática
- ✅ Configurações anti-detecção para evitar bloqueios
- ✅ Suporte para modo headless

## 📝 Próximos Passos

Para implementar resolução automática completa, você precisará:

1. **Escolher um serviço de resolução de captcha** (2Captcha, AntiCaptcha, etc.)
2. **Integrar a API do serviço** no código
3. **Configurar sua API key** no arquivo `.env`

## 🐛 Troubleshooting

### Navegador não abre
- Verifique se o Chrome/Chromium está instalado
- Tente executar sem modo headless: `headless=False`

### Captcha não detectado
- A SHEIN pode ter mudado a estrutura do site
- Verifique manualmente se há captcha na página
- Ajuste os seletores CSS no método `detect_captcha_type()`

### Erro de driver
- O webdriver-manager deve baixar automaticamente
- Se falhar, instale manualmente o ChromeDriver

## 📚 Recursos

- [Selenium Documentation](https://www.selenium.dev/documentation/)
- [2Captcha API Docs](https://2captcha.com/2captcha-api)
- [AntiCaptcha API Docs](https://anticaptcha.atlassian.net/wiki/spaces/API/pages)

## 🤝 Contribuindo

Sinta-se à vontade para melhorar este código e adicionar suporte para outros tipos de captcha ou serviços de resolução.
