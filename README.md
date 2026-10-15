# OráculoInvest

Plataforma de robôs de negociação para **cripto** (Binance Spot) e **forex** (qualquer corretora com cTrader), pelas APIs oficiais, vendida por assinatura mensal no Mercado Pago. Cada cliente opera com as próprias credenciais.
Arquitetura, modelo de dados e decisões de segurança: [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).

## O que já funciona

- **Assinante**: cadastro, login com 2FA (TOTP), planos e assinatura recorrente, conexão de chaves da Binance (cifradas), criação e controle de robôs, caixa de sinais, histórico de ordens, termo de risco, troca de senha e exclusão de conta (LGPD).
- **Robôs**: 4 estratégias (2 de day trade, 2 de swing trade), modalidade **automática** ou **por sinais**, e três ambientes: **simulação** (preço real, saldo fictício), **testnet/conta demo** e **conta real**.
- **Forex (cTrader)**: opera comprado e vendido, tamanho em lotes, stop e alvo enviados à corretora junto com a ordem, horário de mercado respeitado e fechamentos feitos pela corretora (stop, alvo, stop-out) reconciliados automaticamente.
- **Futuros da B3 (MetaTrader 5)**: mini-índice (WIN) e mini-dólar (WDO) pela corretora do próprio cliente, com o Conector OráculoInvest rodando no Windows dele. Vencimento atual escolhido sozinho, rolagem perto do vencimento, day trade zerado antes do fim do pregão, contratos inteiros e custos da B3 na simulação e no backtest.
- **Risco**: stop loss, alvo, tempo máximo posicionado, perda máxima diária (pausa o robô), limite de ordens por dia, botão de encerrar posição e parada geral (kill switch) do admin.
- **Backtest**: testa qualquer estratégia (ou a configuração de um robô) no histórico da Binance, sem olhar o futuro, com taxa e slippage. Mostra taxa de acerto, resultado médio por operação, ganho médio ÷ perda média, fator de lucro, queda máxima, comparação com comprar e segurar, resultado mês a mês e as operações no gráfico de candles.
- **Aprender** (`/aprender`, aberto ao público): trilha de 17 aulas de 3 a 5 minutos em 4 módulos (primeiros passos, gráficos, estratégias, risco e robôs), com 14 gráficos interativos (dados fictícios), quiz em cada aula, progresso salvo no navegador e glossário com busca. Conteúdo em `frontend/lib/learn/lessons.ts`; para criar uma aula, basta acrescentar um item lá.
- **Relatórios em PDF**: o assinante escolhe as moedas (as que têm posição aberta já vêm marcadas), o período e os ambientes, e baixa um PDF com resultado por ambiente, resumo por moeda, posições abertas e todas as ordens. Horário de Brasília; simulação nunca soma com conta real.
- **Gráficos TradingView**: gráfico avançado do TradingView na tela de cada robô e gráfico de candles (TradingView Lightweight Charts) com compras e vendas marcadas no backtest.
- **Admin**: receita recorrente, usuários (suspender, conceder plano de cortesia), assinaturas, planos, robôs, parada geral, auditoria e reprocessamento de webhooks.
- **Segurança**: Argon2id, JWT em cookie httpOnly com CSRF, AES-256-GCM com rotação de chave, recusa de chave com saque, rate limit, cabeçalhos de segurança, auditoria, webhook com HMAC e idempotência de ordens.

## Produção

Passo a passo completo em [`DEPLOY.md`](DEPLOY.md): servidor, domínio, HTTPS automático (Caddy), Mercado Pago, backup e atualização.

## Rodar com Docker (desenvolvimento)

```bash
cp .env.example .env          # preencha JWT_SECRET, ENCRYPTION_KEYS, MP_*, ADMIN_*
docker compose up -d --build
docker compose exec api python -m app.seed      # cria planos e o admin
```

Abra http://localhost:3000. O admin precisa ativar o 2FA em **Segurança** antes de acessar `/admin`.

## Rodar sem Docker (desenvolvimento)

```bash
# API
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=sqlite+aiosqlite:///./dev.db REDIS_URL=memory:// ADMIN_EMAIL=admin@local ADMIN_PASSWORD=TroqueEsta123
python -m app.seed
uvicorn app.main:app --reload            # http://localhost:8000/docs
python -m app.engine.worker              # em outro terminal (robôs)

# Painel
cd frontend
npm install
npm run dev                              # http://localhost:3000
```

`REDIS_URL=memory://` só serve para um processo; com API e worker separados, use Redis de verdade.

## Testes

```bash
cd backend && pytest        # 45 testes: segurança, webhook, Binance, cTrader (servidor simulado), MetaTrader 5 (terminal simulado), estratégias, motor, backtest, relatórios e API
cd frontend && npm run build
```

## Mercado Pago

1. Em *Suas integrações*, crie a aplicação e copie o **Access Token** para `MP_ACCESS_TOKEN`.
2. Em **Webhooks**, cadastre `https://SEU_DOMINIO/api/v1/billing/webhook/mercadopago` com os eventos **Planos e assinaturas** (`subscription_preapproval` e `subscription_authorized_payment`) e copie a **assinatura secreta** para `MP_WEBHOOK_SECRET`.
3. Teste com credenciais e usuários de teste antes de usar as de produção.

As assinaturas recorrentes do Mercado Pago são cobradas no cartão. O webhook valida a assinatura HMAC, responde 200 na hora e consulta o estado real no MP antes de ativar ou pausar.

## Binance

- **Testnet**: crie chaves em https://testnet.binance.vision e cadastre como "Testnet".
- **Conta real**: o assinante cria a chave com leitura + negociação Spot, **sem saque** e com restrição ao IP do servidor (informe esse IP no painel/FAQ). A plataforma recusa chaves com saque habilitado.
- O worker usa dados públicos da Binance; se o servidor estiver em região bloqueada pela Binance, hospede em região permitida.

## Forex com cTrader

Cada cliente conecta a própria conta em **Corretora**, de um destes jeitos:

1. **App próprio (padrão):** o cliente cria um app em https://openapi.ctrader.com/apps, gera no Playground do app o Access Token e o Refresh Token (escopo *trading*) e cola no painel Client ID, Client Secret e os dois tokens. Tudo fica cifrado (AES-256-GCM) por credencial.
2. **Login com cTrader (opcional):** se você registrar um app da plataforma e preencher `CTRADER_CLIENT_ID` e `CTRADER_CLIENT_SECRET`, aparece o botão "Conectar com cTrader". O redirect a cadastrar no app é `{API_PUBLIC_URL}/api/v1/ctrader/callback`.

Detalhes técnicos:
- Conexão JSON por WebSocket na porta 5036 (`demo.ctraderapi.com` e `live.ctraderapi.com`), com heartbeat a cada 10 s e uma conexão compartilhada por app e ambiente.
- O token de acesso vale cerca de 30 dias; o sistema renova com o refresh token alguns dias antes, sob trava no Redis, e atualiza todas as contas que dividiam o mesmo token.
- A simulação de forex usa a conta cTrader do cliente só para cotações e regras do símbolo (tamanho do lote, volume mínimo, horário).
- Robôs de forex em conta real dependem da alavancagem da corretora: confira os limites de risco antes de ligar.

## Futuros da B3 com MetaTrader 5

Pessoa física não tem API direta com a B3; o caminho é o MetaTrader 5 que a corretora já oferece (XP, Clear, Rico, Genial e outras). O MetaTrader 5 só roda no Windows, logado na conta do cliente, então a ligação é feita por um programa pequeno que fica ao lado dele:

```
robô (worker) ──Redis──▶ API ◀──HTTPS (o conector consulta a cada 25 s)── Conector OráculoInvest ──▶ MetaTrader 5 do cliente ──▶ B3
```

- **Conector** (`conector-mt5/`): Python com o pacote oficial `MetaTrader5`. Só abre conexões de saída, então não precisa abrir porta no roteador. Login e senha da corretora nunca saem do computador do cliente; o servidor guarda só o hash de um token do conector.
- **Travas locais** que o servidor não consegue mudar (`conector.ini`): ativos liberados (padrão WIN, WDO) e máximo de contratos por ordem. O conector não soma posição em cima de outra já aberta no contrato e só fecha posições que ele mesmo abriu (número mágico).
- **Demo × real**: o servidor confere o tipo de conta informado pelo MetaTrader 5 e recusa o conector de conta demo numa conta real (e o contrário). Também recusa trocar a conta depois de vinculada.
- **Comandos com prazo**: ordem não entregue a tempo é descartada pelo servidor; sem resposta, a ordem fica "conferindo" e é reconciliada pelo comentário (`OI…`) no histórico do MT5.
- **Vencimentos**: o conector escolhe o contrato com vencimento mais próximo e passa para o seguinte quando faltam 3 dias. Posição de swing num contrato que está vencendo é encerrada ("Rolagem") e a estratégia reentra no novo.
- **Horário**: entradas das 9h05 às 18h20 (Brasília), em dias úteis. Robôs de day trade zeram 10 minutos antes do fim e não abrem nos últimos 15. Feriados da B3 não estão no calendário: a corretora recusa a ordem e o robô tenta no próximo ciclo.
- **Distribuição**: o painel oferece `frontend/public/downloads/conector-oraculoinvest-mt5.zip` (gerado por `conector-mt5/empacotar.sh`). Para entregar um `.exe` que dispensa Python, rode `gerar_exe.bat` num Windows e coloque o resultado no lugar do .zip.
- **Antes da conta real**: teste o conector com a conta demo da sua corretora e confira se ela mantém o comentário das ordens e se a série contínua (`WIN$N`, `WIN$` ou `WIN@N`) existe; sem ela o histórico vem só do contrato atual.
- **Redis obrigatório em produção**: worker e API conversam pela fila do Redis (o `memory://` só serve para testes num único processo).

## TradingView

- **Tela do robô**: widget gratuito *Advanced Chart* do TradingView (`components/TradingViewWidget.tsx`), com o par `BINANCE:<PAR>` e o tempo gráfico do robô. Os dados vêm do próprio TradingView; mantenha o link de crédito abaixo do gráfico.
- **Backtest**: `lightweight-charts` (biblioteca open source do TradingView, licença Apache 2.0) desenha os candles usados no teste com as compras e vendas. O logotipo do TradingView no canto do gráfico é a atribuição exigida pela licença.
- A política de segurança (CSP) em `frontend/next.config.mjs` já libera `s3.tradingview.com` e os iframes do TradingView.

## Nome da plataforma

O nome **OráculoInvest** fica em um lugar só: `BRAND_NAME` no `.env` (usado no build do painel e como `APP_NAME` da API). Antes de lançar, confirme o registro da marca no INPI (classes 9, 36 e 42) e o domínio.

## Antes de lançar

- [ ] Validar com advogado o enquadramento regulatório (CVM 19/20/21), os termos de uso, a política de privacidade e o material de divulgação. Não prometa rentabilidade. No forex, não divulgue nem receba comissão de corretoras estrangeiras sem orientação jurídica.
- [ ] Usar `ENVIRONMENT=production` (as migrações do Alembic rodam sozinhas no deploy).
- [ ] Subir com `docker-compose.prod.yml` (HTTPS pelo Caddy) e agendar `deploy/backup.sh`.
- [ ] Guardar `ENCRYPTION_KEYS` fora do servidor: sem ela as chaves cadastradas ficam ilegíveis.
- [ ] Monitoramento (Sentry, alerta de worker parado, alerta de webhook com falha).
- [ ] Rodar robôs em testnet por algumas semanas antes de liberar conta real.

## Estrutura

```
backend/
  app/
    api/routes/        auth, billing (MP), credentials, ctrader, bots e sinais, backtest, reports (PDF), admin
    core/              config, segurança, criptografia, Redis, rate limit
    engine/            worker, ciclo do robô, executor de ordens, risco, permissões
    services/brokers/  Binance (REST oficial), cTrader (Open API JSON), simulação, fábrica
    strategies/        indicadores e estratégias
    models.py          tabelas
  tests/
frontend/
  app/painel/          painel do assinante
  app/admin/           painel do administrador
docs/ARQUITETURA.md
docker-compose.yml
```
