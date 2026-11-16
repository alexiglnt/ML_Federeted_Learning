# Image unique pour le serveur FastAPI + les pages statiques qu'il sert.
#
# Ne contient PAS server/store/ : ce dossier est le magasin VIVANT (modèles
# publiés, contributions reçues), monté en volume à l'exécution (voir
# docker-compose.yml) — jamais lu au moment du build, précisément pour qu'on
# puisse le vider sans casser la reconstruction de l'image. Le modèle initial
# et ses sommes (publics par construction, aucune mesure brute) viennent de
# server/seed/, un dossier séparé et versionné, distinct du magasin.
FROM python:3.12-slim

WORKDIR /app

COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY server/__init__.py server/app.py server/aggregate.py server/piml.py ./server/
COPY web ./web

COPY server/seed/model_v1.json ./seed/models/model_v1.json
COPY server/seed/aggregate_v1.json ./seed/stats/aggregate_v1.json

COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
