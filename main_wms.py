import time
import schedule
from robots.wms import rodar_extracao_pwa
from utils.horario import dentro_do_expediente
from utils.logger import registrar_log

def tarefa_wms():
    if not dentro_do_expediente():
        return
    registrar_log("[SCHEDULER] Iniciando extração do WMS (Recorrência: 5 min)...")
    sucesso = rodar_extracao_pwa()
    if sucesso:
        registrar_log("[SCHEDULER] Extração do WMS finalizada com sucesso.")
    else:
        registrar_log("[SCHEDULER] Falha na extração do WMS. Tentará novamente no próximo ciclo.")

# Configura a recorrência para 5 minutos
schedule.every(5).minutes.do(tarefa_wms)

if __name__ == "__main__":
    registrar_log("[START] Robô do WMS iniciado.")
    tarefa_wms() # Roda imediatamente a primeira vez
    
    while True:
        schedule.run_pending()
        time.sleep(1)