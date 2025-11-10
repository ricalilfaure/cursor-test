"""
Exemplo simples de uso do captcha solver
"""

from captcha_solver import CaptchaSolver
import time

def main():
    print("🚀 Iniciando solução de captcha da SHEIN...")
    
    # Cria o solver (headless=False para ver o navegador)
    solver = CaptchaSolver(headless=False)
    
    try:
        # Acessa a SHEIN e tenta resolver o captcha
        url = "https://br.shein.com"
        print(f"\n📱 Acessando: {url}")
        
        success = solver.solve_shein_captcha(url)
        
        if success:
            print("\n✅ Sucesso! Captcha resolvido ou não encontrado.")
            print("💡 Agora você pode continuar navegando na página")
            
            # Aguarda um tempo para você interagir com a página
            print("\n⏳ Aguardando 30 segundos para você testar...")
            time.sleep(30)
        else:
            print("\n❌ Não foi possível resolver o captcha automaticamente")
            print("💡 Tente resolver manualmente ou configure um serviço de captcha")
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrompido pelo usuário")
    except Exception as e:
        print(f"\n❌ Erro: {e}")
    finally:
        solver.close()
        print("\n👋 Finalizado!")

if __name__ == "__main__":
    main()
