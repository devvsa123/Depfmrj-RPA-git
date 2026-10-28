"""Janela de funcionamento dos robôs (opcional), para não extrair nem enviar de madrugada e no fim de semana."""
import os
from datetime import datetime


def dentro_do_expediente(agora=None):
    """
    HORARIO_EXPEDIENTE="07:00-18:00" e SO_DIAS_UTEIS=1 no .env limitam quando os robôs rodam.
    Sem essas variáveis, rodam a qualquer hora.
    """
    agora = agora or datetime.now()
    if os.getenv("SO_DIAS_UTEIS", "0") == "1" and agora.weekday() >= 5:
        return False
    faixa = os.getenv("HORARIO_EXPEDIENTE", "").strip()
    if not faixa:
        return True
    try:
        ini, fim = (datetime.strptime(x.strip(), "%H:%M").time() for x in faixa.split("-"))
    except ValueError:
        return True  # valor inválido no .env: não bloqueia o robô
    return ini <= agora.time() <= fim
