# Architecture

```
web (Svelte)  ──HTTP/SSE──►  api (FastAPI)  ──import──►  core (Python)  ──subprocess──►  onec
```

- **core** : seul endroit où vit la logique métier. Testable sans réseau ni interface.
- **api** : traduit HTTP ↔ core. L'optimiseur tourne dans un thread et envoie sa progression en SSE ; pas de WebSocket.
- **web** : ne calcule rien ; il édite un modèle, appelle l'API, affiche des résultats.
- **onec** : moteur NEC-2 externe (OpenNEC). Appelé avec un deck temporaire ; sa sortie texte est parsée.

## Flux d'une simulation

1. L'UI envoie un modèle JSON (`POST /simulate`).
2. L'API construit un `AntennaModel` et appelle `core.simulate`.
3. Le core génère le deck, lance `onec`, parse la sortie, renvoie un `SimulationResult`.
4. L'API le sérialise en JSON ; l'UI trace.

## Points d'attention

- La sortie de `onec` est du texte : le parseur est testé sur des sorties réelles (`core/tests`).
- Le format `.nec` accepte symboles et formules (4NEC2) : on laisse `onec` les évaluer.
