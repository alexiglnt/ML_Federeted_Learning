# Tutoriel — utiliser le site

Ce document explique comment se servir du site, du point de vue d'un
utilisateur qui arrive dessus pour la première fois. Pour l'installation ou le
déploiement, voir [README.md](README.md) et [DEPLOY.md](DEPLOY.md).

Le site sert à une chose : comparer **vos propres mesures de contraintes
résiduelles** (usinage du titane Ti-6Al-4V) au modèle global publié par le
labo, sans jamais faire sortir vos mesures de votre ordinateur.

---

## Avant de commencer

- Un fichier **CSV** (ou `.txt`/`.tsv`) avec une ligne par condition d'usinage.
- Les séparateurs `;` et les virgules décimales (exports Excel européens) sont
  gérés automatiquement, tout comme une éventuelle ligne de titre.
- Pas sûr du format attendu ? Sur la page d'accueil, le lien **« Download the
  template »** (étape 1) télécharge un CSV d'exemple avec les bonnes colonnes
  et deux lignes d'exemple :

  ```
  gamma (deg),r_beta (um),Vc (m/min),h (mm),SRS_L (MPa),SRS_T (MPa)
  0,20,30,0.15,-400,-50
  0,20,50,0.15,-350,-20
  ```

  `gamma`, `r_beta`, `Vc`, `h` sont les quatre paramètres de coupe attendus par
  le modèle. `SRS_L`/`SRS_T` sont des exemples de contrainte résiduelle
  mesurée — le nom de votre colonne cible peut être différent, vous le
  choisirez à l'étape 2.
- Seul le titane est couvert pour l'instant : un fichier sur un autre matériau
  n'a pas les bonnes colonnes et ne pourra pas être mappé.
- Les fichiers Excel (`.xlsx`) ne sont pas lus dans le navigateur : le site
  vous demandera de les réenregistrer en CSV.

---

## Étape 1 — Déposer votre fichier

Sur la page d'accueil, glissez votre fichier dans la zone prévue, ou cliquez
dessus pour ouvrir le sélecteur de fichiers.

**Rien n'est envoyé sur le réseau à cette étape.** Le fichier est lu et
analysé entièrement dans votre navigateur — vous pouvez le vérifier vous-même
en inspectant `web/js/api.js`, qui ne contient que trois appels réseau au
total, aucun ne concernant votre tableau de mesures.

Si le fichier est refusé (mauvais format, colonnes manquantes...), un message
explique pourquoi et comment corriger.

## Étape 2 — Faire correspondre les colonnes

Le site propose une correspondance automatique entre vos noms de colonnes et
les quatre paramètres attendus (`gamma`, `r_beta`, `Vc`, `h`). Vérifiez et
corrigez si besoin, puis choisissez dans le menu déroulant **quelle colonne**
contient la contrainte résiduelle que vous voulez faire prédire.

Le bouton **« Compute my scores »** reste désactivé tant que le mapping n'est
pas valide (colonne manquante, valeurs non numériques...) — les problèmes sont
listés juste au-dessus.

## Étape 3 — Lire vos deux scores

Le calcul tourne et affiche deux scores, qui ne mesurent pas la même chose :

| Score | Ce qui est fait | Question à laquelle il répond |
|---|---|---|
| **Transfer** | le modèle global publié, appliqué tel quel, sans réajustement | notre modèle marche-t-il aussi en dehors de notre labo ? |
| **Refit** | un modèle réajusté sur vos données uniquement, noté en validation croisée (leave-one-out) | vos mesures sont-elles prédictibles, indépendamment de notre modèle ? |

Une phrase de lecture s'affiche automatiquement sous les deux cartes. En
résumé :

- **Les deux bons** → votre jeu de données confirme le modèle publié, c'est le
  meilleur cas.
- **Transfer faible, Refit bon** → vos mesures sont cohérentes entre elles,
  mais notre modèle ne s'applique pas à votre régime. C'est l'information la
  plus utile que vous puissiez nous transmettre : c'est le signe d'un domaine
  que l'étude ne couvre pas encore.
- **Refit mauvais** → même réajusté sur vos seules données, rien ne se dégage.
  Vient souvent d'un domaine expérimental trop resserré, d'une dispersion de
  mesure importante, ou d'une variable déterminante absente du tableau.
- **Entre les deux** → le modèle capte une tendance partielle, à interpréter
  avec le nombre de conditions et l'étendue explorée.

Le détail (**« Full numbers and fitted coefficients »**) donne R², RMSE, MAE
et les coefficients ajustés pour chaque moteur (linéaire et PIML).

## Étape 4 — Contribuer au modèle global (facultatif)

Vous pouvez vous arrêter à l'étape 3 — rien n'oblige à contribuer. Si vous
choisissez de le faire, voici précisément ce qui part et ce qui ne part pas.

**Ce qui est envoyé :**
- Ce que vous tapez dans le formulaire (nom, laboratoire, matériau, méthode de
  mesure, procédé, refroidissement, notes).
- Le nombre de lignes et l'étendue (min–max) de chaque paramètre de coupe.
- Des **sommes statistiques** (`D'D`, `D'y`, `y'y`, `n`) qui permettent de
  réajuster le modèle sur les données réunies de tous les labos, exactement
  comme si les tableaux avaient été fusionnés.
- Les coefficients ajustés chez vous, et les deux scores ci-dessus.

**Ce qui n'est jamais envoyé :** votre tableau de mesures — aucune ligne,
aucune valeur individuelle, à aucun moment.

Un avertissement honnête à lire avant d'envoyer : ces sommes statistiques **ne
sont pas anonymes**. Sur très peu de lignes, elles peuvent révéler beaucoup du
jeu de données — sur une seule ligne, elles la restitueraient entièrement.
C'est pourquoi une contribution doit porter sur **au moins 5 lignes**.

Avant d'envoyer, le lien **« Inspect exactly what will be sent »** affiche le
payload exact en clair. Vous pouvez aussi cliquer sur **« Download it
instead »** pour récupérer ce payload en fichier plutôt que de l'envoyer,
par exemple pour le faire relire par quelqu'un avant de l'envoyer vous-même.

L'envoi demande une **clé d'accès** (fournie par le labo par email) : elle
protège le modèle global contre des modifications par n'importe qui.

Votre contribution n'entre **jamais automatiquement** dans le modèle publié :
elle part dans une file d'attente, relue par un humain avant d'être intégrée.

## En bas de page — L'historique du modèle

La section « The global model » liste les versions déjà publiées. Chaque
nouvelle version résulte d'un réajustement exact sur les sommes regroupées de
tous les contributeurs intégrés — jamais d'une simple moyenne des
coefficients de chacun.

---

## Espace admin (`admin.html`)

Réservé à la personne qui gère le modèle global (probablement vous). Accès via
le lien **« Admin »** en haut de la page d'accueil.

1. **Clé admin** — saisie une fois par onglet, jamais enregistrée ailleurs que
   dans la mémoire de l'onglet (`sessionStorage`) ; « Forget key » l'efface.
2. **File d'attente** — liste les contributions en attente (labo, méthode,
   nombre de lignes — jamais les mesures elles-mêmes). Décochez celles à
   laisser de côté pour un tour ultérieur.
3. **Preview / Publish** — « Preview » calcule la prochaine version sans rien
   écrire, pour vérifier avant de s'engager ; « Publish » l'écrit réellement.
4. **Historique et retour en arrière** — republie une version antérieure à
   l'identique si besoin ; rien n'est jamais supprimé.

Les mêmes actions existent en ligne de commande côté serveur
(`python -m server.aggregate --list|--dry-run|--exclude <id>`), voir
[README.md](README.md#intégrer-une-contribution).

---

## Problèmes fréquents

| Symptôme | Cause probable |
|---|---|
| Fichier refusé à l'étape 1 | Format non reconnu (essayez le template), ou fichier `.xlsx` non converti en CSV |
| Bouton « Compute my scores » grisé | Une colonne obligatoire n'est pas mappée, ou contient des valeurs non numériques |
| Bouton « Send my contribution » refuse d'envoyer | Moins de 5 lignes dans le fichier, clé d'accès manquante ou incorrecte |
| Bandeau « read-only » / contribution impossible | Le serveur tourne sans clé de contribution configurée (`DEAM_FL_API_KEY` absente côté serveur) — les scores restent calculables, seul l'envoi est désactivé |
