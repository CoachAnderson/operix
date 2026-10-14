# Operix — Arquitetura

Plataforma de robôs de negociação para cripto (Binance) e forex (cTrader), pelas APIs oficiais, vendida por assinatura mensal no Mercado Pago.

## 1. Escopo da versão 1

| Item | Decisão |
|---|---|
| Mercados | Cripto à vista (Binance Spot) e forex (cTrader Open API, qualquer corretora cTrader). A interface `Broker` permite plugar B3 via MT5 depois. |
| Modalidades | **Automático** (o robô executa) e **Sinais** (o robô sugere; o assinante confirma no painel). Cada uma com estratégias de **day trade** e de **swing trade**. |
| Execução | Três ambientes por robô: `paper` (simulação interna), `testnet` (Binance Testnet ou conta demo do cTrader) e `live` (conta real). |
| Direção | Cripto: só comprado. Forex: comprado e vendido, com inversão de posição. |
| Cobrança | Assinatura recorrente mensal via Mercado Pago (`/preapproval`), com webhook assinado. |
| Stack | FastAPI + SQLAlchemy 2 (async) + PostgreSQL + Redis · Next.js 15 + Tailwind · Docker Compose. |

## 2. Modelo regulatório que o código assume

A plataforma é **ferramenta**, não gestora:

- o assinante conecta a **própria** conta com as **próprias** credenciais (chaves da Binance; app e tokens do cTrader);
- o assinante **escolhe e parametriza** a estratégia, o tamanho da posição e os limites de risco;
- a plataforma **nunca** recebe, guarda ou movimenta recursos do assinante;
- chaves com permissão de **saque** são **recusadas** (verificado na Binance ao cadastrar);
- operar em conta real exige aceite expresso de termo de risco (registrado com data e IP) e 2FA ativo.

Isso reduz, mas não elimina, o risco de enquadramento como consultoria (Resolução CVM 19), análise (Resolução CVM 20) ou administração de carteira (Resolução CVM 21). Valide o modelo, os termos de uso e o material de marketing com advogado antes do lançamento. Nunca anuncie rentabilidade.

## 3. Componentes

```
                 ┌──────────────────────────┐
  Navegador ───► │ Next.js (web)            │  /api/* → reescrito para a API (mesma origem)
                 └────────────┬─────────────┘
                              │ cookies httpOnly + CSRF
                 ┌────────────▼─────────────┐        ┌───────────────────┐
                 │ FastAPI (api)            │◄──────►│ Mercado Pago      │
                 │ auth · billing · bots    │ webhook│ /preapproval      │
                 │ admin · credenciais      │        └───────────────────┘
                 └──────┬──────────┬────────┘
                        │          │
                 ┌──────▼───┐  ┌───▼────┐
                 │PostgreSQL│  │ Redis  │  rate limit · locks · kill switch
                 └──────▲───┘  └───▲────┘
                        │          │
                 ┌──────┴──────────┴────────┐        ┌───────────────────┐
                 │ Worker (engine)          │◄──────►│ Binance Spot (REST)│
                 │ estratégias · risco      │◄──────►│ cTrader (WS JSON) │
                 │ execução · sinais        │        └───────────────────┘
                 └──────────────────────────┘
```

- **api**: única porta de entrada. Valida sessão, plano e limites; nunca envia ordens diretamente, exceto a confirmação de um sinal pelo assinante, que passa pelo mesmo `Executor` do worker.
- **worker**: processo separado (`python -m app.engine.worker`). A cada ciclo carrega robôs ativos, busca candles, roda a estratégia, aplica o gerenciador de risco e executa ou publica sinal. Usa lock no Redis por robô, então pode escalar horizontalmente.
- **web**: painel do assinante (`/painel`) e do administrador (`/admin`).

## 4. Modelo de dados

| Tabela | Conteúdo principal |
|---|---|
| `users` | e-mail, hash Argon2id, papel (`subscriber`/`admin`), 2FA (segredo cifrado), status, aceite do termo de risco |
| `plans` | nome, preço mensal, `max_bots`, `allow_auto`, `allow_live`, ativo |
| `subscriptions` | usuário, plano, `mp_preapproval_id`, status (`pending`/`active`/`paused`/`cancelled`/`past_due`), próxima cobrança |
| `payments` | cobranças recorrentes recebidas do MP (`authorized_payment`), valor, status |
| `exchange_credentials` | Binance: chave e segredo; cTrader: Client ID/Secret do app do cliente, access e refresh token, conta (`ctidTraderAccountId`), validade do token. Tudo **cifrado com AES-256-GCM** |
| `bots` | dono, mercado (`crypto`/`forex`), credencial, símbolo, estratégia, parâmetros, direção (`allow_short`), tamanho (valor ou lotes), modalidade, ambiente, limites de risco, saldo simulado, status |
| `positions` | posição aberta por robô: lado (comprado/vendido), quantidade, preço de entrada, custo, taxa de entrada, id da posição na corretora |
| `orders` | ordens enviadas: `client_order_id` idempotente, lado, quantidade, preço, status, taxa, PnL realizado |
| `signals` | sinais gerados: ação, preço de referência, motivo, validade, status (`pending`/`executed`/`expired`/`dismissed`) |
| `audit_logs` | quem fez o quê, quando, de onde |
| `webhook_events` | deduplicação de notificações do MP (`topic` + `data.id`) |
| `system_settings` | chave/valor (ex.: kill switch global) |

## 5. Fluxos principais

### Assinatura
1. Assinante escolhe um plano → `POST /api/v1/billing/checkout`.
2. API cria `preapproval` no MP (status `pending`, `external_reference` = id da assinatura) e devolve o `init_point`.
3. Assinante autoriza no MP → MP chama `POST /api/v1/billing/webhook/mercadopago`.
4. API valida a assinatura HMAC (`x-signature`), deduplica, **consulta o recurso no MP** (nunca confia no corpo) e atualiza o status.
5. Robôs só rodam com assinatura `active`. Se a assinatura cair, o worker pausa os robôs do usuário no próximo ciclo.

### Ciclo do robô (worker)
1. Verifica kill switch global, status do robô, assinatura ativa.
2. Busca candles do símbolo/timeframe (dados públicos da Binance).
3. Se há posição aberta, checa stop loss, take profit e tempo máximo (day trade fecha ao fim do prazo).
4. Roda a estratégia → `BUY`, `SELL` ou `HOLD`.
5. Gerenciador de risco: perda diária máxima, número máximo de operações por dia, tamanho da ordem, filtros da corretora (`LOT_SIZE`, `PRICE_FILTER`, `NOTIONAL`).
6. Modalidade `auto` → `Executor` envia a ordem ao broker do ambiente. Modalidade `signals` → grava sinal com validade; o assinante confirma ou descarta no painel.

### Ambientes de execução
| Ambiente | Ordens | Dados de mercado | Saldo |
|---|---|---|---|
| `paper` | simuladas pelo `PaperBroker` com taxa e slippage | Binance pública (real) | virtual, no banco |
| `testnet` | Binance Spot Testnet | testnet | da testnet |
| `live` | Binance Spot real | real | conta do assinante |

### Ciclo do robô de forex (cTrader)
1. Reconcilia ordens sem resposta (procura a posição pelo comentário com o id da ordem) e verifica se a corretora encerrou a posição sozinha (stop, alvo, stop-out); nesse caso registra o fechamento com o resultado informado pela corretora.
2. A estratégia devolve o **alvo** (comprado, vendido ou fora). O motor fecha a posição atual e, se for o caso, abre a contrária no mesmo ciclo.
3. Ordens a mercado levam stop e alvo **relativos**, que ficam no servidor da corretora mesmo se a plataforma cair.
4. Fora do horário do símbolo (agenda informada pela corretora), novas entradas são bloqueadas.

### Backtest
1. `POST /api/v1/backtest` (ou `/backtest/bot/{id}` com a configuração de um robô) baixa o histórico paginado da Binance, com candles extras antes do início para aquecer os indicadores.
2. `engine/backtest.py` usa as mesmas classes de estratégia do robô ao vivo: decide no fechamento do candle e executa na abertura do seguinte; stop e alvo pelas máximas/mínimas (stop primeiro quando os dois são tocados); taxa e slippage em toda ordem.
3. A resposta traz métricas, curva de saldo comparada a comprar e segurar o mesmo valor, resultado mensal, operações e candles para o gráfico. Limite de 30 mil candles por teste e 40 testes por hora por usuário.

## 6. Segurança

- **Senhas**: Argon2id.
- **Sessão**: JWT curto (15 min) + refresh (7 dias) em cookies `httpOnly`, `Secure`, `SameSite=Lax`; refresh rotativo com revogação por `token_version`.
- **CSRF**: double-submit (`csrf_token` cookie + cabeçalho `X-CSRF-Token`) em toda requisição que altera estado.
- **2FA**: TOTP (pyotp), obrigatório para admin e para operar em `live`.
- **Segredos de corretora**: AES-256-GCM com chave mestra fora do banco (`ENCRYPTION_KEY`), com id de versão para rotação. O segredo nunca volta para o front; só os 4 últimos caracteres.
- **Permissões da chave**: ao cadastrar, consulta `GET /sapi/v1/account/apiRestrictions` e recusa chave com saque habilitado; recomenda restrição de IP.
- **Webhook**: HMAC-SHA256 com comparação em tempo constante, deduplicação e consulta ao recurso.
- **Rate limit**: login, cadastro e 2FA limitados por IP e e-mail (Redis).
- **Cabeçalhos**: HSTS, CSP restritiva, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`.
- **Auditoria**: login, falhas de login, alteração de credenciais, troca de ambiente, ordens, ações de admin.
- **Kill switch**: global (admin) e por robô (assinante), checados a cada ciclo e antes de cada ordem.
- **Idempotência de ordens**: `newClientOrderId` gravado antes do envio; em caso de timeout, o worker consulta a ordem pelo id antes de reenviar.

## 7. LGPD

Base legal: execução de contrato. Guarde o mínimo (sem CPF na v1, o MP cuida do pagador). Ofereça exportação e exclusão de conta (rota `DELETE /api/v1/me` anonimiza o usuário e apaga credenciais). Mantenha logs de auditoria pelo prazo exigido e documente na política de privacidade.

## 8. Próximos passos sugeridos

1. Migrations com Alembic (`alembic revision --autogenerate -m "inicial"`).
2. Otimização com validação fora da amostra (walk-forward) no backtest, para reduzir o risco de sobreajuste.
3. Ordens OCO nativas da Binance para stop/alvo no servidor da corretora.
4. Notificação de sinais por e-mail, Telegram ou WhatsApp.
5. Conector MT5 para B3 e Forex atrás da mesma interface `Broker`.
6. Observabilidade: Sentry, métricas Prometheus, alerta de robô parado.
