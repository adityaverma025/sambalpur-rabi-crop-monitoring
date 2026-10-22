"""
Recalibrated Rabi Cropland Isolation & Agricultural Phenology Analysis
Sambalpur District, Odisha, India
Hirakud Canal Command Multi-Temporal Sentinel-2 MSI (10m Resolution)
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
from rasterio.warp import Resampling, reproject

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_OUTPUT_DIR = PROJECT_ROOT / "data" / "output"

MONTH_METADATA = [
    {
        "id": "NOV",
        "file": "NOV.tif",
        "label": "Nov 2025",
        "month_name": "November 2025",
        "stage": "Post-Kharif / Fallow",
        "description": "Post-monsoon drydown and initial fallow preparation",
    },
    {
        "id": "DEC",
        "file": "DEC.tif",
        "label": "Dec 2025",
        "month_name": "December 2025",
        "stage": "Canal Inundation & Land Prep",
        "description": "Hirakud canal discharge, field flooding & puddling",
    },
    {
        "id": "JAN",
        "file": "JAN.tif",
        "label": "Jan 2026",
        "month_name": "January 2026",
        "stage": "Transplanting & Emergence",
        "description": "Dalua rice transplantation & early seedling establishment",
    },
    {
        "id": "FEB",
        "file": "FEB.tif",
        "label": "Feb 2026",
        "month_name": "February 2026",
        "stage": "Tillering & Vegetative Growth",
        "description": "Basal tillering and green biomass expansion",
    },
    {
        "id": "MAR",
        "file": "MAR.tif",
        "label": "Mar 2026",
        "month_name": "March 2026",
        "stage": "Panicle Heading & Canopy Surge",
        "description": "Stem elongation, anthesis & rapid canopy closure",
    },
    {
        "id": "APR",
        "file": "APR.tif",
        "label": "Apr 2026",
        "month_name": "April 2026",
        "stage": "Peak Biomass & Grain Filling",
        "description": "Maximum vegetative vigor, milky/dough grain development",
    },
]


def recalibrate_rabi_cropland_mask():
    """
    Recalibrates the Rabi Cropland Mask to capture the Hirakud canal command agricultural belt:
      - PEAK_NDVI = maximum(FEB, MAR)
      - BASE_NDVI = minimum(NOV, DEC)
      - SEASONAL_AMPLITUDE = PEAK_NDVI - BASE_NDVI
      - Condition 1 (Vegetative Vigour)     : PEAK_NDVI >= 0.35
      - Condition 2 (Active Emergence Surge): SEASONAL_AMPLITUDE >= 0.08
      - Condition 3 (Deciduous Elimination) : Exclude if (NOV >= 0.45 and PEAK_NDVI <= NOV)
      - Condition 4 (Water / Barren Mask)   : Exclude if PEAK_NDVI <= 0.15
    """
    print("=" * 115)
    print(" 1. RECALIBRATING RABI CROPLAND MASK (Hirakud Canal Command Agricultural Belt)")
    print("=" * 115)

    # 1. Load Master Grids
    nov_path = DATA_OUTPUT_DIR / "NOV.tif"
    dec_path = DATA_OUTPUT_DIR / "DEC.tif"
    feb_path = DATA_OUTPUT_DIR / "FEB.tif"
    mar_path = DATA_OUTPUT_DIR / "MAR.tif"

    print("[*] Loading and aligning multi-temporal reference rasters:")
    print(f"    • NOV : {nov_path.name}")
    print(f"    • DEC : {dec_path.name}")
    print(f"    • FEB : {feb_path.name}")
    print(f"    • MAR : {mar_path.name}")

    with rasterio.open(nov_path) as s_nov:
        nov = s_nov.read(1)
        master_meta = s_nov.meta.copy()
        master_transform = s_nov.transform
        master_crs = s_nov.crs
        master_shape = nov.shape

    with rasterio.open(feb_path) as s_feb:
        feb = s_feb.read(1)

    with rasterio.open(mar_path) as s_mar:
        mar = s_mar.read(1)

    # Align DEC.tif to master grid
    with rasterio.open(dec_path) as s_dec:
        if s_dec.shape != master_shape or s_dec.transform != master_transform:
            print("    [Aligning DEC.tif to 10m master grid]...")
            dec = np.full(master_shape, -9999.0, dtype=np.float32)
            reproject(
                source=s_dec.read(1),
                destination=dec,
                src_transform=s_dec.transform,
                src_crs=s_dec.crs,
                dst_transform=master_transform,
                dst_crs=master_crs,
                resampling=Resampling.bilinear,
                src_nodata=-9999.0,
                dst_nodata=-9999.0,
            )
        else:
            dec = s_dec.read(1)

    # Filter Valid Land Pixels
    valid_mask = (
        (nov != -9999.0)
        & (dec != -9999.0)
        & (feb != -9999.0)
        & (mar != -9999.0)
        & (~np.isnan(nov))
        & (~np.isnan(dec))
        & (~np.isnan(feb))
        & (~np.isnan(mar))
        & (nov > 0.0)
        & (dec > 0.0)
        & (feb > 0.0)
        & (mar > 0.0)
        & (nov <= 1.0)
        & (dec <= 1.0)
        & (feb <= 1.0)
        & (mar <= 1.0)
    )

    # Multi-Temporal Metrics
    peak_ndvi = np.maximum(feb, mar)
    base_ndvi = np.minimum(nov, dec)
    seasonal_amplitude = peak_ndvi - base_ndvi

    # Robust Agricultural Decision Rules
    cond1_vigour = peak_ndvi >= 0.35
    cond2_surge = seasonal_amplitude >= 0.08
    cond3_forest = (nov >= 0.45) & (peak_ndvi <= nov)
    cond4_barren = peak_ndvi <= 0.15

    # Final Combined Cropland Mask
    cropland_mask = valid_mask & cond1_vigour & cond2_surge & (~cond3_forest) & (~cond4_barren)
    mask_uint8 = cropland_mask.astype(np.uint8)

    # Area Metrics
    n_pixels = int(np.sum(mask_uint8 == 1))
    area_ha = n_pixels * 0.01          # 10m x 10m = 100 m² = 0.01 ha/pixel
    area_km2 = n_pixels * 100.0 / 1e6   # km²

    print(f"\n[+] Recalibration Summary:")
    print(f"    • Total Valid Terrestrial Pixels    : {np.sum(valid_mask):,}")
    print(f"    • Vegetative Vigour (PEAK >= 0.35)  : {np.sum(valid_mask & cond1_vigour):,}")
    print(f"    • Emergence Surge (AMP >= 0.08)     : {np.sum(valid_mask & cond2_surge):,}")
    print(f"    • Deciduous Forest Pixels Rejected  : {np.sum(valid_mask & cond3_forest):,}")
    print(f"    • Water/Barren Pixels Rejected      : {np.sum(valid_mask & cond4_barren):,}")
    print(f"    • Total Recalibrated Cropland Pixels: {n_pixels:,}")
    print(f"    • Total Rabi Cropped Area (Hectares): {area_ha:,.2f} ha")
    print(f"    • Total Rabi Cropped Area (km²)     : {area_km2:,.2f} km²")

    # Overwrite Cropland Mask GeoTIFF
    mask_out_path = DATA_OUTPUT_DIR / "sambalpur_rabi_cropland_mask.tif"
    mask_meta = master_meta.copy()
    mask_meta.update({
        "driver": "GTiff",
        "dtype": "uint8",
        "count": 1,
        "nodata": 0,
        "compress": "deflate",
    })

    with rasterio.open(mask_out_path, "w", **mask_meta) as dst:
        dst.write(mask_uint8, 1)

    print(f"\n[✓] Calibrated Cropland Mask saved to: {mask_out_path.resolve()}")
    print(f"    Data Type: uint8 | File Size: {mask_out_path.stat().st_size / 1024:.1f} KB")

    return mask_uint8, master_meta, n_pixels, area_ha, area_km2


def compute_cropland_monthly_statistics(cropland_mask: np.ndarray, master_meta: dict) -> pd.DataFrame:
    """
    Computes zonal statistics across all 6 months strictly over the calibrated Rabi cropland mask.
    """
    print("\n" + "=" * 115)
    print(" 2. RE-EXTRACTING ZONAL TIME-SERIES STATS OVER RECALIBRATED CROPLAND")
    print("=" * 115)

    master_shape = cropland_mask.shape
    master_transform = master_meta["transform"]
    master_crs = master_meta["crs"]

    records = []

    for idx, m in enumerate(MONTH_METADATA, 1):
        t0 = time.time()
        file_path = DATA_OUTPUT_DIR / m["file"]
        print(f"[{idx}/6] Analyzing {m['month_name']} ({m['file']})...", end="", flush=True)

        with rasterio.open(file_path) as src:
            if src.shape != master_shape or src.transform != master_transform:
                print(" [Aligning Grid]...", end="", flush=True)
                aligned_arr = np.full(master_shape, -9999.0, dtype=np.float32)
                reproject(
                    source=src.read(1),
                    destination=aligned_arr,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=master_transform,
                    dst_crs=master_crs,
                    resampling=Resampling.bilinear,
                    src_nodata=-9999.0,
                    dst_nodata=-9999.0,
                )
                arr = aligned_arr
            else:
                arr = src.read(1)

        # Sample over calibrated cropland mask
        crop_pixels = arr[cropland_mask == 1]
        valid_crop = crop_pixels[
            (crop_pixels != -9999.0)
            & (~np.isnan(crop_pixels))
            & (crop_pixels >= -1.0)
            & (crop_pixels <= 1.0)
        ]

        mean_val = float(np.mean(valid_crop))
        std_val = float(np.std(valid_crop))
        median_val = float(np.median(valid_crop))
        p10_val = float(np.percentile(valid_crop, 10))
        p25_val = float(np.percentile(valid_crop, 25))
        p75_val = float(np.percentile(valid_crop, 75))
        p90_val = float(np.percentile(valid_crop, 90))
        iqr_val = p75_val - p25_val

        elapsed = time.time() - t0
        print(f" Done ({elapsed:.1f}s | Mean={mean_val:.4f} ± {std_val:.4f})")

        records.append({
            "month_id": m["id"],
            "month_label": m["label"],
            "month_name": m["month_name"],
            "phenology_stage": m["stage"],
            "valid_pixels": len(valid_crop),
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

    # Print Clean Markdown Summary Table
    print("\n" + "=" * 125)
    print("### Recalibrated Rabi Cropland Phenology Summary — Sambalpur District (2025–26)")
    print("=" * 125)
    print("| Month | Agronomic Phenological Stage | Cropland Pixels | Mean NDVI ± 1 Std Dev | Median NDVI | IQR [Q1, Q3] | 10th–90th Range |")
    print("| :--- | :--- | :---: | :---: | :---: | :---: | :---: |")
    for _, r in df.iterrows():
        mean_std = f"{r['mean']:.4f} ± {r['std']:.4f}"
        iqr_str = f"[{r['p25']:.3f}, {r['p75']:.3f}]"
        p_range = f"{r['p10']:.3f} – {r['p90']:.3f}"
        print(f"| **{r['month_label']}** | {r['phenology_stage']} | {r['valid_pixels']:,} | **{mean_std}** | {r['median']:.4f} | {iqr_str} | {p_range} |")
    print("=" * 125)

    return df


def plot_recalibrated_phenology(df: pd.DataFrame, output_path: Path, area_ha: float, area_km2: float):
    """
    Renders publication-grade isolated cropland phenology plot with calibrated acreage.
    """
    print("\n" + "=" * 115)
    print(" 3. RENDERING UPDATED PUBLICATION PHENOLOGY PLOT")
    print("=" * 115)

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(13.5, 7.8), dpi=300)

    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FAFAFA")

    x_indices = np.arange(len(df))
    x_labels = df["month_label"].tolist()

    # Color Palette - Agronomic Emerald Theme
    crop_green = "#1B5E20"       # Deep Emerald Green
    marker_fill = "#2E7D32"      # Rich Leaf Green
    ribbon_fill = "#81C784"      # Soft Green
    iqr_fill = "#C8E6C9"         # Pale Green for IQR
    median_line = "#0D47A1"      # Deep Navy for Median
    box_edge = "#CBD5E1"

    # 1. Shaded Translucent Ribbon (Mean ± 1 Std Dev)
    ax.fill_between(
        x_indices,
        df["mean_minus_std"],
        df["mean_plus_std"],
        color=ribbon_fill,
        alpha=0.35,
        label="Mean ± 1 Std Dev Error Band",
        edgecolor=crop_green,
        linewidth=0.9,
        linestyle="--",
        zorder=2,
    )

    # 2. Interquartile Range (IQR: P25–P75) Shaded Band
    ax.fill_between(
        x_indices,
        df["p25"],
        df["p75"],
        color=iqr_fill,
        alpha=0.30,
        label="Interquartile Range (IQR: P25–P75)",
        zorder=3,
    )

    # 3. Median Dotted Trajectory
    ax.plot(
        x_indices,
        df["median"],
        color=median_line,
        linewidth=2.0,
        linestyle=":",
        alpha=0.85,
        label="Median Cropland NDVI",
        zorder=4,
    )

    # 4. Solid Mean Trajectory Line with Data Points
    ax.plot(
        x_indices,
        df["mean"],
        color=crop_green,
        linewidth=3.2,
        marker="o",
        markersize=11,
        markerfacecolor=marker_fill,
        markeredgecolor="#FFFFFF",
        markeredgewidth=2.4,
        label="Mean Rabi Cropland NDVI",
        zorder=5,
    )

    # Floating Value Callouts Above Data Points
    for idx, row in df.iterrows():
        y_val = row["mean"]
        # Position label cleanly above marker
        offset_y = 18 if idx not in [2, 3] else -28
        ax.annotate(
            f"μ = {y_val:.3f}\n(±{row['std']:.3f})",
            (idx, y_val),
            textcoords="offset points",
            xytext=(0, offset_y),
            ha="center",
            fontsize=10.0,
            fontweight="bold",
            color="#1B5E20",
            bbox=dict(
                boxstyle="round,pad=0.30",
                facecolor="#FFFFFF",
                edgecolor="#A5D6A7",
                linewidth=1.2,
                alpha=0.95,
            ),
            zorder=6,
        )

    # 5. Agronomic Phenology Stage Cards with Pointer Arrows
    stage_callouts = [
        ("Post-Kharif / Fallow", 0.48),
        ("Canal Flooding & Land Prep", 0.35),
        ("Transplanting & Emergence", 0.22),
        ("Tillering & Vegetative Surge", 0.24),
        ("Heading & Canopy Closure", 0.60),
        ("Peak Biomass & Grain Filling", 0.63),
    ]

    for idx, (stage_title, target_y) in enumerate(stage_callouts):
        row = df.iloc[idx]
        arrow_start_y = row["mean_plus_std"] if idx not in [2, 3] else row["mean_minus_std"]

        ax.annotate(
            stage_title,
            xy=(idx, arrow_start_y),
            xytext=(idx, target_y),
            ha="center",
            va="center",
            fontsize=9.2,
            fontweight="bold",
            color="#1E293B",
            bbox=dict(
                boxstyle="square,pad=0.45",
                facecolor="#F8FAFC",
                edgecolor=box_edge,
                linewidth=1.1,
                alpha=0.94,
            ),
            arrowprops=dict(
                arrowstyle="-|>",
                color="#64748B",
                lw=1.2,
                shrinkA=3,
                shrinkB=4,
                connectionstyle="arc3,rad=0.0",
            ),
            zorder=7,
        )

    # Prominent Total Cropped Area Badge
    area_badge_text = (
        f"Calibrated Rabi Cropped Area\n"
        f"• {area_ha:,.1f} Hectares\n"
        f"• {area_km2:,.2f} km²  ({len(df.iloc[0]['valid_pixels'] if isinstance(df.iloc[0]['valid_pixels'], list) else str(df.iloc[0]['valid_pixels']))} pixels)"
    )
    ax.text(
        0.025,
        0.95,
        f"Hirakud Command Rabi Acreage:\n{area_ha:,.1f} ha  ({area_km2:.2f} km²)",
        transform=ax.transAxes,
        fontsize=11,
        fontweight="bold",
        color="#0F5132",
        va="top",
        bbox=dict(
            boxstyle="round,pad=0.55",
            facecolor="#E8F5E9",
            edgecolor="#81C784",
            linewidth=1.4,
            alpha=0.95,
        ),
        zorder=8,
    )

    # Axes limits, ticks & styling
    ax.set_ylim(0.0, 0.72)
    ax.set_xlim(-0.5, len(df) - 0.5)
    ax.set_xticks(x_indices)
    ax.set_xticklabels(x_labels, fontsize=12, fontweight="medium", color="#0F172A")
    ax.yaxis.set_major_locator(ticker.MultipleLocator(0.1))
    ax.yaxis.set_minor_locator(ticker.MultipleLocator(0.05))
    ax.tick_params(axis="y", labelsize=11.5, colors="#334155")
    ax.tick_params(axis="x", pad=10)

    # Grid & Spines
    ax.grid(True, which="major", linestyle="-", linewidth=0.7, color="#E2E8F0", alpha=0.9)
    ax.grid(True, which="minor", linestyle=":", linewidth=0.5, color="#F1F5F9", alpha=0.6)
    ax.set_axisbelow(True)

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    for spine in ["left", "bottom"]:
        ax.spines[spine].set_color("#94A3B8")
        ax.spines[spine].set_linewidth(1.3)

    # Axis Labels
    ax.set_ylabel("Cropland NDVI (Normalized Difference Vegetation Index)", fontsize=13, fontweight="semibold", color="#0F172A", labelpad=14)
    ax.set_xlabel("Rabi 2025–2026 Chronological Window", fontsize=13, fontweight="semibold", color="#0F172A", labelpad=14)

    # Main Title and Subtitle
    fig.suptitle(
        "Rabi 2025–26 Agricultural Phenology Trajectory — Sambalpur District, Odisha",
        fontsize=16,
        fontweight="bold",
        color="#0F172A",
        y=0.97,
        ha="center",
    )
    ax.set_title(
        f"Sentinel-2 MSI 10m Multi-Temporal Time Series  |  Isolated Rabi Cropland: {area_ha:,.1f} ha ({area_km2:.2f} km²)  |  Deciduous Bias Excluded",
        fontsize=11.2,
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
        framealpha=0.96,
        fontsize=10.5,
        title="Cropland Phenological Dynamics",
        title_fontsize=11,
    )
    legend.get_title().set_fontweight("semibold")

    # Footnote metadata caption
    footnote = (
        f"Classification Rules: PEAK_NDVI=max(FEB,MAR) >= 0.35 | BASE_NDVI=min(NOV,DEC) | AMPLITUDE >= 0.08 | Excluded Forest (NOV>=0.45 & PEAK<=NOV) & Water (PEAK<=0.15)\n"
        f"Data Source: Copernicus Data Space Ecosystem (CDSE) | Sentinel-2 L2A (10m Resolution) | Coordinate System: EPSG:32644 (UTM 44N)"
    )
    plt.figtext(0.5, 0.015, footnote, ha="center", fontsize=8.5, color="#64748B")

    plt.tight_layout(rect=[0.02, 0.05, 0.98, 0.94])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"\n[✓] Publication plot successfully saved to: {output_path.resolve()}")
    print(f"    Dimensions: 4050 x 2340 px (300 DPI) | File Size: {output_path.stat().st_size / 1024:.1f} KB")


def main():
    mask, master_meta, n_pixels, area_ha, area_km2 = recalibrate_rabi_cropland_mask()
    df = compute_cropland_monthly_statistics(mask, master_meta)
    plot_path = DATA_OUTPUT_DIR / "sambalpur_rabi_crop_phenology_isolated.png"
    plot_recalibrated_phenology(df, plot_path, area_ha, area_km2)


if __name__ == "__main__":
    main()
