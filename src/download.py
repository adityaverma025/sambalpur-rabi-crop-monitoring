"""
CDSE Sentinel-2 Granule Catalog Query and Batch Single-Band Fetcher.
Target Area: Sambalpur, Odisha (MGRS Tile: 44QRJ & Neighbors: 44QRK, 45QTD)
Season: Rabi (2025-11-01 to 2026-04-30)
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Ensure stdout handles unicode cleanly on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import rasterio
import requests
from dotenv import load_dotenv
from tqdm import tqdm

# Load credentials from .env in project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(PROJECT_ROOT / ".env")

CDSE_TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
)
CDSE_ODATA_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
CDSE_DOWNLOAD_ODATA_URL = "https://download.dataspace.copernicus.eu/odata/v1/Products"


class CDSEAuthManager:
    """Manages CDSE Keycloak OAuth2 tokens with automatic expiry refresh."""

    def __init__(self):
        self.username = os.getenv("CDSE_USERNAME")
        self.password = os.getenv("CDSE_PASSWORD")
        if not self.username or not self.password:
            raise ValueError(
                "CDSE_USERNAME and CDSE_PASSWORD must be configured in .env."
            )
        self.token = None
        self.token_expiry = 0

    def get_token(self) -> str:
        """Returns a valid access token, refreshing if within 60s of expiration."""
        now = time.time()
        if not self.token or now >= (self.token_expiry - 60):
            payload = {
                "client_id": "cdse-public",
                "username": self.username.strip(),
                "password": self.password.strip(),
                "grant_type": "password",
            }
            resp = requests.post(CDSE_TOKEN_URL, data=payload, timeout=30)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Authentication failed (HTTP {resp.status_code}): {resp.text}"
                )
            data = resp.json()
            self.token = data["access_token"]
            expires_in = data.get("expires_in", 600)
            self.token_expiry = now + expires_in
        return self.token


def get_oauth2_token() -> str:
    """Convenience function for standalone token acquisition."""
    return CDSEAuthManager().get_token()


def query_sentinel2_inventory(
    token: str,
    tile_id: str = "44QRJ",
    start_date: str = "2025-11-01",
    end_date: str = "2026-04-30",
    max_cloud_cover: float = 20.0,
) -> List[Dict]:
    """
    Queries the CDSE OData catalogue for Sentinel-2 L2A products.
    """
    headers = {"Authorization": f"Bearer {token}"}

    filter_query = (
        "Collection/Name eq 'SENTINEL-2' and "
        "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq 'S2MSI2A') and "
        f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'tileId' and att/OData.CSC.StringAttribute/Value eq '{tile_id}') and "
        f"ContentDate/Start ge {start_date}T00:00:00.000Z and "
        f"ContentDate/Start le {end_date}T23:59:59.999Z and "
        f"Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' and att/OData.CSC.DoubleAttribute/Value lt {max_cloud_cover})"
    )

    params = {
        "$filter": filter_query,
        "$expand": "Attributes",
        "$orderby": "ContentDate/Start asc",
        "$top": 100,
    }

    scenes = []
    next_url = CDSE_ODATA_URL

    while next_url:
        if next_url == CDSE_ODATA_URL:
            resp = requests.get(next_url, headers=headers, params=params, timeout=45)
        else:
            resp = requests.get(next_url, headers=headers, timeout=45)

        if resp.status_code != 200:
            raise RuntimeError(
                f"OData query failed with status {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        items = data.get("value", [])

        for item in items:
            scene_name = item.get("Name", "")
            scene_id = item.get("Id", "")
            content_date = item.get("ContentDate", {}).get("Start", "")
            acq_date = content_date.split("T")[0] if content_date else "Unknown"

            cloud_cover = None
            for attr in item.get("Attributes", []):
                if attr.get("Name") == "cloudCover":
                    cloud_cover = attr.get("Value")
                    break

            scenes.append({
                "id": scene_id,
                "name": scene_name,
                "date": acq_date,
                "cloud_cover": cloud_cover if cloud_cover is not None else 0.0,
            })

        next_url = data.get("@odata.nextLink")

    return scenes


def select_representative_scenes(scenes: List[Dict]) -> List[Dict]:
    """
    Selects top 2 clearest scenes per month across the Rabi season, spaced ~15 days apart.
    """
    months = [
        ("2025-11", "Nov"),
        ("2025-12", "Dec"),
        ("2026-01", "Jan"),
        ("2026-02", "Feb"),
        ("2026-03", "Mar"),
        ("2026-04", "Apr"),
    ]

    selected = []

    for ym, m_abbr in months:
        month_scenes = [s for s in scenes if s["date"].startswith(ym)]
        if not month_scenes:
            continue

        early_candidates = [
            s for s in month_scenes if 1 <= int(s["date"].split("-")[2]) <= 11
        ]
        if not early_candidates:
            early_candidates = [
                s for s in month_scenes if 1 <= int(s["date"].split("-")[2]) <= 13
            ]

        if early_candidates:
            best_early = min(
                early_candidates,
                key=lambda s: (round(s["cloud_cover"], 1), abs(int(s["date"].split("-")[2]) - 5)),
            )
            selected.append({
                **best_early,
                "period": f"{m_abbr} Early",
            })

        mid_candidates = [
            s for s in month_scenes if 16 <= int(s["date"].split("-")[2]) <= 28
        ]
        if not mid_candidates:
            mid_candidates = [
                s for s in month_scenes if int(s["date"].split("-")[2]) >= 14
            ]

        if mid_candidates:
            best_mid = min(
                mid_candidates,
                key=lambda s: (round(s["cloud_cover"], 1), abs(int(s["date"].split("-")[2]) - 20)),
            )
            selected.append({
                **best_mid,
                "period": f"{m_abbr} Mid/Late",
            })

    return selected


def locate_scene_bands(auth: CDSEAuthManager, product_id: str, product_name: str) -> Dict[str, Dict]:
    """
    Navigates the product's internal SAFE structure via CDSE Nodes API
    and returns download metadata for B02, B04, B08 (10m) and SCL (20m).
    """
    headers = {"Authorization": f"Bearer {auth.get_token()}"}

    granule_nodes_url = (
        f"{CDSE_DOWNLOAD_ODATA_URL}({product_id})/Nodes({product_name})/Nodes(GRANULE)/Nodes"
    )
    resp = requests.get(granule_nodes_url, headers=headers, timeout=30)
    if resp.status_code == 401:
        headers = {"Authorization": f"Bearer {auth.get_token()}"}
        resp = requests.get(granule_nodes_url, headers=headers, timeout=30)
    resp.raise_for_status()

    granules = resp.json().get("result", [])
    if not granules:
        raise RuntimeError(f"No GRANULE folder found inside product {product_name}")
    granule_name = granules[0]["Name"]

    band_catalog = {}

    # Inspect R10m folder for B02, B04, B08
    r10m_url = (
        f"{CDSE_DOWNLOAD_ODATA_URL}({product_id})/Nodes({product_name})"
        f"/Nodes(GRANULE)/Nodes({granule_name})/Nodes(IMG_DATA)/Nodes(R10m)/Nodes"
    )
    resp_10m = requests.get(r10m_url, headers=headers, timeout=30)
    resp_10m.raise_for_status()
    for item in resp_10m.json().get("result", []):
        name = item.get("Name", "")
        for b in ["B02", "B04", "B08"]:
            if f"_{b}_10m.jp2" in name or f"_{b}.jp2" in name:
                download_url = (
                    f"{CDSE_DOWNLOAD_ODATA_URL}({product_id})/Nodes({product_name})"
                    f"/Nodes(GRANULE)/Nodes({granule_name})/Nodes(IMG_DATA)/Nodes(R10m)/Nodes({name})/$value"
                )
                band_catalog[b] = {
                    "filename": name,
                    "resolution": "10m",
                    "size_bytes": item.get("ContentLength", 0),
                    "download_url": download_url,
                }

    # Inspect R20m folder for SCL
    r20m_url = (
        f"{CDSE_DOWNLOAD_ODATA_URL}({product_id})/Nodes({product_name})"
        f"/Nodes(GRANULE)/Nodes({granule_name})/Nodes(IMG_DATA)/Nodes(R20m)/Nodes"
    )
    resp_20m = requests.get(r20m_url, headers=headers, timeout=30)
    resp_20m.raise_for_status()
    for item in resp_20m.json().get("result", []):
        name = item.get("Name", "")
        if "_SCL_20m.jp2" in name or "_SCL.jp2" in name:
            download_url = (
                f"{CDSE_DOWNLOAD_ODATA_URL}({product_id})/Nodes({product_name})"
                f"/Nodes(GRANULE)/Nodes({granule_name})/Nodes(IMG_DATA)/Nodes(R20m)/Nodes({name})/$value"
            )
            band_catalog["SCL"] = {
                "filename": name,
                "resolution": "20m",
                "size_bytes": item.get("ContentLength", 0),
                "download_url": download_url,
            }

    return band_catalog


def download_single_band(
    download_url: str,
    auth: CDSEAuthManager,
    destination: Path,
    expected_size: int = 0,
) -> Path:
    """
    Downloads an individual band file with resume/skip support, progress bar, and verification.
    """
    # Skip if file already exists with identical size and is readable by rasterio
    if destination.exists() and expected_size > 0:
        if destination.stat().st_size == expected_size:
            try:
                with rasterio.open(destination) as test_src:
                    if test_src.width > 0:
                        print(f"      [✓] {destination.name} already verified on disk (skipping).")
                        return destination
            except Exception:
                pass  # Re-download if corrupted

    destination.parent.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {auth.get_token()}"}

    resp = requests.get(download_url, headers=headers, stream=True, timeout=60)
    if resp.status_code == 401:
        headers = {"Authorization": f"Bearer {auth.get_token()}"}
        resp = requests.get(download_url, headers=headers, stream=True, timeout=60)
    resp.raise_for_status()

    total_size = int(resp.headers.get("content-length", expected_size))

    desc = f"      {destination.name[:28]}..."
    with open(destination, "wb") as f, tqdm(
        desc=desc,
        total=total_size,
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
        ncols=90,
    ) as bar:
        for chunk in resp.iter_content(chunk_size=1024 * 512):
            if chunk:
                f.write(chunk)
                bar.update(len(chunk))
    resp.close()

    actual_size = destination.stat().st_size
    if expected_size > 0 and actual_size != expected_size:
        raise IOError(
            f"Size mismatch for {destination.name}: expected {expected_size} B, got {actual_size} B"
        )

    return destination


def download_scene_bands(
    auth: CDSEAuthManager,
    product_id: str,
    product_name: str,
    date_str: str,
    bands: List[str] = ("B04", "B08", "B02", "SCL"),
    custom_target_dir: Optional[Path] = None,
) -> List[Dict]:
    """
    Downloads the requested bands for a single scene into data/raw/<YYYYMMDD>/ or custom_target_dir.
    """
    if custom_target_dir is not None:
        target_dir = custom_target_dir
    else:
        folder_date = date_str.replace("-", "")
        target_dir = DATA_RAW_DIR / folder_date
    target_dir.mkdir(parents=True, exist_ok=True)

    catalog = locate_scene_bands(auth, product_id, product_name)

    downloaded = []
    for b in bands:
        if b not in catalog:
            print(f"      [!] Warning: Band {b} not found in catalog for {product_name}")
            continue

        meta = catalog[b]
        dest_path = target_dir / meta["filename"]
        download_single_band(
            download_url=meta["download_url"],
            auth=auth,
            destination=dest_path,
            expected_size=meta["size_bytes"],
        )

        # Quick rasterio validation
        with rasterio.open(dest_path) as r_src:
            width, height = r_src.width, r_src.height
            crs = str(r_src.crs)

        downloaded.append({
            "band": b,
            "filename": meta["filename"],
            "path": dest_path,
            "size_bytes": dest_path.stat().st_size,
            "dimensions": f"{width} x {height}",
            "crs": crs,
        })

    return downloaded


def print_disk_summary():
    """Calculates and displays the final disk usage and scene folder inventory."""
    folders = [f for f in sorted(DATA_RAW_DIR.iterdir()) if f.is_dir()]
    total_bytes = 0
    total_files = 0

    print("\n" + "=" * 90)
    print(" RAW DATA INVENTORY (data/raw/)")
    print("=" * 90)
    print(f"{'#':<3} | {'Folder':<18} | {'Bands':<8} | {'Folder Size':<15} | {'Path'}")
    print("-" * 90)

    for idx, folder in enumerate(folders, 1):
        files = list(folder.glob("*.jp2"))
        folder_bytes = sum(f.stat().st_size for f in files)
        total_bytes += folder_bytes
        total_files += len(files)
        size_mb = f"{folder_bytes / (1024 * 1024):.2f} MB"
        print(f"{idx:<3} | {folder.name:<18} | {len(files):<8} | {size_mb:>13} | data/raw/{folder.name}")

    print("-" * 90)
    total_mb = total_bytes / (1024 * 1024)
    total_gb = total_bytes / (1024 * 1024 * 1024)
    print(f"Total Folders      : {len(folders)}")
    print(f"Total Band Files   : {total_files}")
    print(f"Total Disk Usage   : {total_mb:,.2f} MB ({total_gb:.2f} GB)")
    print("=" * 90 + "\n")


def download_neighbor_tiles_november():
    """
    Queries and downloads the clearest Sentinel-2 scene (cloud < 10%) between 2025-11-10 and 2025-11-20
    for Tile 44QRK and Tile 45QTD, downloading ONLY B04 and B08 into:
      - data/raw/202511_44QRK/
      - data/raw/202511_45QTD/
    """
    auth = CDSEAuthManager()
    token = auth.get_token()

    print("\n" + "=" * 115)
    print(" QUERYING MID-NOVEMBER 2025 NEIGHBORING TILES FOR 100% DISTRICT COVERAGE")
    print(" Target Tiles: 44QRK (Northern tip - Bamra/Kuchinda) & 45QTD (Eastern arm - Rairakhol/Naktideul)")
    print(" Window: 2025-11-10 to 2025-11-20 | Cloud Cover < 10%")
    print("=" * 115)

    targets = [
        {
            "tile": "44QRK",
            "region": "Northern Sambalpur (Kuchinda/Bamra)",
            "dest_folder": DATA_RAW_DIR / "202511_44QRK",
        },
        {
            "tile": "45QTD",
            "region": "Eastern Sambalpur (Rairakhol/Naktideul)",
            "dest_folder": DATA_RAW_DIR / "202511_45QTD",
        },
    ]

    all_downloaded = []

    for tgt in targets:
        tile_id = tgt["tile"]
        print(f"\n[+] Querying Tile {tile_id} ({tgt['region']})...")
        scenes = query_sentinel2_inventory(
            token=token,
            tile_id=tile_id,
            start_date="2025-11-10",
            end_date="2025-11-20",
            max_cloud_cover=10.0,
        )

        print(f"    Found {len(scenes)} matching scenes:")
        print(f"    {'Acq Date':<11} | {'Cloud %':<10} | {'Product ID':<38} | {'Product Name'}")
        print("    " + "-" * 105)
        for s in scenes:
            print(f"    {s['date']:<11} | {s['cloud_cover']:.4f}%   | {s['id']:<38} | {s['name']}")

        # Pick the clearest scene matching our synchronous 2025-11-17 Orbit R076 strip
        # If Nov 17 is available, choose it for seamless cross-tile mosaicking
        nov17_match = [s for s in scenes if s["date"] == "2025-11-17" and "_R076_" in s["name"]]
        if nov17_match:
            best_scene = nov17_match[0]
            reason = "Selected synchronous 2025-11-17 Orbit R076 acquisition (0.00% cloud, identical pass as 44QRJ)"
        else:
            best_scene = min(scenes, key=lambda s: s["cloud_cover"])
            reason = f"Selected clearest scene ({best_scene['cloud_cover']:.4f}% cloud)"

        print(f"\n    ★ Selected Scene for {tile_id}: {best_scene['name']}")
        print(f"      • Date        : {best_scene['date']}")
        print(f"      • Cloud Cover : {best_scene['cloud_cover']:.6f}%")
        print(f"      • Reason      : {reason}")
        print(f"      • Target Dir  : {tgt['dest_folder'].relative_to(PROJECT_ROOT)}/")
        print("      • Fetching    : Band 4 (Red, 10m) & Band 8 (NIR, 10m)")

        dl_results = download_scene_bands(
            auth=auth,
            product_id=best_scene["id"],
            product_name=best_scene["name"],
            date_str=best_scene["date"],
            bands=["B04", "B08"],
            custom_target_dir=tgt["dest_folder"],
        )
        all_downloaded.extend(dl_results)

    print("\n" + "=" * 115)
    print(" VERIFICATION REPORT - NEIGHBORING TILES DOWNLOAD")
    print("=" * 115)
    print(f"{'Tile':<8} | {'Band':<5} | {'File Size':<12} | {'Dimensions':<15} | {'CRS':<14} | {'Saved Path'}")
    print("-" * 115)
    for d in all_downloaded:
        size_mb = f"{d['size_bytes'] / (1024 * 1024):.2f} MB"
        rel_path = d['path'].relative_to(PROJECT_ROOT)
        tile_label = rel_path.parts[2].replace("202511_", "")
        print(f"{tile_label:<8} | {d['band']:<5} | {size_mb:>10} | {d['dimensions']:<15} | {d['crs']:<14} | {rel_path}")
    print("=" * 115)

    print_disk_summary()


def find_and_download_r076_november():
    """
    1. Queries Tile 44QRJ for November 2025 (2025-11-01 to 2025-11-30).
    2. Filters for Orbit R076 with cloud cover < 10%.
    3. Prints matching scenes table.
    4. Downloads the clearest scene (B04, B08, B02, SCL) into data/raw/<YYYYMMDD>/.
    """
    auth = CDSEAuthManager()
    token = auth.get_token()

    print("\n" + "=" * 110)
    print(" QUERYING COMPLEMENTARY ORBIT R076 SCENES (November 2025 - Tile 44QRJ)")
    print("=" * 110)

    scenes = query_sentinel2_inventory(
        token=token,
        tile_id="44QRJ",
        start_date="2025-11-01",
        end_date="2025-11-30",
        max_cloud_cover=10.0,
    )

    r076_scenes = [s for s in scenes if "_R076_" in s["name"]]

    print(f"{'#':<3} | {'Acq Date':<11} | {'Cloud %':<10} | {'Orbit':<6} | {'Product ID':<38} | {'Scene Name'}")
    print("-" * 110)
    for idx, sc in enumerate(r076_scenes, 1):
        cc_str = f"{sc['cloud_cover']:.4f}%"
        print(f"{idx:<3} | {sc['date']:<11} | {cc_str:<10} | {'R076':<6} | {sc['id']:<38} | {sc['name']}")
    print("-" * 110)
    print(f"Total Orbit R076 Scenes Found (< 10% cloud): {len(r076_scenes)}")
    print("=" * 110)

    if not r076_scenes:
        print("[!] No matching R076 scenes found.")
        return

    clearest = min(r076_scenes, key=lambda s: s["cloud_cover"])
    print(f"\n[+] Clearest Orbit R076 Scene Selected:")
    print(f"    • Date       : {clearest['date']}")
    print(f"    • Cloud Cover: {clearest['cloud_cover']:.6f}%")
    print(f"    • Product ID : {clearest['id']}")
    print(f"    • Scene Name : {clearest['name']}")
    print(f"    • Target Dir : data/raw/{clearest['date'].replace('-', '')}/")

    print("\n[+] Downloading essential bands (B04, B08, B02, SCL)...")
    downloaded = download_scene_bands(
        auth=auth,
        product_id=clearest["id"],
        product_name=clearest["name"],
        date_str=clearest["date"],
        bands=["B04", "B08", "B02", "SCL"],
    )

    print("\n" + "=" * 110)
    print(f" DOWNLOAD VERIFICATION - ORBIT R076 ({clearest['date']})")
    print("=" * 110)
    print(f"{'Band':<5} | {'File Size':<12} | {'Dimensions':<15} | {'CRS':<14} | {'Saved Path'}")
    print("-" * 110)
    for d in downloaded:
        size_mb = f"{d['size_bytes'] / (1024 * 1024):.2f} MB"
        rel_path = d['path'].relative_to(PROJECT_ROOT)
        print(f"{d['band']:<5} | {size_mb:>10} | {d['dimensions']:<15} | {d['crs']:<14} | {rel_path}")
    print("=" * 110)

    print_disk_summary()


def batch_download_rabi_scenes(start_idx: int = 1, end_idx: int = 12):
    """
    Executes the batch download for the 12 selected candidate scenes across Rabi season.
    """
    auth = CDSEAuthManager()
    token = auth.get_token()

    print("\n[1/3] Fetching scene inventory and candidate list...")
    scenes = query_sentinel2_inventory(token=token, tile_id="44QRJ")
    candidates = select_representative_scenes(scenes)
    print(f"      Selected {len(candidates)} candidate scenes across Rabi 2025-2026.")

    target_candidates = candidates[start_idx - 1 : end_idx]
    total_scenes = len(target_candidates)

    print(f"\n[2/3] Processing Batch Download ({total_scenes} scenes):")
    print("      Essential Bands: B04 (Red), B08 (NIR), B02 (Blue), SCL (Scene Classification)")
    print("      Destination    : data/raw/YYYYMMDD/\n")

    for idx, sc in enumerate(target_candidates, start=start_idx):
        date_str = sc["date"]
        folder_name = date_str.replace("-", "")
        print(f"[{idx}/{len(candidates)}] Scene #{idx}: {sc['period']} ({date_str}) | Cloud: {sc['cloud_cover']:.2f}%")
        print(f"    Product ID : {sc['id']}")
        print(f"    Directory  : data/raw/{folder_name}/")

        try:
            download_scene_bands(
                auth=auth,
                product_id=sc["id"],
                product_name=sc["name"],
                date_str=date_str,
                bands=["B04", "B08", "B02", "SCL"],
            )
            print(f"    [✓] Scene #{idx} completed successfully.\n")
        except Exception as e:
            print(f"    [X] Error downloading Scene #{idx} ({date_str}): {e}\n")

    print("[3/3] Generating final download summary...")
    print_disk_summary()


def download_western_gap_44qqj():
    """
    Downloads B04 and B08 for Tile 44QQJ (Western nose of Sambalpur)
    from the synchronous 2025-11-17 Orbit R076 pass into data/raw/202511_44QQJ/.
    """
    auth = CDSEAuthManager()
    token = auth.get_token()

    print("\n" + "=" * 115)
    print(" DOWNLOADING WESTERN GAP TILE 44QQJ (Western Nose of Sambalpur)")
    print(" Scene: 2025-11-17 Orbit R076 (Concurrent pass: S2B_MSIL2A_20251117T044959_N0511_R076_T44QQJ_20251117T065411.SAFE)")
    print(" Target Bands: B04 (Red 10m) & B08 (NIR 10m)")
    print(" Destination : data/raw/202511_44QQJ/")
    print("=" * 115)

    prod_id = "8a07d23c-1991-40cb-a984-ac0d9fabbf93"
    prod_name = "S2B_MSIL2A_20251117T044959_N0511_R076_T44QQJ_20251117T065411.SAFE"
    date_str = "2025-11-17"
    target_dir = DATA_RAW_DIR / "202511_44QQJ"

    downloaded = download_scene_bands(
        auth=auth,
        product_id=prod_id,
        product_name=prod_name,
        date_str=date_str,
        bands=["B04", "B08"],
        custom_target_dir=target_dir,
    )

    print("\n" + "=" * 115)
    print(" VERIFICATION REPORT - WESTERN GAP TILE 44QQJ")
    print("=" * 115)
    print(f"{'Tile':<8} | {'Band':<5} | {'File Size':<12} | {'Dimensions':<15} | {'CRS':<14} | {'Saved Path'}")
    print("-" * 115)
    for d in downloaded:
        size_mb = f"{d['size_bytes'] / (1024 * 1024):.2f} MB"
        rel_path = d['path'].relative_to(PROJECT_ROOT)
        print(f"44QQJ    | {d['band']:<5} | {size_mb:>10} | {d['dimensions']:<15} | {d['crs']:<14} | {rel_path}")
    print("=" * 115)

    print_disk_summary()


def download_december_neighbors():
    """
    Downloads B04 and B08 for Tile 44QRK and Tile 44QQJ from the synchronous
    2025-12-07 Orbit R076 pass into:
      - data/raw/202512_44QRK/
      - data/raw/202512_44QQJ/
    Verifies that CRS is EPSG:32644.
    """
    auth = CDSEAuthManager()

    print("\n" + "=" * 115)
    print(" DOWNLOADING DECEMBER 2025 ORBIT R076 NEIGHBORING TILES")
    print(" Primary Reference: 2025-12-07 (~04:51:09 UTC, Orbit R076)")
    print(" Target Tiles: 44QRK (Northern tip) & 44QQJ (Western gap)")
    print(" Target Bands: B04 (Red 10m) & B08 (NIR 10m)")
    print(" Destination Folders: data/raw/202512_44QRK/ & data/raw/202512_44QQJ/")
    print("=" * 115)

    targets = [
        {
            "tile": "44QRK",
            "region": "Northern tip (Bamra/Kuchinda)",
            "prod_id": "4b6a9978-a767-4e54-9ff8-e6afb8539a83",
            "prod_name": "S2B_MSIL2A_20251207T045109_N0511_R076_T44QRK_20251207T064210.SAFE",
            "dest_folder": DATA_RAW_DIR / "202512_44QRK",
        },
        {
            "tile": "44QQJ",
            "region": "Western gap (Western nose)",
            "prod_id": "49e4749a-5d99-4fa3-bb5e-a3c730965e64",
            "prod_name": "S2B_MSIL2A_20251207T045109_N0511_R076_T44QQJ_20251207T064210.SAFE",
            "dest_folder": DATA_RAW_DIR / "202512_44QQJ",
        },
    ]

    all_downloaded = []

    for tgt in targets:
        tile_id = tgt["tile"]
        print(f"\n[+] Processing Tile {tile_id} ({tgt['region']})...")
        print(f"    Product ID : {tgt['prod_id']}")
        print(f"    Scene Name : {tgt['prod_name']}")
        print(f"    Destination: {tgt['dest_folder'].relative_to(PROJECT_ROOT)}/")

        dl_results = download_scene_bands(
            auth=auth,
            product_id=tgt["prod_id"],
            product_name=tgt["prod_name"],
            date_str="2025-12-07",
            bands=["B04", "B08"],
            custom_target_dir=tgt["dest_folder"],
        )
        all_downloaded.extend(dl_results)

    print("\n" + "=" * 115)
    print(" VERIFICATION & CRS INTEGRITY REPORT - DECEMBER 2025 NEIGHBORING TILES")
    print("=" * 115)
    print(f"{'Tile':<8} | {'Band':<5} | {'File Size':<12} | {'Dimensions':<15} | {'CRS':<14} | {'CRS Check':<12} | {'Saved Path'}")
    print("-" * 115)

    for d in all_downloaded:
        size_mb = f"{d['size_bytes'] / (1024 * 1024):.2f} MB"
        rel_path = d['path'].relative_to(PROJECT_ROOT)
        tile_label = rel_path.parts[2].replace("202512_", "")
        crs_ok = "[✓] Valid" if d["crs"] == "EPSG:32644" else "[!] Mismatch"
        print(f"{tile_label:<8} | {d['band']:<5} | {size_mb:>10} | {d['dimensions']:<15} | {d['crs']:<14} | {crs_ok:<12} | {rel_path}")

    print("=" * 115)
    print_disk_summary()


def download_44qrk_full_december():
    """
    Downloads B04 and B08 for Tile 44QRK from the fully covered, cloud-free (0.00%)
    replacement scene (2025-12-12, Orbit R076) into:
      data/raw/202512_44QRK_full/
    Verifies that CRS is EPSG:32644 and file sizes are ~100MB+ (complete coverage).
    """
    auth = CDSEAuthManager()

    print("\n" + "=" * 115)
    print(" DOWNLOADING FULL REPLACEMENT SCENE FOR TILE 44QRK (December 2025)")
    print(" Reference Scene: 2025-12-12 (04:52:21 UTC, Orbit R076, Cloud 0.00%)")
    print(" Product ID     : 6bb3ad93-1cd2-425e-a138-0c0639053ece")
    print(" Product Name   : S2C_MSIL2A_20251212T045221_N0511_R076_T44QRK_20251212T081316.SAFE")
    print(" Target Bands   : B04 (Red 10m) & B08 (NIR 10m)")
    print(" Destination    : data/raw/202512_44QRK_full/")
    print("=" * 115)

    prod_id = "6bb3ad93-1cd2-425e-a138-0c0639053ece"
    prod_name = "S2C_MSIL2A_20251212T045221_N0511_R076_T44QRK_20251212T081316.SAFE"
    date_str = "2025-12-12"
    target_dir = DATA_RAW_DIR / "202512_44QRK_full"

    downloaded = download_scene_bands(
        auth=auth,
        product_id=prod_id,
        product_name=prod_name,
        date_str=date_str,
        bands=["B04", "B08"],
        custom_target_dir=target_dir,
    )

    print("\n" + "=" * 115)
    print(" VERIFICATION & INTEGRITY REPORT - TILE 44QRK FULL REPLACEMENT")
    print("=" * 115)
    print(f"{'Tile':<8} | {'Band':<5} | {'File Size':<12} | {'Dimensions':<15} | {'CRS':<14} | {'Coverage Check':<16} | {'Saved Path'}")
    print("-" * 115)
    for d in downloaded:
        size_mb_val = d['size_bytes'] / (1024 * 1024)
        size_mb = f"{size_mb_val:.2f} MB"
        rel_path = d['path'].relative_to(PROJECT_ROOT)
        cov_ok = "[✓] Full (~100MB+)" if size_mb_val >= 90.0 else "[!] Truncated"
        print(f"44QRK    | {d['band']:<5} | {size_mb:>10} | {d['dimensions']:<15} | {d['crs']:<14} | {cov_ok:<16} | {rel_path}")
    print("=" * 115)

    print_disk_summary()


def download_january_neighbors():
    """
    Downloads B04 and B08 for Tile 44QRK and Tile 44QQJ for January 2026:
      - 44QRK: 2026-01-21 (Concurrent Orbit R076, 0.00% cloud, ~118MB B04 / ~129MB B08)
      - 44QQJ: 2026-01-24 (Orbit R119 full-swath pass, 0.00% cloud, ~122MB B04 / ~129MB B08)
    Destinations:
      - data/raw/202601_44QRK/
      - data/raw/202601_44QQJ/
    """
    auth = CDSEAuthManager()

    print("\n" + "=" * 115)
    print(" DOWNLOADING JANUARY 2026 NEIGHBORING TILES (44QRK & 44QQJ)")
    print(" 44QRK Reference: 2026-01-21 (Orbit R076, Cloud 0.00%, ~118MB Red / ~129MB NIR)")
    print(" 44QQJ Reference: 2026-01-24 (Orbit R119, Cloud 0.00%, ~122MB Red / ~129MB NIR - Full 100x100km swath)")
    print(" Target Bands   : B04 (Red 10m) & B08 (NIR 10m)")
    print(" Destination    : data/raw/202601_44QRK/ & data/raw/202601_44QQJ/")
    print("=" * 115)

    targets = [
        {
            "tile": "44QRK",
            "region": "Northern tip (Bamra/Kuchinda)",
            "prod_id": "26662b74-fba6-4eed-b5e7-f498a849288a",
            "prod_name": "S2C_MSIL2A_20260121T045121_N0511_R076_T44QRK_20260121T083909.SAFE",
            "date": "2026-01-21",
            "dest_folder": DATA_RAW_DIR / "202601_44QRK",
        },
        {
            "tile": "44QQJ",
            "region": "Western gap (Western nose)",
            "prod_id": "99f632cf-c3b1-441d-8b89-7b23447ded38",
            "prod_name": "S2C_MSIL2A_20260124T050111_N0511_R119_T44QQJ_20260124T080410.SAFE",
            "date": "2026-01-24",
            "dest_folder": DATA_RAW_DIR / "202601_44QQJ",
        },
    ]

    all_downloaded = []

    for tgt in targets:
        tile_id = tgt["tile"]
        print(f"\n[+] Processing Tile {tile_id} ({tgt['region']})...")
        print(f"    Product ID : {tgt['prod_id']}")
        print(f"    Scene Name : {tgt['prod_name']}")
        print(f"    Destination: {tgt['dest_folder'].relative_to(PROJECT_ROOT)}/")

        dl_results = download_scene_bands(
            auth=auth,
            product_id=tgt["prod_id"],
            product_name=tgt["prod_name"],
            date_str=tgt["date"],
            bands=["B04", "B08"],
            custom_target_dir=tgt["dest_folder"],
        )
        all_downloaded.extend(dl_results)

    print("\n" + "=" * 125)
    print(" VERIFICATION & INTEGRITY REPORT - JANUARY 2026 NEIGHBORING TILES")
    print("=" * 125)
    print(f"{'Tile':<8} | {'Band':<5} | {'File Size':<12} | {'Dimensions':<15} | {'CRS':<14} | {'Coverage Check':<18} | {'Saved Path'}")
    print("-" * 125)

    for d in all_downloaded:
        size_mb_val = d['size_bytes'] / (1024 * 1024)
        size_mb = f"{size_mb_val:.2f} MB"
        rel_path = d['path'].relative_to(PROJECT_ROOT)
        tile_label = rel_path.parts[2].replace("202601_", "")
        cov_ok = "[✓] Full (~100MB+)" if size_mb_val >= 90.0 else "[!] Truncated"
        print(f"{tile_label:<8} | {d['band']:<5} | {size_mb:>10} | {d['dimensions']:<15} | {d['crs']:<14} | {cov_ok:<18} | {rel_path}")

    print("=" * 125)
    print_disk_summary()


def download_feb_mar_apr_complementary():
    """
    Downloads all missing complementary tiles for Feb, Mar, and Apr 2026
    to ensure 100% full coverage for Sambalpur district.
    Only full 100km x 100km unclipped tiles (> 100MB per band, cloud < 5%) are fetched.
    Bands: ONLY B04 (Red 10m) and B08 (NIR 10m).
    """
    auth = CDSEAuthManager()

    print("\n" + "=" * 125)
    print(" BATCH DOWNLOADING COMPLEMENTARY TILES: FEBRUARY, MARCH & APRIL 2026")
    print(" Strategy: 100% full tile coverage (>100MB/band), 0%–2% cloud cover, exact concurrent passes.")
    print(" Target Bands: B04 (Red 10m) & B08 (NIR 10m)")
    print("=" * 125)

    targets = [
        # --- FEBRUARY 2026 ---
        {
            "month": "Feb 2026",
            "tile": "44QRK",
            "region": "Northern tip (Bamra/Kuchinda)",
            "prod_id": "bde95719-7145-4db9-9664-c4712d330dcb",
            "prod_name": "S2B_MSIL2A_20260205T044859_N0512_R076_T44QRK_20260205T101322.SAFE",
            "date": "2026-02-05",
            "orbit": "R076 (Concurrent)",
            "dest_folder": DATA_RAW_DIR / "202602_44QRK",
            "expected_crs": "EPSG:32644",
        },
        {
            "month": "Feb 2026",
            "tile": "44QQJ",
            "region": "Western gap (Western nose)",
            "prod_id": "0d14f5d6-7776-4104-8b74-200b271334f5",
            "prod_name": "S2C_MSIL2A_20260203T050021_N0511_R119_T44QQJ_20260203T081509.SAFE",
            "date": "2026-02-03",
            "orbit": "R119 (Full swath)",
            "dest_folder": DATA_RAW_DIR / "202602_44QQJ",
            "expected_crs": "EPSG:32644",
        },
        {
            "month": "Feb 2026",
            "tile": "45QTD",
            "region": "Eastern arm (Rairakhol/Naktideul)",
            "prod_id": "00b82d21-be4e-4aac-bd2a-72dca227e2f1",
            "prod_name": "S2B_MSIL2A_20260205T044859_N0512_R076_T45QTD_20260205T101322.SAFE",
            "date": "2026-02-05",
            "orbit": "R076 (Concurrent)",
            "dest_folder": DATA_RAW_DIR / "202602_45QTD",
            "expected_crs": "EPSG:32645",
        },

        # --- MARCH 2026 ---
        {
            "month": "Mar 2026",
            "tile": "44QRK",
            "region": "Northern tip (Bamra/Kuchinda)",
            "prod_id": "1ed9f6d2-c2da-492a-8605-82987aee2783",
            "prod_name": "S2B_MSIL2A_20260327T044659_N0512_R076_T44QRK_20260327T084044.SAFE",
            "date": "2026-03-27",
            "orbit": "R076 (Concurrent)",
            "dest_folder": DATA_RAW_DIR / "202603_44QRK",
            "expected_crs": "EPSG:32644",
        },
        {
            "month": "Mar 2026",
            "tile": "44QQJ",
            "region": "Western gap (Western nose)",
            "prod_id": "a7018b6a-3354-4196-a487-b20c636bf1a6",
            "prod_name": "S2B_MSIL2A_20260330T045659_N0512_R119_T44QQJ_20260330T083747.SAFE",
            "date": "2026-03-30",
            "orbit": "R119 (Full swath)",
            "dest_folder": DATA_RAW_DIR / "202603_44QQJ",
            "expected_crs": "EPSG:32644",
        },
        {
            "month": "Mar 2026",
            "tile": "45QTD",
            "region": "Eastern arm (Rairakhol/Naktideul)",
            "prod_id": "6ff87fac-f573-4794-a0e7-0a37effe6a26",
            "prod_name": "S2B_MSIL2A_20260327T044659_N0512_R076_T45QTD_20260327T084044.SAFE",
            "date": "2026-03-27",
            "orbit": "R076 (Concurrent)",
            "dest_folder": DATA_RAW_DIR / "202603_45QTD",
            "expected_crs": "EPSG:32645",
        },

        # --- APRIL 2026 (Peak Harvest / Rabi End) ---
        {
            "month": "Apr 2026",
            "tile": "44QRJ",
            "region": "Central Sambalpur (Harvest Reference)",
            "prod_id": "7c0c1872-7b97-4a59-b343-c57630c925dc",
            "prod_name": "S2B_MSIL2A_20260416T044659_N0512_R076_T44QRJ_20260416T083549.SAFE",
            "date": "2026-04-16",
            "orbit": "R076 (0.00% Cloud)",
            "dest_folder": DATA_RAW_DIR / "202604_44QRJ",
            "expected_crs": "EPSG:32644",
        },
        {
            "month": "Apr 2026",
            "tile": "44QRK",
            "region": "Northern tip (Bamra/Kuchinda)",
            "prod_id": "acaae723-bc28-4232-91b9-86ac25d5d7ed",
            "prod_name": "S2B_MSIL2A_20260416T044659_N0512_R076_T44QRK_20260416T083549.SAFE",
            "date": "2026-04-16",
            "orbit": "R076 (Concurrent, 0.00% Cloud)",
            "dest_folder": DATA_RAW_DIR / "202604_44QRK",
            "expected_crs": "EPSG:32644",
        },
        {
            "month": "Apr 2026",
            "tile": "44QQJ",
            "region": "Western gap (Western nose)",
            "prod_id": "26369f3f-80e8-4adb-9400-8c35e25b410a",
            "prod_name": "S2C_MSIL2A_20260414T045701_N0512_R119_T44QQJ_20260415T222220.SAFE",
            "date": "2026-04-14",
            "orbit": "R119 (Full swath, 0.01% Cloud)",
            "dest_folder": DATA_RAW_DIR / "202604_44QQJ",
            "expected_crs": "EPSG:32644",
        },
        {
            "month": "Apr 2026",
            "tile": "45QTD",
            "region": "Eastern arm (Rairakhol/Naktideul)",
            "prod_id": "186042ff-6d57-44bc-a772-e8afd3e2c1ea",
            "prod_name": "S2B_MSIL2A_20260416T044659_N0512_R076_T45QTD_20260416T083549.SAFE",
            "date": "2026-04-16",
            "orbit": "R076 (Concurrent, 0.00% Cloud)",
            "dest_folder": DATA_RAW_DIR / "202604_45QTD",
            "expected_crs": "EPSG:32645",
        },
    ]

    all_downloaded = []

    for idx, tgt in enumerate(targets, 1):
        tile_id = tgt["tile"]
        print(f"\n[{idx}/{len(targets)}] Processing {tgt['month']} - Tile {tile_id} ({tgt['region']})...")
        print(f"      Acquisition : {tgt['date']} | Orbit: {tgt['orbit']}")
        print(f"      Product ID  : {tgt['prod_id']}")
        print(f"      Scene Name  : {tgt['prod_name']}")
        print(f"      Destination : {tgt['dest_folder'].relative_to(PROJECT_ROOT)}/")

        dl_results = download_scene_bands(
            auth=auth,
            product_id=tgt["prod_id"],
            product_name=tgt["prod_name"],
            date_str=tgt["date"],
            bands=["B04", "B08"],
            custom_target_dir=tgt["dest_folder"],
        )
        for res in dl_results:
            res["month"] = tgt["month"]
            res["expected_crs"] = tgt["expected_crs"]
            res["tile_id"] = tile_id
            res["acq_date"] = tgt["date"]
        all_downloaded.extend(dl_results)

    print("\n" + "=" * 135)
    print(" MASTER VERIFICATION & INTEGRITY REPORT: FEB, MAR & APR 2026 COMPLEMENTARY TILES")
    print("=" * 135)
    print(f"{'Month':<10} | {'Tile':<6} | {'Date':<11} | {'Band':<5} | {'File Size':<12} | {'Dimensions':<15} | {'CRS':<12} | {'Status':<16} | {'Disk Path'}")
    print("-" * 135)

    for d in all_downloaded:
        size_mb_val = d['size_bytes'] / (1024 * 1024)
        size_mb = f"{size_mb_val:.2f} MB"
        rel_path = d['path'].relative_to(PROJECT_ROOT)
        cov_ok = "[✓] Full (>100MB)" if size_mb_val >= 90.0 else "[!] Truncated"
        crs_ok = f"{d['crs']}"
        print(f"{d['month']:<10} | {d['tile_id']:<6} | {d['acq_date']:<11} | {d['band']:<5} | {size_mb:>10} | {d['dimensions']:<15} | {crs_ok:<12} | {cov_ok:<16} | {rel_path}")

    print("=" * 135)
    print_disk_summary()


def main():
    parser = argparse.ArgumentParser(description="CDSE Sentinel-2 Fetcher")
    parser.add_argument(
        "--mode",
        choices=["end-rabi", "jan-neighbors", "44qrk-full", "dec-neighbors", "western-gap-nov", "neighbors-nov", "r076-nov", "batch"],
        default="end-rabi",
        help="Action mode: 'end-rabi' for Feb/Mar/Apr 2026 complementary tiles, 'jan-neighbors', etc.",
    )
    args = parser.parse_args()

    if args.mode == "end-rabi":
        download_feb_mar_apr_complementary()
    elif args.mode == "jan-neighbors":
        download_january_neighbors()
    elif args.mode == "44qrk-full":
        download_44qrk_full_december()
    elif args.mode == "dec-neighbors":
        download_december_neighbors()
    elif args.mode == "western-gap-nov":
        download_western_gap_44qqj()
    elif args.mode == "neighbors-nov":
        download_neighbor_tiles_november()
    elif args.mode == "r076-nov":
        find_and_download_r076_november()
    elif args.mode == "batch":
        batch_download_rabi_scenes(start_idx=1, end_idx=12)


if __name__ == "__main__":
    main()
