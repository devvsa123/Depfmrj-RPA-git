import time
import schedule
from robots.singra import rodar_extracao_singra
from utils.horario import dentro_do_expediente
from utils.logger import registrar_log

def tarefa_singra():
    if not dentro_do_expediente():
        return
    registrar_log("[SCHEDULER] Iniciando extração do Singra (Recorrência: 20 min)...")
    sucesso = rodar_extracao_singra()
    if sucesso:
        registrar_log("[SCHEDULER] Extração do Singra finalizada com sucesso.")
    else:
        registrar_log("[SCHEDULER] Falha na extração do Singra. Tentará novamente no próximo ciclo.")

# Configura a recorrência para 20 minutos
schedule.every(20).minutes.do(tarefa_singra)

if __name__ == "__main__":
    registrar_log("[START] Robô do Singra iniciado.")
    tarefa_singra() # Roda imediatamente a primeira vez
    
    while True:
        schedule.run_pending()
        time.sleep(1)