# Open2Nec dans Docker (sur ton PC)

Une image complète : interface, API et moteur de calcul `onec` (OpenNEC). Elle tourne sur ce PC
seulement : la page est sur **http://localhost:8080**, et rien n'est joignable depuis le réseau
ni depuis Internet. Une fois lancée, l'application n'appelle aucun service extérieur.

## 1. Installer Docker (une seule fois)

Sur Ubuntu 26.04, avec les droits administrateur :

```bash
sudo apt update
sudo apt install docker.io docker-compose-v2 docker-buildx
sudo usermod -aG docker "$USER"   # pour lancer docker sans sudo
```

Fermer puis rouvrir la session (ou redémarrer), puis vérifier :

```bash
docker --version && docker compose version
```

## 2. Construire et lancer

Depuis la racine du dépôt :

```bash
bash docker/smoke-test.sh
```

Le script construit l'image (quelques minutes la première fois), la lance, puis vérifie que la page
répond et qu'un dipôle demi-onde donne bien 2,0 à 2,3 dBi. Ensuite, ouvrir http://localhost:8080.

Sans le script :

```bash
docker compose -f docker/compose.yaml up -d --build
```

## 3. Arrêter, relancer

```bash
docker compose -f docker/compose.yaml down      # arrêter
docker compose -f docker/compose.yaml up -d     # relancer (sans reconstruire)
docker compose -f docker/compose.yaml logs -f   # voir le journal
```

Le conteneur redémarre seul avec le PC, sauf s'il a été arrêté par `down`.

## 4. Mettre à jour onec

L'image télécharge `onec` pendant la construction, depuis la release officielle d'OpenNEC
(https://github.com/maurymarkowitz/OpenNEC/releases). La version et l'empreinte SHA-256 de
l'archive `onec-linux-x86_64.zip` sont fixées dans `docker/compose.yaml` (`ONEC_VERSION`,
`ONEC_SHA256`) : une archive modifiée fait échouer la construction.

Pour une nouvelle version :

1. télécharger l'archive et calculer son empreinte : `sha256sum onec-linux-x86_64.zip` ;
2. mettre à jour les deux valeurs dans `docker/compose.yaml` ;
3. reconstruire : `bash docker/smoke-test.sh`.

## 5. Problèmes courants

- **Port 8080 déjà pris** : choisir un autre port avec `OPEN2NEC_PORT`, puis ouvrir
  http://localhost:8099. La variable est à repréciser à chaque lancement.

  ```bash
  OPEN2NEC_PORT=8099 docker compose -f docker/compose.yaml up -d
  OPEN2NEC_PORT=8099 bash docker/smoke-test.sh
  ```

- **« permission denied » sur le socket Docker** : la session n'a pas encore pris en compte le
  groupe `docker` (étape 1) ; se déconnecter puis se reconnecter.
- **Calcul refusé** : les limites sont les mêmes qu'en développement (2000 segments,
  201 fréquences…) ; le message de l'interface donne la raison.

## Ce que contient l'image

- `python:3.13-slim-trixie` (Debian 13 : `onec` demande glibc ≥ 2.38) ;
- le core et l'API d'Open2Nec, avec SciPy pour l'optimiseur (environ 150 Mo) ;
- l'interface construite, servie par le même processus (API sous `/api`) ;
- un utilisateur sans privilèges, un système de fichiers en lecture seule (sauf `/tmp`, où onec
  écrit ses fichiers de calcul), 2 Go de mémoire au plus.
