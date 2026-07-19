FROM python:3.12-slim

# cron : planificateur ; tzdata : pour que CRON_SCHEDULE/TZ soit interprete correctement
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY edocperso_sync.py .
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Etat + logs persistants (montes en volume via docker-compose)
RUN mkdir -p /data /var/log/edocperso
ENV EDOCPERSO_STATE_FILE=/data/edocperso_state.json

# Planification par defaut : tous les jours a 06:05 (surchargable via CRON_SCHEDULE)
ENV CRON_SCHEDULE="5 6 * * *"

ENTRYPOINT ["/entrypoint.sh"]
