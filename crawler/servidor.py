"""Roda o crawler no servidor: nos horários marcados e quando alguém pede pelo site.

Variáveis de ambiente:
  CASA_NOVA_DADOS     pasta de dados (padrão /dados)
  CASA_NOVA_HORARIOS  horas do dia, no horário de Brasília (padrão "7,12,17,22")
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   avisos no Telegram (sem eles, não avisa)

O site pede uma busca criando o arquivo <dados>/pedido-busca. O andamento fica em
<dados>/crawler-status.json, que o site mostra.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

FUSO = timezone(timedelta(hours=-3))
DADOS = Path(os.environ.get("CASA_NOVA_DADOS", "/dados"))
HORARIOS = sorted(int(h) for h in os.environ.get("CASA_NOVA_HORARIOS", "7,12,17,22").split(",") if h.strip())
PEDIDO = DADOS / "pedido-busca"
STATUS = DADOS / "crawler-status.json"
CRAWL = Path(__file__).resolve().parent / "crawl.py"


def agora():
    return datetime.now(FUSO)


def proxima(depois):
    for d in range(2):
        dia = (depois + timedelta(days=d)).replace(minute=0, second=0, microsecond=0)
        for h in HORARIOS:
            t = dia.replace(hour=h)
            if t > depois:
                return t
    return depois + timedelta(hours=6)


def gravar_status(**campos):
    atual = {}
    if STATUS.exists():
        try:
            atual = json.loads(STATUS.read_text())
        except ValueError:
            pass
    atual.update(campos)
    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(atual, ensure_ascii=False))
    tmp.replace(STATUS)


def buscar(motivo):
    inicio = agora()
    print(f"\n=== busca ({motivo}) {inicio:%d/%m %H:%M} ===", flush=True)
    gravar_status(rodando=True, desde=inicio.isoformat(timespec="seconds"), motivo=motivo)
    r = subprocess.run([sys.executable, str(CRAWL), "--dados", str(DADOS)])
    fim = agora()
    gravar_status(rodando=False, terminouEm=fim.isoformat(timespec="seconds"),
                  ok=r.returncode == 0, minutos=round((fim - inicio).total_seconds() / 60, 1))


SEMENTE = Path(__file__).resolve().parent / "semente-casas.json"


def main():
    DADOS.mkdir(parents=True, exist_ok=True)
    alvo = proxima(agora())
    if not (DADOS / "casas.json").exists() and SEMENTE.exists():
        # primeira vez no servidor: parte do que o GitHub Actions já acompanhava,
        # para as casas não virarem "novas" de novo, e já faz a primeira busca
        (DADOS / "casas.json").write_text(SEMENTE.read_text())
        PEDIDO.write_text("primeira vez no servidor")
        print("casas.json inicial copiado do repositório.", flush=True)
    gravar_status(rodando=False, proxima=alvo.isoformat(timespec="seconds"))
    print(f"Crawler no ar. Horários: {HORARIOS}. Próxima busca: {alvo:%d/%m %H:%M}", flush=True)
    while True:
        if PEDIDO.exists():
            PEDIDO.unlink(missing_ok=True)
            buscar("pedido pelo site")
        elif agora() >= alvo:
            buscar("horário")
        else:
            time.sleep(20)
            continue
        alvo = proxima(agora())
        gravar_status(proxima=alvo.isoformat(timespec="seconds"))


if __name__ == "__main__":
    main()
