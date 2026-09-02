# PromoBot — Agregador e Distribuidor de Promoções

O **PromoBot** é um sistema automatizado e desacoplado projetado para monitorar canais e grupos de ofertas no Telegram, extrair e normalizar informações de promoções, converter links para programas de afiliados (Amazon, Mercado Livre, Shopee, etc.), aplicar filtros de preços/descontos, evitar duplicações e publicar as ofertas formatadas em canais ou grupos próprios.

Projetado sob princípios de arquitetura limpa e desacoplada, o núcleo de processamento é completamente agnóstico à plataforma de mensageria, permitindo adicionar adaptadores futuros (como **WhatsApp**) sem qualquer alteração na lógica de negócio.

---

## 1. Arquitetura do Sistema

```
[ TelegramSource ] (ou futuro [ WhatsAppSource ])
       │
       ▼ (RawMessage)
[ Fila Redis: RPUSH/BLPOP ]
       │
       ▼
[ Worker de Processamento ]
       │
       ├─► 1. Identificação de Origem (PostgreSQL)
       ├─► 2. Parser (Extrai título, preços, loja, links, categoria)
       ├─► 3. Provedores de Afiliados (Amazon, Mercado Livre, Shopee, etc.)
       ├─► 4. Deduplicação (URL canônica, ID de produto, Hash de conteúdo, Janela temporal)
       ├─► 5. Filtros de Negócio (Desconto mínimo, teto/piso de preço, palavras bloqueadas)
       ├─► 6. Formatter (Padronização independente de plataforma)
       ├─► 7. Publicador (TelegramPublisher via Bot API / Telethon)
       └─► 8. Auditoria & Histórico (PostgreSQL: promoções, links, publicações, fontes)
```

### Principais Componentes:
- **`app/adapters/`**: Adaptadores de entrada e saída. Contém `TelegramSource` (listener MTProto via Telethon), `TelegramPublisher` (publicador via Telegram Bot API), e interfaces stub prontas para `WhatsAppSource` e `WhatsAppPublisher`.
- **`app/core/`**: Regras de negócio desacopladas:
  - `parser.py`: Extração de preços (moeda brasileira `R$ 1.899,00`, `99,90`), desconto, links e nomes de produtos.
  - `deduplicator.py`: Detecção inteligente de duplicatas por normalização de URLs (removendo `utm_*`, `ref`, etc.), ID de produto (`ASIN`, `MLB`, `Shopee ID`) e hash de conteúdo. Múltiplas fontes da mesma promoção são registradas sem republicar.
  - `filters.py`: Validação de regras de negócio (desconto mínimo, teto de preço, categorias e palavras-chave bloqueadas).
  - `formatter.py`: Formatação padronizada das mensagens com emojis, preços e links de afiliado.
  - `processor.py`: Orquestrador central do pipeline com isolamento de falhas.
- **`app/affiliates/`**: Sistema modular de provedores com registro dinâmico (`AmazonProvider`, `MercadoLivreProvider`, `ShopeeProvider`).
- **`app/database/`**: Modelagem SQLAlchemy 2.0 e repositórios assíncronos (`asyncpg`).
- **`app/workers/`**: Fila em Redis e worker assíncrono de alta resiliência.
- **`app/api/`**: API FastAPI com documentação Swagger interativa em `/docs`.

---

## 2. Stack Tecnológica

- **Linguagem**: Python 3.12+ (compatível com 3.14)
- **Framework Web**: FastAPI & Uvicorn
- **Banco de Dados**: PostgreSQL 16 com SQLAlchemy 2.0 (assíncrono com `asyncpg`)
- **Migrações**: Alembic
- **Mensageria & Cache**: Redis 7
- **Cliente Telegram**: Telethon 1.36+ & HTTP Telegram Bot API (`httpx`)
- **Validação de Dados**: Pydantic v2 & Pydantic-Settings
- **Testes Automatizados**: pytest & pytest-asyncio
- **Containerização**: Docker & Docker Compose

---

## 3. Instalação e Inicialização com Docker Compose

### Pré-requisitos
- Docker Engine 24+ e Docker Compose v2+ instalados na máquina.

### Passo a Passo

1. Clone o repositório ou acesse o diretório do projeto:
   ```bash
   cd promobot
   ```

2. Crie o arquivo de variáveis de ambiente a partir do modelo:
   ```bash
   cp .env.example .env
   ```

3. Edite o arquivo `.env` inserindo suas credenciais do Telegram e dos programas de afiliados (veja a seção [Configuração do Telegram](#4-configuração-do-telegram)).

4. Construa as imagens e inicie todos os containers em segundo plano:
   ```bash
   docker compose build
   docker compose up -d
   ```

5. Verifique o status dos serviços:
   ```bash
   docker compose ps
   ```

6. Acompanhe os logs em tempo real:
   ```bash
   docker compose logs -f
   ```

---

## 4. Configuração do Telegram

Para monitorar canais e publicar ofertas, são necessárias as credenciais do Telegram.

### 4.1 Obter `TELEGRAM_API_ID` e `TELEGRAM_API_HASH`
1. Acesse o portal oficial [https://my.telegram.org](https://my.telegram.org).
2. Faça login com o seu número de telefone do Telegram e insira o código de confirmação.
3. Clique em **API development tools**.
4. Crie uma nova aplicação (ex: `PromoBot Listener`).
5. Copie os valores de `api_id` (numérico) e `api_hash` (string hexadecimal) e cole no seu `.env`:
   ```env
   TELEGRAM_API_ID=1234567
   TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
   ```

### 4.2 Obter `TELEGRAM_BOT_TOKEN` (para Publicação)
1. No Telegram, converse com o [@BotFather](https://t.me/BotFather).
2. Envie o comando `/newbot` e siga as instruções para escolher nome e username.
3. O BotFather fornecerá um token HTTP no formato: `1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ`.
4. Adicione ao seu `.env`:
   ```env
   TELEGRAM_BOT_TOKEN=1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ
   ```

### 4.3 Configurar Canais de Origem (`TELEGRAM_SOURCE_CHATS`)
- Canais ou grupos públicos ou privados dos quais o PromoBot irá capturar mensagens.
- Podem ser usernames com `@` ou IDs numéricos (ex: `-1001234567890`), separados por vírgula:
  ```env
  TELEGRAM_SOURCE_CHATS=@canal_ofertas_1,@canal_ofertas_2,-1001987654321
  ```
- *Nota sobre contas de usuário*: Se você estiver monitorando canais privados nos quais bots não têm permissão para entrar, utilize uma sessão de usuário gerando a string de sessão com Telethon (`TELEGRAM_SESSION_STRING`) ou conectando uma vez via terminal.

### 4.4 Configurar Canal de Destino (`TELEGRAM_TARGET_CHAT`)
- Crie o seu canal ou grupo onde as ofertas serão postadas.
- Adicione o seu bot como **Administrador** do canal com permissão para **Postar Mensagens** (e gerenciar mídia).
- Defina o username ou ID do canal no `.env`:
  ```env
  TELEGRAM_TARGET_CHAT=@meu_canal_promocoes
  ```

---

## 5. Provedores de Afiliados

O PromoBot inclui suporte nativo e extensível para os principais programas de afiliados do Brasil:

| Loja | Variável no `.env` | Como funciona |
|---|---|---|
| **Amazon** | `AMAZON_TAG=minhatag-20` | Extrai o código ASIN (ex: `B08N5WRWNW`), remove parâmetros de rastreamento antigos e injeta sua tag de associado. Suporta links curtos `amzn.to`. |
| **Mercado Livre** | `MERCADOLIVRE_TAG=meu_id_meli` | Extrai o identificador MLB do produto, limpa os parâmetros de terceiros e insere a tag de afiliado (`matt_tool`). |
| **Shopee** | `SHOPEE_TAG=minha_tag`<br>`SHOPEE_APP_ID=meu_app_id` | Extrai identificadores de produto/loja e injeta as credenciais de tracking da Shopee. |

### Como Adicionar um Novo Provedor
Para adicionar uma nova loja (ex: Magazine Luiza, AliExpress, KaBuM):
1. Crie um novo arquivo em `app/affiliates/minhaloja.py` herdando de `AffiliateProvider`:
   ```python
   from app.affiliates.base import AffiliateProvider

   class MinhaLojaProvider(AffiliateProvider):
       @property
       def store_name(self) -> str:
           return "minhaloja"

       def can_handle(self, url: str) -> bool:
           return "minhaloja.com.br" in url

       def extract_product_id(self, url: str) -> str | None:
           # Lógica de extração do ID do produto
           ...

       def convert(self, url: str) -> str:
           # Lógica de injeção da sua tag de afiliado
           ...
   ```
2. Registre o provedor em `app/affiliates/registry.py`:
   ```python
   self.register(MinhaLojaProvider(tag=self.settings.MINHALOJA_TAG))
   ```

---

## 6. Filtros Configuráveis

Todas as regras de triagem são configuráveis externamente no `.env`:

```env
# Desconto mínimo exigido (ex: só postar promoções com 15% de desconto ou mais)
MIN_DISCOUNT_PERCENT=15.0

# Faixa de preço permitida em Reais
MIN_PRICE=10.0
MAX_PRICE=5000.0

# Whitelist e Blacklist de lojas (separadas por vírgula)
ALLOWED_STORES=amazon,mercadolivre,shopee
BLOCKED_STORES=aliexpress

# Whitelist e Blacklist de categorias
ALLOWED_CATEGORIES=eletronicos,informatica,eletrodomesticos
BLOCKED_CATEGORIES=moda

# Palavras-chave bloqueadas (se qualquer uma aparecer no título ou texto, a mensagem é descartada)
BLOCKED_KEYWORDS=esgotado,esgotada,sorteio,rifa,fake,golpe,usado,recondicionado
```

---

## 7. Banco de Dados e Migrações (Alembic)

As migrações são executadas automaticamente na inicialização do container da API via `alembic upgrade head`.

Para interagir com o banco de dados manualmente:

- **Executar migrações**:
  ```bash
  docker compose exec api alembic upgrade head
  ```
- **Criar nova migração após alterar models**:
  ```bash
  docker compose exec api alembic revision --autogenerate -m "nova_coluna"
  ```
- **Reverter última migração**:
  ```bash
  docker compose exec api alembic downgrade -1
  ```

### Tabelas Criadas:
- `sources`: Fontes de monitoramento registradas (Telegram, canais, status de atividade).
- `promotions`: Histórico completo de promoções (título, preços, links, status, hash, erros).
- `promotion_sources`: Rastreamento de múltiplas fontes que capturaram a mesma oferta.
- `affiliate_links`: Registro de links originais convertidos para afiliados.
- `publications`: Log de todas as publicações realizadas com ID da mensagem no canal de destino.
- `filters`: Regras dinâmicas de filtragem.
- `settings`: Configurações persistentes chave-valor.

---

## 8. Logs e Observabilidade

O PromoBot implementa padronização rigorosa de logs para auditoria de cada etapa do pipeline:

```
[TELEGRAM] mensagem recebida de @canal_origem (msg 1042)
[PARSER] promoção identificada: 'Smart TV Samsung 50 4K' - Por: R$ 1899.00 (Loja: amazon)
[AFFILIATE] link convertido: https://amazon.com.br/dp/B08N5WRWNW -> https://amazon.com.br/dp/B08N5WRWNW?tag=minhatag-20
[DEDUP] promoção nova: hash=7f3a8b912c4e...
[FILTER] promoção aprovada (desconto: 24.0%)
[PUBLISHER] publicada no destino @meu_canal_promocoes (msg 8421)
[WORKER] Processamento concluído com sucesso: status=published
```

Se uma oferta duplicada for detectada:
```
[DEDUP] promoção duplicada detectada (id existente: 42)
[SOURCE] Adicionada referência da fonte @canal_b à promoção existente 42
```

### Comandos de Monitoramento:
- Logs gerais de todos os serviços:
  ```bash
  docker compose logs -f
  ```
- Apenas do Worker:
  ```bash
  docker compose logs -f worker
  ```
- Apenas do Listener do Telegram:
  ```bash
  docker compose logs -f telegram_listener
  ```
- Apenas da API:
  ```bash
  docker compose logs -f api
  ```

---

## 9. Endpoints da API

A API FastAPI roda por padrão na porta `8000`. Acesse a documentação interativa Swagger em:
`http://localhost:8000/docs`

- `GET /health`: Diagnóstico de saúde da aplicação, conexão PostgreSQL e Redis.
- `GET /promotions`: Lista promoções capturadas com paginação e filtros (`status`, `store`).
- `GET /promotions/{id}`: Detalhes completos da promoção, incluindo fontes que a capturaram e publicações.
- `GET /sources`: Lista de canais e grupos monitorados.
- `GET /publications`: Histórico de publicações enviadas ao canal de destino.

---

## 10. Execução dos Testes Automatizados

O projeto possui suíte completa de testes unitários e de integração cobrindo o Parser, Provedores de Afiliados, Deduplicação, Filtros, Formatação, Pipeline e API:

```bash
# Executar todos os testes
pytest -v

# Executar com relatório de cobertura (se pytest-cov estiver instalado)
pytest -v --tb=short
```

---

## 11. Troubleshooting (Problemas Comuns)

### 1. `TELEGRAM_API_ID e TELEGRAM_API_HASH não configurados`
- **Causa**: O container `telegram_listener` iniciou sem as credenciais do Telegram.
- **Solução**: Preencha `TELEGRAM_API_ID` e `TELEGRAM_API_HASH` no seu `.env` e execute `docker compose restart telegram_listener`.

### 2. O bot não posta no canal de destino (`Forbidden: bot is not a member of the channel`)
- **Causa**: O bot não foi adicionado ao canal de destino ou não possui permissão de administrador.
- **Solução**: Entre no canal de destino, vá em **Administradores** -> **Adicionar Administrador**, procure pelo username do seu bot e conceda permissão de envio de mensagens.

### 3. Duplicatas não são detectadas após reiniciar os containers
- **Causa**: O volume persistente do Redis ou Postgres não foi mantido.
- **Solução**: O `docker-compose.yml` inclui volumes nomeados persistentes (`postgres_data` e `redis_data`). Certifique-se de não utilizar a flag `-v` no `docker compose down` para preservar os dados.

### 4. Erros em mensagens com fotos (`Telegram API error 400`)
- **Causa**: Imagem corrompida ou legenda excedendo o limite de caracteres do Telegram (1024 caracteres para legendas de mídia).
- **Solução**: O `TelegramPublisher` trata falhas de legenda e envia a oferta como texto quando necessário sem interromper o worker.

---

## 12. Extensibilidade Futura: WhatsApp

O sistema foi concebido com interfaces abstratas para receber novos adaptadores. Para implementar suporte ao WhatsApp:
1. Implemente `WhatsAppSource(MessageSource)` em `app/adapters/whatsapp.py` (usando WhatsApp Cloud API, Evolution API, Baileys ou Z-API).
2. Implemente `WhatsAppPublisher(Publisher)` para publicação no status ou grupos.
3. Adicione o serviço `whatsapp_listener` no `docker-compose.yml`.

O núcleo de negócio (`PromotionParser`, `AffiliateRegistry`, `Deduplicator`, `PromotionFilter`, `PromotionFormatter`, `PromotionProcessor`) continuará idêntico sem nenhuma modificação.
