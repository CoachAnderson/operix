#!/bin/sh
# Gera o .zip que o painel oferece para download (frontend/public/downloads). Rode após mudar o conector.
set -e
cd "$(dirname "$0")"
OUT=../frontend/public/downloads/conector-oraculoinvest-mt5.zip
TMP=$(mktemp -d)
mkdir -p "$TMP/conector-oraculoinvest-mt5" ../frontend/public/downloads
cp oraculo_conector.py requirements.txt conector.ini.exemplo iniciar.bat gerar_exe.bat LEIA-ME.txt "$TMP/conector-oraculoinvest-mt5/"
rm -f "$OUT"
(cd "$TMP" && zip -qr - conector-oraculoinvest-mt5) > "$OUT"
rm -rf "$TMP"
echo "Gerado $OUT"
