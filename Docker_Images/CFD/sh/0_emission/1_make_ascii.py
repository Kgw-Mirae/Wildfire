import os
import sys
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from pyproj import CRS
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import from_bounds
from rasterio.vrt import WarpedVRT

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

from data.Domain.domain_utils import load_domain_config

# ============================================================
# Paths & options
# ============================================================
DOMAIN_INFO = "../data/Domain/output_model_info.txt"
LANDCOVER_TIF = "../../file/LANDCOVER/landcover_5m_lc_class.tif"
OUT_DIR = "./output_landcover"

TARGET_CRS = CRS.from_epsg(5179)
NODATA_VALUE = 0
LC_CLASSES = (1, 2, 3, 4)
MODE_RESAMPLING = getattr(Resampling, "mode", Resampling.nearest)


def read_domain_info(path: str):
    """Read model grid metadata written by 0_TOPO."""
    values = {}
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 2:
                continue
            values[parts[0].upper()] = float(parts[1])

    required = ["XLLCORNER", "YLLCORNER", "CELLSIZE", "NCOLS", "NROWS", "ULX", "ULY"]
    missing = [key for key in required if key not in values]
    if missing:
        raise ValueError(f"Missing keys in domain info {path}: {missing}")

    return {
        "xll": values["XLLCORNER"],
        "yll": values["YLLCORNER"],
        "cellsize": values["CELLSIZE"],
        "ncols": int(values["NCOLS"]),
        "nrows": int(values["NROWS"]),
        "ulx": values["ULX"],
        "uly": values["ULY"],
        "vertical_resolution_m": values.get("VERTICAL_RESOLUTION_M"),
        "kmax": int(values["KMAX"]) if "KMAX" in values else None,
    }


def write_esri_ascii(path, data_2d, meta, nodata_val):
    """Write an ESRI ASCII grid file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(f"NCOLS {meta['ncols']}\n")
        f.write(f"NROWS {meta['nrows']}\n")
        f.write(f"XLLCORNER {meta['xll']:.6f}\n")
        f.write(f"YLLCORNER {meta['yll']:.6f}\n")
        f.write(f"CELLSIZE {meta['cellsize']:.6f}\n")
        f.write(f"NODATA_VALUE {nodata_val}\n")
        for r in range(meta["nrows"]):
            f.write(" ".join(str(int(v)) for v in data_2d[r, :]) + "\n")


def write_esri_ascii_float(path, data_2d, meta, nodata_val):
    """Write a floating-point ESRI ASCII grid file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(f"NCOLS {meta['ncols']}\n")
        f.write(f"NROWS {meta['nrows']}\n")
        f.write(f"XLLCORNER {meta['xll']:.6f}\n")
        f.write(f"YLLCORNER {meta['yll']:.6f}\n")
        f.write(f"CELLSIZE {meta['cellsize']:.6f}\n")
        f.write(f"NODATA_VALUE {nodata_val:.6f}\n")
        for r in range(meta["nrows"]):
            f.write(" ".join(f"{float(v):.8f}" for v in data_2d[r, :]) + "\n")


def write_meta_txt(path, meta):
    """Write metadata text file matching the TOPO model grid."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(f"XLLCORNER {meta['xll']:.6f}\n")
        f.write(f"YLLCORNER {meta['yll']:.6f}\n")
        f.write(f"CELLSIZE {meta['cellsize']:.6f}\n")
        f.write(f"NCOLS {meta['ncols']}\n")
        f.write(f"NROWS {meta['nrows']}\n")
        f.write(f"ULx {meta['ulx']:.6f}\n")
        f.write(f"ULy {meta['uly']:.6f}\n")
        if meta.get("vertical_resolution_m") is not None:
            f.write(f"VERTICAL_RESOLUTION_M {meta['vertical_resolution_m']:.6f}\n")
        if meta.get("kmax") is not None:
            f.write(f"KMAX {meta['kmax']}\n")


def validate_domain_config_matches_info(meta):
    """Warn if the info file shape no longer matches domain_config.json."""
    cfg = load_domain_config(PROJECT_DIR)
    if meta["ncols"] != cfg.outer_npix or meta["nrows"] != cfg.outer_npix:
        print(
            "[WARN] output_model_info.txt shape does not match domain_config.json. "
            "Run 0_TOPO first if this is unexpected."
        )
    if abs(meta["cellsize"] - cfg.resolution_m) > 1.0e-6:
        print(
            "[WARN] output_model_info.txt cellsize does not match domain_config.json. "
            "Run 0_TOPO first if this is unexpected."
        )
    if meta.get("vertical_resolution_m") is None:
        print("[WARN] output_model_info.txt is missing VERTICAL_RESOLUTION_M. Run 0_TOPO first.")
    elif abs(meta["vertical_resolution_m"] - cfg.vertical_resolution_m) > 1.0e-6:
        print(
            "[WARN] output_model_info.txt vertical resolution does not match domain_config.json. "
            "Run 0_TOPO first if this is unexpected."
        )
    if meta.get("kmax") is None:
        print("[WARN] output_model_info.txt is missing KMAX. Run 0_TOPO first.")
    elif meta["kmax"] != cfg.kmax:
        print(
            "[WARN] output_model_info.txt KMAX does not match domain_config.json. "
            "Run 0_TOPO first if this is unexpected."
        )


def domain_bounds(meta):
    xmin = meta["xll"]
    ymax = meta["uly"]
    xmax = xmin + meta["ncols"] * meta["cellsize"]
    ymin = ymax - meta["nrows"] * meta["cellsize"]
    return xmin, ymin, xmax, ymax


def warn_if_domain_outside_source(meta, src):
    """Warn when the requested model domain extends outside the prebuilt raster."""
    xmin, ymin, xmax, ymax = domain_bounds(meta)
    left, bottom, right, top = src.bounds
    if CRS.from_user_input(src.crs) != TARGET_CRS:
        left, bottom, right, top = transform_bounds(
            src.crs, TARGET_CRS, left, bottom, right, top, densify_pts=21
        )
    if xmin < left or xmax > right or ymin < bottom or ymax > top:
        print(
            "[WARN] Model domain extends outside landcover_5m_lc_class.tif. "
            "Cells outside the raster will be filled with 0."
        )


def read_model_grid_from_prebuilt_tif(path: str, meta):
    """Read the prebuilt 5m categorical raster on the exact model grid."""
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Prebuilt landcover raster not found: {path}. "
            "Run prebuild_landcover_5m.py first."
        )

    dst_transform = Affine(
        meta["cellsize"],
        0.0,
        meta["xll"],
        0.0,
        -meta["cellsize"],
        meta["uly"],
    )

    with rasterio.open(path) as src:
        if src.crs is None:
            raise ValueError(f"Prebuilt landcover raster has no CRS: {path}")

        warn_if_domain_outside_source(meta, src)
        if MODE_RESAMPLING == Resampling.nearest:
            print("[WARN] rasterio Resampling.mode is unavailable; using nearest resampling.")

        vrt_opts = dict(
            crs=TARGET_CRS,
            transform=dst_transform,
            width=meta["ncols"],
            height=meta["nrows"],
            resampling=MODE_RESAMPLING,
            nodata=NODATA_VALUE,
            src_nodata=src.nodata if src.nodata is not None else NODATA_VALUE,
        )

        with WarpedVRT(src, **vrt_opts) as vrt:
            arr = vrt.read(1, out_dtype="uint8")

    arr = np.asarray(arr, dtype=np.int16)
    arr[arr < 0] = 0
    return arr


def read_class_ratio_grids_from_prebuilt_tif(path: str, meta):
    """Read class fractions within each model grid cell."""
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Prebuilt landcover raster not found: {path}. "
            "Run prebuild_landcover_5m.py first."
        )

    dst_transform = Affine(
        meta["cellsize"],
        0.0,
        meta["xll"],
        0.0,
        -meta["cellsize"],
        meta["uly"],
    )

    with rasterio.open(path) as src:
        if src.crs is None:
            raise ValueError(f"Prebuilt landcover raster has no CRS: {path}")

        warn_if_domain_outside_source(meta, src)

        bounds = domain_bounds(meta)
        if CRS.from_user_input(src.crs) == TARGET_CRS:
            src_bounds = bounds
        else:
            src_bounds = transform_bounds(TARGET_CRS, src.crs, *bounds, densify_pts=21)

        window = from_bounds(*src_bounds, transform=src.transform)
        data = src.read(
            1,
            window=window,
            boundless=True,
            fill_value=src.nodata if src.nodata is not None else NODATA_VALUE,
        )
        src_transform = src.window_transform(window)

        ratios = {}
        for lc_class in LC_CLASSES:
            src_mask = (data == lc_class).astype("float32")
            dst = np.zeros((meta["nrows"], meta["ncols"]), dtype="float32")
            reproject(
                source=src_mask,
                destination=dst,
                src_transform=src_transform,
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs=TARGET_CRS,
                dst_nodata=0.0,
                resampling=Resampling.average,
            )
            dst[(dst < 1.0e-7)] = 0.0
            dst[(dst > 1.0) & (dst < 1.0 + 1.0e-6)] = 1.0
            ratios[lc_class] = np.clip(dst, 0.0, 1.0)

    return ratios


def main():
    if not os.path.isfile(DOMAIN_INFO):
        raise FileNotFoundError(f"Domain info not found: {DOMAIN_INFO}. Run 0_TOPO first.")

    meta = read_domain_info(DOMAIN_INFO)
    validate_domain_config_matches_info(meta)

#    print("==========================================")
#    print("Extract landcover from prebuilt 5m raster")
#    print("==========================================")
#    print(f"Grid: {meta['ncols']} x {meta['nrows']}, cellsize={meta['cellsize']:.6f}")
#    print(f"Input: {LANDCOVER_TIF}")

    arr = read_model_grid_from_prebuilt_tif(LANDCOVER_TIF, meta)
    ratios = read_class_ratio_grids_from_prebuilt_tif(LANDCOVER_TIF, meta)

    asc_path = os.path.join(OUT_DIR, "LC_CLASS_model.asc")
    meta_path = os.path.join(OUT_DIR, "LC_CLASS_model_info.txt")
    write_esri_ascii(asc_path, arr, meta, NODATA_VALUE)
    for lc_class, ratio in ratios.items():
        ratio_path = os.path.join(OUT_DIR, f"LC_CLASS_RATIO_{lc_class}_model.asc")
        write_esri_ascii_float(ratio_path, ratio, meta, 0.0)
    write_meta_txt(meta_path, meta)

    classes, counts = np.unique(arr, return_counts=True)
    summary = dict(zip(classes.astype(int).tolist(), counts.astype(int).tolist()))

#    print(f"[OK] Saved: {asc_path}")
#    for lc_class in LC_CLASSES:
#        print(f"[OK] Saved: {os.path.join(OUT_DIR, f'LC_CLASS_RATIO_{lc_class}_model.asc')}")
#    print(f"[OK] Saved: {meta_path}")
#    print("LC_CLASS counts:", summary)


if __name__ == "__main__":
    main()
