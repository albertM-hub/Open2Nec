"""Parseur de la sortie texte de onec (format NEC-2 « original »).

Testé sur une sortie réelle (voir core/tests). Le parseur découpe la sortie en blocs
par fréquence, puis lit la table « ANTENNA INPUT PARAMETERS » et le diagramme.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

_FREQ_RE = re.compile(r"FREQUENCY=\s*([0-9.]+E[+-]?\d+)\s*MHZ", re.IGNORECASE)
_NUM = r"[-+]?\d+\.\d+E[+-]\d+"
# TAG SEG V_re V_im I_re I_im Z_re Z_im Y_re Y_im POWER
_INPUT_RE = re.compile(
    rf"^\s*(\d+)\s+(\d+)\s+({_NUM})\s*({_NUM})\s*({_NUM})\s*({_NUM})\s*({_NUM})\s*({_NUM})"
    rf"\s*({_NUM})\s*({_NUM})\s*({_NUM})\s*$"
)
_PATTERN_RE = re.compile(
    r"^\s*(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)"
)


@dataclass
class FeedpointResult:
    tag: int
    segment: int
    impedance: complex  # ohms

    def swr(self, z0: float = 50.0) -> float:
        """ROS par rapport à une impédance de référence z0 (50 Ω par défaut)."""
        gamma = abs((self.impedance - z0) / (self.impedance + z0))
        return math.inf if gamma >= 1 else (1 + gamma) / (1 - gamma)


@dataclass
class PatternPoint:
    theta: float  # degrés (0 = zénith)
    phi: float  # degrés
    gain_total_db: float


@dataclass
class FrequencyResult:
    frequency_mhz: float
    feedpoints: list[FeedpointResult] = field(default_factory=list)
    pattern: list[PatternPoint] = field(default_factory=list)

    @property
    def max_gain_db(self) -> float | None:
        return max((p.gain_total_db for p in self.pattern), default=None)


@dataclass
class SimulationResult:
    frequencies: list[FrequencyResult] = field(default_factory=list)
    raw_output: str = ""


def parse_output(text: str) -> SimulationResult:
    """Découpe la sortie onec en blocs par fréquence et extrait impédances et diagramme."""
    lines = text.splitlines()
    result = SimulationResult(raw_output=text)
    current: FrequencyResult | None = None
    in_pattern = False

    for line in lines:
        m = _FREQ_RE.search(line)
        if m:
            current = FrequencyResult(frequency_mhz=float(m.group(1)))
            result.frequencies.append(current)
            in_pattern = False
            continue
        if current is None:
            continue

        if "ANTENNA INPUT PARAMETERS" in line:
            in_pattern = False
            continue
        if "RADIATION PATTERNS" in line:
            in_pattern = True
            continue

        m = _INPUT_RE.match(line)
        if m and not in_pattern:
            current.feedpoints.append(
                FeedpointResult(
                    tag=int(m.group(1)),
                    segment=int(m.group(2)),
                    impedance=complex(float(m.group(7)), float(m.group(8))),
                )
            )
            continue

        if in_pattern:
            m = _PATTERN_RE.match(line)
            if m:
                # colonnes : THETA PHI VERT HOR TOTAL
                current.pattern.append(
                    PatternPoint(
                        theta=float(m.group(1)),
                        phi=float(m.group(2)),
                        gain_total_db=float(m.group(5)),
                    )
                )
    return result
