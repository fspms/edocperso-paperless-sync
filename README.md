# edocperso-paperless-sync

Synchronise automatiquement les documents deposes sur [eDocPerso](https://edocperso.fr)
vers une instance [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx), via un
conteneur Docker planifie (cron integre).

Cree en reponse a la discussion communautaire
[paperless-ngx#7165](https://github.com/paperless-ngx/paperless-ngx/discussions/7165) —
mais reecrit pour l'API actuelle d'eDocPerso (backend `edp-back`, distinct de celle
decrite dans la discussion d'origine, qui a ete depreciee).

## Fonctionnement

1. Connexion a eDocPerso (email + mot de passe).
2. Listing de tous les documents disponibles (bulletins de paie, attestations,
   documents partages par des collecteurs, etc.).
3. Telechargement des documents pas encore importes (deduplication via un
   fichier d'etat local, jamais reimportes deux fois).
4. Envoi vers Paperless-ngx via son API REST (`/api/documents/post_document/`).

## Demarrage rapide

L'image est prete a l'emploi sur `ghcr.io/fspms/edocperso-paperless-sync`,
pas besoin de builder quoi que ce soit localement.

Commencez par recuperer un fichier `.env` (identifiants eDocPerso + URL/token
Paperless-ngx) :

```bash
cp .env.example .env
# renseigner .env
```

### Option A — Docker Compose

```yaml
services:
  edocperso-sync:
    image: ghcr.io/fspms/edocperso-paperless-sync:latest
    container_name: edocperso-sync
    restart: unless-stopped
    env_file:
      - .env
    environment:
      # Format cron standard : minute heure jour mois jour_semaine
      # Defaut : tous les jours a 06:05. Modifiable ici ou dans .env.
      CRON_SCHEDULE: "5 6 * * *"
      # Lance une synchro immediate au demarrage du conteneur (en plus du cron)
      RUN_ON_START: "true"
      TZ: "Europe/Paris"
    volumes:
      # Etat de dedoublonnage (IDs deja importes) : NE PAS supprimer entre
      # deux deploiements sinon tous les documents seront reimportes.
      - ./data:/data
      # Logs de synchro consultables sans "docker logs"
      - ./logs:/var/log/edocperso
```

```bash
docker compose up -d
docker compose logs -f
```

### Option B — `docker run`

```bash
docker run -d \
  --name edocperso-sync \
  --restart unless-stopped \
  --env-file .env \
  -e CRON_SCHEDULE="5 6 * * *" \
  -e RUN_ON_START="true" \
  -e TZ="Europe/Paris" \
  -v "$(pwd)/data:/data" \
  -v "$(pwd)/logs:/var/log/edocperso" \
  ghcr.io/fspms/edocperso-paperless-sync:latest
```

Mettre a jour vers la derniere image : `docker compose pull && docker compose up -d`
(ou `docker pull ghcr.io/fspms/edocperso-paperless-sync:latest` puis recreer le
conteneur avec `docker run`).

Voir [DEPLOIEMENT.md](DEPLOIEMENT.md) pour le detail (obtention du token API
Paperless-ngx, planification cron, alternative systemd, etc.).

## Configuration

Toutes les options se definissent via variables d'environnement (fichier `.env`,
voir [.env.example](.env.example)) :

| Variable | Description |
|---|---|
| `EDOCPERSO_EMAIL` | Email de connexion eDocPerso |
| `EDOCPERSO_PASSWORD` | Mot de passe eDocPerso |
| `PAPERLESS_URL` | URL de base de votre instance Paperless-ngx |
| `PAPERLESS_TOKEN` | Token API Paperless-ngx |
| `EDOCPERSO_TAG` | Tag applique aux documents importes (defaut: `edocperso`) |
| `CRON_SCHEDULE` | Expression cron (defaut: `5 6 * * *`, tous les jours a 6h05) |
| `RUN_ON_START` | Lance une synchro immediate au demarrage du conteneur (defaut: `true`) |

## Limites connues

- **API non officielle** : eDocPerso ne fournit pas d'API publique. Ce projet
  s'appuie sur les endpoints internes de leur application web (retro-ingenierie),
  qui peuvent changer sans preavis.
- **Pas de support FranceConnect ni MFA** : ne fonctionne que si votre compte
  eDocPerso se connecte avec un simple email + mot de passe.
- Utilisez ce projet a vos risques, et ne partagez jamais votre fichier `.env`.

## Licence

MIT — voir [LICENSE](LICENSE).
