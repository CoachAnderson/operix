#!/usr/bin/env sh
# Backup diário do banco. Agende no cron do servidor:
#   0 3 * * * cd /opt/operix && ./deploy/backup.sh >> backups/backup.log 2>&1
set -eu
cd "$(dirname "$0")/.."
mkdir -p backups
FILE="backups/operix-$(date +%Y-%m-%d_%H%M).sql.gz"
docker compose exec -T db pg_dump -U operix operix | gzip > "$FILE"
find backups -name 'operix-*.sql.gz' -mtime +14 -delete   # guarda 14 dias
echo "Backup ok: $FILE"
# Copie também para fora do servidor (ex.: rclone para um bucket) — backup só local não protege de perda do VPS.
