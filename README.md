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

L'image est publiee automatiquement sur GitHub Container Registry a chaque
modification du depot : pas besoin de builder quoi que ce soit localement.

```bash
cp .env.example .env
# renseigner .env : identifiants eDocPerso + URL/token Paperless-ngx

docker compose up -d
docker compose logs -f
```

`docker compose pull && docker compose up -d` recupere la derniere version de
l'image publiee.

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

## Publication automatique de l'image

Le workflow [`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml)
construit et publie l'image (`linux/amd64` + `linux/arm64`) sur
`ghcr.io/fspms/edocperso-paperless-sync` a chaque push sur `main`, taggee
`latest` (et aussi par SHA de commit / version semver si vous poussez un tag
`vX.Y.Z`). Aucun secret a configurer : GitHub fournit automatiquement le
jeton necessaire.

**Premiere publication uniquement** : le paquet est cree prive par defaut.
Pour que d'autres puissent le telecharger sans authentification, allez sur
la page du paquet (onglet *Packages* du profil ou du depot) > *Package
settings* > *Change visibility* > *Public*.

## Limites connues

- **API non officielle** : eDocPerso ne fournit pas d'API publique. Ce projet
  s'appuie sur les endpoints internes de leur application web (retro-ingenierie),
  qui peuvent changer sans preavis.
- **Pas de support FranceConnect ni MFA** : ne fonctionne que si votre compte
  eDocPerso se connecte avec un simple email + mot de passe.
- Utilisez ce projet a vos risques, et ne partagez jamais votre fichier `.env`.

## Licence

MIT — voir [LICENSE](LICENSE).
