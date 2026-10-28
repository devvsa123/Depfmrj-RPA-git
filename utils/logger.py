import os
from datetime import datetime

from config.settings import PASTA_LOGS_REDE

def registrar_log(mensagem):
    """Salva o status da execução em um arquivo .txt na pasta Documentos"""

    # 1. Definição das pastas
    pasta_documentos = os.path.join(os.path.expanduser('~'), 'Documents')
    caminho_local = os.path.join(pasta_documentos, 'historico_robo.txt')

    caminho_publico = os.path.join(PASTA_LOGS_REDE, 'historico_robo.txt') if PASTA_LOGS_REDE else None

    # 2. Formatação da mensagem
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    texto_log = f"[{agora}] {mensagem}\n"
    
    print(texto_log.strip())
    
    # 3. Salva no arquivo LOCAL primeiro
    try:
        os.makedirs(os.path.dirname(caminho_local), exist_ok=True)
        with open(caminho_local, 'a', encoding='utf-8') as f_local:
            f_local.write(texto_log)
    except Exception as e_local:
        print(f"[{agora}] ❌ ERRO CRÍTICO: Falha ao salvar log local: {e_local}")

    # 4. Tenta salvar no arquivo PÚBLICO (pasta de rede definida em PASTA_LOGS_REDE no .env)
    if not caminho_publico:
        return
    try:
        # Se a pasta não existir na rede, tenta criar (pode dar erro de permissão, o que é normal e será tratado)
        os.makedirs(os.path.dirname(caminho_publico), exist_ok=True)

        with open(caminho_publico, 'a', encoding='utf-8') as f_publico:
            f_publico.write(texto_log)

    except Exception as e_publico:
        alerta_falha = f"[{agora}] ⚠️ [AVISO] Falha de conexão com a pasta pública. O log não subiu para a rede: {e_publico}\n"

        print(alerta_falha.strip())

        # Abre o log local NOVAMENTE e anota a falha lá dentro para seu histórico
        try:
            with open(caminho_local, 'a', encoding='utf-8') as f_local_fallback:
                f_local_fallback.write(alerta_falha)
        except Exception:
            pass