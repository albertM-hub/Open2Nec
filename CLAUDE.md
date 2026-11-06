# CLAUDE.md — contexte pour Claude Code

Open2Nec : interface web moderne pour la simulation d'antennes NEC-2.
Le moteur de calcul est **OpenNEC** (`onec`), appelé en sous-processus. On ne réimplémente pas NEC.

## Architecture (3 couches)

- `core/` : bibliothèque Python pure. **Ne jamais importer FastAPI ni quoi que ce soit lié à l'interface.**
  - `model.py` : modèle d'antenne (fils, excitations, sol, balayage) → génère un deck NEC
  - `engine/` : localise et lance `onec`
  - `results/` : parseur de la sortie texte de `onec`
  - `validate/` : règles de segmentation et avertissements
  - `sweep.py` : balayage de fréquence
  - `importer.py` : import des fichiers `.nec` (4NEC2) vers le modèle
  - `symbols.py` : symboles SY et formules, calculés par `onec`
  - `optimize.py` : optimiseur Nelder-Mead (SciPy, extra `optim`)
  - `pattern.py` : diagramme de rayonnement à une fréquence
  - `presets.py` : modèles d'antennes pré-remplis
- `api/` : FastAPI, fine couche au-dessus du core. Aucune logique de calcul ici.
- `web/` : Svelte + Vite + TypeScript. Client API typé écrit à la main (`web/src/api/client.ts`), aligné sur `api/app/schemas.py`.

## Conventions

- Python ≥ 3.10, typé, `ruff` pour le style.
- Commentaires **en français** quand le code est complexe ; noms de variables/fonctions en anglais.
- Unités : mètres, MHz, ohms. Toute conversion se fait à la frontière (UI).
- Tests : `cd core && pytest`. Un nouveau comportement = un test avec un modèle de référence
  (dipôle demi-onde, vertical quart d'onde, etc.).
- Le binaire `onec` se trouve via `OPEN2NEC_ONEC`, puis `bin/`, puis le `PATH`.
  Les tests qui en ont besoin sont ignorés (skip) s'il est absent.

## À ne pas faire

- Ne pas embarquer ni modifier le code d'OpenNEC dans ce dépôt.
- Ne pas faire dépendre le core d'une interface (web, tkinter, etc.).
- Ne pas parser la sortie de `onec` avec des regex fragiles sans test sur une sortie réelle.

## Commandes utiles

```bash
cd core && pip install -e ".[dev]" && pytest
cd api && pip install -e ../core -e ".[dev]" && uvicorn app.main:app --reload
cd web && npm install && npm run dev
```
