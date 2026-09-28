#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
STACK="${1:-promobot}"
COMPOSE_ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-$STACK}"

# Renderiza o compose com TODAS as interpolações resolvidas
# (o arquivo pode ser trocado para instâncias como o promobot2)
docker compose --project-name "$COMPOSE_PROJECT" --env-file "$COMPOSE_ENV_FILE" -f docker-compose.yml config > /tmp/promobot-rendered.yml

# Normaliza o YAML para o formato aceito pelo `docker stack deploy` (swarm):
#  - depends_on no formato alto (mapa) vira lista de nomes de serviço
#  - cpus numérico vira string
STACK_NAME="$STACK" python3 - <<'EOF'
import os
import yaml

with open('/tmp/promobot-rendered.yml') as f:
    data = yaml.safe_load(f)

# `docker compose config` adiciona `name:` na raiz; swarm não aceita
data.pop('name', None)

for svc in data.get('services', {}).values():
    if isinstance(svc.get('depends_on'), dict):
        svc['depends_on'] = list(svc['depends_on'].keys())
    for port in svc.get('ports', []):
        if isinstance(port, dict):
            for field in ('published', 'target'):
                if field in port:
                    port[field] = int(port[field])
    res = svc.get('deploy', {}).get('resources', {})
    for scope in (res.get('limits'), res.get('reservations')):
        if scope and 'cpus' in scope:
            scope['cpus'] = str(scope['cpus'])

# A API pública da instância principal usa 8011. As demais instâncias ficam
# acessíveis apenas pela rede interna/túnel e não podem disputar essa porta.
if os.environ['STACK_NAME'] != 'promobot' and 'api' in data.get('services', {}):
    data['services']['api'].pop('ports', None)

with open('/tmp/promobot-rendered.yml', 'w') as f:
    yaml.safe_dump(data, f, sort_keys=False)
EOF

echo "Fazendo deploy do stack '${STACK}' a partir do YAML renderizado..."
PW=$(grep -E '^DASHBOARD_PASSWORD=' "$COMPOSE_ENV_FILE" | cut -d= -f2-)
echo "${PW}" | sudo -S docker stack deploy -c /tmp/promobot-rendered.yml "$STACK"

# O compose NÃO declara ports do evolution (evita conflito de host com o fork2,
# que usa o mesmo docker-compose.yml). Republição da porta 8085 é reaplicada aqui
# para que redeploys não derrubem o promobot-evo (túnel vps-vscode -> 127.0.0.1:8085).
if [ "$STACK" = "promobot" ]; then
  echo "${PW}" | sudo -S docker service update --publish-add published=8085,target=8080,protocol=tcp promobot_evolution-api >/dev/null 2>&1 || true
elif [ "$STACK" = "promobot2" ]; then
  # A segunda Evolution API precisa de uma porta própria para abrir o Manager
  # e parear o número do WhatsApp, sem disputar a porta 8085 da instância principal.
  echo "${PW}" | sudo -S docker service update --publish-add published=8086,target=8080,protocol=tcp promobot2_evolution-api >/dev/null 2>&1 || true
fi
