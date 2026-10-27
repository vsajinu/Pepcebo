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
