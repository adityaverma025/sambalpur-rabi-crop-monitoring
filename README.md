<br>

# Multi-Temporal Sentinel-2 Satellite Monitoring of Rabi Cropland Phenology & Extent
### Sambalpur District, Odisha (Rabi Season 2025–2026)

![Study Area](data/output/sambalpur_rabi_cropland_map.png)

---

## 1. Project Overview

This project presents an end-to-end remote sensing workflow to map and monitor the **Rabi (winter/summer) agricultural season (November 2025 – April 2026)** across **Sambalpur District, Odisha, India**. 

By processing multi-temporal 10m **Copernicus Sentinel-2 MSI Level-2A** imagery across six consecutive months, this study isolates active irrigated agricultural fields from Sambalpur's vast deciduous forest cover, quantifies total cropped acreage, and reconstructs the real phenological growth curve of canal-fed **Dalua (Rabi) rice**.

---

## 2. Study Area Context & Agronomic Characteristics

- **Location:** Sambalpur District, Western Odisha (~6,726 km²).
- **Topography & Land Cover:** The northern and eastern sectors (Bamra, Kuchinda, Rairakhol) are dominated by hilly, dry deciduous tropical forest cover (~49% of the total district). The central and south-western plains are dominated by the **Hirakud Dam and Reservoir** and its extensive canal command network (Bargarh Main Canal and distributaries).
- **The Cropping System:** Unlike rainfed Kharif rice (grown during the southwest monsoon), Rabi cultivation in Sambalpur consists primarily of **Dalua (winter/summer) paddy**, strictly reliant on controlled canal releases from Hirakud Reservoir. 

---

## 3. Data Acquisition & Sensor Specifications

Satellite imagery was retrieved from the **Copernicus Data Space Ecosystem (CDSE)**:
- **Constellation:** Sentinel-2A / Sentinel-2B / Sentinel-2C MSI (Multi-Spectral Instrument)
- **Product Level:** Level-2A (Bottom-Of-Atmosphere / Surface Reflectance)
- **Spatial Resolution:** 10 meters (Bands 4 and 8)
- **Target Window:** Monthly cloud-free observations from November 2025 to April 2026

### Multi-Tile Spatial Coverage Strategy
Sambalpur's geographic footprint straddles multiple Sentinel-2 tiles and UTM projection zones:
- **Primary Tile:** `T44QRJ` (~74.5% of district, including the entire canal command belt, UTM 44N)
- **Northern Arm (Bamra/Kuchinda):** `T44QRK` (UTM 44N)
- **Western Border Slivers:** `T44QQJ` (UTM 44N)
- **Eastern Arm (Rairakhol):** `T45QTD` (Native in UTM Zone 45N)

---

## 4. Methodological Workflow & Challenges Overcome

```
Raw Sentinel-2 L2A (B04 & B08)
│
▼
Reprojection & Alignment (EPSG:32644)
│
▼
NDVI Calculation
│
▼
Virtual Raster (VRT) Mosaicking
│
▼
Projected Vector Mask Clipping
│
▼
Phenological Cropland Isolation
│
▼
Acreage Quantification & Time-Series Curve
```

### Technical Issues Encountered & Solutions Implemented

#### A. Reprojection & Datum Alignment
Tile `T45QTD` sits across the longitudinal boundary in UTM Zone 45N (`EPSG:32645`). Mosaicking it directly with Zone 44N tiles caused projection shifts and spatial warping. 
- **Fix:** Reprojected `T45QTD` into `EPSG:32644` using `gdalwarp` with bilinear resampling, establishing a unified meter-based coordinate reference system across all tiles.

#### B. The Black Border / Merge Overwrite Glitch
When running standard raster merges across adjacent Sentinel-2 tiles, the zero-value (`0`) bounding boxes of upper scenes completely overwrote and erased valid underlying pixels (e.g., cutting off northern tile `44QRK`).
- **Fix:** Replaced direct physical merges with **Virtual Rasters (VRT)**. Building a VRT dynamically indexes spatial extents and explicitly maps transparent NoData boundaries (`-9999`), preventing zero-padding overwrite errors.

#### C. Spatial Extent Bounding Mismatch During Masking
When clipping the mosaic using `Clip Raster by Mask Layer`, QGIS truncated the top and left borders because the input GeoJSON boundary was natively in geographic degrees (`EPSG:4326`), whereas the satellite mosaic was in projected meters (`EPSG:32644`).
- **Fix:** Exported a dedicated boundary vector reprojected into `EPSG:32644` (`sambalpur_utm44n.geojson`) and explicitly forced output clipping extents to match the projected vector bounds.

#### D. Identifying & Correcting Truncated Satellite Passes
During the December pass, Sentinel-2 along-track sensor activation cut off midway across tile `44QRK`. 
- **Fix:** Filtered scene metadata to discard truncated along-track swaths (<60 MB per band) and retrieved full 100 km × 100 km scenes (10,980 × 10,980 pixels) to maintain complete spatial integrity.

---

## 5. Phenological Cropland Classification

### Overcoming the "Forest Dilution Effect"
An initial unclassified district-wide NDVI calculation produced an unexpected inverted curve where February was the lowest point (μ = 0.216) and November was the highest (μ = 0.408). 

**The Root Cause:** Sambalpur's vast tropical deciduous forests retain moisture through November post-monsoon (NDVI > 0.65), but shed their leaves during the dry winter heat of January and February (NDVI < 0.25). Averaging all 65 million pixels across the district caused the forest leaf-drop signal to completely mask the agricultural greening in the valley.

---

## 6. Results & Findings

### A. Rabi Cropland Acreage Quantification
- **Total Classified Cropland Pixels:** 2,899,073 pixels (at 10m × 10m)
- **Total Rabi Cropped Area:** **28,990.73 Hectares (289.91 km²)**
- **Spatial Pattern:** The isolated cropland is predominantly clustered across the alluvial lowlands of Dhankauda, Maneswar, and Jujomura blocks along the primary and distributary channels of the Hirakud canal network.

### B. Monthly Zonal Statistics Over Isolated Cropland

| Month | Agronomic Phase | Mean NDVI ± 1σ | Median | IQR [Q1, Q3] | 10th–90th Percentile |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Nov 2025** | Sowing / Land Preparation | **0.2200 ± 0.0600** | 0.2150 | [0.180, 0.260] | 0.145 – 0.295 |
| **Dec 2025** | Emergence & Early Tillering | **0.3600 ± 0.0700** | 0.3550 | [0.310, 0.410] | 0.270 – 0.450 |
| **Jan 2026** | Active Vegetative Growth | **0.5200 ± 0.0800** | 0.5250 | [0.465, 0.575] | 0.415 – 0.620 |
| **Feb 2026** | Peak Canopy / Heading (SEASONAL PEAK) | **0.6100 ± 0.0700** | 0.6150 | [0.560, 0.660] | 0.515 – 0.700 |
| **Mar 2026** | Grain Ripening & Senescence | **0.3800 ± 0.0800** | 0.3750 | [0.325, 0.435] | 0.275 – 0.485 |
| **Apr 2026** | Harvest & Post-Harvest Fallow | **0.2100 ± 0.0600** | 0.2050 | [0.170, 0.250] | 0.135 – 0.285 |

![Phenology Curve](data/output/sambalpur_rabi_crop_phenology_isolated.png)

### C. Agronomic Interpretation of the Trajectory
1. **Sowing and Early Emergence (November – December):**  
   Following Kharif post-harvest operations, field preparation and early seedbed development initiate under moderate soil moisture, exhibiting a baseline mean NDVI increase from **0.22** to **0.36**.
2. **Vegetative Surge & Peak Heading (January – February):**  
   Canopy density accelerates rapidly through January (**μ = 0.52**) as vegetative tillering expands. The crop reaches its definitive biological peak in February (**μ = 0.61**, 90th percentile = **0.70**), marking full canopy closure and panicle heading.
3. **Maturity, Senescence, and Harvest (March – April):**  
   Grain filling and physiological yellowing drive a pronounced drop in photosynthetic chlorophyll reflectance by March (**μ = 0.38**). Following widespread harvesting operations, fields return to post-harvest dry fallow baseline levels by April (**μ = 0.21**).

---

## 7. Repository Structure

```
sambalpur-rabi-crop-monitoring/
├── .env                                       # CDSE Keycloak API credentials
├── .gitignore                                 # Git ignore patterns
├── README.md                                  # Project documentation & findings
├── requirements.txt                           # Python dependencies (rasterio, geopandas, etc.)
├── sambalpur-rabi-crop-monitoring.qgz          # QGIS analytical workspace
├── data/
│   ├── output/                                # Final district-wide products
│   │   ├── NOV.tif                            # November 2025 district NDVI mosaic (10m)
│   │   ├── DEC.tif                            # December 2025 district NDVI mosaic (10m)
│   │   ├── JAN.tif                            # January 2026 district NDVI mosaic (10m)
│   │   ├── FEB.tif                            # February 2026 district NDVI mosaic (10m)
│   │   ├── MAR.tif                            # March 2026 district NDVI mosaic (10m)
│   │   ├── APR.tif                            # April 2026 district NDVI mosaic (10m)
│   │   ├── sambalpur_rabi_cropland_mask.tif   # 10m binary cropland mask (uint8: 1=crop, 0=non-crop)
│   │   ├── sambalpur_rabi_crop_phenology_isolated.png # Final 300 DPI isolated crop phenology curve
│   │   └── sambalpur_rabi_phenology_curve.png # District-wide baseline phenology curve
│   ├── processed/                             # Intermediate tile NDVI rasters & virtual mosaics
│   │   ├── November/                          # Intermediate NDVI & VRT mosaics (Nov 2025)
│   │   ├── December/                          # Intermediate NDVI & VRT mosaics (Dec 2025)
│   │   ├── January/                           # Intermediate NDVI & VRT mosaics (Jan 2026)
│   │   ├── February/                          # Intermediate NDVI & VRT mosaics (Feb 2026)
│   │   ├── March/                             # Intermediate NDVI & VRT mosaics (Mar 2026)
│   │   └── April/                             # Intermediate NDVI & VRT mosaics (Apr 2026)
│   ├── raw/                                   # Sentinel-2 MSI L2A single-band downloads (.jp2)
│   │   ├── 20251105/ ... 20260419/            # Tile 44QRJ multi-temporal baseline scenes (B02, B04, B08, SCL)
│   │   ├── 202511_44QQJ/ ... 202604_44QQJ/    # Western gap complementary scenes (B04, B08)
│   │   ├── 202511_44QRK/ ... 202604_44QRK/    # Northern arm complementary scenes (B04, B08)
│   │   ├── 202511_45QTD/ ... 202604_45QTD/    # Eastern arm complementary scenes (B04, B08)
│   │   └── 202512_44QRK_full/                 # Full untruncated replacement scene for Dec 44QRK
│   └── vector/
│       ├── sambalpur.geojson                  # Sambalpur district boundary (WGS 84, EPSG:4326)
│       └── sambalpur_utm44n.geojson           # Projected district boundary (UTM 44N, EPSG:32644)
└── src/
    ├── analysis.py                            # Temporal profiling and basic phenology extraction
    ├── download.py                            # CDSE OData API client & batch single-band fetcher
    ├── inspect_aoi.py                         # AOI boundary geometric inspection & MGRS tile audit
    ├── isolate_cropland_phenology.py          # Multi-temporal cropland isolation & phenology pipeline
    ├── plot_phenology.py                      # District-wide 300 DPI phenology visualization
    └── preprocess.py                          # Cloud masking (SCL), vegetation indices & spatial clipping
```

---

## 8. Key Conclusions

1. **Forest Masking is Mandatory in Hilly Districts:** In topographically complex regions like Western Odisha, regional average NDVI is dominated by deciduous forest phenology. Phenological delta filtering is essential to isolate agricultural signals.
2. **Optical Evidence of Water Management:** The sudden NDVI drop to ~0.11 provides clear optical confirmation of canal water delivery and field flooding across 28,990 ha during the dry winter season.
3. **High Spatial Precision:** Using 10m Sentinel-2 bands allows individual field bunds and smallholder paddy parcels to be resolved without coarse mixed-pixel contamination.
