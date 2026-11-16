#!/bin/sh
# N'amorce le magasin que s'il est vide (premier démarrage sur un volume tout
# neuf). Sur un volume déjà peuplé — le cas normal après le premier lancement —
# ce script ne touche à rien : écraser model_v1.json à chaque redémarrage
# effacerait silencieusement les versions publiées depuis.
set -e

if [ ! -f /app/server/store/models/model_v1.json ]; then
  echo "[entrypoint] magasin vide : copie du modèle initial fourni avec l'image."
  mkdir -p /app/server/store/models /app/server/store/stats \
           /app/server/store/queue /app/server/store/archive
  cp /app/seed/models/model_v1.json /app/server/store/models/model_v1.json
  cp /app/seed/stats/aggregate_v1.json /app/server/store/stats/aggregate_v1.json
fi

exec uvicorn server.app:app --host 0.0.0.0 --port 8000
