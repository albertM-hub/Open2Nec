# Jalon 3 — balayage interactif (conception validée le 2026-11-02)

## Périmètre

- Réglages : début, fin, points (au lieu de début/pas/points) ; **Z0** (50, 75 ou libre) ; changer
  Z0 relance le calcul.
- Résumé : ROS mini et sa fréquence, résonance(s) (X = 0), bandes à ROS 2 et 1,5 (bornes
  interpolées, largeur en kHz, bande ouverte signalée « > f max »).
- Courbes empilées à curseur partagé (uPlot 1.6.32, MIT, embarqué) : ROS (seuils 2 et 1,5, bande
  grisée), R et X (zéro de X repéré), gain et AV/AR. Zoom par tirer, retour par double-clic,
  survol = toutes les valeurs.
- Abaque de Smith (SVG) normalisée à Z0 : trajectoire, cercles ROS 2 et 1,5, point survolé.
- Gain et AV/AR **dans la direction du lobe principal à la fréquence du diagramme** (comme 4NEC2).
- Hors jalon : fréquence du diagramme réglée par clic, export CSV, ROS au bout d'une ligne.

## Architecture

- **core/sweep.py** : analyse d'un balayage pour un Z0 : ROS, Γ, résonances, bandes (interpolation
  linéaire du ROS entre points). Gain : balayage avec une grille RP de 2 directions (avant et
  arrière) par fréquence.
- **api** : `/simulate` accepte `z0` et `direction` (θ, φ) optionnelle ; renvoie par fréquence
  R, X, ROS, Γ, gain avant/arrière, et le résumé. L'interface appelle `/pattern` puis `/simulate`
  avec la direction du maximum.
- **web** : `charts/SweepCharts.svelte` (uPlot), `charts/SmithChart.svelte` (SVG), survol partagé.

## Tests

- Core sans onec : bornes interpolées, bande ouverte, plusieurs résonances, Z0 = 75 Ω.
- Core avec onec : bande 2:1 d'un dipôle plausible ; Yagi : gain avant/arrière du balayage égal à
  celui du diagramme à la même fréquence (±0,1 dB).
- API : z0, direction, 422. Web : svelte-check, build, essai Chrome (survol, zoom, Z0 75 Ω).
