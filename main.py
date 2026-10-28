import time
import urllib3
import os

from robots.singra import rodar_extracao_singra
from robots.wms import rodar_extracao_pwa
from utils.horario import dentro_do_expediente
from utils.logger import registrar_log

# Desativa alertas de conexão insegura (verify=False no Requests)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def iniciar_robo_mestre():
    registrar_log("==================================================")
    registrar_log("🏁 INICIANDO CICLO AGENDADO DO ROBÔ DUPLO")
    
    # PASSO 1: Tenta rodar o Singra e enviar para Vercel
    sucesso_singra = rodar_extracao_singra()
    
    # PASSO 2: Condiciona o PWA ao sucesso do Singra
    if sucesso_singra:
        registrar_log("✅ Singra finalizado. Dando partida no robô do WMS...")
        # WMS extrai a padrão e o estoque detalhado, enviando as duas para o Vercel
        sucesso_wms = rodar_extracao_pwa()
        
        if sucesso_wms:
            registrar_log("🏆 CICLO COMPLETO FINALIZADO COM SUCESSO!")
        else:
            registrar_log("⚠️ O ciclo terminou com falha na etapa do WMS.")
    else:
        registrar_log("❌ Singra falhou gravemente. O robô do WMS foi abortado.")
        
    registrar_log("==================================================\n")

if __name__ == "__main__":
    registrar_log("🚀 Iniciando o modo contínuo à prova de falhas...")
    
    while True:
        try:
            if dentro_do_expediente():
                iniciar_robo_mestre()
            else:
                registrar_log("🌙 Fora do expediente (HORARIO_EXPEDIENTE / SO_DIAS_UTEIS no .env): ciclo pulado.")
            
        except Exception as e:
            registrar_log(f"💥 ERRO CRÍTICO NO MASTER: {e}")
            
        finally:
            registrar_log("💤 O ciclo terminou. O robô vai dormir por 20 minutos...")
            time.sleep(1200) # 20 minutos