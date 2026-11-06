# Jalon 7 — thème, exemples, image Docker locale (conception validée le 2026-11-04)

## Cadrage

- **Pas de démo publique.** Une image Docker qui tourne en local (et que d'autres
  radioamateurs peuvent reconstruire), page sur http://localhost:8080.
- **Exemples** : quad 2 éléments maintenant ; FCP 80 m et UB50 reportés (pas encore de cotes).
- **Thème** : clair et sombre.

## 1. Thème et exemples

- Couleurs regroupées en **variables CSS** (`app.css`) : fond, surfaces, texte, texte atténué,
  bordures, accent, ok, avertissement, erreur. Sombre = couleurs actuelles ; clair ajouté.
- Bouton dans l'en-tête : Auto (réglage du système) → Clair → Sombre ; choix mémorisé dans le
  navigateur (Auto si le stockage est indisponible).
- Vue 3D (Three.js) et courbes (uPlot, polaires, Smith) lisent les mêmes variables et se
  redessinent au changement de thème. Contrastes du texte vérifiés (WCAG AA) dans les deux thèmes.
- Police du système : aucun service extérieur.
- **Quad 2 éléments** pré-remplie, en symboles (`f`, `lam`, `ad`, `ar`, `sp`, `h`), 14,2 MHz,
  12 m, sol réel ; radiateur réglé pour X ≈ 0 au centre (premier essai : 94 + j33 Ω).
- **Yagi 3 éléments** réécrite en symboles, même géométrie (mêmes résultats, test à l'appui).

## 2. Image Docker locale

- Construction en deux étapes : Node (`npm ci`, `npm run build`) → `python:3.13-slim-trixie`
  (core avec SciPy, API, interface construite). onec demande glibc ≥ 2.38 : Debian 12 (2.36) est
  trop ancienne, Debian 13 trixie (2.41) convient.
- Un seul processus uvicorn : API sous `/api`, interface sous `/` (comme le proxy de Vite).
- onec téléchargé à la construction depuis la release officielle, version fixée
  (`ONEC_VERSION=2.3.3`) et empreinte SHA-256 contrôlée. Une fois lancée, l'application
  n'appelle aucun service extérieur.
- `docker compose up -d --build` dans `docker/` ; port publié sur **127.0.0.1:8080** seulement ;
  utilisateur sans privilèges ; contrôle de santé `/api/health` ; un seul processus ;
  redémarrage automatique. Limites de calcul de l'API inchangées. Taille ≈ 350 Mo.
- `docker/README.md` en français : installer Docker (Ubuntu 26.04, avec sudo),
  construire, lancer, arrêter, mettre à jour onec, port déjà pris.

## Tests

- Quad (vrai onec) : 7 à 8 dBi en espace libre, Z ≈ 100–125 Ω, X ≈ 0 au centre.
- Yagi en symboles : même impédance et même gain que la version en nombres.
- Service local sans Docker : l'API sert l'interface construite (`/`, `/api/health`,
  `/api/simulate`).
- Image : script d'essai (construction, santé, dipôle à 2,15 dBi, arrêt), à lancer une fois
  Docker installé.
- Interface : svelte-check, build, Chrome dans les deux thèmes.

## Déroulement

Sauvegarde préalable, puis core → point d'étape →
API (service des fichiers statiques) → interface (thème) → Docker → Chrome.

## Réalisé et vérifié (2026-11-04)

- Quad : 1,0092 × λ/4 (radiateur), 1,06 × λ/4 (réflecteur), 0,15 λ ; Z = 122,1 − j0,0 Ω,
  11,85 dBi, départ 22°, AV/AR 24 dB (sol réel, 12 m) ; 7,36 dBi, AV/AR 23,5 dB en espace libre ;
  ROS mini 1,02 à 14,200 MHz sur 120 Ω. `Preset.z0` (120 Ω pour la quad) servi par /presets et
  appliqué au chargement.
- Thème : variables CSS, bouton Auto → Clair → Sombre mémorisé ; 3D, uPlot, polaires, Smith
  redessinés. Contrastes AA : boutons sombres passés de 3,2:1 à 5,2:1 (fond --button-bg).
- Correctif : le ROS du bandeau du diagramme était toujours sur 50 Ω ; il suit maintenant le Z0
  (valeur du balayage à la fréquence du diagramme).
- `app.serve` : interface sous `/`, API sous `/api`, CSP `default-src 'self'` (aucun refus dans
  Chrome), middleware ASGI pur (SSE non retenu). Étape finale de l'image simulée sans Docker
  (installation non éditable) : page, presets, dipôle 2,12 dBi.
- Image Docker construite avec succès en CI le 2026-11-06 (job `docker` : build + smoke-test,
  dipôle à 2,12 dBi). Essai sur PC local à faire : installer Docker, puis
  `bash docker/smoke-test.sh` (voir docker/README.md).
