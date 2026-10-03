"""Um leitor por imobiliária (ou por plataforma, quando várias usam a mesma).

Cada leitor devolve uma lista de dicionários com os campos que conseguir:
codigo, link, titulo, categoria, preco, condominio, iptu, area, areaTerreno,
quartos, suites, banheiros, vagas, endereco, bairro, foto, lat, lng.
O filtro (casa, bairro, preço) e a comparação com o histórico ficam em crawl.py.
"""
import base64
import json
import re
import urllib.parse

from bs4 import BeautifulSoup

from comum import achar, ld_json, next_flight, num, objetos_com, objetos_json

BAIRROS_SLUG = ["itacorubi", "santa-monica", "parque-sao-jorge", "corrego-grande"]
BAIRROS_NOME = ["Itacorubi", "Santa Mônica", "Parque São Jorge", "Córrego Grande"]
MAX_PAGINAS = 40


def _texto(el, sep=" | "):
    return el.get_text(sep, strip=True) if el else ""


# ---------------------------------------------------------------- Kenlo
def kenlo(base):
    """Quadra, Bella Floripa e Invista: os 4 bairros numa URL, 12 casas por página.

    Cada site usa um modelo de cartão diferente, então a base é o JSON-LD
    (igual em todos) e o texto do cartão completa quartos, vagas etc.
    """
    def ler(http):
        url = (f"{base}/imoveis/a-venda/casa+casa-de-condominio+sobrado/florianopolis/"
               + "+".join(BAIRROS_SLUG))
        out, vistos = [], set()
        for pagina in range(1, MAX_PAGINAS + 1):
            html = http.html(url + (f"?pagina={pagina}" if pagina > 1 else ""))
            s = BeautifulSoup(html, "html.parser")
            itens = []
            for d in ld_json(html):
                if isinstance(d, dict) and d.get("@type") == "ItemList":
                    itens = [e.get("item") or {} for e in d.get("itemListElement", [])]
            novos = 0
            for it in itens:
                link = it.get("url") or ""
                if not link or link in vistos:
                    continue
                vistos.add(link)
                novos += 1
                href = urllib.parse.urlparse(link).path
                a = s.find("a", href=href)
                card = a
                while card is not None and not any("card" in c for c in (card.get("class") or [])
                                                   if c not in ("card-carousel",)):
                    card = card.parent
                t = _texto(card) if card else ""
                nome = it.get("name") or ""
                imgs = it.get("image") or []
                out.append({
                    "codigo": href.rstrip("/").split("/")[-1],
                    "link": link,
                    "titulo": nome.split(",")[0],
                    "categoria": achar(r"^(.*?) de [\d.,]+ m²", nome, conv=None) or nome.split(" ")[0],
                    "bairro": achar(r"m² (.*?) - Florian", nome, conv=None) or "",
                    "preco": num((it.get("offers") or {}).get("price")),
                    "area": achar(r"de ([\d.,]+) m²", nome) or achar(r"([\d.,]+)\s*m²", t),
                    "quartos": achar(r"-(\d+)-quartos?-", href) or achar(r"(\d+)\s*Quarto", t),
                    "suites": achar(r"(\d+)\s*Su[ií]te", t),
                    "banheiros": achar(r"(\d+)\s*Banheiro", t),
                    "vagas": achar(r"(\d+)\s*Vaga", t),
                    "condominio": achar(r"Condom[ií]nio[^R|]*\|?\s*R\$\s*([\d.,]+)", t),
                    "iptu": achar(r"IPTU\s*R\$\s*([\d.,]+)", t),
                    "foto": imgs[0] if isinstance(imgs, list) and imgs else (imgs if isinstance(imgs, str) else None),
                })
            if not itens or novos == 0 or f"pagina={pagina + 1}" not in html:
                break
        return out
    return ler


# ---------------------------------------------------------------- Vista / Loft (Next.js)
def vista_loft(base):
    """Liderança e Smolka: dados completos embutidos na página de busca."""
    def ler(http):
        q = {"finalidade": "Venda", "cidade": "Florianópolis",
             "bairro": ",".join(BAIRROS_NOME + ["Itacorubi - Parque São Jorge"])}
        out, vistos = [], set()
        for pagina in range(1, MAX_PAGINAS + 1):
            qp = dict(q, **({"page": str(pagina)} if pagina > 1 else {}))
            html = http.html(f"{base}/busca?" + urllib.parse.urlencode(qp))
            objs = objetos_json(next_flight(html), '{"Codigo":')
            novos = 0
            for o in objs:
                cod = str(o.get("Codigo"))
                if cod in vistos:
                    continue
                vistos.add(cod)
                novos += 1
                end = " ".join(x for x in [o.get("TipoEndereco"), o.get("Endereco")] if x)
                out.append({
                    "codigo": cod,
                    "link": f"{base}/imovel/{cod}",
                    "titulo": (o.get("TituloSite") or "").strip().capitalize(),
                    "categoria": o.get("Categoria") or "",
                    "bairro": o.get("Bairro") or o.get("BairroComercial") or "",
                    "preco": num(o.get("ValorVenda")),
                    "area": num(o.get("AreaPrivativa")),
                    "areaTerreno": num(o.get("AreaTotal")),
                    "quartos": num(o.get("Dormitorios")),
                    "suites": num(o.get("Suites")),
                    "banheiros": num(o.get("TotalBanheiros")),
                    "vagas": num(o.get("Vagas")),
                    "endereco": end,
                    "foto": o.get("FotoDestaque"),
                    "lat": o.get("Latitude"), "lng": o.get("Longitude"),
                })
            # a primeira página nem sempre traz o link da próxima: segue até não vir nada novo
            if novos == 0:
                break
        return out
    return ler


# ---------------------------------------------------------------- Tecimob (Daga)
def tecimob(dominio):
    """Daga: a API do site devolve todos os imóveis de uma vez."""
    def ler(http):
        r = http.get("https://api-sites.tecimob.com.br/api/properties",
                     headers={"x-domain": dominio, "Accept": "application/json"})
        out = []
        for p in r.json().get("data", []):
            if (p.get("transaction") or "").upper() != "VENDA":
                continue
            rooms, areas, addr = p.get("rooms") or {}, p.get("areas") or {}, p.get("address") or {}
            val = lambda d, k: num((d.get(k) or {}).get("value")) if isinstance(d.get(k), dict) else None
            maps = p.get("maps") or {}
            out.append({
                "codigo": str(p.get("reference") or p.get("id")),
                "link": f"https://{dominio}/imovel/{p.get('url')}",
                "titulo": p.get("title_formatted") or "",
                "categoria": (p.get("url") or "").split("-a-venda")[0].replace("-", " "),
                "bairro": (addr.get("formatted") or "").split(" - ")[0],
                "preco": num(p.get("price")),
                "condominio": num(p.get("condominium_price")),
                "iptu": num(p.get("territorial_tax_price")),
                "area": val(areas, "primary_area") or val(areas, "private_area") or val(areas, "built_area"),
                "areaTerreno": val(areas, "total_area") or val(areas, "lot_area"),
                "quartos": val(rooms, "bedroom"),
                "suites": val(rooms, "suite"),
                "banheiros": val(rooms, "bathroom"),
                "vagas": val(rooms, "garage"),
                "endereco": " ".join(x for x in [addr.get("street"), addr.get("street_number")] if x),
                "lat": maps.get("latitude"), "lng": maps.get("longitude"),
            })
        return out
    return ler


# ---------------------------------------------------------------- Auxiliadora Predial
def auxiliadora(http):
    base = "https://www.auxiliadorapredial.com.br"
    out, vistos = [], set()
    for slug in BAIRROS_SLUG:
        for pagina in range(1, MAX_PAGINAS + 1):
            url = f"{base}/comprar/residencial/sc+florianopolis+{slug}?tipoImovel=casa"
            if pagina > 1:
                url += f"&page={pagina}"
            html = http.html(url)
            objs = objetos_com(next_flight(html), '"valores":{"valor"')
            objs = [o for o in objs if isinstance(o, dict) and o.get("codigo") and o.get("valores")]
            novos = 0
            for o in objs:
                cod = str(o["codigo"])
                if cod in vistos:
                    continue
                vistos.add(cod)
                novos += 1
                v, e = o.get("valores") or {}, o.get("endereco") or {}
                fotos = o.get("fotos") or o.get("imagens") or []
                foto = fotos[0] if fotos and isinstance(fotos[0], str) else None
                out.append({
                    "codigo": cod,
                    "link": o.get("link") or f"{base}/imovel/venda/{cod}",
                    "titulo": o.get("titulo") or f"{(o.get('categoria') or {}).get('nome', 'Casa')} em {(e.get('bairro') or {}).get('nome', '')}",
                    "categoria": (o.get("categoria") or {}).get("nome", ""),
                    "bairro": (e.get("bairro") or {}).get("nome", ""),
                    "preco": num(v.get("valor")),
                    "condominio": num(v.get("valorCondominio")) if (v.get("valorCondominio") or 0) > 1 else None,
                    "iptu": num(v.get("valorIptu")),
                    "area": num(o.get("areaPrivativa")),
                    "areaTerreno": num(o.get("areaTotal")),
                    "quartos": num(o.get("dormitorios")),
                    "suites": num(o.get("suites")),
                    "banheiros": num(o.get("banheiros")),
                    "vagas": num(o.get("vagas")),
                    "endereco": " ".join(str(x) for x in [e.get("tipoEndereco"), e.get("logradouro"), e.get("numero")] if x),
                    "foto": foto,
                    "caracteristicas": [c.get("nome") for c in o.get("caracteristicaImovel") or [] if isinstance(c, dict)],
                })
            if novos == 0 or len(objs) < 12:
                break
    return out


# ---------------------------------------------------------------- Cesar Vaz (vendas da Ibagy)
def cesar_vaz(http):
    base = "https://cesarvazimoveis.com.br"
    out, vistos = [], set()
    for bairro in BAIRROS_NOME:
        for tipo in ["Casa", "Casa em Condominio", "Sobrado"]:
            q = urllib.parse.urlencode({"municipio": "Florianópolis", "bairro": bairro, "tipo": tipo})
            s = BeautifulSoup(http.html(f"{base}/imoveis/busca?{q}"), "html.parser")
            for h3 in s.select("h3.pull-left"):
                a = h3.find("a", href=True)
                if not a:
                    continue
                cod = a["href"].rstrip("/").split("/")[-1]
                if cod in vistos:
                    continue
                vistos.add(cod)
                card = h3.find_parent("div", class_="row")
                t = _texto(card)
                img = card.find("img") if card else None
                out.append({
                    "codigo": cod,
                    "link": a["href"],
                    "titulo": a.get_text(strip=True),
                    "categoria": tipo,
                    "bairro": (card.find("em").get_text(strip=True) if card and card.find("em") else bairro),
                    "quartos": achar(r"Dormit[óo]rios\s*\|?\s*(\d+)", t),
                    "banheiros": achar(r"Banheiros\s*\|?\s*(\d+)", t),
                    "vagas": achar(r"Vagas\s*\|?\s*(\d+)", t),
                    "area": achar(r"[ÁA]rea Privativa\s*\|?\s*([\d.,]+)", t),
                    "condominio": achar(r"Condom[ií]nio\s*\|?\s*R\$\s*([\d.,]+)", t),
                    "iptu": achar(r"IPTU\s*\|?\s*R\$\s*([\d.,]+)", t),
                    "preco": num(card.select_one("h3.text-success").get_text()) if card and card.select_one("h3.text-success") else None,
                    "foto": img.get("src") if img else None,
                })
    return out


# ---------------------------------------------------------------- Brognoli (também é o estoque da Dalton Andrade)
def brognoli(http):
    """Site novo (Next.js, out/2026): os anúncios vêm prontos em "initialProperties"."""
    base = "https://www.brognoli.com.br"
    out, vistos = [], set()
    for slug in BAIRROS_SLUG:
        for tipo in ("casa", "casa-em-condominio"):
            for pagina in range(1, MAX_PAGINAS + 1):
                url = f"{base}/venda/{tipo}/sc/florianopolis/{slug}" + (f"?pagina={pagina}" if pagina > 1 else "")
                try:
                    html = http.html(url)
                except RuntimeError as e:
                    if "404" in str(e):
                        break  # tipo sem nenhum imóvel no bairro
                    raise
                f = next_flight(html)
                links = {c: u for u, c in re.findall(r'(https://www\.brognoli\.com\.br/imovel/[a-z0-9-]+-cod-(\d+))', f)}
                novos = 0
                for o in objetos_com(f, '"operationType":"SALE"'):
                    cod = str(o.get("code") or "")
                    if not cod or cod in vistos:
                        continue
                    vistos.add(cod)
                    novos += 1
                    fotos = sorted(o.get("photos") or [], key=lambda x: x.get("order") or 0)
                    out.append({
                        "codigo": cod,
                        "link": links.get(cod) or f"{base}/imovel/cod-{cod}",
                        "titulo": o.get("title") or "",
                        "categoria": o.get("propertyTypeName") or "",
                        "bairro": o.get("neighborhoodName") or "",
                        "endereco": "",
                        "area": o.get("builtArea"),
                        "quartos": o.get("bedrooms"),
                        "suites": o.get("suites"),
                        "banheiros": o.get("bathrooms"),
                        "vagas": o.get("parkingSpaces"),
                        "preco": o.get("price"),
                        "lat": o.get("latitude"),
                        "lng": o.get("longitude"),
                        "foto": fotos[0]["url"] if fotos else None,
                    })
                if novos == 0:
                    break
    return out


# ---------------------------------------------------------------- Seiter (BuscaImo)
def seiter(http):
    base = "https://seiterimobiliaria.com.br"
    url = (f"{base}/imoveis/venda/casa+casa-de-condominio+casa-geminada+sobrado/florianopolis/"
           + "+".join("bairro-" + b for b in BAIRROS_SLUG))
    out, vistos = [], set()
    for pagina in range(1, MAX_PAGINAS + 1):
        s = BeautifulSoup(http.html(url + (f"?page={pagina}" if pagina > 1 else "")), "html.parser")
        cards = s.select("div.LI_ImovelInner")
        novos = 0
        for c in cards:
            a = c.select_one("a.Title")
            if not a:
                continue
            link = a["href"]
            if link in vistos:
                continue
            vistos.add(link)
            novos += 1
            t = _texto(c)
            end = c.select_one(".Endereco")
            end_partes = [x.strip() for x in _texto(end, "|").split("|") if x.strip() and x.strip() != ","] if end else []
            img = c.select_one("img.BannerImage")
            ref = _texto(c.select_one(".ImovelId .reference"), "").strip("() ")
            out.append({
                "codigo": ref or _texto(c.select_one(".ImovelId .id"), ""),
                "link": link,
                "titulo": a.get_text(strip=True),
                "categoria": _texto(c.select_one(".SubCategoria"), " "),
                # o endereço vem como "CEP, rua, nº, bairro, cidade…"; o filtro acha o bairro no texto todo
                "bairro": " ".join(end_partes),
                "endereco": next((p for p in end_partes if not p.startswith("CEP")), ""),
                "preco": achar(r"R\$\s*\|?\s*([\d.,]+)\s*\|?\s*Valor de Venda", t),
                "iptu": achar(r"R\$\s*\|?\s*([\d.,]+)\s*\|?\s*IPTU", t),
                "quartos": achar(r"(\d+)\s*\|?\s*Dormit", t),
                "suites": achar(r"(\d+)\s*\|?\s*Su[ií]te", t),
                "banheiros": achar(r"(\d+)\s*\|?\s*Banheiro", t),
                "vagas": achar(r"(\d+)(?:\s*~\s*\d+)?\s*\|?\s*Vaga", t),
                "area": achar(r"Privativo:\s*\|?\s*([\d.,]+)\s*m", t) or achar(r"[ÚU]til:\s*\|?\s*([\d.,]+)\s*m", t),
                "areaTerreno": achar(r"Terreno:\s*\|?\s*([\d.,]+)\s*m", t),
                "foto": img.get("src") if img else None,
            })
        if not cards or novos == 0:
            break
    return out


# ---------------------------------------------------------------- OnLiving (F1 Cia Imobiliária)
def onliving(http):
    base = "https://onliving.com.br/imoveis-para-venda/"
    # 71 Córrego Grande, 34 Itacorubi, 103 Parque São Jorge, 47 Santa Mônica
    # 9 Casa, 10 Casa em Condomínio, 91 Sobrado
    q = "?jsf=jet-engine:pesquisa&tax=cidade:71,34,103,47;tipo-de-imovel:9,10,91"
    out, vistos = [], set()
    for pagina in range(1, MAX_PAGINAS + 1):
        html = http.html(base + q + (f"&pagenum={pagina}" if pagina > 1 else ""))
        s = BeautifulSoup(html, "html.parser")
        itens = s.select(".jet-listing-grid__item")
        novos = 0
        for it in itens:
            a = it.find("a", href=re.compile(r"/imoveis/venda-"))
            if not a:
                continue
            link = a["href"]
            if link in vistos:
                continue
            vistos.add(link)
            novos += 1
            partes = [p.strip() for p in _texto(it).split("|")]
            t = " | ".join(partes)
            nums = [p for p in partes if re.fullmatch(r"\d+", p)]
            out.append({
                "codigo": achar(r"-(\d+)/?$", link, conv=None),
                "link": link,
                "bairro": partes[0] if partes else "",
                "categoria": partes[1] if len(partes) > 1 else "",
                "titulo": (partes[2] if len(partes) > 2 else "").replace("Imóvel á Venda – ", "").split(" – ")[0].strip(),
                # o cartão mostra a "Área Total", que nas casas é o terreno
                "areaTerreno": achar(r"([\d.,]+)\s*m²", t),
                "quartos": num(nums[0]) if len(nums) > 0 else None,
                "banheiros": num(nums[1]) if len(nums) > 1 else None,
                "vagas": num(nums[2]) if len(nums) > 2 else None,
                "preco": achar(r"R\$\s*([\d.,]+)", t),
            })
        paginas = achar(r'"max_num_pages":(\d+)', html)
        if not itens or novos == 0 or (paginas and pagina >= paginas):
            break
    return out


# ---------------------------------------------------------------- Duda Imóveis
def duda(http):
    base = "https://www.dudaimoveis.com.br"
    # Ids internos do site: cidade 2 = Florianópolis; bairros 160 Córrego Grande,
    # 215 Itacorubi, 427 Santa Mônica (Parque São Jorge não existe na lista deles);
    # tipos 3 Casa, 10 Casa em Condomínio, 18 Sobrado.
    filtro = {"finalidade": "comprar", "city": "2", "bairro": ["160", "215", "427"],
              "tipo_imovel": ["3", "10", "18"]}
    f = urllib.parse.quote(base64.b64encode(json.dumps(filtro).encode()).decode())
    out, vistos = [], set()
    for pagina in range(1, MAX_PAGINAS + 1):
        if pagina == 1:
            url = f"{base}/comprar/florianopolis?filters={f}"
        else:
            url = f"{base}/imoveis-paginacao/comprar/florianopolis?filters={f}&page={pagina}&cache=true"
        s = BeautifulSoup(http.html(url), "html.parser")
        itens = s.select("li.imovel")
        novos = 0
        for it in itens:
            a = it.find("a", href=re.compile(r"^/imovel/\d+"))
            if not a:
                continue
            cod = a["href"].split("/")[2]
            if cod in vistos:
                continue
            vistos.add(cod)
            novos += 1
            # o HTML do site deixa os cartões aninhados; fico só com o texto deste
            t = _texto(it).split(" | Cód. ")[0]
            img = it.find("img")
            partes = [p.strip() for p in t.split("|")]
            local = next((p for p in partes if "/SC" in p), "")
            out.append({
                "codigo": cod,
                "link": base + a["href"],
                "titulo": partes[2] if len(partes) > 2 and "/SC" not in partes[2] else "Casa",
                # a busca já pede só Casa, Casa em Condomínio e Sobrado
                "categoria": "Sobrado" if "sobrado" in t.lower() else "Casa",
                "bairro": local.split(" - ")[0],
                "area": achar(r"([\d.,]+)m²\s*\|\s*Privativo", t) or achar(r"([\d.,]+)m²", t),
                "areaTerreno": achar(r"([\d.,]+)m²\s*\|\s*Total", t),
                "quartos": achar(r"(\d+)\s*(?:quarto|dorm)", t),
                "suites": achar(r"(\d+)\s*su[ií]te", t),
                "banheiros": achar(r"(\d+)\s*bwc", t),
                "vagas": achar(r"(\d+)\s*vaga", t),
                "preco": achar(r"Comprar\s*\|\s*R\$\s*([\d.,]+)", t),
                "condominio": achar(r"Condom[ií]nio:\s*R\$\s*([\d.,]+)", t),
                "foto": img.get("src") if img else None,
            })
        if not itens or novos == 0:
            break
    return out


FONTES = {
    "daga": ("Daga Imóveis", tecimob("dagaimoveis.com.br")),
    "quadra": ("Quadra Imobiliária", kenlo("https://www.quadraimobiliaria.com.br")),
    "bella": ("Bella Floripa Imóveis", kenlo("https://www.bellafloripaimoveis.com.br")),
    "invista": ("Invista Imóveis", kenlo("https://www.imobiliariainvista.com.br")),
    "lideranca": ("Liderança Imobiliária", vista_loft("https://liderancaimobiliaria.com.br")),
    "smolka": ("Smolka Imóveis", vista_loft("https://smolkaimoveis.com.br")),
    "auxiliadora": ("Auxiliadora Predial", auxiliadora),
    "cesarvaz": ("Cesar Vaz", cesar_vaz),
    "brognoli": ("Brognoli / Dalton Andrade", brognoli),
    "seiter": ("Seiter Imobiliária", seiter),
    "onliving": ("OnLiving (F1)", onliving),
    "duda": ("Duda Imóveis", duda),
}
