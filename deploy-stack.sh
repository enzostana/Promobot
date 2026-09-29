#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
STACK="${1:-promobot}"
COMPOSE_ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-$STACK}"
RENDERED_FILE="$(mktemp "${TMPDIR:-/tmp}/promobot-rendered.XXXXXX.yml")"
trap 'rm -f "$RENDERED_FILE"' EXIT

# Renderiza o compose com TODAS as interpolações resolvidas
# (o arquivo pode ser trocado para instâncias como o promobot2)
docker compose --project-name "$COMPOSE_PROJECT" --env-file "$COMPOSE_ENV_FILE" -f docker-compose.yml config > "$RENDERED_FILE"

# Normaliza o YAML para o formato aceito pelo `docker stack deploy` (swarm):
#  - depends_on no formato alto (mapa) vira lista de nomes de serviço
#  - cpus numérico vira string
STACK_NAME="$STACK" RENDERED_FILE="$RENDERED_FILE" python3 - <<'EOF'
import os
import yaml

with open(os.environ['RENDERED_FILE']) as f:
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

with open(os.environ['RENDERED_FILE'], 'w') as f:
    yaml.safe_dump(data, f, sort_keys=False)
EOF

echo "Fazendo deploy do stack '${STACK}' a partir do YAML renderizado..."
echo "Construindo imagens da instância '${STACK}'..."
sudo docker compose --project-name "$COMPOSE_PROJECT" --env-file "$COMPOSE_ENV_FILE" -f docker-compose.yml build migrator api worker telegram_listener
sudo docker stack deploy -c "$RENDERED_FILE" "$STACK"

# Swarm ignores depends_on ordering. Force the one-shot migrator to run on
# every deploy, retry failures while Postgres starts, and do not restart the
# application services until the schema is current.
MIGRATOR_SERVICE="${STACK}_migrator"
sudo docker service update --force "$MIGRATOR_SERVICE" >/dev/null
echo "Aguardando migrações do banco (${MIGRATOR_SERVICE})..."
MIGRATION_COMPLETE=false
for _ in $(seq 1 90); do
  task_id="$(sudo docker service ps --no-trunc --format '{{.ID}}' "$MIGRATOR_SERVICE" 2>/dev/null | head -n 1 || true)"
  if [[ -n "$task_id" ]]; then
    task_state="$(sudo docker inspect --type task --format '{{.Status.State}}' "$task_id" 2>/dev/null || true)"
    if [[ "$task_state" == "complete" ]]; then
      MIGRATION_COMPLETE=true
      break
    fi
  fi
  sleep 2
done
if [[ "$MIGRATION_COMPLETE" != true ]]; then
  echo "Migrações não concluíram. Inspecione os logs de ${MIGRATOR_SERVICE} antes de liberar o worker." >&2
  exit 1
fi

# Pick up the freshly built image and start the consumers only after the
# database schema is ready. Existing Redis queue contents are preserved.
for service in api worker telegram_listener; do
  sudo docker service update --force "${STACK}_${service}" >/dev/null
done

# O compose NÃO declara ports do evolution (evita conflito de host com o fork2,
# que usa o mesmo docker-compose.yml). Republição da porta 8085 é reaplicada aqui
# para que redeploys não derrubem o promobot-evo (túnel vps-vscode -> 127.0.0.1:8085).
if [ "$STACK" = "promobot" ]; then
  sudo docker service update --publish-add published=8085,target=8080,protocol=tcp promobot_evolution-api >/dev/null 2>&1 || true
elif [ "$STACK" = "promobot2" ]; then
  # A segunda Evolution API precisa de uma porta própria para abrir o Manager
  # e parear o número do WhatsApp, sem disputar a porta 8085 da instância principal.
  sudo docker service update --publish-add published=8086,target=8080,protocol=tcp promobot2_evolution-api >/dev/null 2>&1 || true
fi
