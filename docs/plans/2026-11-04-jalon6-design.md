# Jalon 6 — symboles et optimiseur (conception validée le 2026-11-04)

## 1. Symboles et formules

- Tableau des **symboles** (nom, formule, valeur calculée) au-dessus du tableau des fils.
- Les cases d'un fil (x, y, z, rayon) acceptent un nombre ou une formule (`-L/2`, `h+0.5`) ;
  la valeur calculée s'affiche sous la formule.
- Import 4NEC2 : cartes SY **gardées**, formules des `GW` gardées dans leurs cases. Les fils issus
  de GM, GA, GR restent en nombres (un fil par segment, plus de formule à laquelle les rattacher) ;
  le bandeau d'import le dit. L'enregistrement réécrit les SY et les formules telles quelles.
- **onec calcule les formules** (on ne réécrit pas l'évaluateur de 4NEC2) : le deck part avec ses
  SY ; l'appel de contrôle (0,3 s après la saisie) renvoie aussi les valeurs calculées par onec,
  lu sans simuler (~5 ms). La 3D et le contrôle voient exactement ce que onec simulera.
- Erreurs (symbole inconnu, boucle, formule invalide, nom invalide) → remarque rouge dans
  « Contrôle du modèle », avec le message d'onec ; Simuler bloqué.
- Sécurité : les formules ne vont qu'à onec, jamais à `eval` ; l'API refuse tout caractère
  étranger à une formule (comme pour les cartes conservées).

## 2. Optimiseur

- **Variables** : symboles cochés, valant un simple nombre ; bornes min/max (±20 % par défaut).
  Avertissement au-delà de 8 à 10 variables.
- **Objectifs pondérés, tous en dB** ; score = Σ poids × critère, à minimiser :

  | Critère | Mesure |
  |---|---|
  | ROS | perte de désadaptation au pire point de la bande (0 dB à ROS 1, 0,512 dB à ROS 2) |
  | Gain | gain moyen sur la bande dans la direction (θ, φ), à maximiser |
  | AV/AR | AV/AR au pire point de la bande, plafonné (30 dB par défaut) |

  Bande : fréquences basse et haute, 3 points par défaut. Z0 et direction : ceux du balayage.
  R et X visés : écartés (le ROS sur Z0 réglable couvre le besoin courant).
- **Algorithme** : Nelder-Mead avec bornes (SciPy). Recherche locale : on affine un modèle proche.
- Géométrie refusée (contrôle du modèle ou onec) → forte pénalité, la recherche continue.
- **Arrêt** : 300 calculs (réglable), convergence ou bouton Arrêter ; on garde le meilleur essai.
- **Résultat** : variables (départ / meilleur), critères (avant / après). **Appliquer** reporte les
  valeurs dans les symboles, **Annuler** revient en arrière ; rien n'est changé sans ce clic.

## 3. Architecture

- **core** : `model.py` (`Symbol`, `AntennaModel.symbols`, cases `float | str`, `SY` après `CE`) ;
  `symbols.py` (`resolve(model)` : onec lit le deck sans simuler → modèle en nombres ou erreur) ;
  `optimize.py` (`optimize(model, variables, objective, on_progress, should_stop)`, sans thread).
  SciPy en dépendance optionnelle `open2nec[optim]` ; sans elle, message clair.
- **api** : `POST /optimize` → identifiant (une recherche à la fois, sinon 409) ;
  `GET /optimize/{id}/events` en SSE (essai, score, critères, valeurs, meilleur) ;
  `POST /optimize/{id}/stop` ; recherche terminée oubliée après 10 min.
  `/validate` renvoie aussi les valeurs calculées.
- **web** : `SymbolTable.svelte`, cases des fils en texte ; `OptimizerPanel.svelte` (variables,
  bornes, poids, bande, nombre de calculs, Lancer/Arrêter) ; en direct : courbe uPlot du score,
  tableau du meilleur essai, 3D du meilleur essai ; Appliquer / Annuler à la fin.
- Durée d'un essai mesurée avec le vrai onec (Yagi pré-remplie, fichier d'un modèle 4NEC2 existant) avant
  de fixer la limite par défaut.

## 4. Tests

- **Symboles** (vrai onec) : dipôle `f=14.2`, `L=142.5/f`, `±L/2` → mêmes extrémités et même
  impédance que le dipôle en nombres ; refus clairs (inconnu, boucle, formule, nom, injection) ;
  import de `import_yagi_4nec2.nec` → SY et formules gardées, réenregistrement → même SY, même
  impédance (±0,5 %).
- **Optimiseur sans onec** (fonction connue) : bornes, arrêt, meilleur gardé, pénalité, progression.
  Critères : ROS 2 → 0,512 dB, ROS 1 → 0 dB, plafond AV/AR.
- **Optimiseur avec onec** : dipôle 14,2 MHz, espace libre, `L` variable, ROS seul sur 72 Ω →
  résonance (X ≈ 0), L ≈ 0,47 à 0,48 λ ; Yagi 2 éléments, réflecteur (longueur, espacement),
  AV/AR → nettement meilleur que le départ, dans les bornes.
- **API** : démarrage, flux SSE complet, arrêt, 409, 422 ; `/validate` avec valeurs calculées.
- **Web** : svelte-check, build ; Chrome : dipôle en symboles optimisé en direct, Arrêter,
  Appliquer/Annuler ; ouverture et enregistrement du fichier 4NEC2. Même séance : essais à
  l'écran restés en attente du jalon 5 (jonctions, croisements, fils parallèles).

## Déroulement

Sauvegarde préalable, puis core → point d'étape →
API → point d'étape → interface → Chrome ; ruff et tous les tests à chaque étape.

## Constats et ajustements pendant le core (2026-11-04)

- **onec n'imprime pas la valeur des symboles.** Sonde : une carte `FR 0 1 0 0 <nom> 0` par
  symbole, lue dans les lignes DATA CARD (6 chiffres significatifs) ; deck lu sans calcul (~5 ms).
  Coordonnées calculées : table des fils (10 µm, comme l'import).
- **onec 2.3.3 laisse passer des erreurs** : boucle `a=b, b=a` → 0 ; doublon → le premier gagne ;
  `1/0` → INF ; noms insensibles à la casse ; `pi`, `sin` redéfinissables ; et surtout, dans une
  carte GW, une formule invalide (`L*q`, `(1+`) devient **0 sans message**. D'où, dans le core :
  nom unique (casse ignorée), non réservé, défini avant usage ; et dans le deck sonde chaque
  formule de fil passe aussi par un symbole auxiliaire `SY _o2n_n=…`, qu'onec contrôle
  (préfixe `_o2n_` interdit aux utilisateurs). Trigonométrie d'onec en degrés (sin(30) = 0,5).
- **Import, règle « tout ou rien »** (plus prudente que la section 1) : formules gardées seulement
  si chaque GW recalculée retombe à l'identique sur le fil lu par onec ; fichier avec GM, GR, GX
  ou GS → tout en nombres (changer `L` ne suivrait pas les copies). GA/GH : en nombres, sans
  empêcher le reste. Symboles cités en avant (accepté par onec) : remontés à l'import.
- **Dipôle de référence** : fil de 1 mm (λ/d ≈ 10 000), résonance à **0,4853 λ** (X = −0,02 Ω),
  pas 0,47–0,48 λ (valeur des conducteurs plus épais). Test : 0,48 < L/λ < 0,49, |X| < 2 Ω.
- **Durées mesurées** : dipôle 21 segments, ~25 ms par essai ; Yagi 3 éléments pré-remplie sur
  sol réel (Sommerfeld, 63 segments) : 170 ms (3 points), 270 ms (5 points). 300 calculs ≈ 50 s.
- SciPy 1.18 + NumPy : ~150 Mo, en option `open2nec[optim]` (à garder en tête pour Docker).

## Vérification dans Chrome (2026-11-04)

- Dipôle réécrit avec `L`, `h` : valeurs calculées sous les formules, 3D et longueur justes.
  Optimisation ROS seul (13,9–14,5 MHz, sol réel) : 18 calculs, 2,8 s, L 10 → 10,314 m, ROS au pire
  point 3,58 → 1,87 ; Appliquer puis Annuler corrects. Arrêter : « arrêtée à la demande », meilleur gardé.
- Fichier `import_symbols_4nec2.nec` : 7 symboles (Ld remonté), formules dans les fils, arc en
  nombres, bandeau correct. Simuler avec formules : diagramme et balayage. Optimisation f et sp
  (ROS 30, gain 40, AV/AR 30 %, θ = 68° repris du diagramme) : 89 calculs, 16,5 s ; AV/AR
  21,4 → 25,9 dB, gain 12,34 → 12,25 dBi, ROS 1,88 → 2,37 (compromis voulu par les poids).
  Enregistrer : SY optimisés, formules intactes.
- Jalon 5 rattrapé : croisement, jonction en milieu de segment, parallèles proches non alignés →
  avertissements justes, lignes et fils 3D marqués.
- Défauts trouvés et corrigés pendant l'essai : bornes de variables remises à zéro pendant la
  frappe ; θ = 90° par défaut au-dessus du sol (aucun rayonnement → recherche inutile : θ = 60°
  par défaut sur sol, et refus clair par le core) ; points des essais peu visibles ; bouton
  « + symbole » sur deux lignes.
