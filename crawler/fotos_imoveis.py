"""Fotos dos imóveis da aba Imóveis (os que vocês cadastram, não só as Novidades).

Para cada imóvel com link de anúncio que ainda não foi lido (ou cujo link mudou):
  - se ele veio das Novidades, usa a galeria da casa (todas as imobiliárias juntas);
  - senão, abre o anúncio e pega todas as fotos e o texto.
As fotos que o imóvel já tem não se repetem (comparação pelo desenho da foto).

O crawler só lê o banco do site. O resultado vai para <dados>/fotos-imoveis.json e o
site (server/src/server.js) junta as fotos novas no imóvel. As fotos ficam em
<dados>/guardadas, que nunca é limpa.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from PIL import Image

import fotos as fotos_github
from detalhes import detalhar
from fotos_servidor import _nome, _salvar, hash_visual, parecidas

ARQ = "fotos-imoveis.json"


def _ler(dados):
    arq = Path(dados) / ARQ
    if arq.exists():
        try:
            return json.loads(arq.read_text())
        except ValueError:
            pass
    return {"resultados": {}}


def _gravar(dados, r):
    arq = Path(dados) / ARQ
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(r, ensure_ascii=False))
    tmp.replace(arq)


def pendentes(dados):
    """Imóveis com link que ainda não tiveram as fotos do anúncio buscadas."""
    db = Path(dados) / "casa-nova.db"
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try:
        linhas = con.execute("SELECT id, data FROM docs WHERE coll = 'imoveis'").fetchall()
        decisoes = dict(con.execute("SELECT id, data FROM docs WHERE coll = 'novidades'").fetchall())
    finally:
        con.close()
    feitos = _ler(dados)["resultados"]
    out = []
    for id_, data in linhas:
        d = json.loads(data)
        link = (d.get("link") or "").strip()
        if not link.startswith("http"):
            continue
        if (d.get("fotosAnuncio") or {}).get("link") == link:
            continue  # já lido e aplicado
        if (feitos.get(id_) or {}).get("link") == link:
            continue  # já lido, esperando o site aplicar
        if d.get("novidadeId") in decisoes:
            d["_anuncios"] = json.loads(decisoes[d["novidadeId"]]).get("anuncios") or []
        out.append((id_, d, link))
    return out


def _hash_existente(dados, foto):
    """Hash visual de uma foto que o imóvel já tem (enviada por vocês ou do crawler)."""
    dados = Path(dados)
    if foto.startswith("f/") or foto.startswith("c/"):
        nome = foto[2:]
        cands = [dados / "fotos" / f"{nome}.jpg", dados / "guardadas" / f"{nome}.jpg"]
    else:
        cands = [dados / "arquivos" / foto]
    for c in cands:
        if c.exists():
            try:
                return hash_visual(Image.open(c))
            except Exception:
                return None
    return None


def _galeria_da_novidade(dados, d):
    """Fotos da casa nas Novidades: a galeria do grupo, já baixada pelo crawler."""
    arq, arq_casas = Path(dados) / "fotos.json", Path(dados) / "casas.json"
    if not d.get("novidadeId") or not arq.exists() or not arq_casas.exists():
        return None
    indice = json.loads(arq.read_text())
    anuncios = json.loads(arq_casas.read_text()).get("imoveis", {})
    # a decisão guarda os anúncios da casa; a galeria é do grupo de qualquer um deles
    lista = None
    for a in [d["novidadeId"]] + d.get("_anuncios", []):
        g = (anuncios.get(a) or {}).get("grupo") or a
        lista = indice.get("galerias", {}).get(g)
        if lista:
            break
    if not lista:
        return None
    hashes = {i["arq"]: int(i["h"], 16) for i in indice.get("urls", {}).values()}
    pasta, guardadas = Path(dados) / "fotos", Path(dados) / "guardadas"
    (guardadas / "c").mkdir(parents=True, exist_ok=True)
    out = []
    for nome in lista:
        for sub in ("", "c"):
            de, para = pasta / sub / f"{nome}.jpg", guardadas / sub / f"{nome}.jpg"
            if de.exists() and not para.exists():
                para.write_bytes(de.read_bytes())
        if nome in hashes:
            out.append((nome, hashes[nome]))
    return out


def _do_anuncio(http, dados, link):
    """Abre o anúncio, baixa todas as fotos para guardadas/ e devolve (fotos, texto)."""
    d = detalhar(http, {"link": link})
    guardadas = Path(dados) / "guardadas"
    (guardadas / "c").mkdir(parents=True, exist_ok=True)
    out = []
    for url in d.get("fotosOrigem") or []:
        conteudo = fotos_github._baixar(url)
        if not conteudo:
            continue
        nome = _nome(url)
        try:
            out.append((nome, _salvar(conteudo, guardadas, nome)))
        except Exception:
            continue
    return out, d.get("descricao")


def processar(http, dados):
    """Lê os imóveis pendentes. Devolve quantos foram lidos."""
    lista = pendentes(dados)
    for id_, d, link in lista:
        r = {"link": link, "em": datetime.now().isoformat(timespec="seconds"), "novas": []}
        try:
            fotos = _galeria_da_novidade(dados, d) if d.get("origem") == "crawler" else None
            texto = None
            if fotos is None:
                fotos, texto = _do_anuncio(http, dados, link)
            vistos = [h for h in (_hash_existente(dados, f) for f in d.get("fotos") or []) if h is not None]
            for nome, h in fotos:
                if any(parecidas(h, o) for o in vistos):
                    continue
                vistos.append(h)
                r["novas"].append("f/" + nome)
            if texto:
                r["texto"] = texto
        except Exception as e:
            r["erro"] = str(e)[:200]
        atual = _ler(dados)
        atual["resultados"][id_] = r
        _gravar(dados, atual)
        print(f"[imóveis] {d.get('titulo') or id_}: {len(r['novas'])} fotos novas"
              + (f" (erro: {r['erro']})" if r.get("erro") else ""), flush=True)
    return len(lista)
