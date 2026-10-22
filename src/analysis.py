"""
Phenology curves, temporal profiling, and crop monitoring analysis.
Generates temporal NDVI/EVI curves, statistical summaries, and mapping visualizations.
"""

from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio

DATA_PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
OUTPUTS_FIGURES_DIR = Path(__file__).resolve().parent.parent / "outputs" / "figures"
OUTPUTS_MAPS_DIR = Path(__file__).resolve().parent.parent / "outputs" / "maps"

OUTPUTS_FIGURES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_MAPS_DIR.mkdir(parents=True, exist_ok=True)


def extract_temporal_profile(raster_paths: list, dates: list):
    """
    Extract mean and standard deviation of vegetation indices across time for crop phenology.
    """
    profile = []
    for date, path in zip(dates, raster_paths):
        with rasterio.open(path) as src:
            data = src.read(1)
            valid_pixels = data[~np.isnan(data)]
            if len(valid_pixels) > 0:
                profile.append({
                    "date": pd.to_datetime(date),
                    "mean": float(np.mean(valid_pixels)),
                    "median": float(np.median(valid_pixels)),
                    "std": float(np.std(valid_pixels)),
                    "p25": float(np.percentile(valid_pixels, 25)),
                    "p75": float(np.percentile(valid_pixels, 75)),
                })
    return pd.DataFrame(profile).sort_values("date")


def plot_phenology_curve(df_profile: pd.DataFrame, index_name: str = "NDVI", save_path: Path = None):
    """Plot and export crop phenology temporal trajectory."""
    plt.figure(figsize=(10, 5))
    plt.plot(df_profile["date"], df_profile["mean"], marker="o", label=f"Mean {index_name}", color="forestgreen")
    plt.fill_between(
        df_profile["date"],
        df_profile["mean"] - df_profile["std"],
        df_profile["mean"] + df_profile["std"],
        alpha=0.2,
        color="forestgreen",
        label="±1 Std Dev"
    )
    plt.title(f"Sambalpur Rabi Season - {index_name} Phenology Curve")
    plt.xlabel("Date")
    plt.ylabel(index_name)
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=300)
    plt.close()


if __name__ == "__main__":
    print("Analysis module initialized.")
