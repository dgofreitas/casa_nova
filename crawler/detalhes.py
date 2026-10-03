"""Abre a página de cada anúncio para pegar a descrição e as fotos.

As páginas trazem também fotos de outros imóveis (sugestões, "veja também"),
então as fotos são filtradas pela pasta do imóvel quando o site organiza as
imagens assim; nos sites de URL opaca vale o JSON-LD ou a ordem da página.
"""
import base64
import html as H
import json
import os
import re

from bs4 import BeautifulSoup

from comum import ld_json, og_image

# no GitHub Actions o site guarda até 8 fotos por casa; no servidor, todas
MAX_FOTOS = int(os.environ.get("CASA_NOVA_MAX_FOTOS") or 8)
NAO_FOTO = re.compile(r"logo|icon|favicon|marca|whats|sprite|placeholder|avatar|selo|banner|"
                      r"settings/main-images|/static/|watermark|creci", re.I)
URL_IMG = re.compile(r"https?://[^\"'\s<>()\\,]+?\.(?:jpe?g|webp|png)(?:\?[^\"'\s<>()\\]*)?", re.I)


def _b64_brognoli(u):
    m = re.search(r"/fotos/[^/]+/([A-Za-z0-9+/=_-]+)", u)
    if not m:
        return ""
    s = m.group(1).split(".")[0]
    try:
        # vem codificado duas vezes
        s = base64.b64decode(s + "=" * (-len(s) % 4)).decode("latin-1")
        return base64.b64decode(s + "=" * (-len(s) % 4)).decode("latin-1")
    except Exception:
        return ""


def chave(u):
    """Identifica a qual imóvel a foto pertence, quando o endereço permite."""
    if not u:
        return None
    m = re.search(r"/fotos/(\d+)/", u)                      # Vista (vistahost, bewezy)
    if m and ("vista" in u or "bewezy" in u):
        return "v" + m.group(1)
    m = re.search(r"/pictures/(\d+)-", u)                    # Auxiliadora
    if m:
        return "a" + m.group(1)
    m = re.search(r"/properties/([0-9a-f-]{36})/", u)        # Tecimob (Daga)
    if m:
        return "t" + m.group(1)
    m = re.search(r"\.r2\.dev/brognoli/(\d+-\d+)/", u)     # Brognoli, site novo (out/2026)
    if m:
        return "b" + m.group(1)
    if "brognoli.com.br/fotos/" in u:
        m = re.search(r"/(\d+-\d+)/", _b64_brognoli(u))
        return "b" + m.group(1) if m else None
    return None


def normalizar(u):
    """Versão grande da foto e uma chave para tirar repetidas."""
    u = H.unescape(u)
    if "vistahost" in u:
        u = re.sub(r"_p(\.\w+)$", r"\1", u)
        return u, u
    if "bewezy.com" in u:
        base = u.split("?")[0]
        return base + "?width=1280", base
    if "brognoli.com.br/fotos/" in u:
        dados = re.search(r"/fotos/[^/]+/(.+)$", u).group(1)
        return "https://www.brognoli.com.br/fotos/g/" + dados, dados.split(".")[0]
    if "tecimob.com.br" in u:
        # a versão reduzida é .webp numa subpasta; a original é .jpg em images/
        nome = re.sub(r"\.\w+$", "", u.rstrip("/").split("/")[-1])
        u = re.sub(r"/images/\d+x\d+/(?:outside/)?", "/images/", u)
        return re.sub(r"\.webp$", ".jpg", u), nome
    if "kenlo.io" in u:
        return u.replace("://imgs.", "://img."), u.split("kenlo.io")[-1]
    if "/pictures/thumbnail/" in u:
        u = u.replace("/pictures/thumbnail/", "/pictures/")
    return u, u.split("?")[0]


def _fotos_ld(html):
    out = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("@type") in ("RealEstateListing", "Product", "Residence", "SingleFamilyResidence", "House") \
                    or "image" in o:
                v = o.get("image") or o.get("photo")
                for x in (v if isinstance(v, list) else [v]):
                    if isinstance(x, str):
                        out.append(x)
                    elif isinstance(x, dict):
                        out.append(x.get("contentUrl") or x.get("url") or "")
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for d in ld_json(html):
        walk(d)
    return [u for u in out if u]


def _fotos_kenlo(html):
    """Sites Kenlo põem só 5 fotos no JSON-LD, mas a lista completa vem num JSON da página."""
    dec = json.JSONDecoder()
    for m in re.finditer(r'"photos":\s*(?=\[\s*\{"picture_full")', html):
        try:
            fotos, _ = dec.raw_decode(html, m.end())
        except ValueError:
            continue
        urls = [f.get("picture_full") for f in fotos if isinstance(f, dict) and f.get("picture_full")]
        if urls:
            return urls
    return []


def extrair_fotos(html, foto_lista=None, limite=MAX_FOTOS):
    if "kenlo.io" in html:
        kenlo = _fotos_kenlo(html)
        if len(kenlo) >= 3:
            return [normalizar(u)[0] for u in kenlo[:limite]]
    texto = H.unescape(html).replace("\\/", "/").replace("\\u0026", "&")
    capa = og_image(html) or foto_lista
    todas = [u for u in URL_IMG.findall(texto) if not NAO_FOTO.search(u)]
    k = chave(capa) or chave(foto_lista)
    if not k:
        # sem capa conhecida (imóvel cadastrado pelo link): a galeria da casa vem
        # antes das sugestões de outros imóveis na página
        k = next((chave(u) for u in todas if chave(u)), None)
    if k:
        candidatas = [u for u in todas if chave(u) == k]
    else:
        ld = [u for u in _fotos_ld(html) if not NAO_FOTO.search(u)]
        if len(ld) >= 3:
            candidatas = ld
        else:
            host = re.match(r"https?://([^/]+)", capa or (todas[0] if todas else "x://")).group(1)
            dom = host.split(".", 1)[-1]
            candidatas = [u for u in todas if dom in u]
        if capa:
            candidatas = [capa] + candidatas
    # logotipos costumam ser PNG; se há fotos JPG/WEBP suficientes, fica só com elas
    if sum(1 for u in candidatas if not re.search(r"\.png", u, re.I)) >= 3:
        candidatas = [u for u in candidatas if not re.search(r"\.png", u, re.I)]
    vistas, out = set(), []
    for u in candidatas:
        grande, ch = normalizar(u)
        if ch in vistas:
            continue
        vistas.add(ch)
        out.append(grande)
        if len(out) >= limite:
            break
    return out


TITULO_DESC = re.compile(r"^\s*(descri[çc][ãa]o( do im[óo]vel| completa)?|sobre o im[óo]vel|"
                         r"sobre este im[óo]vel|detalhes do im[óo]vel)\s*:?\s*$", re.I)


def _limpar(t):
    t = re.sub(r"[ \t\r\f\v]+", " ", t or "")
    t = re.sub(r"\n\s*\n+", "\n", t).strip()
    t = re.sub(r"^(descri[çc][ãa]o( do im[óo]vel| completa)?|sobre o im[óo]vel)\s*:?\s*", "", t, flags=re.I)
    return t[:4000]


def extrair_descricao(html):
    s = BeautifulSoup(html, "html.parser")
    for t in s(["script", "style", "noscript", "svg", "button", "form"]):
        t.decompose()
    candidatas = []
    ficha = s.select_one(".desc-ficha h2")  # Brognoli: título do anúncio e texto logo abaixo
    if ficha:
        tx = _limpar("\n".join([ficha.get_text(" ", strip=True)] +
                               [x.get_text("\n", strip=True) for x in ficha.find_next_siblings()]))
        if len(tx) >= 80:
            candidatas.append(tx)
    for sel in ["#descricao", ".box-description", "[class*=descricao]", "[id*=descricao]",
                ".about", "[class*=description]", "[itemprop=description]"]:
        for el in s.select(sel):
            tx = _limpar(el.get_text("\n", strip=True))
            if 80 <= len(tx) <= 6000:
                candidatas.append(tx)
        if candidatas:
            break
    if not candidatas:
        for no in s.find_all(string=TITULO_DESC):
            titulo = no.parent
            partes = []
            for irmao in titulo.next_siblings:  # inclui texto solto entre <br>
                nome = getattr(irmao, "name", None)
                if nome in ("h1", "h2", "h3", "h4", "legend", "fieldset") and "".join(partes).strip():
                    break
                partes.append(irmao.get_text("\n", strip=True) if nome else str(irmao))
            tx = _limpar("\n".join(partes))
            if len(tx) < 80 and titulo.parent:
                tx = _limpar(titulo.parent.get_text("\n", strip=True))
            if 80 <= len(tx) <= 6000:
                candidatas.append(tx)
    ld = [d.get("description") for d in ld_json(html) if isinstance(d, dict) and isinstance(d.get("description"), str)]
    candidatas += [_limpar(x) for x in ld if len(x) >= 80]
    m = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:)?description["\'][^>]+content=["\']([^"\']+)', html)
    if m:
        candidatas.append(_limpar(H.unescape(m.group(1))))
    candidatas = [c for c in candidatas if c]
    return max(candidatas, key=len) if candidatas else None


def detalhar(http, item):
    """Descrição e endereços das fotos de um anúncio (lista do crawler)."""
    html = http.html(item["link"])
    return {"descricao": extrair_descricao(html),
            "fotosOrigem": extrair_fotos(html, item.get("foto"))}
