"""Point d'entrée de haut niveau : modèle (ou deck brut) → résultats."""

from __future__ import annotations

from .engine import ModelRejected, run_onec
from .model import AntennaModel
from .results import SimulationResult, parse_output


def simulate_deck(deck: str, timeout: float = 120.0) -> SimulationResult:
    """Simule un deck NEC brut (par exemple un fichier .nec de 4NEC2).

    Lève ModelRejected (sous-classe d'EngineError) si onec ne renvoie aucune fréquence
    calculée : c'est le cas quand il refuse le modèle (erreur de géométrie, carte invalide…).
    Sans cela, l'appelant recevrait un résultat vide sans explication.
    """
    output = run_onec(deck, timeout=timeout)
    result = parse_output(output)
    if not result.frequencies:
        tail = [ln.strip() for ln in output.splitlines() if ln.strip()][-5:]
        detail = " / ".join(tail) if tail else "sortie vide"
        raise ModelRejected(f"onec n'a calculé aucune fréquence ({detail})")
    return result


def simulate(model: AntennaModel, timeout: float = 120.0) -> SimulationResult:
    """Simule un AntennaModel.

    onec calcule à la fréquence exacte mais n'en imprime que 5 chiffres significatifs
    (432.1745 MHz → « 4.3217E+02 ») : on reprend donc les fréquences demandées.
    """
    result = simulate_deck(model.to_deck(), timeout=timeout)
    requested = model.sweep.frequencies
    if len(requested) == len(result.frequencies):
        for fr, f in zip(result.frequencies, requested, strict=True):
            fr.frequency_mhz = f
    return result
