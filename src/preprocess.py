"""
Cloud masking (SCL), spatial clipping, and vegetation indices calculation.
Processes raw Sentinel-2 bands to produce cloud-masked NDVI/EVI GeoTIFFs clipped to Sambalpur.
"""

from pathlib import Path
import numpy as np
import rasterio
from rasterio.mask import mask
import geopandas as gpd

DATA_RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
DATA_PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
DATA_VECTOR_DIR = Path(__file__).resolve().parent.parent / "data" / "vector"

DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def load_vector_aoi(vector_path: Path):
    """Load Sambalpur boundary / block shapefile or GeoJSON."""
    gdf = gpd.read_file(vector_path)
    return gdf


def apply_scl_cloud_mask(band_data: np.ndarray, scl_data: np.ndarray) -> np.ndarray:
    """
    Mask clouds, cirrus, and cloud shadows using Sentinel-2 SCL (Scene Classification Layer).
    SCL classes to mask typically include:
      3: Cloud shadows
      8: Cloud medium probability
      9: Cloud high probability
      10: Thin cirrus
    """
    cloud_mask = np.isin(scl_data, [3, 8, 9, 10])
    masked_data = np.where(cloud_mask, np.nan, band_data)
    return masked_data


def calculate_ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    """Calculate Normalized Difference Vegetation Index (NDVI = (NIR - Red) / (NIR + Red))."""
    denominator = nir + red
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where(denominator != 0, (nir - red) / denominator, np.nan)
    return ndvi


def calculate_evi(nir: np.ndarray, red: np.ndarray, blue: np.ndarray, g: float = 2.5, c1: float = 6.0, c2: float = 7.5, l: float = 1.0) -> np.ndarray:
    """Calculate Enhanced Vegetation Index (EVI)."""
    denominator = nir + c1 * red - c2 * blue + l
    with np.errstate(divide="ignore", invalid="ignore"):
        evi = np.where(denominator != 0, g * ((nir - red) / denominator), np.nan)
    return evi


def clip_raster_to_aoi(src_raster_path: Path, aoi_gdf: gpd.GeoDataFrame, output_path: Path):
    """Clip a raster dataset to the AOI vector geometry."""
    with rasterio.open(src_raster_path) as src:
        aoi_projected = aoi_gdf.to_crs(src.crs)
        out_image, out_transform = mask(src, aoi_projected.geometry, crop=True)
        out_meta = src.meta.copy()
        out_meta.update({
            "driver": "GTiff",
            "height": out_image.shape[1],
            "width": out_image.shape[2],
            "transform": out_transform,
        })
        with rasterio.open(output_path, "w", **out_meta) as dst:
            dst.write(out_image)


if __name__ == "__main__":
    print("Preprocess module initialized.")
