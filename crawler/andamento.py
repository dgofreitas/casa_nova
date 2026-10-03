"""Andamento da busca, para o site mostrar as etapas enquanto o crawler trabalha.

Fica em <dados>/crawler-status.json, no campo "etapas" (o resto do arquivo é do
servidor.py: rodando, desde, terminouEm, proxima). Sem pasta de dados (GitHub
Actions, testes) não grava nada.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

FUSO = timezone(timedelta(hours=-3))
ETAPAS = [
    ("fontes", "Ler as imobiliárias"),
    ("anuncios", "Abrir os anúncios e baixar as fotos"),
    ("galerias", "Montar as galerias"),
    ("aviso", "Avisar no Telegram"),
]


def _agora():
    return datetime.now(FUSO).isoformat(timespec="seconds")


class Andamento:
    def __init__(self, dados=None):
        self.arq = Path(dados) / "crawler-status.json" if dados else None
        self.etapas = [{"id": i, "nome": n, "estado": "esperando", "detalhe": "", "itens": []} for i, n in ETAPAS]
        self._gravar()

    def _etapa(self, id_):
        return next(e for e in self.etapas if e["id"] == id_)

    def etapa(self, id_, estado, detalhe=None):
        e = self._etapa(id_)
        if estado == "rodando" and e["estado"] != "rodando":
            e["inicio"] = _agora()
        if estado in ("feito", "erro", "pulado"):
            e["fim"] = _agora()
        e["estado"] = estado
        if detalhe is not None:
            e["detalhe"] = detalhe
        self._gravar()

    def item(self, id_, nome, estado, detalhe=""):
        """Um passo dentro da etapa (uma imobiliária, por exemplo)."""
        itens = self._etapa(id_)["itens"]
        atual = next((x for x in itens if x["nome"] == nome), None)
        if atual is None:
            atual = {"nome": nome}
            itens.append(atual)
        atual.update(estado=estado, detalhe=detalhe)
        self._gravar()

    def _gravar(self):
        if not self.arq:
            return
        try:
            atual = json.loads(self.arq.read_text()) if self.arq.exists() else {}
        except ValueError:
            atual = {}
        atual["etapas"] = self.etapas
        tmp = self.arq.with_suffix(".andamento.tmp")
        tmp.write_text(json.dumps(atual, ensure_ascii=False))
        tmp.replace(self.arq)
