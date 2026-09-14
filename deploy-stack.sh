#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
STACK="${1:-promobot}"

# Renderiza o compose com TODAS as interpolações resolvidas
# (o `docker compose config` lê o .env do diretório automaticamente)
docker compose -f docker-compose.yml config > /tmp/promobot-rendered.yml

# Normaliza o YAML para o formato aceito pelo `docker stack deploy` (swarm):
#  - depends_on no formato alto (mapa) vira lista de nomes de serviço
#  - cpus numérico vira string
python3 - <<'EOF'
import yaml

with open('/tmp/promobot-rendered.yml') as f:
    data = yaml.safe_load(f)

# `docker compose config` adiciona `name:` na raiz; swarm não aceita
data.pop('name', None)

for svc in data.get('services', {}).values():
    if isinstance(svc.get('depends_on'), dict):
        svc['depends_on'] = list(svc['depends_on'].keys())
    res = svc.get('deploy', {}).get('resources', {})
    for scope in (res.get('limits'), res.get('reservations')):
        if scope and 'cpus' in scope:
            scope['cpus'] = str(scope['cpus'])

with open('/tmp/promobot-rendered.yml', 'w') as f:
    yaml.safe_dump(data, f, sort_keys=False)
EOF

echo "Fazendo deploy do stack '${STACK}' a partir do YAML renderizado..."
PW=$(grep -E '^DASHBOARD_PASSWORD=' .env | cut -d= -f2-)
echo "${PW}" | sudo -S docker stack deploy -c /tmp/promobot-rendered.yml "$STACK"

# O compose NÃO declara ports do evolution (evita conflito de host com o fork2,
# que usa o mesmo docker-compose.yml). Republição da porta 8085 é reaplicada aqui
# para que redeploys não derrubem o promobot-evo (túnel vps-vscode -> 127.0.0.1:8085).
if [ "$STACK" = "promobot" ]; then
  echo "${PW}" | sudo -S docker service update --publish-add published=8085,target=8080,protocol=tcp promobot_evolution-api >/dev/null 2>&1 || true
fi