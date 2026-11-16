# Federated residual-stress models — site web

Un collègue charge ses mesures de contraintes résiduelles, voit immédiatement
deux scores, et peut contribuer au modèle global **sans que ses mesures quittent
sa machine**.

## En deux phrases

Le calcul tourne entièrement dans le navigateur du collègue. Le serveur héberge
le modèle global et reçoit, si le collègue le décide, des **sommes agrégées** qui
suffisent à réajuster le modèle sur les données réunies — jamais une seule
mesure.

---

## L'architecture, et pourquoi celle-là

```
   NAVIGATEUR DU COLLÈGUE                        SERVEUR (VPS)
   ┌────────────────────────────┐                ┌──────────────────────────┐
   │ fichier CSV local          │                │                          │
   │        ↓                   │  GET /api/model│  modèle global v N       │
   │ lecture, correspondance    │ ←───────────── │  (coefficients + scores) │
   │        ↓                   │                │                          │
   │ ajustement linéaire + PIML │                │                          │
   │        ↓                   │                │                          │
   │ DEUX SCORES affichés       │                │                          │
   │        ↓                   │                │                          │
   │ [contribuer] ── sommes ──→ │ POST /contribute│ file d'attente          │
   │   D'D, D'y, y'y, n         │                │        ↓                 │
   └────────────────────────────┘                │  relecture humaine       │
     les mesures ne sortent jamais               │        ↓                 │
                                                 │  agrégation → v N+1      │
                                                 └──────────────────────────┘
```

Trois décisions structurent tout le reste.

### 1. Le calcul est dans le navigateur

C'est ce qui rend la confidentialité vérifiable et non promise. Un collègue
travaillant avec un partenaire industriel n'a pas à nous croire : il peut lire
`web/js/api.js`, constater qu'il n'y a que trois appels réseau, et voir dans la
page l'aperçu exact de ce qui partirait s'il cliquait sur « contribuer ».

Conséquence assumée : seuls les moteurs portables tournent sur le site. Le
linéaire et PIML sont de l'algèbre linéaire en dimension 5, triviale en
JavaScript. **GEP, GP et PySR sont hors de portée** — PySR c'est Julia, et les
boucles évolutionnaires prendraient des minutes. Ils restent des outils hors
ligne, pour nous.

### 2. Le serveur héberge le modèle, pas les données

C'est l'architecture canonique de l'apprentissage fédéré : modèle au centre,
données chez les participants.

### 3. L'agrégation est exacte, et ce n'est pas du FedAvg

La plupart des mises en œuvre fédérées **moyennent les coefficients** des
clients. C'est une approximation, mauvaise quand les clients ont des tailles très
inégales — ce qui sera notre cas, entre un laboratoire à 7 conditions et un autre
à 40.

Ici on additionne des **statistiques suffisantes**. Avec `D = [1, X]` :

```
SSE(theta) = y'y − 2 theta'(D'y) + theta'(D'D) theta
```

Cette expression ne dépend des données que par `D'D`, `D'y`, `y'y` et `n`, et ces
quatre quantités **s'additionnent** d'un laboratoire à l'autre. Les coefficients
obtenus sur les sommes sont donc ceux qu'on aurait obtenus en réunissant les
mesures dans un seul tableau. Cela vaut aussi pour PIML, dont la perte est la
même somme des carrés plus une pénalité qui ne porte que sur les coefficients.

Ce n'est pas un argument théorique : `tests/check_aggregation.py` compare les deux
et les trouve identiques à **1e-13**.

### Ce que l'agrégation ne peut pas faire

Le **R² de validation croisée** a besoin de retirer des points un à un : il n'est
pas calculable depuis les sommes. À partir de la version 2, le modèle publie donc
un R² d'apprentissage et conserve à part les scores de validation croisée
calculés par chaque laboratoire chez lui. C'est écrit dans le fichier de modèle
(`loo_note`) et sur la page — plutôt que de laisser périmer un chiffre que le
lecteur croirait à jour.

---

## La limite de confidentialité, dite franchement

Les sommes transmises **ne sont pas anonymes**. `D'D` et `D'y` sont des
statistiques exhaustives : sur très peu de lignes, elles laissent remonter
beaucoup du jeu de données, et sur **une seule ligne elles la restituent
exactement**.

D'où le seuil de `MIN_ROWS = 5` (`server/app.py`), imposé côté serveur et côté
navigateur. Ce n'est pas une contrainte statistique, c'est une précaution.

Ce que nous ne prétendons pas : il n'y a **pas** de garantie de confidentialité
différentielle. Un collègue dont les données sont réellement sensibles doit le
savoir. La page le dit dans ses propres termes, et le bouton « télécharger la
contribution » existe pour qu'il puisse faire relire l'envoi avant qu'il ne
parte.

---

## Les deux scores

Le professeur a demandé les deux, et ils ne mesurent pas la même chose.

| | Ce qui est calculé | La question posée |
|---|---|---|
| **Transfert** | le modèle global appliqué tel quel, sans réajustement | notre modèle publié marche-t-il ailleurs que chez nous ? |
| **Réajustement** | le modèle réajusté sur ses seules données, noté en validation croisée | ses mesures sont-elles prédictibles ? |

Le couple se lit. Transfert faible et réajustement fort signifie : données
propres, mais modèle qui ne se transporte pas — c'est l'information la plus utile
que le site puisse produire, et elle désigne un régime que l'étude ne couvre pas.
`web/js/score.js` en donne une lecture en une phrase à l'écran.

---

## Ce qu'il y a dans le dossier

```
DEPLOY.md             tutoriel de déploiement pas à pas (Docker + Caddy)
Dockerfile, docker-compose.yml, Caddyfile, entrypoint.sh
                      voir DEPLOY.md — server/store/ reste hors de l'image
.env.example        gabarit des deux clés — committé, sans valeurs
.gitignore           exclut .env et le magasin privé du dépôt
server/
  app.py            routes publiques (model, history, status) et protégées
                     par clé (contribute, queue, aggregate, rollback)
  piml.py           LES moteurs — algèbre sur les statistiques suffisantes
  aggregate.py      agrégation et retour à une version antérieure, en CLI
                     (`python -m server.aggregate`) ou via l'API admin
  store/
    models/         model_vN.json — PUBLIÉ, servi par GET /api/model
    stats/          sommes accumulées — PRIVÉ, jamais servi
    queue/          contributions en attente de relecture — PRIVÉ
    archive/        contributions intégrées, conservées — PRIVÉ
web/
  index.html        les quatre étapes
  admin.html        file d'attente, aperçu/publication, retour en arrière
  css/style.css     aucune police ni ressource externe : zéro requête sortante
  js/linalg.js      résolution de systèmes 5×5
  js/models.js      linéaire + PIML + validation croisée + sommes
  js/score.js       les deux scores et leur lecture
  js/parse.js       CSV : séparateur, virgule décimale, lignes de titre, grec
  js/api.js         les trois seuls appels réseau de la page publique
  js/admin_api.js   les appels réseau réservés à l'administration
  js/theme.js       bascule clair/sombre
  js/format.js      dates UTC affichées dans le fuseau du visiteur
  template/         gabarit CSV à donner aux collègues
examples/            jeux de test prêts à l'emploi (réels et synthétiques)
tools/
  fit_pretrained.py produit model_v1.json depuis les données de l'étude
tests/
  run_all.py        tout enchaîner dans un magasin jetable
```

Le point d'entrée à lire en premier est `server/piml.py` : il contient
l'algèbre, et les deux autres implémentations (l'agrégation et le JavaScript) en
découlent.

---

## Faire tourner en local

```bash
cd Federated_Learning_Website
pip install -r server/requirements.txt

# 1. produire le modèle initial depuis les données de l'étude
python tools/fit_pretrained.py

# 2. créer le fichier de clés (une seule fois)
cp .env.example .env
# puis ouvrir .env avec un éditeur de texte et remplir les deux clés

# 3. démarrer le serveur
python -m uvicorn server.app:app --reload --port 8000
```

Puis <http://127.0.0.1:8000>.

### Les clés, dans un fichier `.env`

Les deux clés (`DEAM_FL_API_KEY` pour les collègues, `DEAM_FL_ADMIN_KEY` pour
vous) se règlent dans un fichier `.env`, à la racine de
`Federated_Learning_Website/` — pas dans `web/`, qui est servi tel quel aux
visiteurs. Le serveur le lit tout seul au démarrage (`load_dotenv`).

Ce fichier n'est **jamais** envoyé sur GitHub : il est listé dans `.gitignore`.
`.env.example`, lui, est committé — c'est le gabarit vide, sans valeurs, qui
montre le format attendu.

Si vous préférez régler les clés autrement (variable d'environnement système,
`systemd EnvironmentFile=`…), ça marche aussi : une variable déjà présente dans
l'environnement passe toujours avant le contenu de `.env`.

Si `DEAM_FL_API_KEY` n'est pas définie (fichier `.env` absent ou champ vide),
le site fonctionne en lecture seule : les scores se calculent, les
contributions sont refusées. C'est délibéré — mieux vaut ça qu'un modèle
global ouvert à tous les vents.

### Contrôles

```bash
python tests/run_all.py       # nécessite node
```

Tout se passe dans un magasin temporaire ; le magasin réel n'est pas touché.
Les trois contrôles portent sur les promesses du dispositif : les moteurs du
navigateur donnent les mêmes chiffres que le Python, le serveur refuse ce qu'il
doit refuser sans recevoir de mesure, et l'agrégation reproduit l'ajustement sur
données réunies.

---

## Intégrer une contribution

Les contributions n'entrent **jamais** automatiquement dans le modèle publié :
une route ouverte qui modifierait le modèle global serait empoisonnable, et un
seul envoi erroné dégraderait le modèle de tout le monde sans que personne ne
s'en aperçoive.

```bash
python -m server.aggregate --list      # ce qui attend
python -m server.aggregate --dry-run   # ce que ça donnerait
python -m server.aggregate             # publie model_v(N+1).json
python -m server.aggregate --exclude <id>   # laisser une contribution de côté
```

Regarder d'abord `--list` : la matière, la méthode de mesure et le nombre de
lignes s'y voient. Une contribution en perçage incrémental mélangée à des mesures
par diffraction X n'est pas illégitime, mais elle doit être un choix, pas un
accident — les deux méthodes diffèrent de plusieurs dizaines de MPa sur la même
pièce.

---

## Déploiement

Voir **[DEPLOY.md](DEPLOY.md)** pour le tutoriel pas à pas, écrit pour
quelqu'un qui n'a jamais déployé de site — c'est le document à suivre pour
mettre le site en ligne sur le VPS du professeur. Si Caddy tourne déjà sur le
serveur cible (pour d'autres sites), voir plutôt
`docker-compose.external-caddy.yml` et la section correspondante de
DEPLOY.md — pas de second Caddy à lancer, juste un bloc à ajouter au sien.

En résumé pour qui connaît déjà Docker : `Dockerfile` + `docker-compose.yml`
+ `Caddyfile` à la racine du dossier. `docker compose up -d --build` lance
deux conteneurs — l'application (ce dépôt) et Caddy, qui fait office de
reverse proxy et obtient seul le certificat HTTPS à partir du nom de domaine
écrit dans `Caddyfile`. `server/store/` est monté en volume depuis le disque
du serveur, en dehors de l'image : une mise à jour du code
(`docker compose up -d --build`) ne touche jamais aux versions déjà publiées
ni aux contributions en attente. `entrypoint.sh` n'amorce le magasin avec le
modèle initial (`model_v1.json`, embarqué dans l'image) que s'il est vide —
jamais s'il contient déjà quelque chose.

Le dossier `server/store/` contient du public et du privé. **Seul
`store/models/` est servi**, par `GET /api/model`. `store/stats/`,
`store/queue/` et `store/archive/` ne sont jamais exposés : `web/js/api.js`
et `web/admin.html` sont les seuls fichiers servis statiquement par
l'application, le reste de `server/store/` n'est accessible que par les
routes API qui le protègent explicitement (`GET /api/queue`,
`POST /api/aggregate`, `POST /api/rollback`, toutes trois derrière la clé
admin).

L'agrégation peut tourner sur une machine locale : elle n'a besoin que du contenu
de `store/`. C'est même préférable, cela garde la décision d'intégration hors du
serveur.

---

## Limites actuelles, à traiter ensuite

- **Titane seulement.** Les variables du modèle sont `gamma`, `r_beta`, `Vc`,
  `h`. Un collègue travaillant l'acier n'a ni angle de coupe ni rayon d'arête au
  même sens : son fichier ne se mappe pas. Étendre à plusieurs matières demande
  de repenser le jeu de variables, pas d'ajouter une colonne.
- **CSV seulement.** Lire un `.xlsx` dans le navigateur demande de décompresser
  un ZIP et d'analyser du XML. Un fichier Excel est refusé avec le message qui
  explique comment l'enregistrer en CSV.
- **Le GPR n'est pas dans le navigateur.** Faisable — noyau RBF plus
  optimisation de six hyperparamètres — mais c'est le gros morceau, et il ne
  produit pas d'équation.
- **Une seule clé pour tous les collègues.** Suffisant pour six laboratoires
  connus ; à remplacer par une clé par contributeur si le cercle s'élargit, ne
  serait-ce que pour pouvoir en révoquer une.
- **Propriété des données et signature.** À trancher **avant** le premier envoi
  réel : à qui appartiennent les contributions, qui est crédité sur un article
  issu du modèle agrégé. C'est une question de politique, pas de code, et il est
  beaucoup plus facile de l'écrire sur le site dès le départ que de la rouvrir
  après.
