# Deploiement : sync eDocPerso -> Paperless-ngx

## Pourquoi pas "automatique dans le cloud" ?

eDocPerso ne fournit pas d'API officielle (cf. la discussion GitHub #7165) : les
appels reposent sur des endpoints internes de leur application web. Ce script
doit donc tourner depuis une machine qui a un acces internet normal (pas de
proxy/allowlist restrictif) et, idealement, qui peut aussi joindre votre
instance Paperless-ngx : votre NAS, votre serveur Docker, un Raspberry Pi, etc.
Le plus simple est de le mettre sur la meme machine que Paperless-ngx.

## 1. Prerequis

```bash
python3 -m pip install requests
```

## 2. Recuperer un token API Paperless-ngx

Dans l'interface Paperless-ngx : **Mon profil** (icone en haut a droite) >
**API Token**, ou en ligne de commande sur le serveur :

```bash
python3 manage.py drf_create_token <votre_utilisateur>
```

(Si vous utilisez l'image Docker officielle : `docker exec -it paperless-ngx-webserver-1 python3 manage.py drf_create_token <utilisateur>`)

## 3. Configurer les identifiants

Copiez `edocperso_sync.py` sur votre machine, puis creez un fichier `.env` a
cote (meme dossier) :

```
EDOCPERSO_EMAIL=votre.email@exemple.fr
EDOCPERSO_PASSWORD=votre_mot_de_passe_edocperso
PAPERLESS_URL=https://paperless.example.com
PAPERLESS_TOKEN=le_token_recupere_a_l_etape_2
EDOCPERSO_TAG=edocperso
```

Protegez ce fichier : `chmod 600 .env` (il contient un mot de passe en clair).

## 4. Tester

```bash
python3 edocperso_sync.py --dry-run --verbose
```

Cela liste les documents eDocPerso qui seraient importes, sans rien envoyer.
Verifiez que la liste est coherente, puis lancez un vrai essai :

```bash
python3 edocperso_sync.py --verbose
```

Un fichier `edocperso_state.json` est cree a cote du script : il retient les
IDs deja importes pour ne jamais dupliquer un document lors des prochaines
executions.

## 5. Planifier (cron)

```bash
crontab -e
```

Ajoutez, par exemple pour une execution tous les jours a 6h05 :

```
5 6 * * * cd /chemin/vers/le/script && /usr/bin/python3 edocperso_sync.py >> sync.log 2>&1
```

### Alternative systemd (timer)

`/etc/systemd/system/edocperso-sync.service` :
```ini
[Unit]
Description=Sync eDocPerso vers Paperless-ngx

[Service]
Type=oneshot
WorkingDirectory=/chemin/vers/le/script
ExecStart=/usr/bin/python3 edocperso_sync.py
```

`/etc/systemd/system/edocperso-sync.timer` :
```ini
[Unit]
Description=Lance edocperso-sync chaque jour

[Timer]
OnCalendar=*-*-* 06:05:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now edocperso-sync.timer
```

## 6. Alternative : Docker Compose

Les fichiers `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`, `.env.example`
et `requirements.txt` fournis permettent de faire tourner la synchro en
conteneur, avec cron integre (pas besoin de cron sur l'hote).

```bash
cp .env.example .env
# remplir .env (identifiants edocperso + token Paperless)

docker compose up -d --build
docker compose logs -f      # suit la synchro (une premiere execution
                             # a lieu immediatement au demarrage, puis
                             # selon CRON_SCHEDULE, defaut 06:05/jour)
```

Points a connaitre :

- `CRON_SCHEDULE` (variable d'environnement dans `docker-compose.yml`) accepte
  n'importe quelle expression cron standard (ex: `*/30 * * * *` pour toutes
  les 30 min).
- `RUN_ON_START=false` desactive la synchro immediate au demarrage si vous ne
  voulez attendre que le prochain creneau cron.
- Le dossier `./data` (monte en volume) contient `edocperso_state.json` :
  **ne le supprimez pas**, sinon tous les documents seront reimportes en
  double a la prochaine synchro.
- Le dossier `./logs` contient l'historique des executions, lisible sans
  passer par `docker logs`.
- Le conteneur doit pouvoir joindre `edocperso.fr`, `v2-app.edocperso.fr` et
  votre `PAPERLESS_URL` : verifiez que le reseau Docker/hote n'a pas de
  proxy/allowlist qui bloquerait ces domaines.
- Si Paperless-ngx tourne lui aussi en Docker Compose sur la meme machine,
  vous pouvez rejoindre son reseau Docker et utiliser le nom du service
  (ex: `PAPERLESS_URL=http://webserver:8000`) plutot que l'URL publique.

## 7. Limites connues

- API non officielle : eDocPerso peut la modifier ou la bloquer sans preavis.
- Pas de gestion 2FA/captcha : si votre compte a une double authentification
  active, l'authentification par login/mot de passe simple echouera.
- Les documents sont importes avec pour titre `dossier/nom_du_fichier` et la
  date de depot eDocPerso comme date de creation Paperless ; ajustez
  `upload_document()` dans le script si vous voulez un autre comportement
  (correspondant, type de document, etc. — voir les parametres de
  `post_document` dans le script).
