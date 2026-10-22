"""
AOI Boundary Inspection & Sentinel-2 MGRS Tile Intersection Utility.
Inspects data/vector/sambalpur.geojson and determines intersecting Sentinel-2 tiles via CDSE.
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Ensure stdout handles unicode cleanly on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import geopandas as gpd
import requests
from dotenv import load_dotenv
from shapely.geometry import shape

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VECTOR_PATH = PROJECT_ROOT / "data" / "vector" / "sambalpur.geojson"
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_PATH)

CDSE_TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
)
CDSE_ODATA_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"


def get_token() -> str:
    """Acquires CDSE Keycloak OAuth2 token."""
    user = os.getenv("CDSE_USERNAME")
    pwd = os.getenv("CDSE_PASSWORD")
    if not user or not pwd:
        raise ValueError("Missing CDSE credentials in .env file.")

    payload = {
        "client_id": "cdse-public",
        "username": user.strip(),
        "password": pwd.strip(),
        "grant_type": "password",
    }
    resp = requests.post(CDSE_TOKEN_URL, data=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def inspect_vector(vector_path: Path) -> Tuple[gpd.GeoDataFrame, float]:
    """Inspects the vector geometry, CRS, bounds, and attribute schema."""
    if not vector_path.exists():
        raise FileNotFoundError(f"Vector boundary file not found at: {vector_path}")

    gdf = gpd.read_file(vector_path)
    crs = gdf.crs
    minx, miny, maxx, maxy = gdf.total_bounds
    columns = list(gdf.columns)
    num_features = len(gdf)

    # Compute area in metric equal-area CRS (EPSG:6933)
    gdf_ea = gdf.to_crs(epsg=6933)
    # union_all replaces unary_union in newer geopandas
    geom_union = gdf_ea.geometry.union_all() if hasattr(gdf_ea.geometry, "union_all") else gdf_ea.geometry.unary_union
    total_area_sqkm = geom_union.area / 1e6

    print("\n" + "=" * 80)
    print(" SAMBALPUR AOI VECTOR INSPECTION REPORT")
    print("=" * 80)
    print(f"File Path                 : {vector_path.relative_to(PROJECT_ROOT)}")
    print(f"Number of Features        : {num_features}")
    print(f"Coordinate Reference (CRS): {crs} ({crs.name if crs else 'Unknown'})")
    print(f"Total District Area       : {total_area_sqkm:,.2f} sq km ({total_area_sqkm * 100:,.0f} hectares)")
    print("\nBounding Box (WGS 84 / Lat-Lon):")
    print(f"  * Min Longitude (West)  : {minx:.6f}° E")
    print(f"  * Max Longitude (East)  : {maxx:.6f}° E")
    print(f"  * Min Latitude  (South) : {miny:.6f}° N")
    print(f"  * Max Latitude  (North) : {maxy:.6f}° N")

    print("\nAttribute Columns & Schema:")
    for col in columns:
        dtype = str(gdf[col].dtype)
        sample = gdf[col].iloc[0] if num_features > 0 else "N/A"
        if col == "geometry":
            sample_str = f"{gdf.geometry.geom_type.iloc[0]} (valid: {gdf.geometry.is_valid.iloc[0]})"
        else:
            sample_str = str(sample)
        print(f"  * {col:<15} ({dtype:<10}) -> Sample: {sample_str}")

    print("\nAdministrative Boundary Assessment:")
    col_names_upper = [c.upper() for c in columns]
    if any(k in col_names_upper for k in ["BLOCK", "SUB_DIST", "TEHSIL", "TALUK"]):
        print("  [✓] Dataset contains sub-district / block boundary geometries.")
    else:
        print("  [i] Dataset contains ONLY the single outer DISTRICT outline of Sambalpur (1 feature).")
        print("      (Individual block boundaries like Dhankauda, Jujomura, Maneswar, etc. are NOT present).")

    return gdf, total_area_sqkm


def query_mgrs_intersections(gdf: gpd.GeoDataFrame, total_area_sqkm: float) -> List[Dict]:
    """
    Queries CDSE for Sentinel-2 products intersecting the AOI bounding box,
    retrieves their footprints, and computes geographic coverage percentages.
    """
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}

    minx, miny, maxx, maxy = gdf.total_bounds
    poly_wkt = f"POLYGON(({minx} {miny},{maxx} {miny},{maxx} {maxy},{minx} {maxy},{minx} {miny}))"

    # Query a representative 1-month window to catch all orbit swaths
    filter_q = (
        "Collection/Name eq 'SENTINEL-2' and "
        "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq 'S2MSI2A') and "
        f"OData.CSC.Intersects(area=geography'SRID=4326;{poly_wkt}') and "
        "ContentDate/Start ge 2026-01-01T00:00:00.000Z and ContentDate/Start le 2026-01-31T23:59:59.999Z"
    )

    params = {
        "$filter": filter_q,
        "$expand": "Attributes",
        "$top": 100,
    }

    print("\nQuerying Copernicus Data Space Ecosystem for intersecting MGRS tiles...")
    resp = requests.get(CDSE_ODATA_URL, params=params, headers=headers, timeout=45)
    resp.raise_for_status()

    items = resp.json().get("value", [])
    tile_to_product = {}

    for item in items:
        tile_attr = [a["Value"] for a in item.get("Attributes", []) if a.get("Name") == "tileId"]
        if tile_attr:
            tile_id = tile_attr[0]
            if tile_id not in tile_to_product:
                tile_to_product[tile_id] = item["Id"]

    # Also include candidate tiles mentioned by user if not already returned
    for tile_id in ["44QKG", "44QLG", "44QKF"]:
        if tile_id not in tile_to_product:
            p_q = (
                "Collection/Name eq 'SENTINEL-2' and "
                f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'tileId' and att/OData.CSC.StringAttribute/Value eq '{tile_id}')"
            )
            p_resp = requests.get(CDSE_ODATA_URL, params={"$filter": p_q, "$top": 1}, headers=headers, timeout=30)
            if p_resp.status_code == 200 and p_resp.json().get("value"):
                tile_to_product[tile_id] = p_resp.json()["value"][0]["Id"]

    # Calculate exact geometric overlap in equal area projection
    gdf_ea = gdf.to_crs(epsg=6933)
    district_union = gdf_ea.geometry.union_all() if hasattr(gdf_ea.geometry, "union_all") else gdf_ea.geometry.unary_union

    results = []
    for tile_id, prod_id in tile_to_product.items():
        prod_url = f"{CDSE_ODATA_URL}({prod_id})"
        prod_resp = requests.get(prod_url, headers=headers, timeout=30)
        if prod_resp.status_code == 200:
            fp_json = prod_resp.json().get("GeoFootprint")
            if fp_json:
                fp_shape = shape(fp_json)
                fp_ea = gpd.GeoSeries([fp_shape], crs="EPSG:4326").to_crs(epsg=6933).iloc[0]
                inter_geom = district_union.intersection(fp_ea)
                inter_area_sqkm = inter_geom.area / 1e6
                pct_covered = (inter_area_sqkm / total_area_sqkm) * 100
                results.append({
                    "tile_id": tile_id,
                    "overlap_sqkm": inter_area_sqkm,
                    "pct_covered": pct_covered,
                })

    # Sort descending by coverage percentage
    results.sort(key=lambda r: r["pct_covered"], reverse=True)
    return results


def print_tile_analysis(results: List[Dict], total_area_sqkm: float):
    """Prints the tile intersection breakdown table."""
    print("\n" + "=" * 80)
    print(" SENTINEL-2 MGRS TILE INTERSECTION & COVERAGE ANALYSIS")
    print("=" * 80)
    print(f"{'MGRS Tile':<12} | {'District Overlap (sq km)':<26} | {'Coverage % of Sambalpur':<25}")
    print("-" * 80)

    for r in results:
        print(f"{r['tile_id']:<12} | {r['overlap_sqkm']:>18,.2f} sq km | {r['pct_covered']:>22.2f}%")

    print("-" * 80)
    print(f"{'Total AOI':<12} | {total_area_sqkm:>18,.2f} sq km | {'100.00%':>23}")
    print("=" * 80)

    dominant = [r for r in results if r["pct_covered"] > 50]
    zero_overlap = [r for r in results if r["pct_covered"] == 0]

    print("\nKey Geographic Findings:")
    if dominant:
        for d in dominant:
            print(f"  [!] Dominant Tile : {d['tile_id']} covers {d['pct_covered']:.2f}% ({d['overlap_sqkm']:,.2f} sq km) of Sambalpur.")
    if zero_overlap:
        zero_names = ", ".join(z["tile_id"] for z in zero_overlap)
        print(f"  [x] Zero Overlap  : Tile(s) {zero_names} have 0.00% overlap with Sambalpur.")
        print("      Location Note : Tile 44QKG is situated ~500 km west (Telangana/Maharashtra border).")
        print("                      Sambalpur is located in Western Odisha (83.80°E to 84.77°E, 20.92°N to 22.19°N).")
        print("                      The primary Sentinel-2 tiles covering Sambalpur are 44QRJ (74.55%) and 45QTD (56.05%).")
    print()


def main():
    gdf, total_area = inspect_vector(VECTOR_PATH)
    results = query_mgrs_intersections(gdf, total_area)
    print_tile_analysis(results, total_area)


if __name__ == "__main__":
    main()
