"""Descrições e fotos dos anúncios.

As fotos vão para o branch `fotos` do repositório (pasta passada em --fotos),
num formato que o Apps Script copia para o Drive e o site importa:

  indice.json              {"capas": {id: arquivo}, "galerias": {id: arquivo}}
  capas/<lote>.json        {id: "<jpeg em base64>", ...}   até 10 capas por arquivo
  galerias/<id>.json       {"id": ..., "fotos": ["<jpeg em base64>", ...]}

Só uma casa por grupo (mesmo imóvel em várias imobiliárias) ganha fotos.
"""
import base64
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image

from comum import UA
from detalhes import MAX_FOTOS, detalhar

CAPA_LADO, CAPA_QUALIDADE = 560, 65
FOTO_LADO, FOTO_QUALIDADE = 960, 68
CAPAS_POR_LOTE = 10
MAX_DETALHES_POR_RODADA = 250


def nome_arquivo(id_):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", id_)


def _jpeg(conteudo, lado, qualidade):
    im = Image.open(io.BytesIO(conteudo))
    im = im.convert("RGB")
    im.thumbnail((lado, lado))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=qualidade, optimize=True, progressive=True)
    return b.getvalue()


def _baixar(url):
    try:
        r = requests.get(url, timeout=40, headers={"User-Agent": UA, "Referer": url})
        if r.status_code != 200 or len(r.content) < 2000:
            return None
        return r.content
    except requests.RequestException:
        return None


def completar_detalhes(http, imoveis, espera_por_fonte):
    """Busca descrição e endereços das fotos dos anúncios que ainda não têm."""
    pendentes = [x for x in imoveis.values() if x.get("status") == "ativo" and not x.get("detalhado")]
    pendentes.sort(key=lambda x: x.get("primeiroVisto", ""), reverse=True)
    feitos = 0
    for x in pendentes[:MAX_DETALHES_POR_RODADA]:
        http.espera = espera_por_fonte.get(x["fonte"], 1.0)
        try:
            d = detalhar(http, x)
        except Exception as e:
            x["detalheErro"] = str(e)[:120]
            x["tentativasDetalhe"] = x.get("tentativasDetalhe", 0) + 1
            if x["tentativasDetalhe"] >= 3:
                x["detalhado"] = True   # desiste depois de 3 rodadas
            continue
        if d.get("descricao"):
            x["descricao"] = d["descricao"]
        if d.get("fotosOrigem"):
            x["fotosOrigem"] = d["fotosOrigem"]
            x.setdefault("foto", d["fotosOrigem"][0])
        x["detalhado"] = True
        x.pop("detalheErro", None)
        feitos += 1
    print(f"[detalhes] {feitos} anúncios abertos ({len(pendentes) - feitos} ficaram para a próxima)")


def gerar_fotos(imoveis, pasta):
    pasta = Path(pasta)
    (pasta / "capas").mkdir(parents=True, exist_ok=True)
    (pasta / "galerias").mkdir(parents=True, exist_ok=True)
    arq_indice = pasta / "indice.json"
    indice = json.loads(arq_indice.read_text()) if arq_indice.exists() else {"capas": {}, "galerias": {}}

    # grupos que já têm fotos em algum anúncio
    com_fotos = {x.get("grupo") for i, x in imoveis.items() if i in indice["galerias"]}
    fila = []
    for i, x in imoveis.items():
        if x.get("status") != "ativo" or i in indice["galerias"] or not x.get("fotosOrigem"):
            continue
        if x.get("grupo") in com_fotos:
            continue
        com_fotos.add(x.get("grupo"))
        fila.append(x)

    novas_capas = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for x in fila:
            urls = x["fotosOrigem"][:MAX_FOTOS]
            brutos = [b for b in pool.map(_baixar, urls) if b]
            fotos, capa = [], None
            for b in brutos:
                try:
                    fotos.append(base64.b64encode(_jpeg(b, FOTO_LADO, FOTO_QUALIDADE)).decode())
                    if capa is None:
                        capa = base64.b64encode(_jpeg(b, CAPA_LADO, CAPA_QUALIDADE)).decode()
                except Exception:
                    continue
            if not fotos:
                continue
            nome = f"galerias/{nome_arquivo(x['id'])}.json"
            (pasta / nome).write_text(json.dumps({"id": x["id"], "fotos": fotos}))
            indice["galerias"][x["id"]] = nome
            novas_capas[x["id"]] = capa

    carimbo = datetime.now().strftime("%Y%m%d%H%M")
    ids = list(novas_capas)
    for n in range(0, len(ids), CAPAS_POR_LOTE):
        nome = f"capas/{carimbo}-{n // CAPAS_POR_LOTE + 1:02d}.json"
        lote = {i: novas_capas[i] for i in ids[n:n + CAPAS_POR_LOTE]}
        (pasta / nome).write_text(json.dumps(lote))
        for i in lote:
            indice["capas"][i] = nome

    # tira o que não é mais acompanhado (o crawler esquece quem saiu há 60 dias)
    for tipo in ("capas", "galerias"):
        indice[tipo] = {i: a for i, a in indice[tipo].items() if i in imoveis}
    usados = set(indice["capas"].values()) | set(indice["galerias"].values())
    for arq in list((pasta / "capas").glob("*.json")) + list((pasta / "galerias").glob("*.json")):
        if f"{arq.parent.name}/{arq.name}" not in usados:
            arq.unlink()
    for i, x in imoveis.items():
        x["temFotos"] = i in indice["galerias"]

    indice["geradoEm"] = datetime.now().isoformat(timespec="seconds")
    arq_indice.write_text(json.dumps(indice, indent=1, sort_keys=True))
    total = sum(f.stat().st_size for f in pasta.rglob("*.json"))
    print(f"[fotos] {len(fila)} casas novas com fotos; {len(indice['galerias'])} no total; {total / 1e6:.1f} MB")
    return novas_capas
