# Subir o OráculoInvest em produção

Caminho recomendado para começar: **um servidor Linux (VPS) com Docker**, HTTPS automático pelo Caddy.
Tudo roda no mesmo servidor: PostgreSQL, Redis, API, robôs (worker) e painel.

## 1. Servidor e domínio

- VPS com **Ubuntu 24.04**, mínimo **2 vCPU e 4 GB de RAM** (o build do painel usa memória; com 2 GB, ative swap).
- Região: **Brasil (São Paulo)** ou Europa. Evite servidores nos EUA — a Binance bloqueia acesso à API de lá.
- IP fixo. Ele será o IP que os clientes informam na restrição de IP da chave da Binance.
- Domínio (ex.: `operix.com.br`). Crie um registro **A** `app.operix.com.br` → IP do servidor (e `www.app...` se quiser).

## 2. Preparar o servidor

```bash
ssh root@IP_DO_SERVIDOR
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh          # instala Docker e o plugin compose
ufw allow OpenSSH && ufw allow 80 && ufw allow 443/tcp && ufw allow 443/udp && ufw --force enable
adduser --disabled-password operix && usermod -aG docker operix
```

Se a máquina tiver 2 GB de RAM:
```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

## 3. Enviar o projeto

Pelo seu computador (ou use um repositório Git privado e `git clone`):
```bash
scp operix.zip root@IP_DO_SERVIDOR:/opt/
ssh root@IP_DO_SERVIDOR "cd /opt && apt install -y unzip && unzip operix.zip && chown -R operix:operix /opt/operix"
```

## 4. Configurar o `.env`

```bash
cd /opt/operix && cp .env.example .env && nano .env
```

| Variável | Valor em produção |
|---|---|
| `ENVIRONMENT` | `production` |
| `DOMAIN` | `app.operix.com.br` |
| `PUBLIC_URL`, `API_PUBLIC_URL`, `ALLOWED_ORIGINS` | `https://app.operix.com.br` |
| `POSTGRES_PASSWORD` | senha forte |
| `JWT_SECRET` | `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ENCRYPTION_KEYS` | `python3 -c "import base64,os; print('k1:' + base64.b64encode(os.urandom(32)).decode())"` — **guarde uma cópia fora do servidor** |
| `MP_ACCESS_TOKEN`, `MP_WEBHOOK_SECRET` | credenciais de **produção** do Mercado Pago |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | seu acesso de administrador |
| `CTRADER_CLIENT_ID/SECRET` | opcional (botão "Conectar com cTrader") |

Com `ENVIRONMENT=production` a API se recusa a subir se faltar segredo obrigatório — de propósito.

## 5. Subir

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose exec api python -m app.seed        # cria os planos e o admin (as tabelas já vêm das migrações)
docker compose ps                                  # todos "running"
curl -s https://app.operix.com.br/api/v1/billing/plans   # deve listar os planos
```

O Caddy emite o certificado HTTPS sozinho no primeiro acesso (o DNS precisa já apontar para o servidor).

## 6. Depois de subir

1. Entre com o admin, vá em **Segurança** e ative o 2FA (obrigatório para o painel `/admin`).
2. **Mercado Pago → Webhooks**: URL `https://app.operix.com.br/api/v1/billing/webhook/mercadopago`, eventos de **Planos e assinaturas**. Faça uma assinatura de teste e confira em `/admin` que ela ficou ativa.
3. Informe aos clientes o **IP do servidor** para a restrição de IP da chave da Binance.
4. Backup diário: `crontab -e` e adicione
   `0 3 * * * cd /opt/operix && ./deploy/backup.sh >> backups/backup.log 2>&1`
   Copie os backups para fora do servidor (rclone, bucket S3/R2, etc.).
5. Teste a recuperação ao menos uma vez:
   `gunzip -c backups/ARQUIVO.sql.gz | docker compose exec -T db psql -U operix operix`

## Atualizar uma nova versão

```bash
cd /opt/operix
# envie os arquivos novos (scp/git pull), mantendo o .env
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

As migrações do banco (`backend/migrations/versions`) são aplicadas sozinhas quando a API reinicia com `ENVIRONMENT=production`
(confira no `.env`). Se o robô parar de operar depois de uma atualização, abra a página dele: o painel "Por que entrou ou não entrou?"
mostra se o motor (worker) está rodando e se conseguiu ler os robôs do banco. Para ver o erro direto no servidor:
`docker compose logs --tail=100 worker`.
Quando você mudar tabelas no código, gere a migração **no seu computador**, revise o arquivo e envie junto com a versão:
```bash
cd backend
alembic revision --autogenerate -m "descricao da mudanca"   # com DATABASE_URL apontando para um banco de desenvolvimento
```

## Comandos úteis

| O quê | Comando |
|---|---|
| Logs da API | `docker compose logs -f api` |
| Logs dos robôs | `docker compose logs -f worker` |
| Reiniciar robôs | `docker compose restart worker` |
| Saúde | `curl -s localhost:8000/health` (no servidor) |
| Parar tudo | `docker compose -f docker-compose.yml -f docker-compose.prod.yml down` (os dados ficam nos volumes) |

## Quando crescer

- Banco e Redis gerenciados (ex.: um PostgreSQL gerenciado com backup automático) em vez de contêineres.
- Mais de uma réplica do `worker` (cada robô já tem trava no Redis).
- Monitoramento: Sentry para erros e um alerta se o worker parar (ex.: Uptime Kuma checando `/health`).
