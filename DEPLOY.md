# Déployer le site — tutoriel pas à pas

Ce document suppose que vous n'avez jamais déployé de site web sur un serveur.
Chaque étape se fait en copiant-collant une commande, dans l'ordre. Ça prend
environ 10 minutes la première fois.

## Ce qu'il vous faut avant de commencer

- Un serveur (VPS) sous Linux, avec un accès SSH — c'est ce que vous a fourni
  votre hébergeur, avec une adresse (IP ou nom) et un mot de passe ou une clé.
- Un nom de domaine (ou sous-domaine, ex. `residual-stress.mon-site.fr`) qui
  **pointe déjà** vers l'adresse IP de ce serveur. C'est un réglage chez
  l'hébergeur du domaine (souvent appelé enregistrement DNS de type "A") —
  sans ça, l'étape HTTPS ne fonctionnera pas.
- Deux phrases secrètes que vous choisissez vous-même : une à donner aux
  collègues qui contribuent, une que vous seul connaissez pour administrer le
  site. N'importe quelle phrase suffit, du moment qu'elle n'est devinable par
  personne.

**Si Caddy tourne déjà sur ce serveur** (pour d'autres sites), ne suivez pas
les étapes 5 et 6 ci-dessous telles quelles : allez directement à la section
[Variante : Caddy déjà installé](#variante--caddy-déjà-installé) à la fin de
ce document, qui les remplace. Les autres étapes restent valables.

## Étape 1 — se connecter au serveur

Depuis un terminal (Terminal sur Mac, PowerShell ou WSL sur Windows) :

```bash
ssh votre_utilisateur@adresse-du-serveur
```

Tout ce qui suit se tape **sur le serveur**, une fois connecté.

## Étape 2 — installer Docker

Une seule fois, à la première utilisation de ce serveur :

```bash
curl -fsSL https://get.docker.com | sh
```

Ça prend une à deux minutes. Vérifiez ensuite :

```bash
sudo docker --version
```

Si une version s'affiche, c'est bon.

## Étape 3 — envoyer les fichiers du projet sur le serveur

Depuis **votre propre ordinateur** (pas le serveur), dans le dossier qui
contient `Federated_Learning_Website/` :

```bash
scp -r Federated_Learning_Website votre_utilisateur@adresse-du-serveur:~/
```

Ça copie tout le dossier. Reconnectez-vous ensuite en SSH (étape 1) si ce
n'est pas déjà fait, et allez dans le dossier :

```bash
cd ~/Federated_Learning_Website
```

## Étape 4 — créer le fichier des clés secrètes

```bash
cp .env.example .env
nano .env
```

`nano` ouvre un petit éditeur de texte dans le terminal. Complétez les deux
lignes avec vos phrases secrètes choisies plus haut, par exemple :

```
DEAM_FL_API_KEY=deam-titane-2026
DEAM_FL_ADMIN_KEY=un-secret-que-vous-seul-connaissez
```

Pour enregistrer et quitter `nano` : `Ctrl+O` puis `Entrée`, puis `Ctrl+X`.

Ce fichier ne doit **jamais** être envoyé par mail ni mis sur GitHub — c'est
le mot de passe du site.

## Étape 5 — indiquer votre nom de domaine

```bash
nano Caddyfile
```

Remplacez `votre-domaine.exemple.com` (première ligne non commentée) par
votre vrai nom de domaine, celui qui pointe vers ce serveur. Enregistrez et
quittez comme à l'étape précédente.

## Étape 6 — lancer le site

```bash
sudo docker compose up -d --build
```

La première fois, ça télécharge et prépare tout — comptez une à deux minutes.
`-d` fait tourner le site en arrière-plan : vous pouvez fermer le terminal
sans l'arrêter.

## Étape 7 — vérifier que ça marche

Ouvrez `https://votre-domaine` dans un navigateur. Le certificat HTTPS
s'obtient automatiquement au premier accès — patientez quelques secondes si
la page met un peu de temps à répondre la toute première fois.

Vous pouvez aussi vérifier depuis le terminal :

```bash
curl https://votre-domaine/api/status
```

Une réponse contenant `"ok":true` confirme que tout fonctionne.

---

## Mettre à jour le site plus tard

Quand une nouvelle version du code est prête (renvoyée par `scp` comme à
l'étape 3, ou récupérée par `git pull` si le projet est en dépôt) :

```bash
cd ~/Federated_Learning_Website
sudo docker compose up -d --build
```

**Rien n'est perdu** : les contributions reçues et les versions du modèle déjà
publiées vivent dans le dossier `server/store/`, qui n'est jamais touché par
une mise à jour du code (voir plus bas).

## Arrêter, relancer

```bash
sudo docker compose down    # arrête le site, ne supprime rien
sudo docker compose up -d   # le relance
```

## Où sont les données, et comment les sauvegarder

Tout ce que le site produit — le modèle publié, les contributions en attente,
l'historique des versions — vit dans `~/Federated_Learning_Website/server/store/`
sur le serveur, en dehors de l'image Docker. Pour une sauvegarde, il suffit de
copier ce dossier :

```bash
# depuis votre propre ordinateur
scp -r votre_utilisateur@adresse-du-serveur:~/Federated_Learning_Website/server/store ./sauvegarde-store
```

## Variante : Caddy déjà installé

Si Caddy tourne déjà sur ce serveur pour d'autres sites, les étapes 5 et 6 du
tutoriel principal changent : pas de second Caddy à lancer, c'est celui qui
existe déjà qui doit apprendre ce nouveau site. Le reste (étapes 1 à 4, puis 7
et la suite) ne change pas — remplacez juste `docker compose` par
`docker compose -f docker-compose.external-caddy.yml` partout où vous le
croisez plus loin dans ce document.

### Avant l'étape 5 — vérifier qu'un port est libre

Si Caddy sert déjà d'autres sites sur ce serveur, il est probable que le port
8000 (celui utilisé par défaut) soit déjà pris par l'un d'eux. Vérifiez :

```bash
sudo ss -tlnp | grep LISTEN
```

Repérez un port à quatre chiffres qui n'apparaît nulle part dans cette liste
ni dans votre Caddyfile actuel (ex. `8420`). S'il diffère de `8420`, changez-le
aux **deux** endroits : dans `docker-compose.external-caddy.yml` (la ligne
`"127.0.0.1:8420:8000"`, seul le premier `8420` compte) et dans le bloc
Caddyfile de l'étape 6 ci-dessous.

### Étape 5 (remplace) — lancer seulement l'application

```bash
sudo docker compose -f docker-compose.external-caddy.yml up -d --build
```

Ça démarre l'application seule, jamais exposée directement sur Internet : elle
n'écoute que sur `127.0.0.1:8420`, accessible uniquement depuis ce serveur.

### Étape 6 (remplace) — ajouter le site au Caddy existant

Ouvrez le fichier de configuration de votre Caddy actuel (souvent
`/etc/caddy/Caddyfile`) :

```bash
sudo nano /etc/caddy/Caddyfile
```

Ajoutez ce bloc à la fin, **sans toucher au reste du fichier** (vos autres
sites) :

```
votre-domaine.exemple.com {
    reverse_proxy localhost:8420
}
```

Enregistrez, quittez, puis demandez à Caddy de relire sa configuration — ça ne
coupe pas les autres sites qui tournent dessus :

```bash
sudo systemctl reload caddy
```

Reprenez ensuite à l'étape 7 (vérifier que ça marche) du tutoriel principal.

## Problèmes courants

**`docker: command not found`** — l'étape 2 ne s'est pas terminée
correctement. Relancez la commande d'installation.

**Le certificat HTTPS ne s'obtient pas / erreur de connexion** — vérifiez que
le nom de domaine pointe bien vers l'IP de ce serveur (un changement DNS peut
prendre jusqu'à 24-48h pour se propager partout). Testez avec :

```bash
nslookup votre-domaine
```
L'adresse IP affichée doit correspondre à celle du serveur.

**`port is already allocated` / "already in use"** — un Caddy (ou un autre
serveur web) tourne déjà sur les ports 80 ou 443 de cette machine. C'est
exactement le cas couvert par [Variante : Caddy déjà installé](#variante--caddy-déjà-installé)
ci-dessus : relancez avec `docker-compose.external-caddy.yml` au lieu de
`docker-compose.yml`.

**Pour voir ce qui se passe si quelque chose ne marche pas** :

```bash
sudo docker compose logs app     # les messages du serveur du site
sudo docker compose logs caddy   # les messages liés au certificat HTTPS
```
