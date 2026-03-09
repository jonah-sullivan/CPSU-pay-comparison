import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
from scipy.stats import percentileofscore
from matplotlib.lines import Line2D

# helper function to format percentile as ordinal (e.g., 1st, 2nd, 3rd, etc.)
def format_ordinal(n: int) -> str:
    n_abs = abs(n)
    if 11 <= (n_abs % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n_abs % 10, "th")
    return f"{n}{suffix}"

## Load and process data
df_original = pd.read_excel("CompiledData.xlsx", sheet_name="Data", engine="openpyxl")

# --- Columns to include ---
max_pay_columns = ['APS1_maximum', 'APS2_maximum', 'APS3_maximum', 'APS4_maximum',
                   'APS5_maximum', 'APS6_maximum', 'EL1_maximum', 'EL2_maximum']
n = len(max_pay_columns)
data_per_col = [df_original[col].dropna() for col in max_pay_columns]
df = pd.DataFrame(data_per_col).T

## Plot for each employer
for employer_short in df_original['shortname'].unique():
    employer_long = df_original[df_original['shortname'] == employer_short]['Employer'].iloc[0]
    try:
        print(f"Processing Employer: {employer_short} - {employer_long}")
        employer_values = df_original[df_original['shortname'] == employer_short]
        employer_values = employer_values[max_pay_columns].reset_index(drop=True)

        fig, axes = plt.subplots(2,4, figsize=(15,6))

        rng = np.random.default_rng(42)

        jitter_width = 0.05
        for c,ax in zip(max_pay_columns, axes.ravel()):
            
            # add scatter points for agencies
            x_all = 1 + rng.uniform(-jitter_width, jitter_width, size=len(df[[c]]))
            ax.plot(
                x_all, df[[c]].values, 'o',
                color='#1f77b4', alpha=0.45, markersize=5,
            )
            
            # boxplot
            df[[c]].boxplot(ax=ax, showfliers=False, grid=False)

            #add percentile rank
            try:
                pct = percentileofscore(df[[c]].values.reshape(-1), employer_values[c].values, kind='rank', nan_policy ='omit').item()
                pct = format_ordinal(int(round(pct)))

                ax.plot(
                    1, employer_values[c], marker='D', color='#d62728', markersize=7,
                    label=f'{employer_short}')

                ax.text(.025, .85, f"{employer_short}'s\nPercentile: {pct} ",
                        transform=ax.transAxes, fontsize=11, color='#d62728', fontweight='bold',)
            except Exception as e:
                print(f"Error processing {employer_short} for column {c}: {e}")
                ax.text(.025, .85, f"{employer_short} data not available",
                        transform=ax.transAxes, fontsize=11, color='#d62728', fontweight='bold',)

            # --- set y-limits to boxplot whisker extent + buffer ---
            col_vals = df[c].dropna().values.ravel()
            if col_vals.size > 0:
                q1, q3 = np.percentile(col_vals, [25, 75])
                iqr = q3 - q1
                lower_bound = q1 - 1.5 * iqr
                upper_bound = q3 + 1.5 * iqr
                # clip whiskers to actual data within the bounds (this matches pandas' whisker logic)
                within_lower = col_vals[col_vals >= lower_bound]
                within_upper = col_vals[col_vals <= upper_bound]
                whisker_low = within_lower.min() if within_lower.size > 0 else col_vals.min()
                whisker_high = within_upper.max() if within_upper.size > 0 else col_vals.max()

                # include employer value so it is never clipped
                try:
                    employer_value = float(employer_values[c].iloc[0])
                    whisker_low = min(whisker_low, employer_value)
                    whisker_high = max(whisker_high, employer_value)
                except Exception:
                    pass

            # add a small proportional buffer
            pad = 0.05 * (whisker_high - whisker_low) if (whisker_high > whisker_low) else whisker_high * 0.05
            ax.set_ylim(whisker_low - pad, whisker_high + pad)

            # Improve formatting
            ax.set_xticklabels([c.replace("_maximum", "")], fontsize=10)
            ax.grid(alpha=0.75)
            ax.yaxis.set_major_formatter(mtick.StrMethodFormatter('${x:,.0f}'))

        fig.supylabel('Maximum Annual Salary ($)')
        fig.suptitle(f'{employer_long} ({employer_short})\nMaximum Pay (top increment) for each Pay Classification, as of 13 March 2026', fontsize=16, fontweight='bold')
        plt.tight_layout()
        plt.savefig(f'MembersUnited_Plots/{employer_short}_max_pay_boxplots_all_levels_facet.png', bbox_inches='tight', dpi=300)
    except Exception as e:
        print(f"Error processing employer {employer_short}: {e}")