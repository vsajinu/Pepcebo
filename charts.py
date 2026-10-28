"""Progress charts for /history, rendered with matplotlib to a PNG."""

import io
from datetime import datetime, timedelta

import matplotlib

matplotlib.use("Agg")  # no display on the bot's machine
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

# Dark surface to sit on Discord's dark theme
SURFACE = "#1a1a19"
TEXT = "#f0efec"
TEXT_MUTED = "#c3c2b7"
GRID = "#3a3a38"
TRUE_COLOR = "#3987e5"
ESTIMATE_COLOR = "#d95926"


def history_chart(title: str, unit: str, singles, estimates) -> io.BytesIO:
    """singles and estimates are [(iso timestamp, weight in unit)], oldest first."""
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    series = (
        (singles, "Logged 1RM", TRUE_COLOR, "-", TRUE_COLOR),
        (estimates, "Estimated 1RM (Epley)", ESTIMATE_COLOR, "--", SURFACE),
    )
    best = None
    all_dates = []
    for points, label, color, style, fill in series:
        if not points:
            continue
        dates = [datetime.fromisoformat(t) for t, _ in points]
        weights = [w for _, w in points]
        all_dates += dates
        ax.plot(dates, weights, style, color=color, linewidth=2, marker="o", markersize=7,
                markerfacecolor=fill, markeredgecolor=color, markeredgewidth=2, label=label)
        top = max(range(len(weights)), key=weights.__getitem__)
        if best is None or weights[top] > best[1]:
            best = (dates[top], weights[top])

    # Label only the best point
    if best:
        ax.annotate(f"{best[1]:.1f} {unit}", best, textcoords="offset points", xytext=(0, 10),
                    ha="center", color=TEXT, fontsize=10, fontweight="bold")

    ax.set_title(title, color=TEXT, fontsize=14, loc="left", pad=12)
    ax.set_ylabel(unit, color=TEXT_MUTED)
    ax.tick_params(colors=TEXT_MUTED, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=8))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.margins(x=0.05, y=0.15)
    if max(all_dates) - min(all_dates) < timedelta(days=2):  # too short a span for date ticks
        ax.set_xlim(min(all_dates) - timedelta(days=3), max(all_dates) + timedelta(days=3))
    ax.legend(loc="lower right", frameon=False, labelcolor=TEXT_MUTED)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=SURFACE)
    plt.close(fig)
    buf.seek(0)
    return buf
