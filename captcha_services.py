"""
Módulo para integração com serviços de resolução de captcha
Suporta: 2Captcha, AntiCaptcha, CapSolver
"""

import time
import requests
from typing import Optional
import os


class TwoCaptchaService:
    """Integração com o serviço 2Captcha"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "http://2captcha.com"
    
    def solve_recaptcha_v2(self, site_key: str, page_url: str, timeout: int = 300) -> Optional[str]:
        """
        Resolve reCAPTCHA v2
        
        Args:
            site_key: Chave do site do reCAPTCHA
            page_url: URL da página onde o captcha está
            timeout: Tempo máximo de espera em segundos
        
        Returns:
            Token de resposta do captcha ou None
        """
        # Submete o captcha para resolução
        submit_url = f"{self.base_url}/in.php"
        params = {
            'key': self.api_key,
            'method': 'userrecaptcha',
            'googlekey': site_key,
            'pageurl': page_url,
            'json': 1
        }
        
        response = requests.post(submit_url, data=params)
        result = response.json()
        
        if result.get('status') != 1:
            print(f"❌ Erro ao submeter captcha: {result.get('request')}")
            return None
        
        task_id = result.get('request')
        print(f"📝 Captcha submetido. Task ID: {task_id}")
        print("⏳ Aguardando resolução...")
        
        # Aguarda a resolução
        get_url = f"{self.base_url}/res.php"
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            time.sleep(5)  # Aguarda 5 segundos entre verificações
            
            params = {
                'key': self.api_key,
                'action': 'get',
                'id': task_id,
                'json': 1
            }
            
            response = requests.get(get_url, params=params)
            result = response.json()
            
            if result.get('status') == 1:
                token = result.get('request')
                print("✅ Captcha resolvido!")
                return token
            elif result.get('request') == 'CAPCHA_NOT_READY':
                continue
            else:
                print(f"❌ Erro: {result.get('request')}")
                return None
        
        print("⏱️  Timeout aguardando resolução")
        return None
    
    def solve_hcaptcha(self, site_key: str, page_url: str, timeout: int = 300) -> Optional[str]:
        """Resolve hCaptcha"""
        submit_url = f"{self.base_url}/in.php"
        params = {
            'key': self.api_key,
            'method': 'hcaptcha',
            'sitekey': site_key,
            'pageurl': page_url,
            'json': 1
        }
        
        response = requests.post(submit_url, data=params)
        result = response.json()
        
        if result.get('status') != 1:
            print(f"❌ Erro ao submeter captcha: {result.get('request')}")
            return None
        
        task_id = result.get('request')
        print(f"📝 Captcha submetido. Task ID: {task_id}")
        
        # Aguarda resolução (mesmo processo do reCAPTCHA)
        get_url = f"{self.base_url}/res.php"
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            time.sleep(5)
            
            params = {
                'key': self.api_key,
                'action': 'get',
                'id': task_id,
                'json': 1
            }
            
            response = requests.get(get_url, params=params)
            result = response.json()
            
            if result.get('status') == 1:
                token = result.get('request')
                print("✅ Captcha resolvido!")
                return token
            elif result.get('request') == 'CAPCHA_NOT_READY':
                continue
            else:
                print(f"❌ Erro: {result.get('request')}")
                return None
        
        return None


class AntiCaptchaService:
    """Integração com o serviço AntiCaptcha"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.anti-captcha.com"
    
    def solve_recaptcha_v2(self, site_key: str, page_url: str, timeout: int = 300) -> Optional[str]:
        """Resolve reCAPTCHA v2 usando AntiCaptcha"""
        # Cria a tarefa
        create_url = f"{self.base_url}/createTask"
        payload = {
            "clientKey": self.api_key,
            "task": {
                "type": "NoCaptchaTaskProxyless",
                "websiteURL": page_url,
                "websiteKey": site_key
            }
        }
        
        response = requests.post(create_url, json=payload)
        result = response.json()
        
        if result.get('errorId') != 0:
            print(f"❌ Erro ao criar tarefa: {result.get('errorDescription')}")
            return None
        
        task_id = result.get('taskId')
        print(f"📝 Tarefa criada. Task ID: {task_id}")
        
        # Aguarda resolução
        get_url = f"{self.base_url}/getTaskResult"
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            time.sleep(5)
            
            payload = {
                "clientKey": self.api_key,
                "taskId": task_id
            }
            
            response = requests.post(get_url, json=payload)
            result = response.json()
            
            if result.get('status') == 'ready':
                token = result.get('solution', {}).get('gRecaptchaResponse')
                print("✅ Captcha resolvido!")
                return token
            elif result.get('status') == 'processing':
                continue
            else:
                print(f"❌ Erro: {result.get('errorDescription', 'Erro desconhecido')}")
                return None
        
        return None


def get_captcha_service(service_name: str = "2captcha") -> Optional[object]:
    """
    Retorna uma instância do serviço de captcha configurado
    
    Args:
        service_name: Nome do serviço ('2captcha' ou 'anticaptcha')
    
    Returns:
        Instância do serviço ou None
    """
    api_key = os.getenv('CAPTCHA_API_KEY') or os.getenv('ANTICAPTCHA_API_KEY')
    
    if not api_key:
        return None
    
    if service_name.lower() == "2captcha":
        return TwoCaptchaService(api_key)
    elif service_name.lower() == "anticaptcha":
        return AntiCaptchaService(api_key)
    else:
        return None
