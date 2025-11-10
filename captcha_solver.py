"""
Solução para contornar captchas da SHEIN Brasil
Suporta diferentes tipos de captcha: reCAPTCHA, hCaptcha, e captchas de imagem
"""

import time
import os
from typing import Optional, Dict, Any
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv
import requests
from captcha_services import get_captcha_service

load_dotenv()


class CaptchaSolver:
    """Classe principal para resolver captchas da SHEIN"""
    
    def __init__(self, headless: bool = False):
        """
        Inicializa o solver de captcha
        
        Args:
            headless: Se True, executa o navegador em modo headless
        """
        self.headless = headless or os.getenv('HEADLESS', 'False').lower() == 'true'
        self.driver = None
        self.wait_time = int(os.getenv('WAIT_TIME', '10'))
        self.captcha_api_key = os.getenv('CAPTCHA_API_KEY')
        self.captcha_service = get_captcha_service(os.getenv('CAPTCHA_SERVICE', '2captcha'))
        
    def setup_driver(self) -> webdriver.Chrome:
        """Configura e retorna o driver do Chrome"""
        chrome_options = Options()
        
        if self.headless:
            chrome_options.add_argument('--headless')
        
        # Opções para evitar detecção
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # Script para ocultar webdriver
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            '''
        })
        
        self.driver = driver
        return driver
    
    def detect_captcha_type(self) -> Optional[str]:
        """
        Detecta o tipo de captcha presente na página
        
        Returns:
            Tipo de captcha detectado: 'recaptcha', 'hcaptcha', 'image', ou None
        """
        if not self.driver:
            return None
        
        try:
            # Verifica reCAPTCHA
            if self.driver.find_elements(By.CSS_SELECTOR, 'iframe[src*="recaptcha"]'):
                return 'recaptcha'
            
            # Verifica hCaptcha
            if self.driver.find_elements(By.CSS_SELECTOR, 'iframe[src*="hcaptcha"]'):
                return 'hcaptcha'
            
            # Verifica captcha de imagem genérico
            captcha_elements = self.driver.find_elements(
                By.CSS_SELECTOR, 
                '[class*="captcha"], [id*="captcha"], [class*="verify"], [id*="verify"]'
            )
            if captcha_elements:
                return 'image'
            
            return None
        except Exception as e:
            print(f"Erro ao detectar captcha: {e}")
            return None
    
    def solve_recaptcha_v2(self, site_key: Optional[str] = None) -> bool:
        """
        Resolve reCAPTCHA v2 usando serviço externo (2Captcha, AntiCaptcha, etc.)
        
        Args:
            site_key: Chave do site do reCAPTCHA (opcional, tenta detectar automaticamente)
        
        Returns:
            True se resolvido com sucesso, False caso contrário
        """
        if not self.captcha_api_key:
            print("⚠️  API key não configurada. Configure CAPTCHA_API_KEY no .env")
            print("💡 Você pode usar serviços como 2Captcha ou AntiCaptcha")
            return False
        
        try:
            # Tenta encontrar o iframe do reCAPTCHA
            iframe = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'iframe[src*="recaptcha"]'))
            )
            
            # Extrai site_key se não fornecida
            if not site_key:
                src = iframe.get_attribute('src')
                # Tenta extrair site_key da URL
                if 'k=' in src:
                    site_key = src.split('k=')[1].split('&')[0]
            
            if not site_key:
                print("❌ Não foi possível detectar a site_key do reCAPTCHA")
                return False
            
            print(f"🔍 Site key detectada: {site_key}")
            
            # Tenta resolver usando serviço de captcha
            if self.captcha_service:
                print("📝 Resolvendo via serviço de captcha...")
                token = self.captcha_service.solve_recaptcha_v2(
                    site_key, 
                    self.driver.current_url
                )
                
                if token:
                    # Injeta o token no reCAPTCHA
                    return self._submit_recaptcha_token(token)
                else:
                    print("⚠️  Falha na resolução automática")
                    return False
            else:
                print("⚠️  Serviço de captcha não configurado")
                print("💡 Configure CAPTCHA_API_KEY no .env para resolução automática")
                return False
            
        except Exception as e:
            print(f"❌ Erro ao resolver reCAPTCHA: {e}")
            return False
    
    def solve_hcaptcha(self) -> bool:
        """
        Resolve hCaptcha usando serviço externo
        
        Returns:
            True se resolvido com sucesso, False caso contrário
        """
        if not self.captcha_api_key:
            print("⚠️  API key não configurada")
            return False
        
        try:
            iframe = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'iframe[src*="hcaptcha"]'))
            )
            
            # Extrai site_key do hCaptcha
            src = iframe.get_attribute('src')
            site_key = None
            if 'sitekey=' in src:
                site_key = src.split('sitekey=')[1].split('&')[0]
            
            if not site_key:
                print("❌ Não foi possível detectar a site_key do hCaptcha")
                return False
            
            print(f"🔍 Site key detectada: {site_key}")
            
            # Tenta resolver usando serviço de captcha
            if self.captcha_service:
                print("📝 Resolvendo via serviço de captcha...")
                token = self.captcha_service.solve_hcaptcha(
                    site_key,
                    self.driver.current_url
                )
                
                if token:
                    # Injeta o token no hCaptcha
                    return self._submit_hcaptcha_token(token)
                else:
                    print("⚠️  Falha na resolução automática")
                    return False
            else:
                print("⚠️  Serviço de captcha não configurado")
                return False
                
        except Exception as e:
            print(f"❌ Erro ao resolver hCaptcha: {e}")
            return False
    
    def _submit_recaptcha_token(self, token: str) -> bool:
        """
        Submete o token do reCAPTCHA na página
        
        Args:
            token: Token de resposta do reCAPTCHA
        
        Returns:
            True se submetido com sucesso
        """
        try:
            # Injeta o token usando JavaScript
            script = f"""
            document.getElementById('g-recaptcha-response').innerHTML = '{token}';
            if (typeof ___grecaptcha_cfg !== 'undefined') {{
                ___grecaptcha_cfg.clients[0].callback('{token}');
            }}
            """
            self.driver.execute_script(script)
            time.sleep(2)
            
            # Verifica se o captcha foi resolvido
            if not self.detect_captcha_type() or self.detect_captcha_type() != 'recaptcha':
                print("✅ Token do reCAPTCHA submetido com sucesso!")
                return True
            else:
                print("⚠️  Token submetido, mas captcha ainda presente")
                return False
        except Exception as e:
            print(f"❌ Erro ao submeter token: {e}")
            # Tenta método alternativo
            try:
                self.driver.execute_script(
                    f"___grecaptcha_cfg.clients[0].callback('{token}')"
                )
                time.sleep(2)
                return True
            except:
                return False
    
    def _submit_hcaptcha_token(self, token: str) -> bool:
        """
        Submete o token do hCaptcha na página
        
        Args:
            token: Token de resposta do hCaptcha
        
        Returns:
            True se submetido com sucesso
        """
        try:
            # Injeta o token usando JavaScript
            script = f"""
            if (typeof hcaptcha !== 'undefined') {{
                var widgetId = Object.keys(hcaptcha.widgets)[0];
                hcaptcha.submit(widgetId, '{token}');
            }}
            """
            self.driver.execute_script(script)
            time.sleep(2)
            
            # Verifica se o captcha foi resolvido
            if not self.detect_captcha_type() or self.detect_captcha_type() != 'hcaptcha':
                print("✅ Token do hCaptcha submetido com sucesso!")
                return True
            else:
                print("⚠️  Token submetido, mas captcha ainda presente")
                return False
        except Exception as e:
            print(f"❌ Erro ao submeter token: {e}")
            return False
    
    def wait_for_manual_solve(self, timeout: int = 300) -> bool:
        """
        Aguarda o usuário resolver o captcha manualmente
        
        Args:
            timeout: Tempo máximo de espera em segundos
        
        Returns:
            True se o captcha foi resolvido, False se timeout
        """
        print("⏳ Aguardando resolução manual do captcha...")
        print("👤 Por favor, resolva o captcha no navegador")
        
        start_time = time.time()
        captcha_type = self.detect_captcha_type()
        
        while time.time() - start_time < timeout:
            time.sleep(2)
            current_type = self.detect_captcha_type()
            
            # Se não detectar mais captcha, provavelmente foi resolvido
            if current_type is None and captcha_type is not None:
                print("✅ Captcha parece ter sido resolvido!")
                time.sleep(2)  # Aguarda um pouco mais para confirmar
                return True
        
        print("⏱️  Timeout aguardando resolução do captcha")
        return False
    
    def solve_shein_captcha(self, url: str = "https://br.shein.com") -> bool:
        """
        Método principal para resolver captcha da SHEIN
        
        Args:
            url: URL da SHEIN para acessar
        
        Returns:
            True se o captcha foi resolvido com sucesso
        """
        if not self.driver:
            self.setup_driver()
        
        try:
            print(f"🌐 Acessando {url}...")
            self.driver.get(url)
            time.sleep(3)
            
            # Detecta o tipo de captcha
            captcha_type = self.detect_captcha_type()
            
            if captcha_type is None:
                print("✅ Nenhum captcha detectado na página")
                return True
            
            print(f"🔍 Captcha detectado: {captcha_type}")
            
            # Tenta resolver baseado no tipo
            if captcha_type == 'recaptcha':
                if not self.solve_recaptcha_v2():
                    print("🔄 Tentando resolução manual...")
                    return self.wait_for_manual_solve()
            
            elif captcha_type == 'hcaptcha':
                if not self.solve_hcaptcha():
                    print("🔄 Tentando resolução manual...")
                    return self.wait_for_manual_solve()
            
            else:
                print("🔄 Tipo de captcha não suportado automaticamente")
                return self.wait_for_manual_solve()
            
            return True
            
        except Exception as e:
            print(f"❌ Erro ao resolver captcha: {e}")
            return False
    
    def close(self):
        """Fecha o navegador"""
        if self.driver:
            self.driver.quit()
            print("🔒 Navegador fechado")


def main():
    """Função principal de exemplo"""
    solver = CaptchaSolver(headless=False)
    
    try:
        # Tenta resolver o captcha da SHEIN
        success = solver.solve_shein_captcha("https://br.shein.com")
        
        if success:
            print("✅ Captcha resolvido com sucesso!")
            # Aqui você pode continuar com suas ações na página
            input("Pressione Enter para fechar...")
        else:
            print("❌ Não foi possível resolver o captcha")
    
    finally:
        solver.close()


if __name__ == "__main__":
    main()
