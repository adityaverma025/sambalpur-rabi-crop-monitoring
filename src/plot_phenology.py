"""
Rabi 2025-2026 Crop Phenology Trajectory Generator
Sambalpur District, Odisha, India
Satellite: Copernicus Sentinel-2 MSI (10m Resolution)
"""

import os
import sys
import time
from pathlib import Path

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd
import rasterio

# Project Directory Structure
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DATA_OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
DATA_VECTOR_DIR = PROJECT_ROOT / "data" / "vector"

MONTH_METADATA = [
    {
        "id": "NOV",
        "file": "NOV.tif",
        "label": "Nov 2025",
        "month_name": "November 2025",
        "stage": "Sowing / Land Prep",
        "description": "Post-monsoon land preparation, early sowing & nursery emergence",
    },
    {
        "id": "DEC",
        "file": "DEC.tif",
        "label": "Dec 2025",
        "month_name": "December 2025",
        "stage": "Crop Emergence & Tillering",
        "description": "Vegetative tillering and basal canopy development",
    },
    {
        "id": "JAN",
        "file": "JAN.tif",
        "label": "Jan 2026",
        "month_name": "January 2026",
        "stage": "Active Canopy Growth",
        "description": "Stem elongation, rapid green leaf area expansion",
    },
    {
        "id": "FEB",
        "file": "FEB.tif",
        "label": "Feb 2026",
        "month_name": "February 2026",
        "stage": "Peak Vegetative / Heading",
        "description": "Panicle heading & anthesis, maximum photosynthetic vitality",
    },
    {
        "id": "MAR",
        "file": "MAR.tif",
        "label": "Mar 2026",
        "month_name": "March 2026",
        "stage": "Grain Filling & Senescence",
        "description": "Dough stage, chlorophyll decline & canopy yellowing",
    },
    {
        "id": "APR",
        "file": "APR.tif",
        "label": "Apr 2026",
        "month_name": "April 2026",
        "stage": "Harvest / Post-Harvest Fallow",
        "description": "Crop harvesting, dry stubble & residual biomass/soil",
    },
]


def inspect_workspace():
    """Inspects raw, processed, and output data directories."""
    print("=" * 105)
    print(" 1. WORKSPACE INSPECTION")
    print("=" * 105)

    # 1. Raw Data
    raw_folders = [d for d in DATA_RAW_DIR.iterdir() if d.is_dir()] if DATA_RAW_DIR.exists() else []
    raw_files = list(DATA_RAW_DIR.rglob("*.jp2")) if DATA_RAW_DIR.exists() else []
    raw_size_gb = sum(f.stat().st_size for f in raw_files) / (1024 ** 3)
    print(f"[*] data/raw/       : {len(raw_folders)} scene folders | {len(raw_files)} band files (.jp2) | Total Size: {raw_size_gb:.2f} GB")

    # 2. Processed Data
    proc_folders = [d for d in DATA_PROCESSED_DIR.iterdir() if d.is_dir()] if DATA_PROCESSED_DIR.exists() else []
    proc_tifs = list(DATA_PROCESSED_DIR.rglob("*.tif")) if DATA_PROCESSED_DIR.exists() else []
    proc_size_gb = sum(f.stat().st_size for f in proc_tifs) / (1024 ** 3)
    print(f"[*] data/processed/ : {len(proc_folders)} month directories | {len(proc_tifs)} intermediate GeoTIFFs | Total Size: {proc_size_gb:.2f} GB")

    # 3. Output Data
    out_files = list(DATA_OUTPUT_DIR.glob("*.tif")) if DATA_OUTPUT_DIR.exists() else []
    out_size_gb = sum(f.stat().st_size for f in out_files) / (1024 ** 3)
    print(f"[*] data/output/    : {len(out_files)} final district mosaics | Total Size: {out_size_gb:.2f} GB")

    print("\n[+] Detecting & Validating 6 Target Monthly GeoTIFFs in data/output/:")
    print(f"{'Month':<10} | {'Filename':<10} | {'Status':<10} | {'Dimensions (H x W)':<20} | {'CRS':<12} | {'NoData Value'}")
    print("-" * 105)

    all_valid = True
    for m in MONTH_METADATA:
        p = DATA_OUTPUT_DIR / m["file"]
        if not p.exists():
            print(f"{m['label']:<10} | {m['file']:<10} | [X] MISSING | {'-':<20} | {'-':<12} | -")
            all_valid = False
            continue

        try:
            with rasterio.open(p) as src:
                dim_str = f"{src.height:,} x {src.width:,}"
                crs_str = str(src.crs)
                nodata_val = str(src.nodata)
                print(f"{m['label']:<10} | {m['file']:<10} | [✓] Valid   | {dim_str:<20} | {crs_str:<12} | {nodata_val}")
        except Exception as e:
            print(f"{m['label']:<10} | {m['file']:<10} | [!] ERROR   | {str(e)[:35]}")
            all_valid = False

    print("=" * 105)
    if not all_valid:
        raise RuntimeError("One or more monthly district rasters are missing or unreadable.")


def extract_monthly_statistics() -> pd.DataFrame:
    """
    Opens each monthly district raster, filters NoData, invalid bounds,
    and deep permanent water bodies (NDVI <= 0.0), and extracts statistical moments.
    """
    print("\n" + "=" * 105)
    print(" 2. STATISTICAL MOMENTS EXTRACTION (Terrestrial Vegetative Dynamics, NDVI > 0.0)")
    print("=" * 105)

    records = []

    for idx, m in enumerate(MONTH_METADATA, 1):
        t0 = time.time()
        file_path = DATA_OUTPUT_DIR / m["file"]
        print(f"[{idx}/6] Processing {m['month_name']} ({m['file']})...", end="", flush=True)

        with rasterio.open(file_path) as src:
            arr = src.read(1)

        # Masking criteria:
        # 1. NoData (-9999.0)
        # 2. NaN values
        # 3. Valid NDVI range [-1.0, 1.0]
        # 4. Filter deep permanent water bodies (NDVI <= 0.0) to capture terrestrial/agricultural phenology
        valid_mask = (arr != -9999.0) & (~np.isnan(arr)) & (arr > 0.0) & (arr <= 1.0)
        valid_ndvi = arr[valid_mask]

        n_pixels = len(valid_ndvi)
        mean_val = float(np.mean(valid_ndvi))
        std_val = float(np.std(valid_ndvi))
        median_val = float(np.median(valid_ndvi))
        p10_val = float(np.percentile(valid_ndvi, 10))
        p25_val = float(np.percentile(valid_ndvi, 25))
        p75_val = float(np.percentile(valid_ndvi, 75))
        p90_val = float(np.percentile(valid_ndvi, 90))
        iqr_val = p75_val - p25_val

        elapsed = time.time() - t0
        print(f" Done ({elapsed:.1f}s | {n_pixels:,} valid pixels)")

        records.append({
            "month_id": m["id"],
            "month_label": m["label"],
            "month_name": m["month_name"],
            "phenology_stage": m["stage"],
            "valid_pixels": n_pixels,
            "mean": mean_val,
            "std": std_val,
            "median": median_val,
            "p10": p10_val,
            "p25": p25_val,
            "p75": p75_val,
            "p90": p90_val,
            "iqr": iqr_val,
            "mean_minus_std": max(0.0, mean_val - std_val),
            "mean_plus_std": min(1.0, mean_val + std_val),
        })

    df = pd.DataFrame(records)

    print("\n" + "=" * 120)
    print(" MONTHLY PHENOLOGICAL STATISTICAL SUMMARY — SAMBALPUR DISTRICT (RABI 2025-2026)")
    print("=" * 120)
    print(f"{'Month':<10} | {'Phenological Stage':<28} | {'Valid Pixels':<12} | {'Mean ± Std':<17} | {'Median':<8} | {'IQR [Q1, Q3]':<17} | {'P10 - P90 Range'}")
    print("-" * 120)
    for _, r in df.iterrows():
        mean_std = f"{r['mean']:.4f} ± {r['std']:.4f}"
        iqr_str = f"[{r['p25']:.3f}, {r['p75']:.3f}]"
        p_range = f"{r['p10']:.3f} - {r['p90']:.3f}"
        print(f"{r['month_label']:<10} | {r['phenology_stage']:<28} | {r['valid_pixels']:>12,} | {mean_std:<17} | {r['median']:<8.4f} | {iqr_str:<17} | {p_range}")
    print("=" * 120)

    return df


def plot_publication_phenology_curve(df: pd.DataFrame, output_path: Path):
    """
    Renders publication-grade temporal phenology visualization.
    """
    print("\n" + "=" * 105)
    print(" 3. RENDERING PUBLICATION-GRADE PHENOLOGY FIGURE")
    print("=" * 105)

    # Clean publication styling
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(13, 7.5), dpi=300)

    # Set background and spine styling
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FAFAFA")

    x_indices = np.arange(len(df))
    x_labels = df["month_label"].tolist()

    # Color Palette
    line_color = "#1B5E20"       # Deep Emerald Green
    ribbon_color = "#81C784"     # Soft Meadow Green
    median_color = "#0D47A1"     # Navy Blue for Median
    marker_edge = "#0B3D0B"
    box_bg = "#FFFFFF"

    # 1. Translucent Shaded Ribbon (Mean ± 1 Std Dev)
    ax.fill_between(
        x_indices,
        df["mean_minus_std"],
        df["mean_plus_std"],
        color=ribbon_color,
        alpha=0.32,
        label="Mean ± 1 Std Dev Band",
        edgecolor=line_color,
        linewidth=0.8,
        linestyle="--",
    )

    # 2. IQR Non-parametric Bounds (P25 - P75)
    ax.fill_between(
        x_indices,
        df["p25"],
        df["p75"],
        color="#A5D6A7",
        alpha=0.25,
        label="Interquartile Range (IQR: P25–P75)",
    )

    # 3. Median Trajectory (Subtle dashed line)
    ax.plot(
        x_indices,
        df["median"],
        color=median_color,
        linewidth=1.8,
        linestyle=":",
        alpha=0.75,
        label="Median NDVI",
    )

    # 4. Solid Mean NDVI Trajectory with Markers
    line = ax.plot(
        x_indices,
        df["mean"],
        color=line_color,
        linewidth=3.0,
        marker="o",
        markersize=10,
        markerfacecolor="#2E7D32",
        markeredgecolor=box_bg,
        markeredgewidth=2.2,
        zorder=5,
        label="Mean District NDVI",
    )

    # Annotate Mean values at each data point
    for idx, row in df.iterrows():
        y_val = row["mean"]
        ax.annotate(
            f"{y_val:.3f}",
            (idx, y_val),
            textcoords="offset points",
            xytext=(0, 14),
            ha="center",
            fontsize=10.5,
            fontweight="bold",
            color="#1B5E20",
            bbox=dict(boxstyle="round,pad=0.25", facecolor="#FFFFFF", edgecolor="#C8E6C9", linewidth=1.0, alpha=0.9),
            zorder=6,
        )

    # 5. Phenological Stage Callouts & Annotation Cards
    callout_y = 0.70
    for idx, row in df.iterrows():
        stage_name = row["phenology_stage"]
        mean_y = row["mean"]

        # Alternating vertical alignment or clean banner above points
        ax.annotate(
            stage_name,
            xy=(idx, row["mean_plus_std"]),
            xytext=(idx, 0.63 if idx % 2 == 0 else 0.72),
            ha="center",
            va="center",
            fontsize=9.0,
            fontweight="semibold",
            color="#1E293B",
            bbox=dict(
                boxstyle="square,pad=0.45",
                facecolor="#F8FAFC",
                edgecolor="#CBD5E1",
                linewidth=1.0,
                alpha=0.92,
            ),
            arrowprops=dict(
                arrowstyle="-|>",
                color="#64748B",
                lw=1.1,
                shrinkA=3,
                shrinkB=5,
                connectionstyle="arc3,rad=0.0",
            ),
            zorder=7,
        )

    # Axes limits, ticks, and formatting
    ax.set_ylim(0.0, 0.85)
    ax.set_xlim(-0.5, len(df) - 0.5)
    ax.set_xticks(x_indices)
    ax.set_xticklabels(x_labels, fontsize=12, fontweight="medium", color="#1E293B")
    ax.yaxis.set_major_locator(ticker.MultipleLocator(0.1))
    ax.yaxis.set_minor_locator(ticker.MultipleLocator(0.05))
    ax.tick_params(axis="y", labelsize=11, colors="#334155")
    ax.tick_params(axis="x", pad=8)

    # Grid lines
    ax.grid(True, which="major", linestyle="-", linewidth=0.7, color="#E2E8F0", alpha=0.85)
    ax.grid(True, which="minor", linestyle=":", linewidth=0.5, color="#F1F5F9", alpha=0.6)
    ax.set_axisbelow(True)

    # Spines
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    for spine in ["left", "bottom"]:
        ax.spines[spine].set_color("#94A3B8")
        ax.spines[spine].set_linewidth(1.2)

    # Labels and Titles
    ax.set_ylabel("Normalized Difference Vegetation Index (NDVI)", fontsize=12.5, fontweight="semibold", color="#0F172A", labelpad=12)
    ax.set_xlabel("Rabi 2025–2026 Chronological Window", fontsize=12.5, fontweight="semibold", color="#0F172A", labelpad=12)

    # Multi-line Title and Subtitle
    fig.suptitle(
        "Rabi 2025–26 Crop Phenology Trajectory — Sambalpur District, Odisha",
        fontsize=16,
        fontweight="bold",
        color="#0F172A",
        y=0.97,
        ha="center",
    )
    ax.set_title(
        "Sentinel-2 MSI 10m Multi-Temporal NDVI Time Series  |  Terrestrial Agricultural Dynamics (Water Bodies Masked)",
        fontsize=11.5,
        fontstyle="italic",
        color="#475569",
        pad=18,
    )

    # Legend
    legend = ax.legend(
        loc="upper right",
        frameon=True,
        facecolor="#FFFFFF",
        edgecolor="#E2E8F0",
        framealpha=0.95,
        fontsize=10.5,
        title="Phenological Indicators",
        title_fontsize=11,
    )
    legend.get_title().set_fontweight("semibold")

    # Footnote metadata caption
    footnote = (
        "Data Source: Copernicus Data Space Ecosystem (CDSE) | Sentinel-2 L2A BOA Reflectance (B04 Red, B08 NIR)\n"
        "Spatial Resolution: 10m | District AOI Area: 6,726.09 km² (Sambalpur, Odisha) | Coordinate System: WGS 84 / UTM Zone 44N (EPSG:32644)"
    )
    plt.figtext(0.5, 0.015, footnote, ha="center", fontsize=8.5, color="#64748B", style="normal")

    plt.tight_layout(rect=[0.02, 0.05, 0.98, 0.94])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"[✓] Publication figure saved successfully to: {output_path.resolve()}")
    print(f"    Dimensions: 3900 x 2250 px (300 DPI) | File Size: {output_path.stat().st_size / 1024:.1f} KB")


def main():
    inspect_workspace()
    df = extract_monthly_statistics()
    fig_path = DATA_OUTPUT_DIR / "sambalpur_rabi_phenology_curve.png"
    plot_publication_phenology_curve(df, fig_path)


if __name__ == "__main__":
    main()
