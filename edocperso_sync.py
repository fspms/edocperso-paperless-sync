#!/usr/bin/env python3
"""
edocperso_sync.py

Recupere automatiquement les documents deposes sur eDocPerso (edocperso.fr)
et les importe dans Paperless-ngx via son API REST.

Le site edocperso.fr a ete refondu (backend "edp-back" opere par Silae) et
n'utilise plus l'API decrite dans la discussion GitHub
https://github.com/paperless-ngx/paperless-ngx/discussions/7165 (celle-ci
renvoie desormais 404). Les endpoints ci-dessous ont ete retrouves en
inspectant le trafic reseau du site en date de juillet 2026 :
  - POST /edp-back/api/v1/login              (credentials -> header Set-Authorization: JWT)
  - POST /edp-back/api/v1/documents           (liste paginee de tous les documents)
  - POST /edp-back/api/v1/documents/download  (contenu binaire d'un ou plusieurs documents)
  - GET  /edp-back/api/v1/folders             (arborescence des dossiers, pour le libelle)

ATTENTION : eDocPerso n'expose pas d'API publique/officielle. Ce script
utilise des points d'entree internes de leur application web, qui peuvent
changer ou casser sans preavis. Utilisez-le a vos risques, et ne partagez
jamais vos identifiants edocperso. Ce script ne gere pas FranceConnect ni
une eventuelle authentification a deux facteurs : il ne fonctionne que si
votre compte se connecte avec un simple email + mot de passe.

--------------------------------------------------------------------------
Configuration (variables d'environnement, ou fichier .env a cote du script)
--------------------------------------------------------------------------
EDOCPERSO_EMAIL         Email de connexion edocperso
EDOCPERSO_PASSWORD      Mot de passe edocperso
PAPERLESS_URL           URL de base de Paperless-ngx (ex: https://paperless.example.com)
PAPERLESS_TOKEN         Token API Paperless-ngx (Reglages > Mon profil > API Token,
                        ou: python manage.py drf_create_token <user>)
EDOCPERSO_STATE_FILE    (optionnel) chemin du fichier d'etat, defaut:
                        ./edocperso_state.json
EDOCPERSO_TAG           (optionnel) nom d'un tag Paperless a appliquer aux
                        documents importes (ex: "edocperso"). Le tag doit
                        deja exister ou sera cree via l'API si absent.

--------------------------------------------------------------------------
Usage
--------------------------------------------------------------------------
python3 edocperso_sync.py            # lance une synchro complete
python3 edocperso_sync.py --dry-run  # liste ce qui serait importe, sans rien envoyer
python3 edocperso_sync.py --verbose  # logs detailles

Planification recommandee : cron quotidien sur la machine qui heberge
(ou peut joindre) votre instance Paperless-ngx. Voir DEPLOIEMENT.md.
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_STATE_FILE = SCRIPT_DIR / "edocperso_state.json"
DEFAULT_ENV_FILE = SCRIPT_DIR / ".env"

EDOCPERSO_BASE_URL = "https://edocperso.fr/edp-back"
EDOCPERSO_LOGIN_URL = f"{EDOCPERSO_BASE_URL}/api/v1/login"
EDOCPERSO_FOLDERS_URL = f"{EDOCPERSO_BASE_URL}/api/v1/folders"
EDOCPERSO_DOCUMENTS_URL = f"{EDOCPERSO_BASE_URL}/api/v1/documents"
EDOCPERSO_DOWNLOAD_URL = f"{EDOCPERSO_BASE_URL}/api/v1/documents/download"

PAGE_SIZE = 200

REQUEST_TIMEOUT = 60

logger = logging.getLogger("edocperso_sync")


def load_dotenv(path: Path) -> None:
    """Charge un fichier .env minimal (KEY=VALUE) sans dependance externe."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


class ConfigError(RuntimeError):
    pass


class Config:
    def __init__(self):
        load_dotenv(DEFAULT_ENV_FILE)

        self.edocperso_email = os.environ.get("EDOCPERSO_EMAIL")
        self.edocperso_password = os.environ.get("EDOCPERSO_PASSWORD")
        self.paperless_url = (os.environ.get("PAPERLESS_URL") or "").rstrip("/")
        self.paperless_token = os.environ.get("PAPERLESS_TOKEN")
        self.state_file = Path(os.environ.get("EDOCPERSO_STATE_FILE", str(DEFAULT_STATE_FILE)))
        self.tag_name = os.environ.get("EDOCPERSO_TAG", "edocperso")

        missing = [
            name
            for name, val in [
                ("EDOCPERSO_EMAIL", self.edocperso_email),
                ("EDOCPERSO_PASSWORD", self.edocperso_password),
                ("PAPERLESS_URL", self.paperless_url),
                ("PAPERLESS_TOKEN", self.paperless_token),
            ]
            if not val
        ]
        if missing:
            raise ConfigError(
                "Variables manquantes : " + ", ".join(missing) +
                f"\nDefinissez-les en variables d'environnement ou dans {DEFAULT_ENV_FILE}"
            )


# --------------------------------------------------------------------------
# Client eDocPerso
# --------------------------------------------------------------------------

class EdocPersoError(RuntimeError):
    pass


class EdocPersoClient:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.token = None
        self._http = requests.Session()

    def authenticate(self) -> None:
        logger.info("Authentification aupres d'eDocPerso...")
        resp = self._http.post(
            EDOCPERSO_LOGIN_URL,
            json={"email": self.email, "password": self.password},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code >= 400:
            raise EdocPersoError(
                f"Echec de connexion (HTTP {resp.status_code}): {resp.text[:300]}"
            )

        token = resp.headers.get("Set-Authorization")
        if not token:
            raise EdocPersoError(
                "Pas de token recu (header Set-Authorization absent). "
                "L'API a peut-etre encore change, ou le compte necessite "
                "FranceConnect / une double authentification non geree par ce script."
            )
        self.token = token[len("Bearer "):] if token.startswith("Bearer ") else token
        self._http.headers["Authorization"] = f"Bearer {self.token}"
        logger.info("Authentification reussie.")

    def list_folders(self) -> dict:
        """Retourne un dict {folderId: {name, parentId}} pour construire des chemins lisibles."""
        resp = self._http.get(
            EDOCPERSO_FOLDERS_URL,
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            f["id"]: {"name": f.get("name", ""), "parentId": f.get("parentId")}
            for f in data.get("folders", [])
        }

    def folder_path(self, folder_id: str, folders: dict) -> str:
        parts = []
        seen = set()
        current = folder_id
        while current and current in folders and current not in seen:
            seen.add(current)
            parts.append(folders[current]["name"])
            current = folders[current]["parentId"]
        return "/".join(reversed(parts))

    def list_documents(self) -> list:
        """Retourne tous les documents (toutes categories/dossiers confondus)."""
        if not self.token:
            raise EdocPersoError("Non authentifie: appelez authenticate() d'abord.")

        items = []
        offset = 0
        while True:
            resp = self._http.post(
                EDOCPERSO_DOCUMENTS_URL,
                json={"paging": {"limit": PAGE_SIZE, "offset": offset}},
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("items", [])
            items.extend(batch)
            total = data.get("paging", {}).get("total", len(items))
            offset += len(batch)
            if not batch or offset >= total:
                break
        return items

    def download_document(self, document_id: str) -> bytes:
        if not self.token:
            raise EdocPersoError("Non authentifie: appelez authenticate() d'abord.")

        resp = self._http.post(
            EDOCPERSO_DOWNLOAD_URL,
            json={"documentIds": [document_id], "folderIds": []},
            headers={"Accept": "*/*", "Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.content


# --------------------------------------------------------------------------
# Client Paperless-ngx
# --------------------------------------------------------------------------

class PaperlessClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self._http = requests.Session()
        self._http.headers["Authorization"] = f"Token {token}"

    def get_or_create_tag(self, name: str) -> int:
        resp = self._http.get(
            f"{self.base_url}/api/tags/",
            params={"name__iexact": name},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if results:
            return results[0]["id"]

        resp = self._http.post(
            f"{self.base_url}/api/tags/",
            json={"name": name},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def upload_document(self, filename: str, content: bytes, title: str,
                         created: str = None, tag_id: int = None) -> str:
        """Envoie un document a Paperless-ngx. Retourne l'UUID de la tache d'ingestion."""
        files = {"document": (filename, content)}
        data = {"title": title}
        if created:
            data["created"] = created
        if tag_id:
            data["tags"] = str(tag_id)

        resp = self._http.post(
            f"{self.base_url}/api/documents/post_document/",
            files=files,
            data=data,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.text.strip('"')


# --------------------------------------------------------------------------
# Etat local (dedoublonnage)
# --------------------------------------------------------------------------

def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"imported_ids": []}


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------
# Programme principal
# --------------------------------------------------------------------------

def run(dry_run: bool = False) -> int:
    config = Config()
    state = load_state(config.state_file)
    imported_ids = set(state.get("imported_ids", []))

    edp = EdocPersoClient(config.edocperso_email, config.edocperso_password)
    edp.authenticate()
    folders = edp.list_folders()
    documents = edp.list_documents()
    logger.info("Documents trouves sur eDocPerso: %d", len(documents))

    # On ignore les documents pas encore prets ou bloques (GDPR/retention)
    ready_documents = [
        d for d in documents
        if d.get("state", "Ready") == "Ready" and not d.get("isGDPRBlocked")
    ]

    new_files = [d for d in ready_documents if d.get("id") not in imported_ids]
    logger.info("Nouveaux documents a importer: %d", len(new_files))

    for f in new_files:
        f["folder_path"] = edp.folder_path(f.get("folderId"), folders)

    if dry_run:
        for f in new_files:
            logger.info("  [dry-run] %s/%s (id=%s)", f.get("folder_path"), f.get("title"), f.get("id"))
        return 0

    if not new_files:
        return 0

    paperless = PaperlessClient(config.paperless_url, config.paperless_token)
    tag_id = None
    if config.tag_name:
        try:
            tag_id = paperless.get_or_create_tag(config.tag_name)
        except requests.RequestException as exc:
            logger.warning("Impossible de creer/recuperer le tag '%s': %s", config.tag_name, exc)

    imported_count = 0
    failed_count = 0

    for f in new_files:
        doc_id = f.get("id")
        doc_title = f.get("title", doc_id)
        extension = f.get("fileExtension", "") or ""
        filename = doc_title if doc_title.lower().endswith(extension.lower()) else f"{doc_title}{extension}"
        folder_path = f.get("folder_path", "")
        title = f"{folder_path}/{doc_title}" if folder_path else doc_title

        try:
            logger.info("Telechargement: %s", title)
            content = edp.download_document(doc_id)

            logger.info("Envoi vers Paperless-ngx: %s", title)
            paperless.upload_document(
                filename=filename,
                content=content,
                title=title,
                created=f.get("dateAdded"),
                tag_id=tag_id,
            )

            imported_ids.add(doc_id)
            state["imported_ids"] = sorted(imported_ids)
            save_state(config.state_file, state)  # sauvegarde apres chaque succes
            imported_count += 1

        except Exception as exc:  # noqa: BLE001 - on ne veut pas arreter la synchro pour 1 echec
            failed_count += 1
            logger.error("Echec import '%s' (id=%s): %s", title, doc_id, exc)

        time.sleep(0.5)  # petite pause pour ne pas marteler les serveurs

    logger.info("Termine. Importes: %d, echecs: %d", imported_count, failed_count)
    return 1 if failed_count else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronise eDocPerso vers Paperless-ngx")
    parser.add_argument("--dry-run", action="store_true", help="Liste sans rien importer")
    parser.add_argument("--verbose", action="store_true", help="Logs detailles")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    try:
        return run(dry_run=args.dry_run)
    except ConfigError as exc:
        logger.error("Configuration invalide: %s", exc)
        return 2
    except EdocPersoError as exc:
        logger.error("Erreur eDocPerso: %s", exc)
        return 3
    except requests.RequestException as exc:
        logger.error("Erreur reseau: %s", exc)
        return 4


if __name__ == "__main__":
    sys.exit(main())
