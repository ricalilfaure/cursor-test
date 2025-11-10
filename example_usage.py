#!/usr/bin/env python3
"""
Exemplo de uso do SheinCaptchaSolver
"""

from shein_captcha_solver import SheinCaptchaSolver
import os

def exemplo_basico():
    """Exemplo básico de uso"""
    print("=== Exemplo Básico ===")
    
    # Cria o solver (sem API key - resolução manual)
    solver = SheinCaptchaSolver(headless=False)
    
    try:
        # Navega e tenta resolver o captcha
        if solver.bypass_captcha():
            print("✓ Captcha resolvido! Você pode continuar navegando.")
            print("Pressione Enter para fechar...")
            input()
        else:
            print("✗ Falha ao resolver captcha")
    finally:
        solver.close()


def exemplo_com_api():
    """Exemplo com API key do 2captcha"""
    print("=== Exemplo com API 2captcha ===")
    
    # Carrega API key do ambiente ou configuração
    api_key = os.getenv('CAPTCHA_API_KEY')
    
    if not api_key:
        print("API key não encontrada. Usando modo manual.")
        api_key = None
    
    solver = SheinCaptchaSolver(api_key_2captcha=api_key, headless=False)
    
    try:
        # Navega para uma URL específica
        url = "https://br.shein.com"
        if solver.bypass_captcha(url=url):
            print("✓ Sucesso! Continuando navegação...")
            
            # Aqui você pode adicionar suas ações
            # Exemplo: fazer login, buscar produtos, etc.
            
            print("Pressione Enter para fechar...")
            input()
    finally:
        solver.close()


def exemplo_programatico():
    """Exemplo de uso programático avançado"""
    print("=== Exemplo Programático ===")
    
    solver = SheinCaptchaSolver(headless=False)
    
    try:
        # Navega para o site
        if solver.navigate_to_shein():
            print("Página carregada!")
            
            # Aguarda e resolve captcha
            if solver.wait_for_captcha_and_solve():
                print("Captcha resolvido!")
                
                # Você pode continuar com suas ações aqui
                # Exemplo:
                # driver = solver.driver
                # elemento = driver.find_element(By.ID, "algum-id")
                # elemento.click()
                
                print("Pressione Enter para fechar...")
                input()
    finally:
        solver.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        modo = sys.argv[1]
        if modo == "api":
            exemplo_com_api()
        elif modo == "programatico":
            exemplo_programatico()
        else:
            exemplo_basico()
    else:
        exemplo_basico()
