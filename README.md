# PromoBot — Agregador e Distribuidor de Promoções

O **PromoBot** captura promoções de várias fontes — canais/grupos do Telegram e caçadores automáticos de ofertas (Mercado Livre e Shopee) —, extrai e normaliza título, preços e desconto, converte os links para programas de afiliados (Amazon, Mercado Livre, Shopee), aplica filtros por nicho e anti-scam, evita duplicações e publica as ofertas formatadas no Telegram e no WhatsApp.

O núcleo de processamento é desacoplado da plataforma de mensageria: os adaptadores de entrada/saída (`Telegram`, `WhatsApp`) são plugáveis, e a lógica de negócio (`parser`, `filters`, `deduplicator`, `formatter`, `processor`) permanece idêntica para qualquer canal novo. Também inclui um **painel de controle**, um **dashboard** com filtros e um **site público** de ofertas.

---

## Funcionalidades

- **Caçador Mercado Livre** — faz scraping da página pública de ofertas (`/ofertas`, até N páginas), filtra por keywords, desconto mínimo e teto de preço, e publica as ofertas. Os links são gerados pelo **Gerador de Links oficial de afiliado** (links curtos `meli.la`) usando a sessão `ssid` da sua conta — o link publicado é sempre o **produto ofertado, com a headline atribuída**, nunca a lista `/social/<word>`.
- **Caçador Shopee** — busca via Open API de Afiliados Shopee por keyword, com filtros de desconto, vendas mínimas, avaliação e teto de preço.
- **Listener do Telegram** — captura mensagens de canais/grupos de origem via MTProto (Telethon).
- **Publicação dupla** — Telegram (Bot API) e **WhatsApp (Evolution API)**, com imagem quando disponível.
- **OAuth Mercado Livre** — fluxo completo (Authorization Code + PKCE) que guarda o refresh token para renovar o token e trocar cookies de forma segura.
- **Painel de controle (`/painel`)** — tags de afiliado, filtros (keywords viravam **chips**: adicione/remova termos de busca e exclusões), destino, configuração dos caçadores, envio de promoção de teste e pause do bot.
- **Dashboard (`/dashboard`)** — métricas e tabela de promoções com filtros por status/loja/categoria e modo escuro.
- **Site público** — catálogo de ofertas na raiz da aplicação ("Rufino Promo").
- **Settings dinâmicas** — valores editáveis ficam em tabela própria do PostgreSQL com cache em memória (TTL curto); alterações valem sem reiniciar o worker.
- **Resiliência** — fila Redis com retry/backoff, dead-letter, descarte de mensagens antigas (>15 min), média local em cache com limpeza automática.

---

## Arquitetura do Sistema

```
[ TelegramSource (Telethon) ]   [ Caçador MEL (scraping) ]   [ Caçador Shopee (Open API) ]
        │                               │                            │
        └───────────────► RawMessage ◄──┴────────────────────────────┘
                          │
                          ▼
              [ Fila Redis: RPUSH/BLPOP ]
                          │
                          ▼
              [ Worker de Processamento ]
                          │
                          ├─► 1. Parser (título, preços, loja, links, categoria)
                          ├─► 2. Categoria (allowlist de nicho: tecnologia/academia)
                          ├─► 3. Provedores de Afiliados (Amazon, MEL, Shopee)
                          ├─► 4. Deduplicação (URL canônica, ID de produto, hash, janela temporal)
                          ├─► 5. Filtros de Negócio (preço, desconto, lojas, categorias, anti-scam)
                          ├─► 6. Formatter (padronização com emojis e links de afiliado)
                          └─► 7. Publicador (Telegram Bot API + WhatsApp Evolution API)
                          │
                          ▼
              [ PostgreSQL: promoções, fontes, publicações, settings ]
```

### Principais Componentes
- **`app/adapters/`** — `TelegramSource` (listener MTProto via Telethon), `TelegramPublisher` (Bot API) e `WhatsAppPublisher` (Evolution API).
- **`app/core/`** — regras de negócio desacopladas: `parser.py` (preços em `R$ 1.899,00`, desconto, categoria), `deduplicator.py` (duplicatas por URL canônica/id/hash), `filters.py` (preço, lojas, categorias, keywords), `formatter.py`, `processor.py` (orquestrador) e `runtime_settings.py` (overrides dinâmicos).
- **`app/affiliates/`** — provedores modulares com registro dinâmico: `AmazonProvider`, `MercadoLivreProvider` (+ `MeliLinkMinter` para o mint oficial) e `ShopeeProvider`.
- **`app/finder/`** — caçadores automáticos: `MercadoLivreFinder` (scraping SSR) e `ShopeeFinder` (Open API).
- **`app/database/`** — SQLAlchemy 2.0 assíncrono e repositórios.
- **`app/workers/`** — fila Redis, worker resiliente (retry/dead-letter) e health server.
- **`app/api/`** — API FastAPI: painel, dashboard, site público, OAuth MEL, promoções e fontes.

---

## Stack Tecnológica

- **Linguagem**: Python 3.12
- **Framework Web**: FastAPI & Uvicorn
- **Banco de Dados**: PostgreSQL 16 com SQLAlchemy 2.0 (assíncrono)
- **Migrações**: Alembic
- **Mensageria & Cache**: Redis 7
- **Cliente Telegram**: Telethon 1.36+ & Telegram Bot API (`httpx` com retry)
- **WhatsApp**: Evolution API (REST)
- **Validação**: Pydantic v2 & Pydantic-Settings
- **Testes**: pytest & pytest-asyncio (suíte de 156 testes)
- **Containerização**: Docker Compose (desenvolvimento) e Docker Swarm (produção)

---

## Instalação e Inicialização

### Pré-requisitos
- Docker Engine 24+ e Docker Compose v2+.

### Passo a Passo (desenvolvimento local)

1. Clone o repositório e acesse o diretório:
   ```bash
   cd promobot
   ```

2. Crie o arquivo de ambiente a partir do modelo:
   ```bash
   cp .env.example .env
   ```

3. Crie os arquivos de segredos em `./secrets/` (o compose os monta em `/run/secrets/`). Veja `./secrets/README.md` para a lista completa. Exemplo:
   ```bash
   echo "sua_senha_segura" > ./secrets/postgres_password.txt
   chmod 600 ./secrets/postgres_password.txt
   ```

4. Edite o `.env` com suas credenciais (Telegram, afiliados, caçadores).

5. Construa e suba os containers:
   ```bash
   docker compose build
   docker compose up -d
   ```

6. Acompanhe os logs:
   ```bash
   docker compose logs -f
   ```

> **Produção**: o deploy em produção usa **Docker Swarm**, secret files, healthchecks e Cloudflare Tunnel. Veja o passo a passo completo em [`docs/PRODUCTION.md`](docs/PRODUCTION.md).

---

## Configuração

### Telegram

Obtenha `TELEGRAM_API_ID` e `TELEGRAM_API_HASH` em [https://my.telegram.org](https://my.telegram.org) → **API development tools**, e o token do bot com o [@BotFather](https://t.me/BotFather).

```env
TELEGRAM_API_ID=1234567
# TELEGRAM_API_HASH, TELEGRAM_BOT_TOKEN e TELEGRAM_SESSION_STRING (opcional) em ./secrets/
TELEGRAM_SESSION_NAME=promobot_session
TELEGRAM_LISTENER_ENABLED=true

# Canais de origem (separados por vírgula) e canal/grupo de destino
TELEGRAM_SOURCE_CHATS=@canal_ofertas_1,-1001987654321
TELEGRAM_TARGET_CHAT=-1001234567890
```

### WhatsApp (publicação via Evolution API)

```env
EVOLUTION_URL=https://sua-instancia.evolutionapi.com.br
EVOLUTION_INSTANCE=nome_da_instancia
EVOLUTION_API_KEY=chave_da_api
WHATSAPP_TARGET_CHAT=120363410512355040@g.us
WHATSAPP_ENABLED=1
WHATSAPP_WITH_IMAGE=1
```

### Caçador Mercado Livre

O caçador raspa a página pública de ofertas — **não** exige API de busca (o endpoint `/sites/MLB/search` foi descontinuado pelo Mercado Livre). O fluxo OAuth (`/mel/connect`) renova refresh token, e o mint oficial de links usa a sessão `ssid` da sua conta.

```env
MEL_API_CLIENT_ID=<app_id>
# MEL_API_CLIENT_SECRET em ./secrets/; sessão ssid via MERCADOLIVRE_SESSION_FILE
MEL_FINDER_ENABLED=1
MEL_FINDER_KEYWORDS=smart tv,smartphone,fone bluetooth,whey,creatina
MEL_FINDER_MIN_DISCOUNT=20.0
MEL_FINDER_MAX_PRICE=1500.0
MEL_FINDER_INTERVAL_MIN=10
MEL_FINDER_PAGES=3
MERCADOLIVRE_ROUTE=product
MERCADOLIVRE_MINT=true
MEL_OAUTH_REDIRECT_URI=https://seu-dominio/
```

As keywords e exclusões também podem ser editadas no painel via **chips** (adicionar/remover termos) — a lista vazia volta ao padrão do ambiente.

### Caçador Shopee (Open API)

```env
# SHOPEE_API_APP_ID e SHOPEE_API_SECRET em ./secrets/
SHOPEE_FINDER_ENABLED=0
SHOPEE_FINDER_KEYWORDS=fone bluetooth,smart watch,smart tv
SHOPEE_FINDER_MIN_DISCOUNT=20.0
SHOPEE_FINDER_MIN_SALES=50
SHOPEE_FINDER_MIN_RATING=4.0
SHOPEE_FINDER_MAX_PRICE=500.0
SHOPEE_FINDER_INTERVAL_MIN=30
```

---

## Provedores de Afiliados

| Loja | Variável no `.env` | Como funciona |
|---|---|---|
| **Amazon** | `AMAZON_TAG=minhatag-20` | Extrai o ASIN, limpa parâmetros de rastreamento antigos e injeta sua tag. Suporta links curtos `amzn.to`. |
| **Mercado Livre** | `MERCADOLIVRE_TAG=id`<br>`MERCADOLIVRE_WORD=word` | Extrai o MLB do produto e insere `matt_tool`/`matt_word`. Com `MERCADOLIVRE_MINT=true`, gera o **link oficial de afiliado** (`meli.la/…`) via sessão `ssid` — a headline é atribuída e o link abre **sempre o produto da oferta**, nunca a lista `/social`. |
| **Shopee** | `SHOPEE_TAG=tag`<br>`SHOPEE_APP_ID=app_id` | Resolve shortlinks (`shp.ee`, `br.shp.ee`, `s.shopee.com.br`) e injeta o `aff_trace_key` do usuário. |

A atribuição de comissão acompanha a sua conta/tag em cada programa: links `meli.la` têm `ref` assinado ligado à sua conta; produtos e social carregam `matt_tool=<sua tag>`; Shopee carrega `aff_trace_key=<sua tag>`.

### Como Adicionar um Novo Provedor

1. Crie um arquivo em `app/affiliates/minhaloja.py` herdando de `AffiliateProvider`:
   ```python
   from app.affiliates.base import AffiliateProvider

   class MinhaLojaProvider(AffiliateProvider):
       @property
       def store_name(self) -> str:
           return "minhaloja"

       def can_handle(self, url: str) -> bool:
           return "minhaloja.com.br" in url

       def convert(self, url: str) -> str:
           # Lógica de injeção da sua tag de afiliado
           ...
   ```
2. Registre o provedor em `app/affiliates/registry.py`.

---

## Filtros Configuráveis

Regras globais configuráveis por variável de ambiente ou pelo painel:

```env
MIN_DISCOUNT_PERCENT=0.0
# MIN_PRICE=10.0
# MAX_PRICE=3000.0

ALLOWED_STORES=
BLOCKED_STORES=amazon

# Allowlist estrita de categorias: só os nichos do canal
ALLOWED_CATEGORIES=tecnologia,academia
BLOCKED_CATEGORIES=

# Palavras-chave bloqueadas (anti-scam; se aparecerem no título/texto, descarta)
BLOCKED_KEYWORDS=esgotado,sorteio,rifa,fake,esgotada,golpe

REQUIRED_KEYWORDS=
```

Categorias são inferidas automaticamente no parser a partir do texto (com tolerância a acentos e plurais, ex.: "Câmeras" → tecnologia). Mensagens sem categoria aceitável, de loja bloqueada ou com palavra anti-scam são descartadas e registradas como `filtered_out`.

---

## Painel, Dashboard e Site

- **`/painel`** — autenticado (Basic Auth): tags de afiliado, filtros e keywords com seletor de **chips** (adicionar/remover termos de busca e exclusões), destino (Telegram/WhatsApp), configuração dos caçadores, promoção de teste e pause/resume do bot.
- **`/dashboard`** — tabela de promoções com status/loja/categoria, tema claro/escuro e botão de acesso ao painel.
- **`/` (site público)** — catálogo de ofertas "Rufino Promo" com paginação e filtros.
- **`/mel/connect`** — fluxo de autorização OAuth do Mercado Livre (retorna o refresh token para a conta salva).

---

## Banco de Dados e Migrações (Alembic)

As migrações rodam automaticamente na inicialização do serviço `migrator` (`alembic upgrade head`).

```bash
# Interagir manualmente
docker compose exec api alembic upgrade head
docker compose exec api alembic revision --autogenerate -m "nova_coluna"
docker compose exec api alembic downgrade -1
```

### Tabelas Principais

- `promotions` — histórico completo (título, preços, links, status, hash, erro).
- `promotion_sources` — múltiplas fontes da mesma oferta.
- `publications` — log de publicações com ID da mensagem no destino.
- `sources` — canais/grupos monitorados.
- `settings` — configurações persistentes chave-valor (overrides do painel).

---

## Logs e Observabilidade

Exemplo do fluxo em produção:

```
[PARSER] promoção identificada: 'Smart TV LG 43" Full HD' - Por: R$ 1419.0 (Loja: mercadolivre)
[MELI] Link oficial do afiliado detectado; mantendo intacto.
[AFFILIATE] link convertido: https://meli.la/27AVDj7 -> https://meli.la/27AVDj7
[FILTER] promoção aprovada
[PUBLISHER] publicada no destino -1003970125306 (msg 192)
[WHATSAPP] publicada em 120363410512355040@g.us (msg 3EB05089DB6602C8F49831)
[WORKER] Processamento concluído com sucesso: status=published
```

Se a oferta já foi publicada:

```
[DEDUP] promoção duplicada detectada (id existente: 400)
[WORKER] Processamento concluído com sucesso: status=duplicate
```

Comandos úteis:

```bash
docker compose logs -f                  # todos
docker compose logs -f worker           # apenas o worker
docker compose logs -f telegram_listener
docker compose logs -f api
```

---

## Endpoints da API

Documentação Swagger interativa em `http://localhost:8000/docs`.

- `GET /health` — saúde da aplicação (PostgreSQL e Redis).
- `GET /promotions` — lista promoções com paginação e filtros (`status`, `store`, `category`).
- `GET /promotions/{id}` — detalhes completos, incluindo fontes e publicações.
- `GET /sources` — canais/grupos monitorados.
- `GET /publications` — histórico de publicações.
- `GET /dashboard` — dashboard de promoções.
- `GET /painel` — painel de controle (autenticado).
- `GET /mel/connect` — OAuth Mercado Livre.
- `GET /` — site público de ofertas.

---

## Testes Automatizados

```bash
# Rodar toda a suíte
pytest

# Com detalhes
pytest -v
```

A suíte (156 testes) cobre parser, provedores de afiliados (inclui mint oficial MEL), caçadores (scraping e multi-página), deduplicação, filtros, formatação, pipeline, painel e configurações dinâmicas.

---

## Troubleshooting

1. **"`TELEGRAM_API_ID e TELEGRAM_API_HASH não configurados`"**
   Verifique as credenciais no `.env`/secrets e reinicie o listener: `docker compose restart telegram_listener`.

2. **O bot não posta no canal (`Forbidden: bot is not a member of the channel`)**
   Adicione o bot como **Administrador** do canal de destino com permissão de postagem.

3. **O WhatsApp não publica**
   Confirme `EVOLUTION_URL`, `EVOLUTION_INSTANCE`, `EVOLUTION_API_KEY` e `WHATSAPP_TARGET_CHAT` (JID no formato `numero@g.us`), e que o número pareado está no grupo.

4. **Os links caem na lista `/social` do perfil**
   Verifique se `MERCADOLIVRE_ROUTE=product`, `MERCADOLIVRE_MINT=true` e se a sessão `ssid` (`MERCADOLIVRE_SESSION_FILE`) está válida. O pipeline mantém intacto links oficiais do próprio afiliado e recalcança no produto com as tags `matt_tool`/`matt_word`.

5. **Mudanças no painel não surtem efeito**
   O worker lê as settings a cada ciclo com TTL curto (3 s) — aguarde o próximo ciclo do caçador ou reinicie o worker.