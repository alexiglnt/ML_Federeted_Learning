"""Agrégation fédérée : publie une nouvelle version du modèle global.

Deux façons de la déclencher, qui passent toutes les deux par
``run_aggregation`` ci-dessous — une seule implémentation, jamais deux qui
pourraient diverger :

    python -m server.aggregate --list           # ce qui attend
    python -m server.aggregate --dry-run        # ce que ça donnerait
    python -m server.aggregate                  # publie model_v(N+1).json
    python -m server.aggregate --exclude <id>   # laisser une contribution de côté

ou, depuis la page d'administration du site (``web/admin.html``), via
``POST /api/aggregate`` (``server/app.py``), protégée par la clé admin.

Pourquoi l'agrégation est EXACTE ici
------------------------------------
La plupart des mises en œuvre d'apprentissage fédéré moyennent les poids des
clients (FedAvg) : c'est une approximation, et sur des clients aux tailles très
inégales elle est mauvaise. Ici on ne moyenne pas les coefficients, on
additionne les statistiques suffisantes. Avec ``D = [1, X]`` :

    SSE(theta) = y'y - 2 theta'(D'y) + theta'(D'D) theta

Cette expression ne dépend des données QUE par ``D'D``, ``D'y``, ``y'y`` et
``n``, et ces quatre quantités sont additives d'un laboratoire à l'autre. Les
coefficients obtenus sur les sommes sont donc exactement, au chiffre près, ceux
qu'on aurait obtenus en réunissant les mesures dans un seul tableau — alors
qu'aucune mesure n'a bougé. Cela vaut aussi pour PIML, dont la perte est la
même somme des carrés plus une pénalité sur les coefficients seuls.

Ce qui n'est PAS agrégeable exactement : le R² de validation croisée, qui a
besoin de retirer des points un à un. Les scores publiés sont donc ceux des
laboratoires, reportés tels quels, plus un R² d'apprentissage calculé sur les
sommes réunies. C'est dit dans le fichier de modèle et sur la page.

L'algèbre est dans ``server/piml.py``, partagée avec le script qui produit le
modèle initial : c'est la seule façon de garantir que la version 2 est bien la
suite de la version 1 et non le résultat d'un autre algorithme.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from server.piml import (add, pooled_scaler, solve_ols, solve_piml,
                         to_standardised, train_metrics)

HERE = Path(__file__).resolve().parent
# Voir server/app.py : DEAM_FL_STORE permet aux contrôles de travailler sur une
# copie jetable du magasin. Utilisée par la CLI ; POST /api/aggregate passe son
# propre STORE (déjà résolu par app.py) à run_aggregation directement.
STORE = Path(os.environ.get("DEAM_FL_STORE") or (HERE / "store")).resolve()


# --------------------------------------------------------------------------- #
# File d'attente
# --------------------------------------------------------------------------- #
def read_queue(queue_dir: Path) -> list[tuple[Path, dict]]:
    out = []
    for path in sorted(queue_dir.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("status") == "pending":
            out.append((path, record))
    return out


def all_versions(models_dir: Path) -> list[int]:
    return sorted(int(p.stem.split("_v")[1]) for p in models_dir.glob("model_v*.json")
                 if p.stem.split("_v")[1].isdigit())


def latest_version(models_dir: Path) -> int:
    versions = all_versions(models_dir)
    if not versions:
        raise RuntimeError("No model has been published. Run tools/fit_pretrained.py.")
    return max(versions)


# --------------------------------------------------------------------------- #
# Agrégation — le seul endroit qui écrit une nouvelle version
# --------------------------------------------------------------------------- #
def run_aggregation(store: Path, exclude: list[str] | None = None,
                     dry_run: bool = False) -> dict[str, Any]:
    """Publie (ou simule) la version suivante du modèle depuis la file d'attente.

    Renvoie un compte-rendu structuré plutôt que d'imprimer, pour rester
    utilisable aussi bien depuis ``main()`` (CLI) que depuis
    ``POST /api/aggregate`` (page d'administration) : les deux publient par
    exactement le même chemin de code.
    """
    exclude = set(exclude or [])
    models_dir = store / "models"
    stats_dir = store / "stats"
    queue_dir = store / "queue"
    archive_dir = store / "archive"

    queue = read_queue(queue_dir)
    version = latest_version(models_dir)
    model = json.loads((models_dir / f"model_v{version}.json")
                       .read_text(encoding="utf-8"))
    stats_path = stats_dir / f"aggregate_v{version}.json"
    if not stats_path.exists():
        raise RuntimeError(
            f"Sufficient statistics are missing for version {version} "
            f"({stats_path.name}). Without them, exact aggregation is "
            f"impossible.")
    pooled_store = json.loads(stats_path.read_text(encoding="utf-8"))

    features = model["features"]
    signs = np.array([model["penalised_sign"][f] for f in features])

    used: list[dict] = []
    skipped: list[dict] = []
    for path, record in queue:
        payload = record["payload"]
        contributor = payload["contributor"]
        summary = {
            "id": record["id"], "lab": contributor["lab"],
            "target": payload["target"], "n_rows": payload["dataset"]["n_rows"],
        }
        if record["id"] in exclude:
            skipped.append({**summary, "reason": "set aside"})
            continue
        target = payload["target"]
        if payload["features"] != features or target not in pooled_store["targets"]:
            skipped.append({**summary, "reason": "incompatible variables or target"})
            continue

        entry = pooled_store["targets"][target]
        entry["pooled"] = add(entry["pooled"], payload["sufficient_statistics"])
        entry.setdefault("sources", []).append({
            "label": f"{contributor['lab']} ({payload['dataset']['measurement_method']})",
            "n": payload["dataset"]["n_rows"],
            "contribution_id": record["id"],
            "model_version": payload["model_version"],
        })
        used.append({"path": path, "record": record, "target": target, **summary})

    result: dict[str, Any] = {
        "from_version": version,
        "to_version": None,
        "dry_run": dry_run,
        "used": [{"id": u["id"], "lab": u["lab"], "target": u["target"],
                  "n_rows": u["n_rows"]} for u in used],
        "skipped": skipped,
        "targets": {},
    }

    if not used:
        result["message"] = "No usable contribution: nothing to publish."
        return result

    new_version = version + 1
    for target, entry in pooled_store["targets"].items():
        pooled = entry["pooled"]
        target_model = model["targets"][target]

        mean, std = pooled_scaler(pooled)
        pooled_z = to_standardised(pooled, mean, std)

        theta_lin = solve_ols(pooled_z)
        lam = float(target_model["engines"]["piml"].get("lambda", 5.0))
        theta_piml = solve_piml(pooled, lam, signs)

        target_model["scaler"] = {"mean": mean.tolist(), "std": std.tolist()}
        target_model["n_train"] = int(pooled["n"])
        target_model["n_contributions"] = len(
            [s for s in entry["sources"] if "contribution_id" in s])
        target_model["contributors"] = [
            s["label"] for s in entry["sources"] if "contribution_id" in s]

        lin = target_model["engines"]["linear"]
        lin["intercept"] = float(theta_lin[0])
        lin["coef"] = theta_lin[1:].tolist()
        lin["train"] = train_metrics(pooled_z, theta_lin)
        # Le R² LOO du modèle réuni n'est pas calculable sans les données ; on
        # le retire plutôt que de laisser périmer celui de la version d'avant,
        # qui serait lu comme s'il portait sur les données réunies.
        lin["loo"] = {}
        lin["loo_note"] = ("not computable after aggregation: leave-one-out "
                           "cross-validation requires removing points one at a "
                           "time, which the summed statistics do not allow. See "
                           "contributed_scores.")

        piml = target_model["engines"]["piml"]
        piml["intercept"] = float(theta_piml[0])
        piml["coef"] = theta_piml[1:].tolist()
        piml["train"] = train_metrics(pooled, theta_piml)
        piml["loo"] = {}
        piml["loo_note"] = lin["loo_note"]
        piml.pop("lambda_scan_loo_r2", None)

        contributed = [
            {"lab": u["record"]["payload"]["contributor"]["lab"],
             "n_rows": u["record"]["payload"]["dataset"]["n_rows"],
             "measurement_method":
                 u["record"]["payload"]["dataset"]["measurement_method"],
             "scores": u["record"]["payload"].get("scores", {})}
            for u in used if u["target"] == target]
        if contributed:
            target_model["contributed_scores"] = contributed

        result["targets"][target] = {
            "n_train": target_model["n_train"],
            "linear_train_r2": lin["train"]["R2"],
            "piml_train_r2": piml["train"]["R2"],
        }

    model["version"] = new_version
    model["created_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    model["provenance"]["aggregated_from"] = [u["record"]["id"] for u in used]
    model["provenance"]["aggregation"] = (
        "exact pooled refit from summed sufficient statistics "
        "(not FedAvg weight averaging)")
    pooled_store["version"] = new_version

    result["to_version"] = new_version
    result["message"] = (
        f"Preview: {len(used)} contribution(s) would produce version "
        f"{new_version}. Nothing was written." if dry_run else
        f"Version {new_version} published with {len(used)} contribution(s).")

    if dry_run:
        return result

    # Les contributions intégrées sortent de la file mais sont conservées :
    # sans elles, impossible de refaire l'agrégation ni de retirer plus tard
    # une contribution qui se révélerait fautive.
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / f"model_v{new_version}.json").write_text(
        json.dumps(model, indent=2, ensure_ascii=False), encoding="utf-8")
    stats_dir.mkdir(parents=True, exist_ok=True)
    (stats_dir / f"aggregate_v{new_version}.json").write_text(
        json.dumps(pooled_store, indent=2), encoding="utf-8")

    archive_dir.mkdir(parents=True, exist_ok=True)
    for u in used:
        record = u["record"]
        record["status"] = "aggregated"
        record["aggregated_into"] = new_version
        (archive_dir / u["path"].name).write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        u["path"].unlink()

    return result


# --------------------------------------------------------------------------- #
# Retour à une version antérieure — jamais en supprimant une version publiée
# --------------------------------------------------------------------------- #
def run_rollback(store: Path, target_version: int) -> dict[str, Any]:
    """Republie le contenu d'une version passée comme nouvelle version courante.

    Ne supprime et n'écrase jamais un fichier existant : l'historique reste
    complet (v1 -> v2 -> v3 -> v4, avec v4 identique à v2) plutôt que de faire
    comme si v3 n'avait jamais existé. C'est la même logique de traçabilité
    que l'archivage des contributions intégrées dans run_aggregation.

    Republie aussi les sommes suffisantes de la version ciblée (pas seulement
    le fichier de modèle) : sans elles, la prochaine contribution échouerait à
    trouver les statistiques à partir desquelles s'agréger.
    """
    models_dir = store / "models"
    stats_dir = store / "stats"

    versions = all_versions(models_dir)
    if not versions:
        raise RuntimeError("No model has been published. Run tools/fit_pretrained.py.")
    current = max(versions)

    if target_version not in versions:
        raise RuntimeError(
            f"Version {target_version} not found. Available: {versions}.")
    if target_version == current:
        raise RuntimeError(f"Version {target_version} is already the latest.")

    stats_path = stats_dir / f"aggregate_v{target_version}.json"
    if not stats_path.exists():
        raise RuntimeError(
            f"Sufficient statistics are missing for version {target_version} "
            f"({stats_path.name}): rolling back to this version would break "
            f"the aggregation of any future contribution.")

    model = json.loads((models_dir / f"model_v{target_version}.json")
                       .read_text(encoding="utf-8"))
    pooled_store = json.loads(stats_path.read_text(encoding="utf-8"))

    new_version = current + 1
    model["version"] = new_version
    model["created_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    model.setdefault("provenance", {})
    model["provenance"]["rolled_back_from"] = current
    model["provenance"]["rolled_back_to_content_of"] = target_version
    pooled_store["version"] = new_version

    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / f"model_v{new_version}.json").write_text(
        json.dumps(model, indent=2, ensure_ascii=False), encoding="utf-8")
    stats_dir.mkdir(parents=True, exist_ok=True)
    (stats_dir / f"aggregate_v{new_version}.json").write_text(
        json.dumps(pooled_store, indent=2), encoding="utf-8")

    return {
        "from_version": current,
        "to_version": new_version,
        "rolled_back_to": target_version,
        "message": (f"Version {new_version} published, with content identical to "
                   f"version {target_version}."),
    }


# --------------------------------------------------------------------------- #
# Ligne de commande
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Federated aggregation: publishes a new version of the "
                    "global model.")
    parser.add_argument("--list", action="store_true",
                        help="show the queue and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="compute the new version without writing anything")
    parser.add_argument("--exclude", nargs="*", default=[],
                        metavar="ID",
                        help="IDs of contributions to set aside")
    args = parser.parse_args()

    queue_dir = STORE / "queue"
    queue = read_queue(queue_dir)
    if args.list or not queue:
        if not queue:
            print("Queue is empty.")
        for _, record in queue:
            payload = record["payload"]
            who = payload["contributor"]
            data = payload["dataset"]
            print(f"  {record['id']}  {record['received_utc']}  "
                  f"{payload['target']:>6}  n={data['n_rows']:<4} "
                  f"{data['material']:<12} {data['measurement_method']:<14} "
                  f"{who['lab']} ({who['name']})")
        return

    try:
        result = run_aggregation(STORE, exclude=args.exclude, dry_run=args.dry_run)
    except RuntimeError as error:
        raise SystemExit(str(error))

    print(f"\n{result['message']}")
    for s in result["skipped"]:
        print(f"  - {s['id']} skipped ({s['reason']})")
    if not result["used"]:
        return

    for target, summary in result["targets"].items():
        print(f"  {target:>6}  n={summary['n_train']:<5} "
              f"linear R2_app = {summary['linear_train_r2']:+.3f}   "
              f"piml R2_app = {summary['piml_train_r2']:+.3f}")

    if args.dry_run:
        return

    print(f"\n[out] store/models/model_v{result['to_version']}.json  (to upload to the VPS)")
    print(f"[out] store/stats/aggregate_v{result['to_version']}.json  (private)")


if __name__ == "__main__":
    main()
