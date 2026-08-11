"""Enchaîne tous les contrôles, dans un magasin jetable.

    python tests/run_all.py

Le magasin réel — celui dont les fichiers partent sur le serveur — n'est jamais
touché : tout se passe dans un dossier temporaire désigné par ``DEAM_FL_STORE``.
Le serveur est démarré sur un port de test puis arrêté.

Trois choses sont vérifiées, dans cet ordre :

  1. les moteurs du navigateur donnent les mêmes chiffres que le Python ;
  2. le serveur refuse ce qu'il doit refuser et ne reçoit aucune mesure ;
  3. l'agrégation depuis les sommes reproduit l'ajustement sur données réunies.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
API_KEY = "test-key-123"
ADMIN_KEY = "admin-456"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run(label: str, command: list[str], env: dict) -> bool:
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    result = subprocess.run(command, cwd=ROOT, env=env)
    return result.returncode == 0


def wait_for(url: str, timeout: float = 25.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    return False


def main() -> int:
    if shutil.which("node") is None:
        print("node est nécessaire pour contrôler le code du navigateur.")
        return 2

    store = Path(tempfile.mkdtemp(prefix="deam_fl_store_"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "DEAM_FL_STORE": str(store),
        "DEAM_FL_API_KEY": API_KEY,
        "DEAM_FL_ADMIN_KEY": ADMIN_KEY,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(ROOT),
    }
    fixture = store / "fixture.json"
    reference = store / "reference.json"
    ok = True
    server = None

    try:
        print(f"magasin jetable : {store}")

        # --- modèle initial ------------------------------------------------
        if not run("Modèle initial (tools/fit_pretrained.py)",
                   [PYTHON, "tools/fit_pretrained.py"], env):
            return 1

        # --- données de référence et fixture -------------------------------
        with open(reference, "w", encoding="utf-8") as handle:
            if subprocess.run([PYTHON, "tests/dump_reference_data.py"],
                              cwd=ROOT, env=env, stdout=handle).returncode:
                return 1
        if not run("Jeu de contrôle (tests/gen_fixture.mjs)",
                   ["node", "tests/gen_fixture.mjs", str(fixture), str(store)],
                   env):
            return 1

        # --- 1. moteurs ----------------------------------------------------
        ok &= run("1. Les moteurs du navigateur contre le Python",
                  ["node", "tests/check_engines.mjs", str(reference), str(store)],
                  env)

        # --- 2. serveur ----------------------------------------------------
        print(f"\ndémarrage du serveur sur le port {port}")
        server = subprocess.Popen(
            [PYTHON, "-m", "uvicorn", "server.app:app", "--port", str(port),
             "--log-level", "warning"],
            cwd=ROOT, env=env)
        if not wait_for(f"{base}/api/status"):
            print("le serveur n'a pas répondu ; contrôles interrompus")
            return 1
        with urllib.request.urlopen(f"{base}/api/status") as response:
            status = json.load(response)
        print(f"  statut : {status}")

        ok &= run("2. Le serveur : accès, refus, confidentialité",
                  ["node", "tests/check_server.mjs", str(fixture), base], env)

        # --- 3. agrégation --------------------------------------------------
        if not run("Agrégation (server/aggregate.py)",
                   [PYTHON, "-m", "server.aggregate"], env):
            return 1
        ok &= run("3. L'agrégation contre un ajustement sur données réunies",
                  [PYTHON, "tests/check_aggregation.py", str(fixture), str(store)],
                  env)
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        shutil.rmtree(store, ignore_errors=True)

    print(f"\n{'=' * 70}")
    print("TOUS LES CONTRÔLES PASSENT" if ok else "DES CONTRÔLES ÉCHOUENT")
    print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
