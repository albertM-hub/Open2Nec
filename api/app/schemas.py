"""Schémas Pydantic de l'API (contrat JSON avec le front). Aucune logique de calcul ici."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from open2nec.cards import parse_card
from open2nec.importer import MAX_IMPORT_BYTES
from open2nec.optimize import DEFAULT_MAX_EVALUATIONS
from open2nec.symbols import as_value, formula_error

# Limites de calcul (au-delà : réponse 422). Ordres de grandeur sur un PC courant :
# - la matrice NEC fait N² nombres complexes : 2000 segments ≈ 64 Mo, quelques secondes ;
# - chaque point de diagramme est calculé et renvoyé pour chaque fréquence : on borne le produit
#   (50 000 = grille par défaut de 5°, 37 × 73 points, sur 18 fréquences).
MAX_SEGMENTS_TOTAL = 2000
MAX_FREQUENCIES = 201
MAX_PATTERN_POINTS_TOTAL = 50_000
# Un fichier importé peut découper un arc ou une hélice en fils d'un segment : on admet autant
# de fils que de segments
MAX_WIRES = MAX_SEGMENTS_TOTAL
MAX_EXTRA_CARDS = 500
MAX_SYMBOLS = 200
MAX_OPTIMIZE_EVALUATIONS = 2000
MAX_VARIABLES = 20

# Case d'un fil : un nombre, ou une formule (« -L/2 ») calculée par onec. Une formule ne passe
# que si sa forme est sûre (formula_error) : aucune ligne arbitraire ne doit parvenir à onec.
Value = float | str


def _check_value(v: float | str) -> float | str:
    v = as_value(v)
    if isinstance(v, str) and (err := formula_error(v)):
        raise ValueError(f"formule « {v[:40]} » : {err}")
    return v


class WireIn(BaseModel):
    tag: int = Field(ge=1)
    segments: int = Field(ge=1, le=MAX_SEGMENTS_TOTAL)
    start: tuple[Value, Value, Value]
    end: tuple[Value, Value, Value]
    radius: Value

    @field_validator("start", "end")
    @classmethod
    def check_point(cls, p: tuple[Value, Value, Value]) -> tuple[Value, Value, Value]:
        return tuple(_check_value(v) for v in p)  # type: ignore[return-value]

    @field_validator("radius")
    @classmethod
    def check_radius(cls, r: Value) -> Value:
        r = _check_value(r)
        if isinstance(r, float) and r <= 0:
            raise ValueError("le rayon doit être positif")
        return r


class SymbolIn(BaseModel):
    """Symbole 4NEC2 (carte SY). Règles de nom et d'ordre : contrôle du modèle (core)."""

    name: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    formula: str = Field(min_length=1, max_length=200)

    @field_validator("formula")
    @classmethod
    def check_formula(cls, f: str) -> str:
        _check_value(f)
        return f.strip()  # gardée telle que saisie (« 9 » reste « 9 »)


class ExcitationIn(BaseModel):
    tag: int = Field(ge=1)
    segment: int = Field(ge=1)
    voltage_re: float = 1.0
    voltage_im: float = 0.0
    kind: Literal[0, 5] = 0  # EX 0 (courant) ou EX 5, conservé d'un fichier importé


class GroundIn(BaseModel):
    kind: str = Field(default="free", pattern="^(free|perfect|real)$")
    epsilon_r: float = Field(default=13.0, ge=1)
    conductivity: float = Field(default=0.005, ge=0)  # S/m
    exact: bool = True  # sol réel : Sommerfeld (GN 2) ou approché (GN 0)


class SweepIn(BaseModel):
    start_mhz: float = Field(gt=0)
    step_mhz: float = Field(default=0.0, ge=0)
    count: int = Field(default=1, ge=1, le=MAX_FREQUENCIES)


class PatternIn(BaseModel):
    n_theta: int = Field(default=37, ge=1, le=181)  # 1° de pas sur 0–180° au plus fin
    n_phi: int = Field(default=73, ge=1, le=361)
    d_theta: float = Field(default=5.0, ge=0, le=180)
    d_phi: float = Field(default=5.0, ge=0, le=360)


class GeometryIn(BaseModel):
    """Géométrie commune aux deux calculs : fils, sources, sol."""

    wires: list[WireIn] = Field(min_length=1, max_length=MAX_WIRES)
    symbols: list[SymbolIn] = Field(default=[], max_length=MAX_SYMBOLS)
    excitations: list[ExcitationIn] = Field(max_length=50)
    ground: GroundIn = GroundIn()
    # Cartes conservées d'un fichier importé (LD, TL, NT, EX, EK, KH), en valeurs numériques.
    # Contrôle strict : aucune ligne arbitraire ne doit parvenir à onec.
    extra_cards: list[str] = Field(default=[], max_length=MAX_EXTRA_CARDS)

    @field_validator("extra_cards")
    @classmethod
    def check_extra_cards(cls, cards: list[str]) -> list[str]:
        return [parse_card(c).text() for c in cards]  # ValueError → 422

    @model_validator(mode="after")
    def check_segments(self) -> "GeometryIn":
        total = sum(w.segments for w in self.wires)
        if total > MAX_SEGMENTS_TOTAL:
            raise ValueError(
                f"modèle trop lourd : {total} segments au total (maximum {MAX_SEGMENTS_TOTAL})"
            )
        return self


class DirectionIn(BaseModel):
    """Direction (degrés NEC : θ depuis le zénith, φ depuis +X) du gain suivi pendant le balayage."""

    theta: float = Field(ge=0, le=180)
    phi: float = Field(ge=-360, le=720)


class ModelIn(GeometryIn):
    """Balayage en fréquence (POST /simulate)."""

    sweep: SweepIn
    pattern: PatternIn | None = None
    z0: float = Field(default=50.0, gt=0, le=10_000)  # impédance de référence du ROS (Ω)
    # Gain avant (direction) et arrière (φ + 180°) à chaque fréquence ; incompatible avec pattern
    direction: DirectionIn | None = None

    @model_validator(mode="after")
    def check_pattern_budget(self) -> "ModelIn":
        if self.pattern and self.direction:
            raise ValueError("pattern et direction s'excluent : choisir l'un ou l'autre")
        if self.pattern:
            points = self.pattern.n_theta * self.pattern.n_phi * self.sweep.count
            if points > MAX_PATTERN_POINTS_TOTAL:
                raise ValueError(
                    f"diagramme trop lourd : {points} points (points de la grille × fréquences, "
                    f"maximum {MAX_PATTERN_POINTS_TOTAL}) ; réduire la grille ou le nombre de "
                    "fréquences"
                )
        return self


class PatternRequest(GeometryIn):
    """Diagramme à une fréquence (POST /pattern). La grille est fixée par le core."""

    frequency_mhz: float = Field(gt=0, le=100_000)


class FeedpointOut(BaseModel):
    tag: int
    segment: int
    r: float
    x: float
    swr_50: float | None  # None si infini


class PatternPointOut(BaseModel):
    theta: float
    phi: float
    gain_db: float


class FrequencyOut(BaseModel):
    frequency_mhz: float
    feedpoints: list[FeedpointOut]
    max_gain_db: float | None
    pattern: list[PatternPointOut]


class SweepPointOut(BaseModel):
    frequency_mhz: float
    r: float
    x: float
    swr: float | None  # par rapport à z0 ; None si infini
    gamma_re: float  # coefficient de réflexion (abaque de Smith)
    gamma_im: float
    gain_db: float | None  # dans la direction demandée
    gain_back_db: float | None  # direction opposée en azimut
    front_to_back_db: float | None


class BandOut(BaseModel):
    threshold: float  # ROS
    low_mhz: float
    high_mhz: float
    low_open: bool  # encore sous le seuil au début du balayage
    high_open: bool  # encore sous le seuil à la fin du balayage
    width_khz: float


class SweepSummaryOut(BaseModel):
    z0: float
    min_swr: float | None
    min_swr_mhz: float | None
    resonances: list[float]
    bands: list[BandOut]


class SimulationOut(BaseModel):
    frequencies: list[FrequencyOut]  # résultat brut : toutes les sources, diagramme éventuel
    points: list[SweepPointOut]  # premier point d'alimentation, analysé pour z0
    summary: SweepSummaryOut
    warnings: list[str]


class CutPointOut(BaseModel):
    angle: (
        float  # degrés (azimut, ou angle de la coupe verticale : 0 avant, 90 zénith, 180 arrière)
    )
    gain_db: float  # dBi ; -999.99 = pas de rayonnement dans cette direction


class PatternSummaryOut(BaseModel):
    max_gain_db: float
    max_phi: float  # azimut du maximum, degrés depuis +X
    max_theta: float  # θ NEC du maximum (depuis le zénith), à renvoyer tel quel à /simulate
    takeoff_deg: float  # élévation du maximum
    front_to_back_db: float | None  # None si l'arrière ne rayonne pas du tout
    azimuth_cut: list[CutPointOut]
    elevation_cut: list[CutPointOut]


class PatternOut(BaseModel):
    frequency_mhz: float
    feedpoints: list[FeedpointOut]
    summary: PatternSummaryOut | None  # None si onec ne renvoie aucun gain
    warnings: list[str]


class PresetOut(BaseModel):
    id: str
    name: str
    description: str
    design_mhz: float
    z0: float  # impédance de référence du ROS proposée pour ce modèle (Ω)
    model: ModelIn


class ImportIn(BaseModel):
    filename: str = Field(default="", max_length=255)
    content: str = Field(min_length=1, max_length=MAX_IMPORT_BYTES)


class ExtraCardOut(BaseModel):
    text: str
    description: str


class ImportOut(BaseModel):
    model: ModelIn
    frequency_mhz: float  # fréquence proposée pour le diagramme
    extra: list[ExtraCardOut]  # cartes conservées, décrites en clair
    dropped: list[str]  # cartes écartées
    notes: list[str]


class ValidateIn(GeometryIn):
    """Contrôle du modèle (POST /validate) ; λ prise à la fréquence la plus haute utilisée."""

    max_frequency_mhz: float = Field(gt=0, le=100_000)


class IssueOut(BaseModel):
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    wires: list[int]  # rangs dans `wires` (= lignes du tableau, à partir de 0)
    symbols: list[int] = []  # rangs dans `symbols`


class ResolvedWireOut(BaseModel):
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    radius: float


class ValidateOut(BaseModel):
    issues: list[IssueOut]
    # Valeurs calculées par onec (formules) ; vides si le modèle n'a pas de formule ou si une
    # erreur de symbole empêche le calcul
    symbol_values: dict[str, float]
    wires: list[ResolvedWireOut]  # fils en nombres (vue 3D) ; vide en cas d'erreur de formule


# --- Optimiseur (jalon 6) ---------------------------------------------------------------------


class VariableIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    low: float
    high: float


class ObjectiveIn(BaseModel):
    band_low_mhz: float = Field(gt=0, le=100_000)
    band_high_mhz: float = Field(gt=0, le=100_000)
    n_points: int = Field(default=3, ge=1, le=21)
    z0: float = Field(default=50.0, gt=0, le=10_000)
    direction: DirectionIn | None = None
    w_swr: float = Field(default=100.0, ge=0, le=100)  # poids en %
    w_gain: float = Field(default=0.0, ge=0, le=100)
    w_fb: float = Field(default=0.0, ge=0, le=100)
    fb_cap_db: float = Field(default=30.0, gt=0, le=60)


class OptimizeIn(GeometryIn):
    variables: list[VariableIn] = Field(min_length=1, max_length=MAX_VARIABLES)
    objective: ObjectiveIn
    max_evaluations: int = Field(default=DEFAULT_MAX_EVALUATIONS, ge=1, le=MAX_OPTIMIZE_EVALUATIONS)


class OptimizeStarted(BaseModel):
    id: str


class CriteriaOut(BaseModel):
    swr_max: float | None  # None si infini
    swr_loss_db: float
    gain_db: float | None
    fb_db: float | None


class TrialOut(BaseModel):
    n: int  # 0 = modèle de départ
    values: dict[str, float]
    score: float
    criteria: CriteriaOut | None
    error: str | None


class OptimizeStatus(BaseModel):
    id: str
    state: Literal["running", "done", "failed"]
    reason: str | None  # fin : "converged", "max_evaluations", "stopped"
    error: str | None  # état "failed" : message
    evaluations: int
    max_evaluations: int
    start: TrialOut | None
    best: TrialOut | None
