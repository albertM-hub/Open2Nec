# Jalon 2 — vue 3D, diagramme de rayonnement (conception validée le 2026-11-02)

## Périmètre

- Saisie par **tableau de fils** (x1 y1 z1, x2 y2 z2, rayon, segments), fil alimenté au choix
  (source au segment central), **modèles pré-remplis** pour démarrer.
- **Vue 3D** (Three.js, embarqué, aucun service extérieur) : fils, point d'alimentation, sol, axes ;
  rotation/zoom ; mise à jour en direct pendant la saisie.
- **Diagramme à une fréquence**, en **coupes 2D** : azimut (à l'angle de départ du lobe max) et
  élévation (direction du max et opposée), avec gain max, angle de départ, rapport AV/AR,
  impédance et ROS.
- Balayage ROS existant conservé.
- Hors jalon : import `.nec` (jalon 4), lobe 3D, charges LD, lignes TL, sources multiples, sauvegarde.

## Architecture

Tout calcul dans le core ; l'API transmet ; l'interface dessine.

- **core/open2nec/pattern.py**
  - `pattern_grid(ground)` : pas de 2° ; demi-sphère (46 × 180) avec sol, sphère (91 × 180) sans.
  - `analyze_pattern(freq_result)` : gain max et direction, angle de départ (= 90° − θ),
    coupe azimut, coupe élévation (avant + arrière), rapport AV/AR.
- **api** : schéma commun `GeometryIn` (fils, excitations, sol) ; `ModelIn` = géométrie + balayage.
  Nouvelle route `POST /pattern` (géométrie + fréquence) → résumé, deux coupes, Z, ROS.
  Grille fixée par le core : pas de limite à négocier. Mêmes contrôles 422/503 que `/simulate`.
- **web** : `editor/presets.ts`, `editor/WireTable.svelte`, `viewer3d/GeometryView.svelte`,
  `charts/PolarChart.svelte` (SVG, sert aux deux coupes), assemblage dans `App.svelte`.
  « Simuler » appelle `/simulate` et `/pattern` en parallèle.
- Conventions : azimut 0° = axe +X (boom d'une Yagi), affiché en haut ; échelle radiale en dB
  de Gmax − 30 dB à Gmax.

## Erreurs

1. Saisie invalide (rayon ≤ 0, segments < 1, fil de longueur nulle, case vide) : case surlignée,
   « Simuler » grisé avec la raison ; la vue 3D ignore la ligne fautive.
2. 422 (excitation, taille, modèle refusé par onec) : message clair.
3. 503 : « moteur de calcul indisponible ».
4. Avertissements de segmentation en orange.
5. Si un des deux appels échoue, l'autre résultat reste affiché.

## Modèles pré-remplis (cotes réglées avec onec, résonants sur 20 m)

Dipôle λ/2 à 10 m ; ground plane λ/4 + 4 radians inclinés, base à 3 m ; Yagi 3 él. à 12 m ;
V inversé sommet 12 m. Tous sur sol réel, aucun fil à z = 0.

## Tests

- Core (onec réel) : dipôle espace libre ≈ 2,1 dBi travers, AV/AR ≈ 0 ; dipôle λ/2 sur sol parfait,
  départ ≈ 30° ; Yagi AV/AR > 10 dB, max vers +X. Tests unitaires de `analyze_pattern` sur grille
  synthétique (sans onec).
- Chaque modèle pré-rempli : simulation sans erreur, ROS < 2 à sa fréquence.
- API : `/pattern` 200 sur dipôle, 422 sur excitation invalide.
- Web : `svelte-check`, build, contrôle réel dans Chrome.

## Ordre

Core → API → interface, avec un point d'étape à chaque fois.
