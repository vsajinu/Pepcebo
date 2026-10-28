"""IPF GL points: compares powerlifting totals across bodyweights."""

import math

LB_PER_KG = 2.20462

# IPF GL coefficients (A, B, C) for classic (raw) powerlifting
MALE = (1199.72839, 1025.18162, 0.00921)
FEMALE = (610.32796, 1045.59282, 0.03048)

# The IPF formula is not defined below this bodyweight (kg)
MIN_BW = 35


def to_kg(value: float, unit: str) -> float:
    return value / LB_PER_KG if unit == "lb" else value


def from_kg(value_kg: float, unit: str) -> float:
    return value_kg * LB_PER_KG if unit == "lb" else value_kg


def gl_points(total_kg: float, bodyweight_kg: float, sex: str) -> float:
    a, b, c = MALE if sex == "male" else FEMALE
    bw = max(bodyweight_kg, MIN_BW)
    return total_kg * 100 / (a - b * math.exp(-c * bw))


def total_for_gl(gl: float, bodyweight_kg: float, sex: str) -> float:
    """The total (kg) that scores the given GL at this bodyweight."""
    a, b, c = MALE if sex == "male" else FEMALE
    bw = max(bodyweight_kg, MIN_BW)
    return gl * (a - b * math.exp(-c * bw)) / 100


# Epley gets shaky past this many reps
MAX_REPS = 20


def epley(weight: float, reps: int) -> float:
    """Estimated 1 rep max from a set. A single is already a max."""
    return weight if reps == 1 else weight * (1 + reps / 30)


# Rank tiers by GL: (name, emoji, embed color, minimum GL)
TIERS = (
    ("Bronze", "🟤", 0xA0632B, 0),
    ("Silver", "⚪", 0xA8B0B8, 45),
    ("Gold", "🟡", 0xE5B53A, 60),
    ("Platinum", "💠", 0x4FC1C9, 70),
    ("Diamond", "💎", 0x5B8DEF, 80),
    ("Grandmaster", "👑", 0xC0392B, 90),
    ("Ascender", "🌌", 0x9B59B6, 100),
)


def tier(gl: float):
    """Returns (tier, next tier or None) for a GL score."""
    index = max(i for i, t in enumerate(TIERS) if gl >= t[3])
    return TIERS[index], TIERS[index + 1] if index + 1 < len(TIERS) else None
