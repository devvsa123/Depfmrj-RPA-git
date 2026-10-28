import os
import time
import pandas as pd
import win32com.client
from datetime import datetime
from pywinauto import Application

from config.settings import (
    NIP, 
    SENHA_NIP, 
    SERVIDORES_SINGRA, 
    PASTA_DOWNLOADS, 
    PASTA_RAIZ,
    CAM_SINGRA,
    DESTINO_SINGRA
)
from utils.envio import enviar
from utils.logger import registrar_log

# Desativa alertas de conexões inseguras (verify=False)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def esperar_carregar(ie, tempo_limite=40):
    inicio = time.time()
    while ie.Busy or ie.ReadyState != 4:
        if time.time() - inicio > tempo_limite:
            raise Exception(f"⏳ A página travou após {tempo_limite} segundos. Reiniciando...")
        time.sleep(0.5)

def rodar_extracao_singra():
    registrar_log("🤖 [SINGRA] Iniciando o robô do Singra em background...")
    
    situacoes_pendentes = {
        "RMT": ["EA", "ES", "EX", "TR"],
        "RMC": ["EA", "ES", "EX", "TR"]
    }
    ciclo = 1
    lista_de_planilhas = []

    def tem_pendencia():
        return any(len(lista) > 0 for lista in situacoes_pendentes.values())

    while tem_pendencia():
        pendencias_str = f"RMT: {situacoes_pendentes['RMT']} | RMC: {situacoes_pendentes['RMC']}"
        registrar_log(f"🔄 [SINGRA] Ciclo {ciclo}: Faltam extrair -> {pendencias_str}")

        for servidor in SERVIDORES_SINGRA:
            if not tem_pendencia():
                break

            print(f"\n🌐 Tentando conectar no servidor: {servidor}")
            ie = None
            
            try:
                ie = win32com.client.Dispatch("InternetExplorer.Application")
                ie.Visible = True 
                ie.Left = 200
                ie.Top = 200
                
                ie.Navigate(servidor)
                esperar_carregar(ie)
                doc = ie.Document

                print("   🔐 Fazendo Login...")
                time.sleep(2)
                doc.getElementsByName("CIWEDNIP")[0].value = NIP
                doc.getElementsByName("CIWEDSENHA")[0].value = SENHA_NIP
                doc.getElementsByName("IWCBTCONFIRMA")[0].click()
                esperar_carregar(ie)
                doc = ie.Document

                links = doc.getElementsByTagName("A")
                for i in range(links.length):
                    if links[i].innerText and "DEPÓSITO" in links[i].innerText.strip():
                        links[i].click()
                        break
                esperar_carregar(ie)
                doc = ie.Document 

                doc.getElementsByName("TIWCPTBUTTON1")[0].click()
                doc.getElementsByName("TIWCPTEDIT2")[0].value = CAM_SINGRA
                
                try: doc.parentWindow.execScript("window.alert = function() {}; window.confirm = function() { return true; };", "JavaScript")
                except: pass 
                
                doc.getElementsByName("TIWCPTBUTTON2")[0].click()
                esperar_carregar(ie)
                doc = ie.Document
                
                botoes_ok = doc.getElementsByName("IWCPTBTNOK")
                if botoes_ok:
                    botoes_ok[0].click()
                esperar_carregar(ie)
                
                print(f"   ✅ Login concluído. Iniciando extrações...")
                
                for tipo_rm in ["RMT", "RMC"]:
                    for situacao in list(situacoes_pendentes[tipo_rm]):
                        print(f"\n   🔄 Extraindo {tipo_rm} na situação: {situacao}")
                        doc = ie.Document

                        try:
                            doc.getElementById("IWCMNPADRAO_submenu4").click() 
                            time.sleep(0.5)
                            doc.getElementById("IWCMNPADRAO_submenu75").click() 
                            time.sleep(0.5)
                            doc.getElementById("IWCMNPADRAO_submenu92").click() 
                        except: pass

                        time.sleep(2)
                        esperar_carregar(ie)
                        doc = ie.Document 

                        tipo_rm_elementos = doc.getElementsByName("IWCPTCBTIPORMEDITFRAMECADFCONSULTARFORNECIMENTO")
                        if getattr(tipo_rm_elementos, 'length', 0) == 0:
                            raise Exception(f"A tela de Consulta não abriu para a situação {situacao}.")

                        tipo_rm_elementos[0].value = tipo_rm
                        
                        campo_situacao = doc.getElementsByName("IWDBCPTELGSITUACAOEDITFRAMECADFCONSULTARFORNECIMENTO")[0]
                        campo_situacao.value = situacao
                        try: campo_situacao.fireEvent("onchange") 
                        except: pass
                        
                        doc.getElementsByName("IWDBCPTELGCAMFORNECEDOREDITFRAMECADFCONSULTARFORNECIMENTO")[0].value = CAM_SINGRA
                        doc.getElementsByName("IWCPTBTNFILTRARFRAMECADFCONSULTARFORNECIMENTO")[0].click()
                        esperar_carregar(ie)

                        sucesso_ao_clicar = False
                        try:
                            img_extrair = doc.querySelector("img[alt='Extrair']")
                            if img_extrair:
                                elemento_pai = img_extrair.parentElement
                                if not elemento_pai or getattr(elemento_pai, 'disabled', False):
                                    print("      Botão 'Extrair' desativado (planilha vazia).")
                                else:
                                    elemento_pai.click() 
                                    sucesso_ao_clicar = True 
                        except: pass

                        if not sucesso_ao_clicar:
                            situacoes_pendentes[tipo_rm].remove(situacao) 
                            continue 

                        time.sleep(1)
                        arquivos_antes = set(os.listdir(PASTA_DOWNLOADS))
                        
                        try:
                            ie.Left = 200 
                            ie.Top = 200
                            hwnd = ie.HWND
                            app = Application(backend="uia").connect(handle=hwnd)
                            janela_ie = app.window(handle=hwnd)
                            
                            time.sleep(1)
                            barra = janela_ie.child_window(class_name="Frame Notification Bar")
                            botao_salvar = barra.child_window(title="Salvar", control_type="SplitButton")
                            if not botao_salvar.exists():
                                botao_salvar = barra.child_window(title="Salvar", control_type="Button")
                            
                            try: botao_salvar.invoke() 
                            except: botao_salvar.click()
                            
                        except:
                            if situacao in situacoes_pendentes[tipo_rm]:
                                situacoes_pendentes[tipo_rm].remove(situacao)
                            continue 

                        arquivo_recente = None
                        inicio_espera = time.time()
                        
                        while time.time() - inicio_espera < 45: 
                            arquivos_agora = set(os.listdir(PASTA_DOWNLOADS))
                            arquivos_novos = arquivos_agora - arquivos_antes
                            arquivos_prontos = [f for f in arquivos_novos if not f.endswith(('.partial', '.crdownload', '.tmp'))]
                            
                            if arquivos_prontos:
                                arquivo_recente = os.path.join(PASTA_DOWNLOADS, arquivos_prontos[0])
                                time.sleep(1) 
                                break
                            time.sleep(1)
                            
                        if not arquivo_recente:
                            raise Exception("Download demorou mais de 45s.")

                        try:
                            botao_fechar = barra.child_window(title="Fechar", control_type="Button")
                            if botao_fechar.exists():
                                try: botao_fechar.invoke()
                                except: botao_fechar.click()
                        except:
                            pass
                        
                        try:
                            try: df_temp = pd.read_csv(arquivo_recente, sep=';', encoding='utf-8')
                            except: df_temp = pd.read_csv(arquivo_recente, sep=';', encoding='cp1252')
                        except Exception as e:
                            raise Exception(f"Erro na leitura: {e}")

                        df_temp = df_temp.loc[:, ~df_temp.columns.str.contains('^Unnamed')]
                        colunas_texto = df_temp.select_dtypes(include=['object']).columns
                        for col in colunas_texto:
                            df_temp[col] = df_temp[col].str.replace("'", "", regex=False).str.strip()
                        
                        df_temp["'SITUACAO_RM'"] = situacao 
                        df_temp["'TIPO_RM'"] = tipo_rm

                        # Salva os dados na memória RAM do Python
                        lista_de_planilhas.append(df_temp)

                        # Apaga o arquivo temporário da pasta downloads

                        os.remove(arquivo_recente)
                        
                        situacoes_pendentes[tipo_rm].remove(situacao)
                        print(f"      📦 Dados da {tipo_rm} {situacao} capturados com sucesso!")

            except Exception as e:
                print(f"   ⚠️ Falha no servidor ou erro: {e}")
                os.system("taskkill /F /IM iexplore.exe >nul 2>&1")
                time.sleep(1)

        if tem_pendencia():
            time.sleep(3) 
            ciclo += 1

    registrar_log("🏗️ [SINGRA] Todas as extrações concluídas! Preparando envio...")
    
    if lista_de_planilhas:
        df_final = pd.concat(lista_de_planilhas, ignore_index=True)
        nome_arquivo_blob = "planilha_rms_unificada.csv"
        caminho_final = os.path.join(PASTA_RAIZ, nome_arquivo_blob)
        
        df_final.to_csv(caminho_final, sep=';', index=False, encoding='utf-8')
        
        registrar_log(f"☁️ [SINGRA] Enviando {nome_arquivo_blob}...")
        ok = enviar({nome_arquivo_blob: caminho_final}, DESTINO_SINGRA, "SINGRA")
        if ok:
            os.remove(caminho_final)
        os.system("taskkill /F /IM iexplore.exe >nul 2>&1")
        return ok

    os.system("taskkill /F /IM iexplore.exe >nul 2>&1")
    return False