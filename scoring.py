"""Scoring formulas: IPF GL and DOTS points, 1 rep max estimates, and meet attempts."""

import math

LB_PER_KG = 2.20462

# IPF GL coefficients (A, B, C) for classic (raw) powerlifting
MALE = (1199.72839, 1025.18162, 0.00921)
FEMALE = (610.32796, 1045.59282, 0.03048)

# The IPF formula is not defined below this bodyweight (kg)
MIN_BW = 35

# DOTS coefficients (a, b, c, d, e) for a·bw⁴ + b·bw³ + c·bw² + d·bw + e, and the bodyweight range they hold for
DOTS_MALE = (-0.0000010930, 0.0007391293, -0.1918759221, 24.0900756, -307.75076)
DOTS_FEMALE = (-0.0000010706, 0.0005158568, -0.1126655495, 13.6175032, -57.96288)
DOTS_BW = {"male": (40, 210), "female": (40, 150)}

FORMULAS = {"gl": "IPF GL", "dots": "DOTS"}


def to_kg(value: float, unit: str) -> float:
    return value / LB_PER_KG if unit == "lb" else value


def from_kg(value_kg: float, unit: str) -> float:
    return value_kg * LB_PER_KG if unit == "lb" else value_kg


def gl_points(total_kg: float, bodyweight_kg: float, sex: str) -> float:
    return total_kg * 100 / _gl_denominator(bodyweight_kg, sex)


def _gl_denominator(bodyweight_kg: float, sex: str) -> float:
    a, b, c = MALE if sex == "male" else FEMALE
    bw = max(bodyweight_kg, MIN_BW)
    return a - b * math.exp(-c * bw)


def dots_points(total_kg: float, bodyweight_kg: float, sex: str) -> float:
    return total_kg * 500 / _dots_denominator(bodyweight_kg, sex)


def _dots_denominator(bodyweight_kg: float, sex: str) -> float:
    a, b, c, d, e = DOTS_MALE if sex == "male" else DOTS_FEMALE
    low, high = DOTS_BW[sex]
    bw = min(max(bodyweight_kg, low), high)
    return a * bw**4 + b * bw**3 + c * bw**2 + d * bw + e


def points(total_kg: float, bodyweight_kg: float, sex: str, formula: str = "gl") -> float:
    """Score a total with the chosen formula ("gl" or "dots")."""
    if formula == "dots":
        return dots_points(total_kg, bodyweight_kg, sex)
    return gl_points(total_kg, bodyweight_kg, sex)


def total_for_points(score: float, bodyweight_kg: float, sex: str, formula: str = "gl") -> float:
    """The total (kg) that gets this score at this bodyweight."""
    if formula == "dots":
        return score * _dots_denominator(bodyweight_kg, sex) / 500
    return score * _gl_denominator(bodyweight_kg, sex) / 100


# Epley gets shaky past this many reps
MAX_REPS = 20


def epley(weight: float, reps: int) -> float:
    """Estimated 1 rep max from a set. A single is already a max."""
    return weight if reps == 1 else weight * (1 + reps / 30)


# Common 1 rep max formulas, for /1rm. Each takes (weight, reps) with reps > 1.
ONE_RM_FORMULAS = {
    "Epley": lambda w, r: w * (1 + r / 30),
    "Brzycki": lambda w, r: w * 36 / (37 - r),
    "Lander": lambda w, r: w * 100 / (101.3 - 2.67123 * r),
    "Lombardi": lambda w, r: w * r**0.10,
    "Mayhew": lambda w, r: w * 100 / (52.2 + 41.9 * math.exp(-0.055 * r)),
    "O'Conner": lambda w, r: w * (1 + r / 40),
    "Wathan": lambda w, r: w * 100 / (48.8 + 53.8 * math.exp(-0.075 * r)),
}


def one_rm_estimates(weight: float, reps: int) -> dict:
    """{formula name: estimated max}. A single is already a max."""
    return {name: weight if reps == 1 else f(weight, reps) for name, f in ONE_RM_FORMULAS.items()}


# Meet attempts as a share of the max you're going for: a safe opener, a solid second, then the target
ATTEMPT_PERCENTS = (0.91, 0.96, 1.00)
# Plates go up in 2.5 kg at meets, 5 lb in most gyms
INCREMENT = {"kg": 2.5, "lb": 5}


def attempts(target: float, unit: str) -> list:
    """1st, 2nd, and 3rd attempts for a target max, in the same unit, rounded to loadable weights."""
    step = INCREMENT[unit]
    opener = math.floor(target * ATTEMPT_PERCENTS[0] / step) * step  # round the opener down, never up
    second = round(target * ATTEMPT_PERCENTS[1] / step) * step
    third = round(target * ATTEMPT_PERCENTS[2] / step) * step
    return [opener, second, third]


# Rank tiers: (name, emoji, embed color, minimum score per formula).
# DOTS runs about 4.9x GL across bodyweights, so the floors line up.
TIERS = (
    ("Bronze", "🟤", 0xA0632B, {"gl": 0, "dots": 0}),
    ("Silver", "⚪", 0xA8B0B8, {"gl": 45, "dots": 225}),
    ("Gold", "🟡", 0xE5B53A, {"gl": 60, "dots": 300}),
    ("Platinum", "💠", 0x4FC1C9, {"gl": 70, "dots": 350}),
    ("Diamond", "💎", 0x5B8DEF, {"gl": 80, "dots": 400}),
    ("Grandmaster", "👑", 0xC0392B, {"gl": 90, "dots": 450}),
    ("Ascender", "🌌", 0x9B59B6, {"gl": 100, "dots": 500}),
)


def tier(score: float, formula: str = "gl"):
    """Returns (tier, next tier or None) for a score. Each tier's floor is (name, emoji, color, floor)."""
    floors = [(name, emoji, color, mins[formula]) for name, emoji, color, mins in TIERS]
    index = max(i for i, t in enumerate(floors) if score >= t[3])
    return floors[index], floors[index + 1] if index + 1 < len(floors) else None
