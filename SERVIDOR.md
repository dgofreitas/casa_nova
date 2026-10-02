# Casa Nova no servidor

O site e o crawler rodam no mesmo servidor do moneyTrackr e do Contopia (Oracle, ARM),
em https://minhacasanova.duckdns.org.

```
casa-nova-crawler ──► volume casa_nova_dados ◄── casa-nova-app ◄── Caddy do moneyTrackr (HTTPS)
   (Python, busca       casas.json, fotos/,        (Node: página,
    nos horários)       casa-nova.db, arquivos/     API, login)
```

- **casa-nova-crawler** busca às 7h, 12h, 17h e 22h, ou na hora quando alguém clica
  em **Buscar agora**. Guarda todas as fotos de cada anúncio e, quando a mesma casa
  está em várias imobiliárias, junta as fotos de todas e tira as repetidas.
- **casa-nova-app** serve a página, o login (Diogo e Cinthia), o banco (SQLite) e as fotos.
  A página é a mesma `site/casa-nova.html` do Claude: o arquivo `server/public/shim.js`
  recria, sobre a API do servidor, as funções que ela usava do Claude.
- No servidor não há "Preencher com IA". O texto do anúncio fica pronto para copiar.

## Publicar

Cada mudança em `server/`, `site/`, `crawler/` ou `docker-compose.yml` no branch
principal dispara **Publicar no servidor** (`.github/workflows/deploy.yml`). Esse
workflow monta as imagens, manda para o GHCR e reinicia os containers.

Segredos do repositório (Settings → Secrets and variables → Actions):

| Segredo | O que é |
|---|---|
| `SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY` | os mesmos do Contopia |
| `SENHA_DIOGO`, `SENHA_CINTHIA` | as senhas de cada um no site (sem aspas simples) |

O endereço chega ao site por um bloco no `caddy/Caddyfile` do moneyTrackr.

## Passar do site antigo (Claude) para o servidor

1. Com o site novo no ar, o Diogo entra e clica em **Importar do site antigo**,
   escolhendo o arquivo de migração (imóveis, decisões, documentos e arquivos).
2. Depois disso, o GitHub Actions deixa de buscar (o crawler do servidor assume,
   inclusive os avisos no Telegram) e o Apps Script do Google pode ser apagado.

## Rodar no computador

```bash
CASA_NOVA_DADOS=./dados CASA_NOVA_MAX_FOTOS=80 python crawler/crawl.py --dados ./dados --sem-telegram
CASA_NOVA_DADOS=./dados SENHA_DIOGO=teste node server/src/server.js   # http://localhost:3000
```
