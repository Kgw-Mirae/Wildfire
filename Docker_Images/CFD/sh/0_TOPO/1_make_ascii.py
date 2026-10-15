import os
import sys
from pathlib import Path
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from affine import Affine
from pyproj import CRS

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

from data.Domain.domain_utils import load_domain_config

# ===== Paths & options =====
LOCATION_TXT = "../data/Event/location.txt"          # line1: UTM-K X, line2: UTM-K Y
TIF_DEFAULT  = "../../file/DEM/mosaic_dem.tif"       # input DEM (GeoTIFF)
OUT_DIR      = "./output"                            # output directory
RESAMPLING   = Resampling.average                    # DEM-friendly

# Target CRS: UTM-K (EPSG:5179)
TARGET_CRS = CRS.from_epsg(5179)

def read_location(path: str):
    """Read UTM-K x/y from a text file (line1: x, line2: y)."""
    with open(path, "r", encoding="utf-8-sig") as f:
        lines = [ln.strip() for ln in f.readlines()]

    vals = [ln for ln in lines if ln != ""]
    if len(vals) < 2:
        raise ValueError(f"Location file must have 2 lines (UTM-K X, Y): {path}")

    x = float(vals[0])
    y = float(vals[1])

    return x, y

def write_esri_ascii(path, data_2d, xllcorner, yllcorner, cellsize, nodata_val):
    """Write an ESRI ASCII grid file."""
    nrows, ncols = data_2d.shape
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(f"NCOLS {ncols}\n")
        f.write(f"NROWS {nrows}\n")
        f.write(f"XLLCORNER {xllcorner:.6f}\n")
        f.write(f"YLLCORNER {yllcorner:.6f}\n")
        f.write(f"CELLSIZE {cellsize:.6f}\n")
        f.write(f"NODATA_VALUE {nodata_val}\n")
        for r in range(nrows):
            f.write(" ".join(str(v) for v in data_2d[r, :]) + "\n")

def write_meta_txt(
    meta_path,
    *,
    xll,
    yll,
    cellsize,
    ncols,
    nrows,
    ulx,
    uly,
    vertical_resolution_m,
    kmax,
):
    """Write metadata text file for downstream use."""
    os.makedirs(os.path.dirname(meta_path) or ".", exist_ok=True)

    with open(meta_path, "w", encoding="utf-8") as f:
        f.write(f"XLLCORNER {xll:.6f}\n")
        f.write(f"YLLCORNER {yll:.6f}\n")
        f.write(f"CELLSIZE {cellsize:.6f}\n")
        f.write(f"NCOLS {ncols}\n")
        f.write(f"NROWS {nrows}\n")
        f.write(f"ULx {ulx:.6f}\n")
        f.write(f"ULy {uly:.6f}\n")
        f.write(f"VERTICAL_RESOLUTION_M {vertical_resolution_m:.6f}\n")
        f.write(f"KMAX {kmax}\n")

def run_one(
    x,
    y,
    res_m: float,
    inner_npix: int,
    out_npix: int,
    tif_in: str,
    asc_name: str,
    meta_name: str,
    vertical_resolution_m: float,
    kmax: int,
):
    """Crop+reproject DEM around UTM-K center (x, y) and export ASCII grid."""
    cx, cy = x, y

    inner_span = inner_npix * res_m
    half_inner = 0.5 * inner_span
    halo_cells = (out_npix - inner_npix) // 2
    halo_span  = halo_cells * res_m

    xmin = cx - half_inner - halo_span
    xmax = cx + half_inner + halo_span
    ymin = cy - half_inner - halo_span
    ymax = cy + half_inner + halo_span

    transform = Affine(res_m, 0, xmin, 0, -res_m, ymax)

    with rasterio.open(tif_in) as src:
        dst_nodata = src.nodata if src.nodata is not None else -9999

        vrt_opts = dict(
            crs=TARGET_CRS,
            transform=transform,
            width=out_npix,
            height=out_npix,
            resampling=RESAMPLING,
            nodata=dst_nodata
        )

        with WarpedVRT(src, **vrt_opts) as vrt:
            arr = vrt.read(1)

    xll = xmin
    yll = ymax - out_npix * res_m

    asc_path = os.path.join(OUT_DIR, asc_name)
    write_esri_ascii(
        asc_path,
        arr,
        xllcorner=xll,
        yllcorner=yll,
        cellsize=res_m,
        nodata_val=dst_nodata
    )

    ulx, uly = xmin, ymax
    meta_path = os.path.join(OUT_DIR, meta_name)
    write_meta_txt(
        meta_path,
        xll=xll,
        yll=yll,
        cellsize=res_m,
        ncols=out_npix,
        nrows=out_npix,
        ulx=ulx,
        uly=uly,
        vertical_resolution_m=vertical_resolution_m,
        kmax=kmax,
    )
    return asc_path, meta_path

def main():
    if not os.path.isfile(TIF_DEFAULT):
        raise FileNotFoundError(f"Input DEM not found: {TIF_DEFAULT}")
    if not os.path.isfile(LOCATION_TXT):
        raise FileNotFoundError(f"Location file not found: {LOCATION_TXT}")

    x, y = read_location(LOCATION_TXT)
    cfg = load_domain_config(PROJECT_DIR)
    os.makedirs(OUT_DIR, exist_ok=True)

#    print("==========================================")
#    print("Read event location (UTM-K / EPSG:5179)")
#    print("==========================================")
#    print(f"X = {x:.2f}")
#    print(f"Y = {y:.2f}")

    targets = [
        {
            "res": float(cfg.topo_source_res_m),
            "inner_npix": cfg.topo_inner_npix,
            "out_npix": cfg.topo_outer_npix,
            "asc_name": "output_topo_source.asc",
            "meta_name": "output_topo_source_info.txt",
            "vertical_resolution_m": cfg.vertical_resolution_m,
            "kmax": cfg.kmax,
        },
        {
            "res": float(cfg.resolution_m),
            "inner_npix": cfg.inner_npix,
            "out_npix": cfg.outer_npix,
            "asc_name": "output_model.asc",
            "meta_name": "output_model_info.txt",
            "vertical_resolution_m": cfg.vertical_resolution_m,
            "kmax": cfg.kmax,
        },
    ]

    for t in targets:
        run_one(
            x,
            y,
            t["res"],
            t["inner_npix"],
            t["out_npix"],
            TIF_DEFAULT,
            t["asc_name"],
            t["meta_name"],
            t["vertical_resolution_m"],
            t["kmax"],
        )

if __name__ == "__main__":
    main()
