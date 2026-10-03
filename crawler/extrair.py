"""Lê a descrição do anúncio e tira os dados que o formulário do site usa.

Faz o papel que a IA ("Preencher com IA") fazia, só com regras de texto, e devolve
o mesmo formato que a página já sabe aplicar (applyIA): números, "sim"/null para
piscina, churrasqueira e gourmet junto da piscina, destaques e um resumo curto.
Só diz "sim" quando o anúncio fala; não inventa "não" por falta de menção.
"""
import re

from comum import num, sem_acento

NUMEROS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
           "sete": 7, "oito": 8}
QTD = r"(\d{1,2}|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito)"

# destaques que valem a pena no cartão (padrão no texto sem acento -> como aparece)
DESTAQUES = [
    (r"su[ií]te master|suite master", "Suíte master"),
    (r"closet", "Closet"),
    (r"lareira", "Lareira"),
    (r"energia solar|placas? solar|painel solar|fotovoltaic", "Energia solar"),
    (r"aquecimento (?:a gas|solar|central)|aquecedor a gas", "Aquecimento a gás/solar"),
    (r"hidromassagem|banheira", "Banheira/hidromassagem"),
    (r"home office|escritorio", "Escritório/home office"),
    (r"edicula", "Edícula"),
    (r"jardim", "Jardim"),
    (r"quintal", "Quintal"),
    (r"vista (?:para|pro|definitiva|panoramica|privilegiada|para o mar|mar)", "Vista"),
    (r"condominio fechado", "Condomínio fechado"),
    (r"portaria 24|seguranca 24", "Portaria 24h"),
    (r"ar[- ]condicionado|split", "Ar-condicionado"),
    (r"moveis planejados|mobiliad", "Móveis planejados"),
    (r"lavabo", "Lavabo"),
    (r"terraco|rooftop", "Terraço"),
    (r"aceita permuta|permuta", "Aceita permuta"),
    (r"aceita financiamento|financiamento", "Aceita financiamento"),
]


def _qtd(t, palavras):
    """Número antes de uma palavra ("3 suítes", "três dormitórios")."""
    m = re.search(QTD + r"\s+(?:amplas?\s+|grandes?\s+|confortaveis\s+)?(?:" + palavras + ")", t)
    if not m:
        return None
    v = m.group(1)
    return int(v) if v.isdigit() else NUMEROS.get(v)


def _valor(t, rotulo):
    """Valor em reais depois de um rótulo ("Condomínio: R$ 450", "IPTU R$ 1.890/ano")."""
    m = re.search(rotulo + r"[^\dr\n]{0,25}r\$\s*([\d.]+(?:,\d{2})?)", t)
    if not m:
        return None, ""
    return num(m.group(1)), t[m.end():m.end() + 20]


def _sem(t, coisa):
    return re.search(r"(?:sem|nao (?:possui|tem)|nao ha)\s+(?:\w+\s+){0,2}" + coisa, t) is not None


def extrair(descricao):
    if not descricao:
        return {}
    original = descricao
    t = sem_acento(descricao)
    r = {}

    # quantidades: só valem como palpite quando o anúncio não trouxe o número
    r["quartos"] = _qtd(t, r"quartos?|dormitorios?|dorms?")
    r["suites"] = _qtd(t, r"suites?")
    # banheiros pelo texto erra muito ("banheiro social" conta um só): fica de fora
    r["vagas"] = _qtd(t, r"vagas?|garagens?")

    cond, _ = _valor(t, r"condominio")
    if cond and cond < 10000:
        r["condominio"] = cond
    iptu, depois = _valor(t, r"iptu")
    if iptu:
        # o formulário pede IPTU por ano; só multiplica se o anúncio disser que é mensal
        r["iptu"] = round(iptu * 12) if re.match(r"\s*(?:/|por|ao)?\s*(?:mes|mensal)", depois) else iptu

    m = re.search(r"([\d.,]+)\s*m(?:²|2)\s*(?:de\s+)?(?:area\s+)?(?:privativa|construida|util|de constru)", t)
    if m:
        r["area"] = num(m.group(1))
    m = re.search(r"terreno\s+(?:de|com)\s+([\d.,]+)\s*m(?:²|2)|([\d.,]+)\s*m(?:²|2)\s*de\s+terreno", t)
    if m:
        r["areaTerreno"] = num(m.group(1) or m.group(2))

    # lazer: "sim" quando o anúncio menciona; null quando não fala (ou fala "espaço para piscina")
    tem_piscina = re.search(r"piscina", t) and not _sem(t, "piscina") \
        and not re.search(r"espaco (?:para|pra) (?:construir |fazer )?(?:uma )?piscina", t)
    if tem_piscina:
        r["piscina"] = "sim"
    tem_churras = re.search(r"churrasqueira|churrasq|parrilla|espaco gourmet com churras", t) and not _sem(t, "churrasqueira")
    if tem_churras:
        r["churrasqueira"] = "sim"
    if tem_piscina and (tem_churras or "gourmet" in t):
        # gourmet integrado: piscina e churrasqueira/gourmet na mesma frase (mesmo espaço de lazer)
        for frase in re.split(r"[.;\n!]", t):
            if "piscina" in frase and re.search(r"churrasq|gourmet|area de festas|lazer", frase):
                r["gourmetPiscina"] = "sim"
                break

    destaques = []
    for padrao, nome in DESTAQUES:
        if re.search(padrao, t) and nome not in destaques:
            destaques.append(nome)
    if destaques:
        r["destaques"] = destaques[:6]

    # resumo: a primeira frase do anúncio que não seja só um título em maiúsculas
    for frase in re.split(r"(?<=[.!?])\s+|\n", original.strip()):
        frase = frase.strip(" -•*")
        if len(frase) >= 40 and not frase.isupper():
            r["resumo"] = frase[:220] + ("…" if len(frase) > 220 else "")
            break

    return {k: v for k, v in r.items() if v not in (None, "", [])}
