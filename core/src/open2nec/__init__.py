"""Open2Nec : bibliothèque de simulation d'antennes NEC-2 (moteur : OpenNEC / onec)."""

from .model import (
    AntennaModel,
    Excitation,
    FrequencySweep,
    Ground,
    RadiationGrid,
    Symbol,
    Wire,
)
from .results import FrequencyResult, SimulationResult
from .simulate import simulate, simulate_deck

__all__ = [
    "AntennaModel",
    "Excitation",
    "FrequencyResult",
    "FrequencySweep",
    "Ground",
    "RadiationGrid",
    "SimulationResult",
    "Symbol",
    "Wire",
    "simulate",
    "simulate_deck",
]
__version__ = "0.1.0"
