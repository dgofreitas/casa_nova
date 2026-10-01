"""Envio de mensagens pelo robô do Telegram.

Precisa de duas variáveis de ambiente (segredos do GitHub):
  TELEGRAM_BOT_TOKEN  o token que o @BotFather entrega
  TELEGRAM_CHAT_ID    o id do grupo (ou da conversa) que recebe os avisos
"""
import os

import requests

LIMITE = 3900  # o Telegram aceita até 4096 caracteres por mensagem


def _pedacos(texto):
    atual = ""
    for linha in texto.split("\n"):
        if len(atual) + len(linha) + 1 > LIMITE and atual:
            yield atual
            atual = ""
        atual += linha + "\n"
    if atual.strip():
        yield atual


def enviar(texto):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram não configurado (faltam TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).")
        return
    for parte in _pedacos(texto):
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30, data={
            "chat_id": chat, "text": parte, "parse_mode": "HTML", "disable_web_page_preview": "true"})
        if not r.ok:
            print("Falha no Telegram:", r.status_code, r.text[:300])
