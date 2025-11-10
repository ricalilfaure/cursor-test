# Solução para Bypass do Captcha da SHEIN Brasil

Este projeto fornece uma solução automatizada para contornar o captcha da SHEIN Brasil usando Selenium e APIs de resolução de captcha.

## 🚀 Funcionalidades

- Automação do navegador usando Selenium
- Integração com API 2captcha para resolução automática de captcha
- Suporte para resolução manual quando necessário
- Configurações anti-detecção para evitar bloqueios
- Interface simples e fácil de usar

## 📋 Pré-requisitos

- Python 3.7 ou superior
- Google Chrome instalado
- ChromeDriver (pode ser instalado automaticamente com webdriver-manager)
- Conta na [2captcha](https://2captcha.com) (opcional, para resolução automática)

## 🔧 Instalação

1. Clone o repositório ou baixe os arquivos

2. Instale as dependências:
```bash
pip install -r requirements.txt
```

3. (Opcional) Configure sua API key do 2captcha:
   - Copie `config.json.example` para `config.json`
   - Adicione sua API key do 2captcha no arquivo
   - Ou defina a variável de ambiente: `export CAPTCHA_API_KEY="sua_api_key"`

## 📖 Como Usar

### Uso Básico

Execute o script principal:
```bash
python shein_captcha_solver.py
```

O script irá:
1. Abrir o navegador Chrome
2. Navegar para o site da SHEIN Brasil
3. Detectar e resolver o captcha automaticamente (se API key configurada)
4. Ou aguardar resolução manual

### Uso Programático

```python
from shein_captcha_solver import SheinCaptchaSolver

# Com API key do 2captcha
solver = SheinCaptchaSolver(api_key_2captcha="sua_api_key")

# Sem API key (resolução manual)
solver = SheinCaptchaSolver()

# Navegar e resolver captcha
solver.bypass_captcha()

# Continuar com suas ações...
# Exemplo: fazer login, buscar produtos, etc.

# Fechar o navegador
solver.close()
```

## 🔑 Obter API Key do 2captcha

1. Acesse [https://2captcha.com](https://2captcha.com)
2. Crie uma conta
3. Adicione créditos à sua conta
4. Copie sua API key do painel
5. Adicione no arquivo `config.json` ou como variável de ambiente

## ⚙️ Configurações Avançadas

### Modo Headless

Para executar sem interface gráfica:
```python
solver = SheinCaptchaSolver(headless=True)
```

### URL Personalizada

```python
solver.bypass_captcha(url="https://br.shein.com/categoria-especifica")
```

## ⚠️ Avisos Importantes

- **Uso Responsável**: Este script deve ser usado apenas para fins legítimos e pessoais
- **Termos de Serviço**: Verifique os termos de serviço da SHEIN antes de usar automação
- **Rate Limiting**: Evite fazer muitas requisições em pouco tempo para não ser bloqueado
- **API Costs**: O uso da API 2captcha tem custos associados

## 🐛 Solução de Problemas

### ChromeDriver não encontrado

Instale o ChromeDriver ou use webdriver-manager:
```bash
pip install webdriver-manager
```

### Captcha não é resolvido automaticamente

- Verifique se sua API key do 2captcha está correta
- Certifique-se de ter créditos suficientes na conta 2captcha
- O script aguardará resolução manual se a automática falhar

### Navegador é detectado como bot

O script já inclui configurações anti-detecção. Se ainda assim for detectado:
- Tente usar um perfil de usuário real do Chrome
- Aumente os delays entre ações
- Use proxies rotativos

## 📝 Notas

- O script aguarda até 60 segundos para resolução manual do captcha
- A resolução automática via 2captcha pode levar alguns minutos
- O navegador permanece aberto após resolver o captcha para você continuar navegando

## 🤝 Contribuições

Contribuições são bem-vindas! Sinta-se à vontade para abrir issues ou pull requests.

## 📄 Licença

Este projeto é fornecido "como está" para fins educacionais e de uso pessoal.