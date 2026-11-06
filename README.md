# Open2Nec

Interface web moderne pour la simulation d'antennes **NEC-2**, pensée comme un successeur
spirituel de 4NEC2 : éditeur de géométrie, vue 3D, balayage SWR/impédance, optimiseur.

Le calcul est délégué à [OpenNEC](https://github.com/maurymarkowitz/OpenNEC) (`onec`, MIT),
un moteur NEC-2 en C rapide, multi-cœur, compatible avec les extensions de 4NEC2.
Open2Nec n'en est **pas** un fork : c'est une interface et une bibliothèque Python par-dessus.

Avancement : voir [docs/roadmap.md](docs/roadmap.md).

## Architecture

```
core/   bibliothèque Python pure (modèle, cartes NEC, appel de onec, parseur)
api/    FastAPI : fine couche HTTP au-dessus du core
web/    Svelte + Vite + TypeScript (+ Three.js pour la 3D)
```

Règle d'or : `core` ne dépend jamais de FastAPI ni d'une interface.

## Démarrage rapide (core + CLI)

```bash
# 1. Obtenir onec (binaire des releases OpenNEC, ou make dans le dépôt OpenNEC)
export OPEN2NEC_ONEC=/chemin/vers/onec

# 2. Installer le core
cd core
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Tester
pytest

# 4. Simuler un dipôle
open2nec run ../examples/dipole.nec
```

## Docker

Image locale complète (interface, API et `onec`), servie sur http://localhost:8080 :

```bash
bash docker/smoke-test.sh
```

Installation de Docker, arrêt et mise à jour de `onec` : voir
[docker/README.md](docker/README.md). L'image est construite et essayée en CI (job `docker` : build
+ smoke-test) et sur un PC Ubuntu : dipôle à 2,12 dBi. Si le port 8080 est pris :
`OPEN2NEC_PORT=8099 bash docker/smoke-test.sh`.

## Licence

MIT (voir `LICENSE`). OpenNEC est distribué séparément sous sa propre licence MIT.
