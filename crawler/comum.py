"""Funções compartilhadas pelos leitores de cada imobiliária."""
import json
import re
import time
import unicodedata

import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

PRECO_MAX = 2_100_000

# Nome oficial de cada bairro e as formas como as imobiliárias escrevem.
BAIRROS = {
    "Itacorubi": ["itacorubi", "itacurubi"],
    "Santa Mônica": ["santa monica", "sta monica"],
    "Parque São Jorge": ["parque sao jorge", "pq sao jorge", "pq. sao jorge",
                         "itacorubi - parque sao jorge"],
    "Córrego Grande": ["corrego grande"],
}


class Http:
    """Sessão HTTP com espera entre pedidos e algumas tentativas."""

    def __init__(self, espera=1.0):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
        self.espera = espera
        self._ultimo = 0.0

    def get(self, url, **kw):
        erro = None
        for tentativa in range(3):
            falta = self.espera - (time.time() - self._ultimo)
            if falta > 0:
                time.sleep(falta)
            self._ultimo = time.time()
            try:
                r = self.s.get(url, timeout=40, **kw)
                if r.status_code == 429:
                    # pediu para ir mais devagar: espera o que o site mandar (ou 30s, 60s…)
                    erro = "o site pediu para esperar (HTTP 429)"
                    try:
                        pausa = int(r.headers.get("Retry-After", ""))
                    except ValueError:
                        pausa = 30 * (tentativa + 1)
                    time.sleep(min(pausa, 120))
                    continue
                if r.status_code in (500, 502, 503, 504):
                    erro = f"o site respondeu com erro (HTTP {r.status_code})"
                    time.sleep(5 * (tentativa + 1))
                    continue
                if r.status_code == 403:
                    raise RuntimeError("o site recusou o acesso (HTTP 403, proteção anti-robô)")
                if r.status_code >= 400:
                    raise RuntimeError(f"o site respondeu com erro (HTTP {r.status_code})")
                return r
            except requests.RequestException as e:
                erro = type(e).__name__
                time.sleep(5 * (tentativa + 1))
        raise RuntimeError(erro or "falha desconhecida")

    def html(self, url, **kw):
        r = self.get(url, **kw)
        r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else "utf-8"
        return r.text


def sem_acento(s):
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def bairro_oficial(texto):
    """Devolve o nome oficial se o texto citar um dos 4 bairros, senão None.

    Parque São Jorge é testado primeiro porque às vezes vem como
    "Itacorubi - Parque São Jorge".
    """
    t = re.sub(r"[^a-z ]+", " ", sem_acento(texto))
    t = re.sub(r"\s+", " ", t)
    for nome in ["Parque São Jorge", "Santa Mônica", "Córrego Grande", "Itacorubi"]:
        for v in BAIRROS[nome]:
            v = re.sub(r"[^a-z ]+", " ", v)
            v = re.sub(r"\s+", " ", v).strip()
            if re.search(r"\b" + v + r"\b", t):
                return nome
    return None


NAO_CASA = re.compile(r"apart|cobertura|terreno|lote\b|loteamento|sala|loja|comercial|galp|"
                      r"kitnet|studio|st[uú]dio|flat|loft|pr[eé]dio|ch[aá]cara|s[ií]tio|"
                      r"garagem|box|pousada|hotel|[aá]rea\b|garden|duplex|pavilh|dep[oó]sito")


def tipo_casa(categoria, titulo=""):
    """Classifica como Casa / Casa em condomínio / Sobrado, ou None se não for casa.

    A categoria informada pela imobiliária manda. Sem ela, vale o começo do
    título ("Casa com 3 quartos…", "Apartamento…").
    """
    c = sem_acento(categoria)
    base = c or sem_acento(titulo)[:60]
    if not base or "comercial" in base:
        return None
    eh_casa = re.search(r"\bcasas?\b|sobrado|geminad", base)
    if not eh_casa:
        return None
    # Se a categoria/título começa por outro tipo ("Terreno com casa antiga"), não é casa.
    outro = NAO_CASA.search(base)
    if outro and outro.start() < eh_casa.start():
        return None
    tudo = base + " " + sem_acento(titulo)
    if "sobrado" in base:
        return "Sobrado"
    if "condominio" in tudo:
        return "Casa em condomínio"
    return "Casa"


def num(v):
    """Converte '1.250.000,00', 'R$ 980.000', '150,34', 3 etc. em número."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v if v > 0 else None
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        n = float(s)
    except ValueError:
        return None
    if n <= 0:
        return None
    return int(n) if n.is_integer() else round(n, 2)


def achar(padrao, texto, grupo=1, conv=num):
    m = re.search(padrao, texto or "", re.I | re.S)
    if not m:
        return None
    return conv(m.group(grupo)) if conv else m.group(grupo).strip()


def ld_json(html):
    """Todos os blocos application/ld+json da página, já decodificados."""
    out = []
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            out.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            pass
    return out


def next_flight(html):
    """Junta o conteúdo de self.__next_f.push (páginas Next.js com App Router)."""
    partes = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html)
    return "".join(json.loads('"' + p + '"') for p in partes)


def objetos_json(texto, inicio):
    """Decodifica todos os objetos JSON que começam com o trecho `inicio`."""
    dec = json.JSONDecoder()
    out = []
    for m in re.finditer(re.escape(inicio), texto):
        try:
            o, _ = dec.raw_decode(texto, m.start())
            out.append(o)
        except json.JSONDecodeError:
            pass
    return out


def og_image(html):
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', html)
    return m.group(1) if m else None


def objetos_com(texto, marcador):
    """Objetos JSON que contêm a chave `marcador` (ex.: '"codigo":'), mesmo quando
    o objeto não começa por ela. Volta até a chave '{' que abre o objeto."""
    dec = json.JSONDecoder()
    out, inicios = [], set()
    for m in re.finditer(re.escape(marcador), texto):
        prof, i = 0, m.start()
        while i > 0:
            i -= 1
            ch = texto[i]
            if ch == "}":
                prof += 1
            elif ch == "{":
                if prof == 0:
                    break
                prof -= 1
        if i in inicios:
            continue
        inicios.add(i)
        try:
            o, _ = dec.raw_decode(texto, i)
            out.append(o)
        except json.JSONDecodeError:
            pass
    return out
