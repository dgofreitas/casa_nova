"""Testa como um site responde ao crawler, a partir do servidor.

Uso (dentro do container do crawler):  python diagnostico.py https://site/ [outro…]
Para cada endereço tenta: direto, imitando o Chrome, e imitando o Chrome pelo
WARP (CASA_NOVA_PROXY). Mostra o código HTTP e se veio o desafio do Cloudflare.
"""
import os
import sys
import time

import requests
from curl_cffi import requests as cr

from comum import PROXY, UA

# só a tela de bloqueio; o script "challenge-platform" aparece também em páginas liberadas
DESAFIO = ("Just a moment", "Attention Required", "cf-browser-verification")


def resumo(nome, fazer):
    t0 = time.time()
    try:
        r = fazer()
        corpo = r.text[:200000]
        desafio = (r.status_code in (403, 503) and any(x in corpo for x in DESAFIO)) \
            or r.headers.get("cf-mitigated") == "challenge"
        print(f"  {nome:28} HTTP {r.status_code}  {len(r.content):>8} bytes  "
              f"{'DESAFIO DO CLOUDFLARE' if desafio else 'ok' if r.status_code < 400 else 'recusado'}"
              f"  ({time.time() - t0:.1f}s)")
    except Exception as e:
        print(f"  {nome:28} FALHOU: {type(e).__name__}: {str(e)[:150]}")


def main():
    urls = [u for u in sys.argv[1:] if u.startswith(("http://", "https://"))]
    if PROXY:
        print("Saída pelo WARP:")
        try:
            t = cr.get("https://www.cloudflare.com/cdn-cgi/trace", proxy=PROXY, timeout=30).text
            print("  " + " ".join(x for x in t.split() if x.split("=")[0] in ("ip", "loc", "warp", "colo")))
        except Exception as e:
            print(f"  WARP não respondeu: {e}")
    else:
        print("CASA_NOVA_PROXY não está configurado: o teste pelo WARP fica de fora.")
    for u in urls:
        print(f"\n{u}")
        resumo("direto", lambda: requests.get(u, headers={"User-Agent": UA, "Accept-Language": "pt-BR"}, timeout=40))
        resumo("imitando o Chrome", lambda: cr.get(u, impersonate="chrome", timeout=40))
        if PROXY:
            resumo("imitando o Chrome pelo WARP", lambda: cr.get(u, impersonate="chrome", proxy=PROXY, timeout=60))


if __name__ == "__main__":
    main()
