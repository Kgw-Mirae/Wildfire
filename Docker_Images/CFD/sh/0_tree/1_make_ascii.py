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

# ============================================================
# Paths & options
# ============================================================
LOCATION_TXT = "../data/Event/location.txt"   # line1: UTM-K X, line2: UTM-K Y
OUT_DIR = "./output_tree"

# Tree raster inputs
TREE_RASTERS = {
    "HEIGHT":  "../../file/TREE/HEIGHT_100m.tif",
    "FRTP_CD": "../../file/TREE/FRTP_CD_100m.tif",
    "DNST_CD": "../../file/TREE/DNST_CD_100m.tif",
}

# Target CRS: UTM-K
TARGET_CRS = CRS.from_epsg(5179)

# Resampling method by variable
RESAMPLING_MAP = {
    "HEIGHT": Resampling.average,
    "FRTP_CD": Resampling.nearest,
    "DNST_CD": Resampling.nearest,
}


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


def build_output_paths(varname: str):
    """Create output file paths."""
    base = f"{varname}_model"
    asc_path = os.path.join(OUT_DIR, f"{base}.asc")
    meta_path = os.path.join(OUT_DIR, f"{base}_info.txt")
    return asc_path, meta_path


def get_domain_bounds(cx, cy, cfg):
    """Build outer-domain bounds from center coordinate."""
    inner_span = cfg.inner_npix * cfg.resolution_m
    half_inner = 0.5 * inner_span
    halo_span = cfg.halo_cells * cfg.resolution_m

    xmin = cx - half_inner - halo_span
    xmax = cx + half_inner + halo_span
    ymin = cy - half_inner - halo_span
    ymax = cy + half_inner + halo_span

    return xmin, xmax, ymin, ymax


def choose_nodata(src, varname):
    """Choose output nodata value."""
    if src.nodata is not None:
        return src.nodata

    if varname == "HEIGHT":
        return -9999.0
    else:
        return -9999


def maybe_cast_array(arr, varname, nodata_val):
    """Cast array dtype depending on variable type."""
    if varname == "HEIGHT":
        return arr.astype("float32")

    out = arr.copy()
    mask = out != nodata_val
    out[mask] = out[mask].round()
    return out.astype("int32")


def run_one_raster(x, y, varname, tif_in, cfg):
    """Crop + reproject one tree raster around UTM-K center and export ASCII."""
    xmin, xmax, ymin, ymax = get_domain_bounds(x, y, cfg)

    transform = Affine(cfg.resolution_m, 0, xmin, 0, -cfg.resolution_m, ymax)
    resampling_method = RESAMPLING_MAP[varname]

    with rasterio.open(tif_in) as src:
        dst_nodata = choose_nodata(src, varname)

        vrt_opts = dict(
            crs=TARGET_CRS,
            transform=transform,
            width=cfg.outer_npix,
            height=cfg.outer_npix,
            resampling=resampling_method,
            nodata=dst_nodata
        )

        with WarpedVRT(src, **vrt_opts) as vrt:
            arr = vrt.read(1)

    arr = maybe_cast_array(arr, varname, dst_nodata)

    xll = xmin
    yll = ymax - cfg.outer_npix * cfg.resolution_m
    ulx = xmin
    uly = ymax

    asc_path, meta_path = build_output_paths(varname)

    write_esri_ascii(
        asc_path,
        arr,
        xllcorner=xll,
        yllcorner=yll,
        cellsize=cfg.resolution_m,
        nodata_val=dst_nodata
    )

    write_meta_txt(
        meta_path,
        xll=xll,
        yll=yll,
        cellsize=cfg.resolution_m,
        ncols=cfg.outer_npix,
        nrows=cfg.outer_npix,
        ulx=ulx,
        uly=uly,
        vertical_resolution_m=cfg.vertical_resolution_m,
        kmax=cfg.kmax,
    )
#    print(f"[OK] {varname} -> {asc_path}")


def check_inputs():
    """Check all input files exist."""
    if not os.path.isfile(LOCATION_TXT):
        raise FileNotFoundError(f"Location file not found: {LOCATION_TXT}")

    for varname, path in TREE_RASTERS.items():
        if not os.path.isfile(path):
            raise FileNotFoundError(f"{varname} raster not found: {path}")


def main():
    check_inputs()
    os.makedirs(OUT_DIR, exist_ok=True)

    x, y = read_location(LOCATION_TXT)
    cfg = load_domain_config(PROJECT_DIR)

#    print("==========================================")
#    print("Read event location (UTM-K / EPSG:5179)")
#    print("==========================================")
#    print(f"X = {x:.2f}")
#    print(f"Y = {y:.2f}")
#    print("")

    for varname, tif_in in TREE_RASTERS.items():
        run_one_raster(x, y, varname, tif_in, cfg)

#    print("")
#    print(f"All {cfg.resolution_m} m tree rasters processed successfully.")


if __name__ == "__main__":
    main()
