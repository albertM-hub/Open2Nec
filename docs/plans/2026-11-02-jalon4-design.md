# Jalon 4 — ouverture et enregistrement des fichiers .nec (conception validée le 2026-11-02)

## Constats de départ (onec 2.3.2)

- `onec -w x.nec2` ne résout pas les symboles (SY) et perd la ligne SY : inutilisable pour l'import.
- En retirant les cartes d'exécution (RP, XQ, NE, NH…), `onec` lit le fichier en ~5 ms et imprime :
  la table **SEGMENTATION DATA** (géométrie développée : formules évaluées, GM/GR, arcs GA en segments)
  et les lignes **DATA CARD** (GN, LD, EX, FR… en valeurs numériques).
- On reconstruit donc le modèle à partir de ce qu'onec a compris, sans réécrire l'évaluateur de 4NEC2.

## Périmètre

- **Ouvrir** (bouton + glisser-déposer) un `.nec` 4NEC2 (`.maa` MMANA si onec le lit correctement).
  - Fils → tableau éditable, avec colonne **tag** (numéros d'origine conservés). Segments alignés,
    contigus, de même tag et rayon → un fil ; arcs/hélices → suite de petits fils.
  - GN → sol (εr, σ modifiables ; GN 0 approché ou GN 2 exact) ; 1re source `EX 0` → alimentation ;
    1er FR → balayage, diagramme au centre.
  - Cartes électriques (LD, TL, NT, EX supplémentaires, EK, KH) → **conservées** en lecture seule,
    décrites en français, renvoyées à onec à chaque calcul.
  - Cartes d'affichage (RP, PT, PQ, NE, NH, WG, PL, CP) → écartées et listées.
  - Bandeau : fichier, ce qui est repris, pertes (« symboles figés en valeurs »…).
- **Enregistrer en .nec** : modèle courant, cartes conservées comprises (écrit par le core).
- Hors jalon : symboles rendus (jalon 6), édition des cartes conservées, export `.maa`.

## Architecture

- **core/model.py** : `AntennaModel.extra_cards` (lignes NEC numériques, écrites entre GN et EX) ;
  `Ground.exact` (GN 2 / GN 0).
- **core/importer.py** : retrait des cartes d'exécution → onec → lecture de SEGMENTATION DATA et des
  DATA CARD (testée sur sorties réelles) → regroupement en fils → tri des cartes → `ImportResult`
  (modèle, fréquence, notes, cartes écartées). Carte inconnue → refus.
- **core/validate** : `check_excitations` additionne les segments des fils de même tag
  (numérotation NEC d'un arc découpé).
- **api** : `POST /import` (nom + contenu JSON, ≤ 1 Mo) → modèle ; `POST /export` → texte .nec.
  `ModelIn.extra_cards` validé strictement (code autorisé, nombres seuls) : pas d'injection de cartes.
- **web** : colonne tag, alimentation (tag, segment), barre Ouvrir/Enregistrer + bandeau, champs εr/σ,
  `ExtraCards.svelte`.

## Erreurs (422, message en clair)

onec refuse le fichier (son message) ; surfaces SP/SM, GN avec radians/second milieu, carte inconnue,
aucune EX 0 → refus motivé ; fichier vide, trop gros ou non textuel → refus avant onec.
Tolérés avec note : plusieurs FR (1er gardé), symboles figés.

## Tests

- Fichiers d'essai réalistes + sortie onec réelle dans `core/tests/data/` (tests sans onec).
- Regroupement : dipôle → 1 fil ; GM → 2 fils (tags 1, 2) ; arc → petits fils de même tag.
- **Fidélité** : fichier importé puis réécrit → même impédance (±0,5 %) que l'original, trappe comprise.
- Refus : surfaces, radians, carte inconnue, sans source.
- API : import 200/422 ; export avec cartes conservées ; carte piégée refusée.
- Web : svelte-check, build, essai réel dans Chrome (ouvrir, simuler, enregistrer).
