# Crawler do Casa Nova

Procura casas à venda no Itacorubi, Santa Mônica, Parque São Jorge e Córrego Grande,
até R$ 2,1 milhões, em 12 imobiliárias de Florianópolis. Roda sozinho no GitHub
Actions às 7h, 12h, 17h e 22h, avisa no Telegram e alimenta a aba **Novidades** do site.

```
GitHub Actions ──► data/casas.json + branch "fotos" ──► Telegram (resumo + álbum com as capas)
                          │
             Google Apps Script (de hora em hora)
                          ▼
   Google Drive: casa-nova-casas.json, casa-nova-fotos.json e a pasta "Casa Nova - fotos"
                          │
       site Casa Nova (conector do Google Drive) ──► aba Novidades
```

Nada disso usa a IA do Claude, então não gasta tokens.

## Imobiliárias lidas

| Imobiliária | Como é lida |
|---|---|
| Daga Imóveis | API do site (Tecimob) |
| Quadra, Bella Floripa, Invista | Página de busca (Kenlo) |
| Liderança, Smolka | Página de busca (Vista/Loft) |
| Auxiliadora Predial | Página de busca, um bairro por vez |
| Brognoli (é também o estoque da Dalton Andrade) | Página de busca, um bairro por vez |
| Cesar Vaz (faz as vendas da Ibagy) | Página de busca, um bairro por vez |
| Seiter | Página de busca |
| OnLiving (F1) | Página de busca |
| Duda Imóveis | Página de busca (Parque São Jorge não existe no site deles) |

Ficaram de fora: Creditoreal, imoveis-sc.com.br e Viva Real (bloqueiam robôs).

## Fotos e descrição

Na primeira vez que vê um anúncio, o crawler abre a página dele e guarda o texto da
descrição e até 8 fotos, reduzidas (capa de 560 px e galeria de 960 px). Uma casa
anunciada por várias imobiliárias ganha fotos uma vez só. As fotos ficam no branch
`fotos` do repositório, que é refeito a cada busca (sem histórico, para não crescer).

Nos sites Kenlo (Quadra, Bella, Invista) as fotos vêm da lista completa da página,
e não das 5 do resumo. Quando uma imobiliária passa a mostrar mais fotos, o crawler
refaz a galeria daquela casa (sem repetir o aviso no Telegram).

Sempre que alguém com o Google Drive conectado abre o site, ele traz para o próprio
armazenamento primeiro as capas e depois as galerias, uma casa por vez. Cada casa
fica salva assim que chega, então dá para fechar a página no meio: na próxima vez ele
continua de onde parou. Quem clica numa foto passa na frente. Ao marcar **Tenho
interesse**, as fotos e o texto do anúncio vão junto para Imóveis, e o texto já fica
pronto em "Preencher com IA".

## Regras

- **Só casas residenciais**: casa, casa em condomínio, sobrado, geminada.
- **Preço**: entra até R$ 2.100.000. Acima de R$ 1.900.000 aparece o selo "negociar".
- **Mesma casa em várias imobiliárias** vira um cartão só: mesmo bairro e quartos,
  área e preço até 5% de diferença e, quando os dois anúncios dizem a rua, a mesma
  rua e o mesmo número (número diferente só vale se área e preço forem idênticos,
  porque aí é erro de digitação).
- **Saiu do ar**: só depois de 3 buscas seguidas sem aparecer, e nunca quando
  o site da imobiliária falhou.
- **Primeira busca**: vira a base inicial. O Telegram recebe um resumo, e não 100 avisos.

## Configuração (uma vez só)

### 1. Robô do Telegram

1. No Telegram, abra uma conversa com **@BotFather**, mande `/newbot` e siga as
   instruções. No fim ele entrega um **token** (algo como `123456:ABC-...`).
2. Crie um grupo com você e a Cinthia e adicione o robô novo ao grupo.
3. Mande qualquer mensagem no grupo (por exemplo "oi").
4. Abra no navegador `https://api.telegram.org/bot<TOKEN>/getUpdates`
   (troque `<TOKEN>` pelo token). Procure `"chat":{"id":-100...`: esse número,
   com o sinal de menos, é o **chat id** do grupo.

### 2. Segredos no GitHub

No repositório: **Settings → Secrets and variables → Actions → New repository secret**.
Crie dois:

- `TELEGRAM_BOT_TOKEN`: o token do passo 1
- `TELEGRAM_CHAT_ID`: o chat id do passo 1

### 3. Primeira busca

Em **Actions → Buscar casas novas → Run workflow**. Em uns 5 minutos chega a
mensagem no Telegram e o arquivo `data/casas.json` aparece no repositório.
Depois disso ele roda sozinho nos horários acima.

> O GitHub só agenda workflows que estão no branch principal do repositório.

### 4. Google Apps Script (leva o resultado até o Drive)

1. Abra https://script.google.com e clique em **Novo projeto**.
2. Apague o que estiver no editor e cole todo o conteúdo de
   [`apps-script.gs`](apps-script.gs).
3. Salve (ícone de disquete) com o nome "Casa Nova".
4. Na lista de funções ao lado de **Depurar**, escolha **instalar** e clique em **Executar**.
   O Google pede permissão para acessar o Drive e a internet: autorize.

Ele atualiza o arquivo `casa-nova-casas.json` no seu Drive de hora em hora.

### 5. Site

Abra o Casa Nova e vá na aba **Novidades**. Na primeira vez o site pede permissão
para usar o Google Drive: autorize. Basta o Diogo autorizar, porque o que ele trouxer
fica salvo e aparece também para a Cinthia.

## Rodar no computador

```bash
pip install -r crawler/requirements.txt
python crawler/crawl.py --sem-telegram            # todas as imobiliárias
python crawler/crawl.py --sem-telegram --so daga  # só uma
```

## Quando uma imobiliária muda o site

O Telegram avisa "Não consegui ler hoje: …" e a aba Novidades mostra a imobiliária
em vermelho em "Ver imobiliárias". O leitor de cada site fica em `fontes.py`.
