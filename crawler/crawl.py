"""Roda todas as imobiliárias, atualiza o histórico e avisa no Telegram.

Uso: python crawler/crawl.py [--sem-telegram] [--so daga,quadra] [--fotos PASTA]

Arquivos:
  data/casas.json   tudo o que o crawler acompanha (lido pelo site e pelo Apps Script)
"""
import argparse
import base64
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from comum import PRECO_MAX, Http, bairro_oficial, sem_acento, tipo_casa  # noqa: E402
from fontes import FONTES  # noqa: E402
import fotos  # noqa: E402
import telegram  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
ARQ = RAIZ / "data" / "casas.json"
FUSO = timezone(timedelta(hours=-3))
# Liderança e Smolka ficam no mesmo servidor e bloqueiam quem pede rápido demais
ESPERA = {"lideranca": 4.0, "smolka": 4.0}
AUSENCIAS_PARA_SAIR = 3      # rodadas seguidas sem aparecer até marcar "saiu do ar"
MANTER_SAIU_DIAS = 60        # depois disso o imóvel que saiu deixa de ser acompanhado
LIMITE_ORCAMENTO = 1_900_000
CAMPOS = ["titulo", "tipo", "preco", "condominio", "iptu", "area", "areaTerreno", "quartos",
          "suites", "banheiros", "vagas", "endereco", "bairro", "foto", "lat", "lng", "link"]


def agora():
    return datetime.now(FUSO).isoformat(timespec="seconds")


def carregar():
    if ARQ.exists():
        return json.loads(ARQ.read_text())
    return {"versao": 1, "rodadas": 0, "imoveis": {}, "fontes": {}}


def salvar(estado):
    ARQ.parent.mkdir(exist_ok=True)
    ARQ.write_text(json.dumps(estado, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def normalizar(fonte, bruto):
    bairro = bairro_oficial(bruto.get("bairro") or "") or bairro_oficial(bruto.get("titulo") or "")
    tipo = tipo_casa(bruto.get("categoria"), bruto.get("titulo"))
    if not bairro or not tipo or not bruto.get("codigo"):
        return None
    r = {k: bruto.get(k) for k in CAMPOS if bruto.get(k) not in (None, "", [])}
    r.update({"bairro": bairro, "tipo": tipo, "fonte": fonte, "codigo": str(bruto["codigo"]),
              "cidade": "Florianópolis - SC"})
    if not r.get("titulo"):
        r["titulo"] = f"{tipo} no {bairro}"
    return r


TIPOS_RUA = r"\b(rua|r|avenida|av|servidao|serv|sv|travessa|tv|rodovia|rod|estrada|alameda|al|via|sc|geral)\b"


NAO_SAO_RUAS = {"itacorubi", "santa monica", "parque sao jorge", "pq sao jorge", "itacorubi parque sao jorge",
                "corrego grande", "florianopolis", "centro", "trindade"}


def rua_numero(endereco):
    """("buriti", "379") a partir de "Avenida Buriti, 379"; partes ausentes viram None."""
    if not endereco:
        return None, None
    t = sem_acento(endereco)
    m = re.search(r"\b(\d{1,5})\b", t)
    numero = m.group(1) if m else None
    rua = re.sub(r"\d+", " ", t)
    rua = re.sub(TIPOS_RUA, " ", rua)
    rua = re.sub(r"\b(de|da|do|dos|das|e)\b", " ", rua)
    rua = re.sub(r"[^a-z ]", " ", rua)
    rua = " ".join(rua.split())
    # algumas imobiliárias põem o bairro ou a cidade no lugar da rua: isso não é endereço
    if not rua or rua in NAO_SAO_RUAS:
        return None, numero
    return rua, numero


def identicos(a, b):
    """Área e preço iguais (até 1%): número diferente na mesma rua é erro de digitação."""
    return all(a.get(k) and b.get(k) and abs(a[k] - b[k]) / max(a[k], b[k]) <= 0.01 for k in ("area", "preco"))


def mesma_rua(r1, r2):
    # "buriti" bate com "buriti", e "joao pio duarte silva" com "joao pio duarte"
    return r1 == r2 or r1 in r2 or r2 in r1


def distancia(a, b):
    """Diferença relativa entre dois anúncios, ou None se não parecem o mesmo imóvel.

    Precisa de área e preço batendo (até 5%), mesmo bairro, mesmo número de
    quartos quando os dois informam, imobiliárias diferentes e, quando os dois
    informam o endereço, a mesma rua e o mesmo número.
    """
    if a["fonte"] == b["fonte"] or a["bairro"] != b["bairro"]:
        return None
    if a.get("quartos") and b.get("quartos") and a["quartos"] != b["quartos"]:
        return None
    # endereço é o sinal mais forte: rua diferente, ou mesma rua com outro número, são casas diferentes
    rua_a, num_a = rua_numero(a.get("endereco"))
    rua_b, num_b = rua_numero(b.get("endereco"))
    if rua_a and rua_b:
        if not mesma_rua(rua_a, rua_b):
            return None
        if num_a and num_b and num_a != num_b and not identicos(a, b):
            return None
    total, usados = 0.0, set()
    for campo in ("area", "areaTerreno", "preco"):
        x, y = a.get(campo), b.get(campo)
        if x and y:
            d = abs(x - y) / max(x, y)
            if d > 0.05:
                return None
            total += d
            usados.add(campo)
    if not {"area", "preco"} <= usados:
        return None
    return total


def agrupar(imoveis):
    """Junta anúncios do mesmo imóvel em imobiliárias diferentes.

    Os pares mais parecidos se juntam primeiro, e um grupo só aceita alguém
    que seja parecido com todos os que já estão nele (e de outra imobiliária).
    Isso evita encadear as várias casas iguais de um mesmo condomínio.
    """
    ids = sorted(i for i, x in imoveis.items() if x.get("status") == "ativo")
    pares = []
    for n, a in enumerate(ids):
        for b in ids[n + 1:]:
            d = distancia(imoveis[a], imoveis[b])
            if d is not None:
                pares.append((d, a, b))
    grupo = {i: {i} for i in ids}
    for _, a, b in sorted(pares):
        ga, gb = grupo[a], grupo[b]
        if ga is gb:
            continue
        fontes_a = {imoveis[i]["fonte"] for i in ga}
        if fontes_a & {imoveis[i]["fonte"] for i in gb}:
            continue
        if all(distancia(imoveis[x], imoveis[y]) is not None for x in ga for y in gb):
            uniao = ga | gb
            for i in uniao:
                grupo[i] = uniao
    for i, x in imoveis.items():
        x["grupo"] = min(grupo[i]) if i in grupo else i


def rodar(so=None, pasta_fotos=None):
    estado = carregar()
    primeira = estado["rodadas"] == 0
    quando = agora()
    imoveis = estado["imoveis"]
    eventos = {"novos": [], "baixou": [], "subiu": [], "saiu": [], "voltou": []}
    http = Http(espera=1.0)

    for fonte, (nome, ler) in FONTES.items():
        if so and fonte not in so:
            continue
        info = estado["fontes"].setdefault(fonte, {"nome": nome})
        info["nome"] = nome
        t0 = time.time()
        http.espera = ESPERA.get(fonte, 1.0)
        try:
            brutos = ler(http)
            erro = None
        except Exception as e:  # um site fora do ar não derruba os outros
            brutos, erro = [], str(e)[:300]
        casas = [c for c in (normalizar(fonte, b) for b in brutos) if c]
        anterior = info.get("casas", 0)
        # 0 casas onde antes havia várias: provavelmente o site mudou ou falhou
        suspeito = not casas and anterior >= 3
        info.update({"quando": quando, "lidos": len(brutos), "segundos": round(time.time() - t0)})
        if erro or suspeito:
            info["ok"] = False
            info["erro"] = erro or "nenhuma casa encontrada (antes havia %d)" % anterior
            info["falhasSeguidas"] = info.get("falhasSeguidas", 0) + 1
            print(f"[{fonte}] FALHOU: {info['erro']}")
            continue
        info.update({"ok": True, "erro": None, "falhasSeguidas": 0, "casas": len(casas)})
        print(f"[{fonte}] {len(brutos)} lidos, {len(casas)} casas nos bairros")

        vistos = set()
        for c in casas:
            id_ = f"{fonte}:{c['codigo']}"
            if id_ in vistos:
                continue
            vistos.add(id_)
            velho = imoveis.get(id_)
            if velho is None:
                # só entra se couber no teto; sem preço entra para vocês olharem
                if c.get("preco") and c["preco"] > PRECO_MAX:
                    continue
                c.update({"id": id_, "primeiroVisto": quando, "ultimoVisto": quando, "status": "ativo",
                          "ausencias": 0, "historicoPreco": [{"data": quando, "preco": c.get("preco")}]})
                imoveis[id_] = c
                eventos["novos"].append(id_)
                continue
            if velho.get("status") == "saiu":
                eventos["voltou"].append(id_)
                velho.pop("saiuEm", None)
            p0, p1 = velho.get("preco"), c.get("preco")
            if p1 and p0 and p1 != p0:
                velho.setdefault("historicoPreco", []).append({"data": quando, "preco": p1})
                eventos["baixou" if p1 < p0 else "subiu"].append((id_, p0, p1))
            for k, v in c.items():
                if v not in (None, ""):
                    velho[k] = v
            velho.update({"ultimoVisto": quando, "status": "ativo", "ausencias": 0})

        # quem desta imobiliária não apareceu hoje
        for id_, x in list(imoveis.items()):
            if x["fonte"] != fonte or id_ in vistos or x.get("status") != "ativo":
                continue
            x["ausencias"] = x.get("ausencias", 0) + 1
            if x["ausencias"] >= AUSENCIAS_PARA_SAIR:
                x["status"] = "saiu"
                x["saiuEm"] = quando
                eventos["saiu"].append(id_)

    # esquece quem saiu há muito tempo
    limite = (datetime.now(FUSO) - timedelta(days=MANTER_SAIU_DIAS)).isoformat()
    for id_ in [i for i, x in imoveis.items() if x.get("status") == "saiu" and x.get("saiuEm", "") < limite]:
        del imoveis[id_]

    fotos.completar_detalhes(http, imoveis, ESPERA)
    agrupar(imoveis)
    capas_novas = fotos.gerar_fotos(imoveis, pasta_fotos) if pasta_fotos else {}
    estado["rodadas"] += 1
    estado["ultimaRodada"] = quando
    estado["eventos"] = {"quando": quando, "baseInicial": primeira,
                         **{k: [e if isinstance(e, str) else e[0] for e in v] for k, v in eventos.items()}}
    salvar(estado)
    return estado, eventos, primeira, capas_novas


# ---------------------------------------------------------------- Telegram
def brl(v):
    return "R$ " + f"{v:,.0f}".replace(",", ".") if v else "sem preço"


def linha(x):
    partes = [x["tipo"]]
    if x.get("quartos"):
        partes.append(f"{x['quartos']} quartos")
    if x.get("area"):
        partes.append(f"{x['area']:g} m²")
    selo = " ⚠️ acima de 1,9 mi" if (x.get("preco") or 0) > LIMITE_ORCAMENTO else ""
    nome = FONTES[x["fonte"]][0]
    return (f"• <a href=\"{html.escape(x['link'])}\">{html.escape(', '.join(partes))}</a> — "
            f"{html.escape(x['bairro'])} · <b>{brl(x.get('preco'))}</b>{selo} · {html.escape(nome)}")


def legenda(x):
    partes = [x["tipo"]] + ([f"{x['quartos']} quartos"] if x.get("quartos") else []) + \
             ([f"{x['area']:g} m²"] if x.get("area") else [])
    return f"{', '.join(partes)} · {x['bairro']} · {brl(x.get('preco'))} · {FONTES[x['fonte']][0]}"


def mensagem(estado, eventos, primeira):
    im = estado["imoveis"]
    falhas = [f"{v['nome']}: {v.get('erro')}" for v in estado["fontes"].values() if v.get("ok") is False]
    if primeira:
        ativos = [x for x in im.values() if x.get("status") == "ativo"]
        grupos = {x["grupo"] for x in ativos}
        txt = [f"🏡 <b>Casa Nova: primeira busca feita</b>",
               f"Encontrei {len(grupos)} casas diferentes ({len(ativos)} anúncios) nos 4 bairros, até R$ 2,1 mi.",
               "Elas aparecem na aba Novidades do site. A partir de agora aviso só o que mudar."]
        if falhas:
            txt.append("\n⚠️ Não consegui ler: " + html.escape("; ".join(falhas)))
        return "\n".join(txt)

    # um aviso por casa (grupo), mesmo que várias imobiliárias anunciem
    def por_grupo(ids):
        vistos, out = set(), []
        for i in ids:
            g = im.get(i, {}).get("grupo", i)
            if g not in vistos:
                vistos.add(g)
                out.append(i)
        return out
    novos = por_grupo(eventos["novos"])
    blocos = []
    if novos:
        blocos.append(f"🏠 <b>{len(novos)} casa{'s' if len(novos) > 1 else ''} nova{'s' if len(novos) > 1 else ''}</b>\n"
                      + "\n".join(linha(im[i]) for i in novos))
    if eventos["baixou"]:
        blocos.append("📉 <b>Baixou de preço</b>\n" + "\n".join(
            linha(im[i]) + f" (era {brl(de)})" for i, de, para in eventos["baixou"]))
    if eventos["voltou"]:
        blocos.append("🔁 <b>Voltou a ser anunciada</b>\n" + "\n".join(linha(im[i]) for i in eventos["voltou"]))
    if eventos["saiu"]:
        blocos.append("🚪 <b>Saiu do ar</b> (vendida ou retirada)\n" + "\n".join(linha(im[i]) for i in eventos["saiu"]))
    novas_falhas = [v for v in estado["fontes"].values() if v.get("ok") is False and v.get("falhasSeguidas") == 1]
    if novas_falhas:
        blocos.append("⚠️ Não consegui ler hoje: " + html.escape(", ".join(v["nome"] for v in novas_falhas)))
    return "\n\n".join(blocos)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sem-telegram", action="store_true")
    ap.add_argument("--so", default="")
    ap.add_argument("--fotos", default="", help="pasta do branch de fotos")
    a = ap.parse_args()
    so = set(x for x in a.so.split(",") if x) or None
    estado, eventos, primeira, capas = rodar(so, a.fotos or None)
    msg = mensagem(estado, eventos, primeira)
    print("\n" + (msg or "(nada novo para avisar)"))
    if msg and not a.sem_telegram:
        telegram.enviar(msg)
        if not primeira:
            # as capas das casas novas, num álbum logo depois do resumo
            im = estado["imoveis"]
            album = [(base64.b64decode(capas[i]), legenda(im[i])) for i in eventos["novos"] if i in capas]
            telegram.album(album)


if __name__ == "__main__":
    main()
