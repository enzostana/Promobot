#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${MOTODEV_ENV_FILE:-/home/cinadmin/promobot-fork2/.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Arquivo de configuração Motodev não encontrado: $ENV_FILE" >&2
  exit 1
fi
if [[ ! -t 0 ]]; then
  echo "Execute este script em um terminal interativo para inserir o ssid sem exibi-lo." >&2
  exit 1
fi

read -r -s -p "SSID da conta afiliada Motodev (entrada oculta): " ssid
printf '\n'
trap 'unset ssid' EXIT
if [[ -z "${ssid//[[:space:]]/}" ]]; then
  echo "O ssid não pode ficar vazio." >&2
  exit 1
fi

new_secret_name="promobot2mel_session_$(date -u +%Y%m%d%H%M%S)_$$"
sudo -v
if ! printf '%s' "$ssid" | sudo docker secret create "$new_secret_name" - >/dev/null; then
  echo "Não foi possível criar o Docker Secret. Nenhuma configuração foi alterada." >&2
  exit 1
fi
unset ssid

python3 - "$ENV_FILE" "$new_secret_name" <<'PY'
import os
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
secret_name = sys.argv[2]
updates = {
    "MEL_SESSION_SECRET_NAME": secret_name,
    "MERCADOLIVRE_MINT": "true",
    "MERCADOLIVRE_MINT_STRICT": "false",
}
mode = stat.S_IMODE(path.stat().st_mode)
lines = path.read_text().splitlines()
written = set()
result = []

for line in lines:
    key = line.partition("=")[0].strip()
    if key in updates:
        if key not in written:
            result.append(f"{key}={updates[key]}")
            written.add(key)
    else:
        result.append(line)

for key, value in updates.items():
    if key not in written:
        result.append(f"{key}={value}")

temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
temporary.write_text("\n".join(result) + "\n")
temporary.chmod(mode)
os.replace(temporary, path)
PY

cd "$ROOT_DIR"
ENV_FILE="$ENV_FILE" ./deploy-stack.sh promobot2

echo "Motodev atualizado com mint oficial habilitado e fallback preservado."
echo "Confira um link de produto no grupo antes de ativar mercadolivre_mint_strict no painel."
