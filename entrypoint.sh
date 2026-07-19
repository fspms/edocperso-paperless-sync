#!/bin/bash
set -euo pipefail

ENV_FILE=/app/container.env
LOG_FILE=/var/log/edocperso/sync.log

# 1. Exporter les variables d'environnement du conteneur dans un fichier que
#    cron pourra sourcer (cron ne herite pas de l'environnement du process 1).
printenv | grep -E '^(EDOCPERSO_|PAPERLESS_)' | sed 's/^\(.*\)$/export \1/' > "$ENV_FILE"
chmod 600 "$ENV_FILE"

touch "$LOG_FILE"

# 2. Ecrire le crontab a partir de CRON_SCHEDULE (defaut fourni dans le Dockerfile)
CRON_SCHEDULE="${CRON_SCHEDULE:-5 6 * * *}"
cat > /etc/cron.d/edocperso-sync <<EOF
${CRON_SCHEDULE} root . ${ENV_FILE}; cd /app && /usr/local/bin/python3 edocperso_sync.py >> ${LOG_FILE} 2>&1
EOF
chmod 0644 /etc/cron.d/edocperso-sync
crontab /etc/cron.d/edocperso-sync

echo "[entrypoint] Planification cron : ${CRON_SCHEDULE}"

# 3. Optionnel : lancer une synchro immediate au demarrage du conteneur
if [ "${RUN_ON_START:-true}" = "true" ]; then
    echo "[entrypoint] Synchro initiale au demarrage..."
    (. "$ENV_FILE"; cd /app && python3 edocperso_sync.py --verbose) 2>&1 | tee -a "$LOG_FILE" || true
fi

# 4. Demarrer cron au premier plan et suivre les logs pour que
#    `docker logs` / `docker compose logs -f` affiche l'activite.
cron
tail -F "$LOG_FILE"
