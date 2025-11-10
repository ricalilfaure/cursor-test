#!/usr/bin/env python3
"""
Solução para contornar o captcha da SHEIN Brasil
Usa Selenium para automação do navegador e API 2captcha para resolução de captcha
"""

import time
import json
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException

try:
    from webdriver_manager.chrome import ChromeDriverManager
    WEBDRIVER_MANAGER_AVAILABLE = True
except ImportError:
    WEBDRIVER_MANAGER_AVAILABLE = False


class SheinCaptchaSolver:
    def __init__(self, api_key_2captcha=None, headless=False):
        """
        Inicializa o solver de captcha da SHEIN
        
        Args:
            api_key_2captcha: Chave da API do 2captcha (opcional)
            headless: Se True, executa o navegador em modo headless
        """
        self.api_key = api_key_2captcha
        self.driver = None
        self.setup_driver(headless)
    
    def setup_driver(self, headless=False):
        """Configura o driver do Selenium"""
        chrome_options = Options()
        
        # Opções para evitar detecção
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        if headless:
            chrome_options.add_argument('--headless')
        
        try:
            # Tenta usar webdriver-manager se disponível
            if WEBDRIVER_MANAGER_AVAILABLE:
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
            else:
                self.driver = webdriver.Chrome(options=chrome_options)
            
            # Remove a propriedade webdriver para evitar detecção
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    })
                '''
            })
        except Exception as e:
            print(f"Erro ao configurar o driver: {e}")
            print("Certifique-se de que o ChromeDriver está instalado e no PATH")
            print("Ou instale webdriver-manager: pip install webdriver-manager")
            raise
    
    def solve_captcha_with_2captcha(self, site_key=None, page_url=None):
        """
        Resolve o captcha usando a API 2captcha
        
        Args:
            site_key: Site key do reCAPTCHA (se aplicável)
            page_url: URL da página onde o captcha está
        
        Returns:
            Token do captcha resolvido ou None
        """
        if not self.api_key:
            print("API key do 2captcha não fornecida. Pulando resolução automática.")
            return None
        
        # Para reCAPTCHA v2
        if site_key:
            print("Enviando captcha para resolução via 2captcha...")
            submit_url = "http://2captcha.com/in.php"
            submit_data = {
                'key': self.api_key,
                'method': 'userrecaptcha',
                'googlekey': site_key,
                'pageurl': page_url or 'https://br.shein.com',
                'json': 1
            }
            
            response = requests.post(submit_url, data=submit_data)
            result = response.json()
            
            if result['status'] != 1:
                print(f"Erro ao enviar captcha: {result.get('request', 'Erro desconhecido')}")
                return None
            
            captcha_id = result['request']
            print(f"Captcha enviado. ID: {captcha_id}. Aguardando resolução...")
            
            # Aguarda a resolução
            get_url = "http://2captcha.com/res.php"
            for _ in range(40):  # Aguarda até 4 minutos (40 * 6 segundos)
                time.sleep(6)
                get_data = {
                    'key': self.api_key,
                    'action': 'get',
                    'id': captcha_id,
                    'json': 1
                }
                response = requests.get(get_url, params=get_data)
                result = response.json()
                
                if result['status'] == 1:
                    token = result['request']
                    print("Captcha resolvido com sucesso!")
                    return token
                elif result['request'] != 'CAPCHA_NOT_READY':
                    print(f"Erro ao resolver captcha: {result.get('request', 'Erro desconhecido')}")
                    return None
            
            print("Timeout ao aguardar resolução do captcha")
            return None
        
        return None
    
    def inject_captcha_token(self, token):
        """Injeta o token do captcha resolvido na página"""
        if not token:
            return False
        
        try:
            # Tenta encontrar e preencher o campo do token do reCAPTCHA
            script = f"""
            var token = '{token}';
            
            // Para reCAPTCHA v2
            var textarea = document.querySelector('textarea[name="g-recaptcha-response"]');
            if (textarea) {{
                textarea.value = token;
                textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
                textarea.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
            
            // Para reCAPTCHA v3
            var callback = window.grecaptcha?.ready;
            if (callback) {{
                callback(function() {{
                    var siteKey = document.querySelector('[data-sitekey]')?.getAttribute('data-sitekey');
                    if (siteKey) {{
                        grecaptcha.execute(siteKey, {{action: 'submit'}}).then(function(token) {{
                            var input = document.querySelector('input[name="g-recaptcha-response"]');
                            if (input) input.value = token;
                        }});
                    }}
                }});
            }}
            
            // Dispara evento de callback
            if (window.grecaptcha?.callback) {{
                window.grecaptcha.callback(token);
            }}
            
            return true;
            """
            
            self.driver.execute_script(script)
            time.sleep(2)
            return True
        except Exception as e:
            print(f"Erro ao injetar token: {e}")
            return False
    
    def wait_for_captcha_and_solve(self, timeout=30):
        """
        Aguarda o aparecimento do captcha e tenta resolvê-lo
        
        Args:
            timeout: Tempo máximo de espera em segundos
        
        Returns:
            True se o captcha foi resolvido, False caso contrário
        """
        try:
            # Aguarda o captcha aparecer
            print("Aguardando captcha aparecer...")
            
            # Tenta encontrar diferentes tipos de captcha
            captcha_selectors = [
                "iframe[src*='recaptcha']",
                "div[class*='recaptcha']",
                "iframe[title*='reCAPTCHA']",
                "#captcha",
                ".captcha"
            ]
            
            captcha_found = False
            for selector in captcha_selectors:
                try:
                    WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    captcha_found = True
                    print(f"Captcha encontrado: {selector}")
                    break
                except TimeoutException:
                    continue
            
            if not captcha_found:
                print("Nenhum captcha detectado na página")
                return True  # Considera sucesso se não há captcha
            
            # Tenta encontrar o site key do reCAPTCHA
            site_key = None
            try:
                # Procura por data-sitekey
                element = self.driver.find_element(By.CSS_SELECTOR, '[data-sitekey]')
                site_key = element.get_attribute('data-sitekey')
            except NoSuchElementException:
                # Tenta encontrar no iframe
                try:
                    iframe = self.driver.find_element(By.CSS_SELECTOR, "iframe[src*='recaptcha']")
                    iframe_src = iframe.get_attribute('src')
                    # Extrai o site key da URL do iframe
                    if 'k=' in iframe_src:
                        site_key = iframe_src.split('k=')[1].split('&')[0]
                except NoSuchElementException:
                    pass
            
            if site_key and self.api_key:
                print(f"Site key encontrado: {site_key}")
                current_url = self.driver.current_url
                token = self.solve_captcha_with_2captcha(site_key, current_url)
                
                if token:
                    return self.inject_captcha_token(token)
                else:
                    print("Não foi possível resolver o captcha automaticamente")
                    print("Aguardando resolução manual...")
                    # Aguarda o usuário resolver manualmente
                    time.sleep(60)
                    return True
            else:
                print("Site key não encontrado ou API key não configurada")
                print("Aguardando resolução manual do captcha...")
                # Aguarda o usuário resolver manualmente
                time.sleep(60)
                return True
                
        except Exception as e:
            print(f"Erro ao processar captcha: {e}")
            return False
    
    def navigate_to_shein(self, url="https://br.shein.com"):
        """Navega para o site da SHEIN Brasil"""
        print(f"Navegando para {url}...")
        self.driver.get(url)
        time.sleep(3)
        
        # Aguarda a página carregar completamente
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except TimeoutException:
            print("Timeout ao carregar a página")
            return False
        
        return True
    
    def bypass_captcha(self, url="https://br.shein.com", wait_time=5):
        """
        Método principal para contornar o captcha da SHEIN
        
        Args:
            url: URL da SHEIN para acessar
            wait_time: Tempo de espera após resolver o captcha
        
        Returns:
            True se bem-sucedido, False caso contrário
        """
        try:
            # Navega para o site
            if not self.navigate_to_shein(url):
                return False
            
            # Aguarda e resolve o captcha
            if self.wait_for_captcha_and_solve():
                print("Captcha resolvido com sucesso!")
                time.sleep(wait_time)
                return True
            else:
                print("Falha ao resolver o captcha")
                return False
                
        except Exception as e:
            print(f"Erro durante o bypass: {e}")
            return False
    
    def close(self):
        """Fecha o navegador"""
        if self.driver:
            self.driver.quit()
            print("Navegador fechado")


def main():
    """Função principal"""
    import os
    
    # Carrega a API key do ambiente ou arquivo de configuração
    api_key = os.getenv('CAPTCHA_API_KEY')
    
    if not api_key:
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                api_key = config.get('2captcha_api_key')
        except FileNotFoundError:
            print("AVISO: API key do 2captcha não encontrada.")
            print("Você pode:")
            print("1. Criar um arquivo config.json com sua API key")
            print("2. Ou definir a variável de ambiente CAPTCHA_API_KEY")
            print("3. Ou resolver o captcha manualmente quando aparecer")
            api_key = None
    
    # Cria o solver
    solver = SheinCaptchaSolver(api_key_2captcha=api_key, headless=False)
    
    try:
        # Tenta contornar o captcha
        success = solver.bypass_captcha()
        
        if success:
            print("\n✓ Sucesso! Você pode continuar navegando.")
            print("Pressione Enter para fechar o navegador...")
            input()
        else:
            print("\n✗ Falha ao contornar o captcha")
            
    except KeyboardInterrupt:
        print("\n\nInterrompido pelo usuário")
    finally:
        solver.close()


if __name__ == "__main__":
    main()
