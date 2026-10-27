"""IPF weight class rankings built from the OpenIPF bulk CSV.

Run `python ipf_data.py` to download the latest data and rebuild ipf_stats.json.
The bot only reads the JSON, so rerun this whenever you want fresher rankings.
"""

import csv
import io
import json
import os
import urllib.request
import zipfile
from bisect import bisect_left, bisect_right

DATA_URL = "https://openpowerlifting.gitlab.io/opl-csv/files/openipf-latest.zip"
ZIP_PATH = os.path.join("data", "openipf-latest.zip")
STATS_PATH = os.path.join("data", "ipf_stats.json")

CATEGORIES = ("total", "squat", "bench", "deadlift")
CSV_COLUMNS = {
    "total": "TotalKg",
    "squat": "Best3SquatKg",
    "bench": "Best3BenchKg",
    "deadlift": "Best3DeadliftKg",
}

# Current IPF weight classes: upper limit in kg, or None for the open (+) class
WEIGHT_CLASSES = {
    "male": (59, 66, 74, 83, 93, 105, 120, None),
    "female": (47, 52, 57, 63, 69, 76, 84, None),
}
TOP_N = 10


def weight_class(bodyweight_kg: float, sex: str) -> str:
    """Label of the current IPF class for a bodyweight, e.g. '83' or '120+'."""
    limits = WEIGHT_CLASSES[sex]
    for limit in limits[:-1]:
        if bodyweight_kg <= limit:
            return str(limit)
    return f"{limits[-2]}+"


def _float(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


def build():
    os.makedirs("data", exist_ok=True)
    print(f"Downloading {DATA_URL} ...")
    urllib.request.urlretrieve(DATA_URL, ZIP_PATH)

    # Each lifter's best result per (sex, class), counted once even if they competed many times
    # best[(sex, class)][name] = {"country": str, "total": kg, "squat": kg, ...}
    best = {}
    with zipfile.ZipFile(ZIP_PATH) as z:
        csv_name = next(n for n in z.namelist() if n.endswith(".csv"))
        with z.open(csv_name) as raw:
            for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8")):
                # Raw full-power meets only, so totals and single lifts compare like for like
                if row["Equipment"] != "Raw" or row["Event"] != "SBD" or row["Sex"] not in ("M", "F"):
                    continue
                bodyweight = _float(row["BodyweightKg"])
                if bodyweight <= 0:
                    continue
                sex = "male" if row["Sex"] == "M" else "female"
                # Bucket by bodyweight so old meets map onto today's classes
                lifter = best.setdefault((sex, weight_class(bodyweight, sex)), {}).setdefault(
                    row["Name"], {"country": row["Country"]}
                )
                for category, column in CSV_COLUMNS.items():
                    kg = _float(row[column])  # failed lifts are negative, DQs are blank
                    if kg > lifter.get(category, 0):
                        lifter[category] = kg
    os.remove(ZIP_PATH)  # ~70 MB and only needed for this build

    stats = {}
    for (sex, wc), lifters in best.items():
        entry = stats.setdefault(sex, {}).setdefault(wc, {})
        for category in CATEGORIES:
            ranked = sorted(
                ((data[category], name, data["country"]) for name, data in lifters.items() if category in data),
                reverse=True,
            )
            entry[category] = {
                "values": [kg for kg, _, _ in reversed(ranked)],  # ascending, for bisect
                "top": [[name, country, kg] for kg, name, country in ranked[:TOP_N]],
            }

    with open(STATS_PATH, "w", encoding="utf-8") as f:
        json.dump(stats, f)
    print(f"Wrote {STATS_PATH}")


_stats = None


def load():
    """Load the prebuilt rankings, or None if ipf_data.py hasn't been run yet."""
    global _stats
    if _stats is None and os.path.exists(STATS_PATH):
        with open(STATS_PATH, encoding="utf-8") as f:
            _stats = json.load(f)
    return _stats


def compare(kg: float, values: list) -> tuple:
    """Returns (percent of lifters you beat, your would-be rank, lifters in the class)."""
    beaten = bisect_left(values, kg)
    rank = len(values) - bisect_right(values, kg) + 1
    return 100 * beaten / len(values), rank, len(values)


if __name__ == "__main__":
    build()
