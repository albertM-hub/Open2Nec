# Jalon 5 — contrôle du modèle (conception validée le 2026-11-02)

## Constat (onec 2.3.2)

`onec -t` contient ~60 messages de contrôle mais, en pratique : sans calcul (`-n`) il ne signale que
tags en double, rayon trop gros, segments très longs ; avec calcul, le sol n'apparaît que via
l'erreur fatale suivie du plantage (OpenNEC #30). Source en bout de fil, fil branché au milieu
d'un autre, jonction mal segmentée, fils parallèles proches : rien. Aucune gravité, code retour 0.
→ Contrôles écrits dans le core ; `onec -t` n'est pas utilisé.

## Contrôles (λ à la fréquence la plus haute : balayage ou diagramme)

- **Erreurs** (Simuler bloqué) : fil sous le sol ou posé à plat sur le sol ; fils superposés ;
  source sur fil/segment inexistant ; carte conservée (LD, TL, NT, EX) visant un fil/segment
  inexistant.
- **Avertissements** : segments > λ/10 (> λ/5) ou < 0,001 λ ; segment < 8 × rayon ; fil aboutissant
  au milieu d'un segment d'un autre fil (non connecté pour NEC) ; jonction avec segments ou rayons
  dans un rapport > 5:1 ; source sur un bout de fil libre ; fils parallèles à < 0,05 λ aux segments
  non alignés ; fils qui se croisent sans être connectés.
- **Conseils** : nombre de segments pair sur le fil alimenté au centre ; segment alimenté > λ/20 ;
  sol réel approché (GN 0) avec un fil à < 0,1 λ du sol.
- Contrôles deux à deux limités à 500 fils (au-delà, conseil le signalant).

## Architecture

- **core/validate** : `validate_model(model, max_frequency_mhz) -> list[Issue]` (gravité, code,
  message en français, indices des fils concernés).
- **api** : `POST /validate` ; `/simulate` et `/pattern` → 422 si erreur, avertissements renvoyés.
- **web** : panneau « Contrôle du modèle » en direct (≈ 0,3 s après la saisie), lignes surlignées
  dans le tableau, fils colorés en 3D.

## Tests

- Un modèle minimal par contrôle (déclenché) et sa version corrigée (non déclenché).
- Les 4 modèles pré-remplis : ni erreur ni avertissement.
- Calibrage : aucun des fichiers d'essai importables et calculés par onec n'est bloqué.
- Web : svelte-check, build, essai Chrome.
