"""Serveur du site d'apprentissage fédéré — modèle global et contributions.

Rôle exact du serveur, et rien de plus :

  * il **héberge le modèle global** et le distribue (``GET /api/model``) ;
  * il **reçoit les mises à jour** envoyées par les navigateurs des collègues
    (``POST /api/contribute``) et les met en attente ;
  * il sert les pages statiques.

Ce qu'il ne fait pas, volontairement :

  * il ne reçoit ni ne stocke aucune mesure brute. Le calcul a lieu entièrement
    dans le navigateur du collègue ; seuls des coefficients et des sommes
    agrégées circulent.
  * il n'intègre pas automatiquement une contribution au modèle publié. Une
    route ouverte qui modifierait le modèle global serait empoisonnable : un
    seul envoi malveillant ou simplement erroné dégraderait le modèle de tout
    le monde, silencieusement. Les contributions atterrissent donc dans une
    file d'attente, et l'agrégation est une action délibérée, lancée à la main
    (``python -m server.aggregate``). Ça préserve aussi le contrôle
    scientifique : on regarde ce qui arrive avant de le publier.

Lancement en local pour tester :

    cd Federated_Learning_Website
    pip install -r server/requirements.txt
    uvicorn server.app:app --reload --port 8000

puis http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from server.aggregate import run_aggregation, run_rollback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Les clés vivent dans Federated_Learning_Website/.env — jamais dans web/ (ce
# dossier est servi tel quel par StaticFiles, un fichier qui y traînerait
# serait lisible par n'importe quel visiteur) et jamais dans le dépôt (voir
# .gitignore). load_dotenv() ne remplace pas une variable déjà présente dans
# l'environnement : un déploiement qui préfère systemd EnvironmentFile= ou un
# export manuel continue de fonctionner sans .env du tout.
load_dotenv(ROOT / ".env")

# Le magasin est déplaçable par DEAM_FL_STORE : les contrôles automatiques s'en
# servent pour travailler sur une copie jetable, sans risquer d'écrire dans le
# magasin réel — celui dont les fichiers partent sur le serveur.
STORE = Path(os.environ.get("DEAM_FL_STORE") or (HERE / "store")).resolve()
MODELS_DIR = STORE / "models"
QUEUE_DIR = STORE / "queue"
WEB_DIR = ROOT / "web"

for _d in (MODELS_DIR, QUEUE_DIR, STORE / "stats"):
    _d.mkdir(parents=True, exist_ok=True)

# Nombre minimal de lignes pour qu'une contribution soit acceptée.
# Ce n'est pas une contrainte statistique mais une précaution de
# confidentialité : les sommes envoyées (D'D, D'y) ne sont pas anonymes sur
# très peu de lignes — à une seule ligne, elles la restituent exactement.
MIN_ROWS = 5

# Clé partagée attendue dans l'en-tête X-API-Key. À définir dans .env (voir
# .env.example) ou dans l'environnement du service. Si elle est absente, le
# serveur démarre quand même mais REFUSE toute contribution : mieux vaut un
# site en lecture seule qu'un modèle global ouvert à tous les vents.
API_KEY = os.environ.get("DEAM_FL_API_KEY", "").strip()
# Clé d'administration, distincte : elle seule donne accès à la file d'attente.
ADMIN_KEY = os.environ.get("DEAM_FL_ADMIN_KEY", "").strip()

app = FastAPI(title="DEAM — Federated residual-stress models",
              version="1.0",
              docs_url="/api/docs", openapi_url="/api/openapi.json")


# --------------------------------------------------------------------------- #
# Accès au magasin
# --------------------------------------------------------------------------- #
def model_versions() -> list[int]:
    """Versions disponibles, dans l'ordre croissant."""
    out = []
    for path in MODELS_DIR.glob("model_v*.json"):
        match = re.fullmatch(r"model_v(\d+)", path.stem)
        if match:
            out.append(int(match.group(1)))
    return sorted(out)


def load_model(version: int | None = None) -> dict[str, Any]:
    versions = model_versions()
    if not versions:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Aucun modèle global publié. Lancez tools/fit_pretrained.py.")
    wanted = versions[-1] if version is None else version
    path = MODELS_DIR / f"model_v{wanted}.json"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"Version {wanted} inconnue. "
                            f"Disponibles : {versions}")
    return json.loads(path.read_text(encoding="utf-8"))


def require_contributor_key(x_api_key: str = Header(default="")) -> None:
    if not API_KEY:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Les contributions sont fermées : aucune clé n'est configurée sur "
            "le serveur (variable d'environnement DEAM_FL_API_KEY).")
    # Comparaison à temps constant : une comparaison naïve laisse deviner la
    # clé caractère par caractère en mesurant le temps de réponse.
    if not secrets.compare_digest(x_api_key.strip(), API_KEY):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Clé d'accès invalide ou absente.")


def require_admin_key(x_admin_key: str = Header(default="")) -> None:
    if not ADMIN_KEY or not secrets.compare_digest(x_admin_key.strip(),
                                                   ADMIN_KEY):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Réservé à l'administrateur.")


# --------------------------------------------------------------------------- #
# Contrat de la contribution
# --------------------------------------------------------------------------- #
class Contributor(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    lab: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=200)


class Dataset(BaseModel):
    """Métadonnées du jeu de données — sans les données.

    La méthode de mesure est obligatoire : diffraction des rayons X et perçage
    incrémental ne donnent pas la même valeur sur la même pièce (biais
    systématique de plusieurs dizaines de MPa). Réunir les deux sans le savoir
    fabriquerait un modèle qui moyenne deux conventions différentes.
    """
    n_rows: int = Field(ge=MIN_ROWS)
    material: str = Field(min_length=1, max_length=120)
    process: str | None = Field(default=None, max_length=120)
    coolant: str | None = Field(default=None, max_length=120)
    measurement_method: Literal["XRD", "hole-drilling", "neutron",
                                "contour", "other"]
    feature_ranges: dict[str, tuple[float, float]] = {}
    notes: str | None = Field(default=None, max_length=2000)


class SufficientStats(BaseModel):
    """``D'D``, ``D'y``, ``y'y``, ``n`` avec ``D = [1, X]``.

    C'est la mise à jour de modèle proprement dite : elle permet de refaire
    l'ajustement sur les données réunies au coefficient près, sans transporter
    une seule mesure.
    """
    n: int = Field(ge=MIN_ROWS)
    dtd: list[list[float]]
    dty: list[float]
    yty: float

    @field_validator("dtd")
    @classmethod
    def _square_and_finite(cls, v):
        size = len(v)
        if size < 2 or any(len(row) != size for row in v):
            raise ValueError("dtd doit être une matrice carrée")
        arr = np.asarray(v, float)
        if not np.isfinite(arr).all():
            raise ValueError("dtd contient des valeurs non finies")
        # D'D est une matrice de Gram : symétrique et semi-définie positive.
        # Un envoi qui ne l'est pas est soit corrompu, soit fabriqué à la main ;
        # dans les deux cas il n'a rien à faire dans la file.
        if not np.allclose(arr, arr.T, atol=1e-6 * max(1.0, np.abs(arr).max())):
            raise ValueError("dtd n'est pas symétrique")
        if float(np.min(np.linalg.eigvalsh(arr))) < -1e-6 * max(
                1.0, np.abs(arr).max()):
            raise ValueError("dtd n'est pas semi-définie positive")
        return v

    @field_validator("dty")
    @classmethod
    def _finite(cls, v):
        if not np.isfinite(np.asarray(v, float)).all():
            raise ValueError("dty contient des valeurs non finies")
        return v


class EngineFit(BaseModel):
    intercept: float
    coef: list[float]
    space: Literal["raw", "standardised"]
    lambda_: float | None = Field(default=None, alias="lambda")
    loo: dict[str, float] = {}
    train: dict[str, float] = {}

    model_config = {"populate_by_name": True}


class Contribution(BaseModel):
    schema_: Literal["deam-fl-contribution/1"] = Field(alias="schema")
    model_version: int
    target: str = Field(min_length=1, max_length=60)
    features: list[str]
    contributor: Contributor
    dataset: Dataset
    sufficient_statistics: SufficientStats
    local_fit: dict[str, EngineFit] = {}
    scores: dict[str, dict[str, float]] = {}

    model_config = {"populate_by_name": True}


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/api/model")
def get_model(version: int | None = None):
    """Le modèle global. C'est ce que le navigateur télécharge au démarrage."""
    return load_model(version)


@app.get("/api/history")
def get_history():
    """Historique des versions : montre si le modèle s'améliore à mesure que
    des laboratoires contribuent. C'est l'argument du site en une seule vue."""
    out = []
    for version in model_versions():
        model = load_model(version)
        entry = {
            "version": version,
            "created_utc": model.get("created_utc"),
            "material": model.get("material"),
            "targets": {},
        }
        for name, target in model.get("targets", {}).items():
            entry["targets"][name] = {
                "n_train": target.get("n_train"),
                "n_contributions": target.get("n_contributions", 0),
                "loo_r2": {engine: fit.get("loo", {}).get("R2")
                           for engine, fit in target.get("engines", {}).items()},
            }
        out.append(entry)
    return {"versions": out, "latest": model_versions()[-1] if out else None}


@app.get("/api/status")
def get_status():
    """De quoi diagnostiquer une installation sans lire les journaux."""
    versions = model_versions()
    return {
        "ok": bool(versions),
        "model_versions": versions,
        "contributions_open": bool(API_KEY),
        "min_rows": MIN_ROWS,
        "pending_contributions": len(list(QUEUE_DIR.glob("*.json"))),
    }


@app.post("/api/contribute", status_code=status.HTTP_202_ACCEPTED,
          dependencies=[Depends(require_contributor_key)])
def contribute(payload: Contribution):
    """Met une mise à jour de modèle en file d'attente.

    Réponse 202 et non 200, à dessein : le serveur accuse réception, il ne
    prétend pas avoir intégré quoi que ce soit. L'intégration est une décision
    humaine.
    """
    model = load_model()

    if payload.target not in model.get("targets", {}):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Grandeur « {payload.target} » absente du modèle global. "
            f"Connues : {', '.join(model.get('targets', {}))}")

    # L'ordre des variables fait partie du contrat : une contribution dont les
    # colonnes sont permutées produirait des coefficients silencieusement faux.
    if payload.features != model.get("features"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Variables incompatibles avec le modèle global.\n"
            f"Attendu : {model.get('features')}\nReçu : {payload.features}")

    expected = len(payload.features) + 1      # + la colonne d'ordonnée
    stats = payload.sufficient_statistics
    if len(stats.dtd) != expected or len(stats.dty) != expected:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Dimensions incohérentes : {expected} attendues pour "
            f"{len(payload.features)} variables.")
    # D'D[0,0] vaut la somme de la colonne de 1, donc n. Si les deux ne
    # concordent pas, les sommes ne viennent pas du jeu annoncé.
    if abs(stats.dtd[0][0] - stats.n) > 1e-6:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "dtd[0][0] devrait valoir n : les sommes envoyées sont incohérentes.")
    if stats.n != payload.dataset.n_rows:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Le nombre de lignes annoncé ne correspond pas aux sommes envoyées.")

    received = datetime.now(timezone.utc)
    record = {
        "id": uuid.uuid4().hex[:12],
        "received_utc": received.isoformat(timespec="seconds"),
        "status": "pending",
        "payload": payload.model_dump(by_alias=True),
    }
    name = f"{received:%Y%m%dT%H%M%S}_{payload.target}_{record['id']}.json"
    (QUEUE_DIR / name).write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "accepted": True,
        "id": record["id"],
        "target": payload.target,
        "n_rows": stats.n,
        "message": ("Contribution reçue et mise en attente de validation. "
                    "Aucune donnée brute n'a été transmise ni conservée. "
                    "Elle sera intégrée à la prochaine version du modèle "
                    "global après vérification."),
    }


@app.get("/api/queue", dependencies=[Depends(require_admin_key)])
def get_queue():
    """File d'attente — administrateur uniquement."""
    out = []
    for path in sorted(QUEUE_DIR.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        payload = record.get("payload", {})
        out.append({
            "id": record.get("id"),
            "file": path.name,
            "received_utc": record.get("received_utc"),
            "status": record.get("status"),
            "target": payload.get("target"),
            "contributor": payload.get("contributor", {}),
            "dataset": payload.get("dataset", {}),
            "scores": payload.get("scores", {}),
        })
    return {"pending": out, "count": len(out)}


class AggregateRequest(BaseModel):
    """Ce que la page d'administration envoie pour prévisualiser ou publier.

    ``dry_run`` calcule et renvoie ce que donnerait la nouvelle version sans
    rien écrire — c'est ce que le bouton « Aperçu » utilise, pour que le
    professeur voie les scores avant de s'engager. ``exclude`` laisse une
    contribution dans la file pour un tour ultérieur, exactement comme
    ``--exclude`` en ligne de commande.
    """
    exclude: list[str] = []
    dry_run: bool = False


@app.post("/api/aggregate", dependencies=[Depends(require_admin_key)])
def aggregate(payload: AggregateRequest = AggregateRequest()):
    """Prévisualise ou publie la version suivante — administrateur uniquement.

    Appelle ``run_aggregation``, exactement la fonction que
    ``python -m server.aggregate`` utilise en ligne de commande : la page
    d'administration n'est qu'une autre façon de déclencher le même calcul,
    jamais une implémentation parallèle qui pourrait diverger.
    """
    try:
        return run_aggregation(STORE, exclude=payload.exclude,
                               dry_run=payload.dry_run)
    except RuntimeError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error))


class RollbackRequest(BaseModel):
    to_version: int


@app.post("/api/rollback", dependencies=[Depends(require_admin_key)])
def rollback(payload: RollbackRequest):
    """Republie une version passée comme nouvelle version — administrateur
    uniquement.

    Ne supprime rien : la ``v4`` publiée par ce point de terminaison a le même
    contenu que ``v2``, mais ``v3`` reste dans l'historique. Voir
    ``run_rollback`` pour pourquoi (traçabilité, et les sommes de la
    contribution suivante doivent partir d'un état cohérent).
    """
    try:
        return run_rollback(STORE, payload.to_version)
    except RuntimeError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error))


# --------------------------------------------------------------------------- #
# Pages statiques
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    page = WEB_DIR / "index.html"
    if not page.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "web/index.html manquant")
    return FileResponse(page)


# Monté en dernier : la racine « / » ne doit pas avaler les routes /api/*.
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
