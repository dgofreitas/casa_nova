"""Fotos quando o crawler roda no servidor: todas as fotos de todos os anúncios.

Tudo fica na pasta de dados (volume do Docker):

  fotos/<nome>.jpg        foto grande (até 1600 px)
  fotos/c/<nome>.jpg      a mesma foto reduzida, para capas e miniaturas
  fotos.json              {"urls": {url: {"arq": nome, "h": hash visual}},
                           "galerias": {grupo: [nome, ...]}, "geradoEm": ...}

Quando a mesma casa está em várias imobiliárias, a galeria do grupo junta as
fotos de todos os anúncios e tira as repetidas. A comparação é pelo desenho da
foto (hash visual), porque cada imobiliária reduz a foto para um tamanho diferente.
"""
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from PIL import Image

import fotos as fotos_github

GRANDE_LADO, GRANDE_QUALIDADE = 1600, 78
CAPA_LADO, CAPA_QUALIDADE = 560, 70
MESMA_FOTO = 6            # bits diferentes no hash de 64 bits para considerar a mesma foto
MARCA = "fotosCompletas"  # anúncio já aberto pedindo todas as fotos


def completar(http, imoveis, espera_por_fonte):
    """Abre os anúncios que ainda não foram lidos pedindo todas as fotos."""
    fotos_github.completar_detalhes(http, imoveis, espera_por_fonte,
                                    pendente=lambda x: not x.get(MARCA), marca=MARCA)


def hash_visual(im):
    """dHash de 64 bits: resiste a redução, compressão e pequenas mudanças de cor."""
    g = im.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for lin in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[lin * 9 + col] > px[lin * 9 + col + 1])
    return bits


def parecidas(h1, h2):
    return bin(h1 ^ h2).count("1") <= MESMA_FOTO


def _salvar(conteudo, pasta, nome):
    im = Image.open(io.BytesIO(conteudo))
    im = im.convert("RGB")
    h = hash_visual(im)
    grande = im.copy()
    grande.thumbnail((GRANDE_LADO, GRANDE_LADO))
    grande.save(pasta / f"{nome}.jpg", "JPEG", quality=GRANDE_QUALIDADE, optimize=True, progressive=True)
    im.thumbnail((CAPA_LADO, CAPA_LADO))
    im.save(pasta / "c" / f"{nome}.jpg", "JPEG", quality=CAPA_QUALIDADE, optimize=True, progressive=True)
    return h


def _nome(url):
    return hashlib.sha1(url.encode()).hexdigest()[:20]


def baixar(imoveis, dados):
    """Baixa as fotos que faltam, monta a galeria de cada grupo e apaga as que sobraram.

    Devolve {id do anúncio: bytes da capa} das casas que ganharam galeria agora.
    """
    dados = Path(dados)
    pasta = dados / "fotos"
    (pasta / "c").mkdir(parents=True, exist_ok=True)
    arq_indice = dados / "fotos.json"
    indice = json.loads(arq_indice.read_text()) if arq_indice.exists() else {}
    urls = indice.get("urls", {})
    antes = dict(indice.get("galerias", {}))

    ativos = {i: x for i, x in imoveis.items() if x.get("status") == "ativo" and x.get("fotosOrigem")}
    faltam = [u for x in ativos.values() for u in x["fotosOrigem"]
              if u not in urls or not (pasta / f"{urls[u]['arq']}.jpg").exists()]
    faltam = list(dict.fromkeys(faltam))

    def um(url):
        conteudo = fotos_github._baixar(url)
        if not conteudo:
            return url, None
        nome = _nome(url)
        try:
            return url, {"arq": nome, "h": format(_salvar(conteudo, pasta, nome), "016x")}
        except Exception:
            return url, None

    baixadas = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for url, info in pool.map(um, faltam):
            if info:
                urls[url] = info
                baixadas += 1

    # galeria de cada grupo: anúncio com mais fotos primeiro, depois as fotos novas dos outros
    grupos = {}
    for i, x in ativos.items():
        grupos.setdefault(x.get("grupo") or i, []).append(x)
    galerias = {}
    for g, membros in grupos.items():
        membros.sort(key=lambda x: (-len(x["fotosOrigem"]), x["id"]))
        lista, hashes = [], []
        for x in membros:
            for u in x["fotosOrigem"]:
                info = urls.get(u)
                if not info:
                    continue
                h = int(info["h"], 16)
                if any(parecidas(h, o) for o in hashes):
                    continue
                hashes.append(h)
                lista.append(info["arq"])
        if lista:
            galerias[g] = lista

    # apaga as fotos de anúncios que o crawler não acompanha mais
    usadas = {u for x in imoveis.values() for u in (x.get("fotosOrigem") or [])}
    urls = {u: i for u, i in urls.items() if u in usadas}
    nomes = {i["arq"] for i in urls.values()}
    apagadas = 0
    for f in list(pasta.glob("*.jpg")) + list((pasta / "c").glob("*.jpg")):
        if f.stem not in nomes:
            f.unlink()
            apagadas += 1

    for i, x in imoveis.items():
        x["temFotos"] = (x.get("grupo") or i) in galerias

    indice = {"urls": urls, "galerias": galerias, "geradoEm": datetime.now().isoformat(timespec="seconds")}
    tmp = arq_indice.with_suffix(".tmp")
    tmp.write_text(json.dumps(indice))
    tmp.replace(arq_indice)
    total = sum(f.stat().st_size for f in pasta.rglob("*.jpg"))
    print(f"[fotos] {baixadas} baixadas, {apagadas} apagadas; {len(galerias)} galerias, "
          f"{sum(len(v) for v in galerias.values())} fotos; {total / 1e6:.0f} MB")

    capas = {}
    for g, lista in galerias.items():
        if g in antes:
            continue
        for x in grupos[g]:
            capas[x["id"]] = (pasta / "c" / f"{lista[0]}.jpg").read_bytes()
    return capas
