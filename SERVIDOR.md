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
- Os imóveis da aba **Imóveis** também ganham todas as fotos: o crawler abre o link do
  anúncio de cada imóvel (os que vieram das Novidades usam a galeria da casa) e junta
  as fotos que faltam, sem repetir as que o imóvel já tem. Vale para imóveis novos e
  para quando o link muda. Sites que bloqueiam robôs (Viva Real, ZAP) ficam de fora.
- Uma busca interrompida (deploy, servidor reiniciado) recomeça sozinha, e as fotos
  são gravadas a cada 10 anúncios, então aparecem no site aos poucos.
- Sites que recusam o robô (HTTP 403) ganham mais duas tentativas: imitando a conexão
  do Chrome e, se ainda assim recusarem, saindo pelo **casa-nova-warp** (Cloudflare
  WARP, grátis), porque alguns recusam o endereço do servidor da Oracle. Só o crawler
  usa o WARP, e só para esses sites. Se o WARP também for recusado, o plano B é sair
  pela internet de casa (Raspberry com Tailscale), trocando `CASA_NOVA_PROXY`.
- **casa-nova-app** serve a página, o login (Diogo e Cinthia), o banco (SQLite) e as fotos.
  A página é a mesma `site/casa-nova.html` do Claude: o arquivo `server/public/shim.js`
  recria, sobre a API do servidor, as funções que ela usava do Claude.
- No servidor não há "Preencher com IA". No lugar dela, o crawler lê a descrição de cada
  anúncio (`crawler/extrair.py`) e tira piscina, churrasqueira, gourmet junto da piscina,
  condomínio, IPTU, áreas, quartos, suítes, vagas, destaques e um resumo. Ao marcar
  **Tenho interesse** o imóvel já nasce preenchido, e os imóveis cadastrados pelo link
  também são completados. Só entram os campos vazios, uma vez: se vocês apagarem um
  campo, ele não volta. O texto do anúncio continua pronto para copiar.

## Publicar

Cada mudança em `server/`, `site/`, `crawler/` ou `docker-compose.yml` no branch
principal dispara **Publicar no servidor** (`.github/workflows/deploy.yml`). Esse
workflow monta as imagens, manda para o GHCR e reinicia os containers.

Segredos do repositório (Settings → Secrets and variables → Actions):

| Segredo | O que é |
|---|---|
| `SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY` | os mesmos do Contopia |
| `SENHA_DIOGO`, `SENHA_CINTHIA` | as senhas de cada um no site (sem aspas simples) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | o robô do Telegram (já existiam) |

O endereço chega ao site por um bloco no `caddy/Caddyfile` do moneyTrackr.

## Vindo do site antigo (Claude)

Os imóveis, as decisões, o checklist e os arquivos do site antigo entram pelo botão
**Importar do site antigo** (só aparece para o Diogo). O crawler do GitHub Actions foi
desligado: o do servidor busca e manda os avisos no Telegram. O Apps Script do Google
e os arquivos `casa-nova-*.json` no Drive não são mais usados e podem ser apagados.

## Rodar no computador

```bash
CASA_NOVA_DADOS=./dados CASA_NOVA_MAX_FOTOS=80 python crawler/crawl.py --dados ./dados --sem-telegram
CASA_NOVA_DADOS=./dados SENHA_DIOGO=teste node server/src/server.js   # http://localhost:3000
```
