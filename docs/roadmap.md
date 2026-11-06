# Feuille de route

Chaque jalon est publiable seul (et peut faire l'objet d'un article sur hamanalyst.org).

1. **Socle** — modèle de géométrie, génération du deck, appel de `onec`, parseur. *(fait)*
2. **API + vue 3D** — affichage de la géométrie, simulation à une fréquence, diagramme de rayonnement. *(fait le 2026-11-02 : tableau de fils, 4 modèles pré-remplis, vue Three.js, coupes azimut/élévation ; voir docs/plans/2026-11-02-jalon2-design.md)*
3. **Balayage** — SWR et impédance en fonction de la fréquence, courbes interactives. *(fait le 2026-11-02 : ROS et bandes 2/1,5, R/X, gain et AV/AR, abaque de Smith, Z0 réglable, uPlot ; voir docs/plans/2026-11-02-jalon3-design.md)*
4. **Import/export `.nec`** — ouverture des modèles 4NEC2 existants (via `onec`, qui lit les symboles et formules). *(fait le 2026-11-02 : 93 de 113 modèles 4NEC2 de tiers (non redistribués) importés et fidèles à 0,2 % près ; voir docs/plans/2026-11-02-jalon4-design.md)*
5. **Validation** — avertissements sur segments, jonctions, sol. *(fait le 2026-11-02 : contrôles écrits dans le core, `onec -t` s'étant révélé trop lacunaire ; voir docs/plans/2026-11-02-jalon5-design.md)*
6. **Optimiseur** — variables, objectifs (SWR, gain, F/B), progression en direct. *(fait le 2026-11-04 : symboles SY et formules gardés à l'import et à l'enregistrement, calculés par onec ; optimiseur Nelder-Mead pondéré en dB, suivi SSE, Appliquer/Annuler ; voir docs/plans/2026-11-04-jalon6-design.md)*
7. **Finitions** — thème, exemples (FCP 80 m, UB50), Docker, démo en ligne. *(partiel au 2026-11-06 : thème clair/sombre/auto, quad 2 éléments et Yagi en symboles faits ; image Docker construite et essayée en CI (job `docker` : build + smoke-test) et sur un PC Ubuntu, dipôle à 2,12 dBi ; FCP 80 m et UB50 en attente de leurs cotes ; pas de démo publique ; voir docs/plans/2026-11-04-jalon7-design.md)*
