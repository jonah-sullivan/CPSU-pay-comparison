"""Box plots of maximum pay from 2026 to March 2029 for each agency.

Reads the CSV written by extract_current_and_march_2029_pay.py and saves one figure
per agency: for each pay grade, one box per year of all agencies' pay, with the
selected agency highlighted on each.
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import pandas as pd
from scipy.stats import percentileofscore

SCRIPT_DIR = Path(__file__).resolve().parent
INPUT_CSV = SCRIPT_DIR / "aps_pay_2026_2029.csv"
OUTPUT_DIR = SCRIPT_DIR / "plots"

GRADES = ["APS1", "APS2", "APS3", "APS4", "APS5", "APS6", "EL1", "EL2"]
# (CSV column suffix, axis label, colour) - one blue ramp, light to dark over time
PERIODS = [
    ("2026", "Mar 2026", "#86b6ef"),
    ("2027", "Mar 2027", "#3987e5"),
    ("2028", "Mar 2028", "#256abf"),
    ("2029", "Mar 2029", "#104281"),
]
AGENCY_COLOR = "#d62728"
TEXT_COLOR = "#333333"
JITTER_WIDTH = 0.06


CPSU_PAY_RISE_RATE = 5.0  # % a year, for comparison
CPSU_PAY_RISE_COLOR = "red"


# helper function to format percentile as ordinal (e.g., 1st, 2nd, 3rd, etc.)
def format_ordinal(n: int) -> str:
    n_abs = abs(n)
    if 11 <= (n_abs % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n_abs % 10, "th")
    return f"{n}{suffix}"


def whisker_range(values: np.ndarray) -> tuple[float, float]:
    """Return the 1.5*IQR whisker extent, matching matplotlib's boxplot."""
    q1, q3 = np.percentile(values, [25, 75])
    iqr = q3 - q1
    within = values[(values >= q1 - 1.5 * iqr) & (values <= q3 + 1.5 * iqr)]
    return within.min(), within.max()


def project(base: float, rates: list[float]) -> list[float]:
    """Compound base by each annual % rate, returning base plus one value per rate."""
    values = [base]
    for rate in rates:
        values.append(values[-1] * (1 + rate / 100))
    return values


def plot_agency(df: pd.DataFrame, agency: str, long_name: str) -> plt.Figure:
    agency_row = df.loc[agency]
    rng = np.random.default_rng(42)
    fig, axes = plt.subplots(2, 4, figsize=(20, 9))

    for grade, ax in zip(GRADES, axes.ravel()):
        low, high = np.inf, -np.inf
        tick_labels = []
        for x, (year, label, color) in enumerate(PERIODS, start=1):
            values = df[f"{grade}-{year}"].dropna().to_numpy()
            if values.size == 0:
                tick_labels.append(label)
                continue

            # scatter points for all agencies, then the box on top
            x_all = x + rng.uniform(-JITTER_WIDTH, JITTER_WIDTH, size=values.size)
            ax.plot(x_all, values, "o", color=color, alpha=0.4, markersize=4)
            ax.boxplot(
                values,
                positions=[x],
                widths=0.6,
                showfliers=False,
                medianprops={"color": TEXT_COLOR, "linewidth": 1.5},
            )
            whisker_low, whisker_high = whisker_range(values)
            low, high = min(low, whisker_low), max(high, whisker_high)

            # highlight this agency and its percentile rank
            agency_value = agency_row[f"{grade}-{year}"]
            if pd.isna(agency_value):
                pct_text = "n/a"
            else:
                ax.plot(
                    x,
                    agency_value,
                    marker="D",
                    color=AGENCY_COLOR,
                    markeredgecolor="white",
                    markersize=8,
                    zorder=5,
                )
                pct = percentileofscore(values, agency_value, kind="strict")
                pct_text = format_ordinal(round(pct))
                low, high = min(low, agency_value), max(high, agency_value)
            tick_labels.append(f"{label}\n{pct_text}")

        # project this agency's current pay forward by a flat rise
        base = agency_row[f"{grade}-{PERIODS[0][0]}"]
        if not pd.isna(base):
            later_years = [year for year, _, _ in PERIODS[1:]]
            xs = range(1, len(PERIODS) + 1)
            for rates, color, linestyle in (
                ([CPSU_PAY_RISE_RATE] * len(later_years), CPSU_PAY_RISE_COLOR, "-"),
            ):
                projected = project(base, rates)
                ax.plot(
                    xs,
                    projected,
                    color=color,
                    linestyle=linestyle,
                    linewidth=2,
                    marker="o",
                    markersize=3,
                    zorder=4,
                )
                low, high = min(low, min(projected)), max(high, max(projected))

        if np.isfinite(low):
            pad = 0.05 * (high - low) if high > low else high * 0.05
            ax.set_ylim(low - pad, high + pad)

        ax.set_xlim(0.4, len(PERIODS) + 0.6)
        ax.set_xticks(
            range(1, len(PERIODS) + 1), tick_labels, fontsize=9, color=TEXT_COLOR
        )
        ax.set_title(grade, fontsize=12, fontweight="bold")
        ax.grid(axis="y", alpha=0.5)
        ax.yaxis.set_major_formatter(mtick.StrMethodFormatter("${x:,.0f}"))

    fig.supylabel("Maximum Annual Salary ($)")
    fig.suptitle(
        f"{long_name} ({agency})\n"
        "Maximum Pay (top increment) for each Pay Classification, "
        "13 March 2026 to March 2029\n"
        "according to the APSC Pay Calculator, with CPSU claim of 5% a year for comparison\n"
        f"Relative to all APS Employers, with {agency}'s percentile under each year",
        fontsize=15,
        fontweight="bold",
    )
    fig.legend(
        handles=[
            plt.Line2D(
                [], [], marker="D", color=AGENCY_COLOR, linestyle="", label=agency
            ),
            plt.Line2D(
                [],
                [],
                marker="o",
                color=PERIODS[1][2],
                alpha=0.6,
                linestyle="",
                label="All agencies (one dot per agency)",
            ),
            plt.Line2D(
                [],
                [],
                color=CPSU_PAY_RISE_COLOR,
                linestyle="-",
                linewidth=2,
                label=f"{agency} current pay + CPSU claim of {CPSU_PAY_RISE_RATE:g}% a year",
            ),
        ],
        loc="lower center",
        ncol=4,
        frameon=False,
        bbox_to_anchor=(0.5, -0.03),
    )
    fig.tight_layout()
    return fig


def main():
    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig").set_index("Agency")
    required = ["Agency name"] + [
        f"{grade}-{year}" for grade in GRADES for year, _, _ in PERIODS
    ]
    missing = [column for column in required if column not in df.columns]
    if missing:
        sys.exit(
            f"{INPUT_CSV.name} is missing columns {missing[:4]}...; "
            "re-run extract_current_and_march_2029_pay.py first"
        )
    OUTPUT_DIR.mkdir(exist_ok=True)

    for agency in df.index:
        long_name = df.loc[agency, "Agency name"]
        if pd.isna(long_name):
            long_name = agency
        print(f"Processing Employer: {agency} - {long_name}")
        try:
            fig = plot_agency(df, agency, long_name)
            fig.savefig(
                OUTPUT_DIR / f"{agency}_2026_to_2029_boxplots.png",
                bbox_inches="tight",
                dpi=300,
            )
            plt.close(fig)
        except Exception as e:  # noqa: BLE001 - keep going so one bad agency doesn't stop the batch
            print(f"Error processing employer {agency}: {e}")


if __name__ == "__main__":
    main()
