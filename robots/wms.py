import os
from datetime import datetime
from playwright.sync_api import sync_playwright

from config.settings import (
    WMS_LOGIN_URL, 
    WMS_RELATORIO_URL, 
    WMS_ESTOQUE_DETALHADO,
    USUARIO_WMS, 
    SENHA_WMS,
    DESTINO_WMS,
    GITHUB_PASTA_WMS,
    PASTA_RAIZ
)
from utils.envio import enviar
from utils.logger import registrar_log

# Desativa alertas de conexões inseguras
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def rodar_extracao_pwa():
    registrar_log("🤖 [WMS] Iniciando o robô visual (PWA)...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="msedge") 
        context = browser.new_context()
        page = context.new_page()

        try:
            print("1. Acessando a tela de login do WMS...")
            page.goto(WMS_LOGIN_URL)
            
            print("2. Preenchendo credenciais e entrando...")
            page.fill("input[name='ucLogin$txtloginusuario']", USUARIO_WMS)
            page.fill("input[name='ucLogin$txtloginsenha']", SENHA_WMS)
            page.click("input[name='ucLogin$btnLogar']")
            page.wait_for_load_state("networkidle")
            print("   Login realizado!")

            agora_str = datetime.now().strftime("%Y%m%d_%H%M%S")

            # =========================================================
            # EXTRAÇÃO 1: RELATÓRIO PADRÃO
            # =========================================================
            print("3. Abrindo a tela de consultas (Grid Padrão)...")
            page.goto(WMS_RELATORIO_URL)
            page.wait_for_selector("#ImageButton4")

            print("4. Baixando a primeira planilha (Pode demorar uns minutos)...")
            with page.expect_download(timeout=300000) as informacao_download_1:
                page.click("#ImageButton4", timeout=300000)
            
            download_1 = informacao_download_1.value
            nome_arquivo_1 = f"planilha_estoque.xls"
            caminho_final_1 = os.path.join(PASTA_RAIZ, nome_arquivo_1)
            download_1.save_as(caminho_final_1)
            print(f"  ✅ SUCESSO! Primeira planilha salva como: {nome_arquivo_1}")

            # =========================================================
            # EXTRAÇÃO 2: ESTOQUE DETALHADO (NOVO NOME .XLSX)
            # =========================================================
            print("5. Abrindo a tela do Estoque Detalhado...")
            page.goto(WMS_ESTOQUE_DETALHADO)
            
            page.wait_for_selector("#ImageButton4")
            print("6. Baixando a segunda planilha (Estoque Detalhado)...")
            with page.expect_download(timeout=300000) as informacao_download_2:
                page.click("#ImageButton4", timeout=300000)
            
            download_2 = informacao_download_2.value
            
            # NOME EXATO ALTERADO CONFORME SUA SOLICITAÇÃO
            nome_arquivo_2 = "controle-estoque.xlsx"
            caminho_final_2 = os.path.join(PASTA_RAIZ, nome_arquivo_2)
            download_2.save_as(caminho_final_2)
            print(f"  ✅ SUCESSO! Segunda planilha salva como: {nome_arquivo_2}")

            # =========================================================
            # ENVIO (GitHub privado e/ou Vercel, conforme DESTINO_WMS no .env)
            # =========================================================
            print("7. Enviando as planilhas...")
            if not enviar({nome_arquivo_1: caminho_final_1, nome_arquivo_2: caminho_final_2}, DESTINO_WMS, "WMS", GITHUB_PASTA_WMS):
                return False

            registrar_log("🏆 [WMS] Operação concluída! Ambas as planilhas foram enviadas e limpas da pasta.")
            return True

        except Exception as e:
            registrar_log(f"❌ [WMS] Ocorreu um erro no processo: {e}")
            return False
            
        finally:
            print("Limpando arquivos residuais e fechando o navegador...")

            # Tenta apagar a planilha 1 se ela existir
            try:
                if 'caminho_final_1' in locals() and os.path.exists(caminho_final_1):
                    os.remove(caminho_final_1)
            except Exception: pass

            # Tenta apagar a planilha 2 se ela existir
            try:
                if 'caminho_final_2' in locals() and os.path.exists(caminho_final_2):
                    os.remove(caminho_final_2)
            except Exception: pass

            browser.close()