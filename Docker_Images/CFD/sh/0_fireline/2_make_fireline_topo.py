#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
import sys
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Dict, Optional, Tuple, Any, List
from datetime import datetime

import numpy as np
import geopandas as gpd
from shapely.geometry import box
from shapely.ops import polygonize, unary_union
from shapely.prepared import prep
from shapely.strtree import STRtree


# =========================
# USER SETTINGS
# =========================
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

from data.Domain.domain_utils import load_domain_config
from fireline_schedule import build_fireline_schedule

GEOJSON_DIR = PROJECT_DIR / "data" / "Geojson"
GRID_HEADER_TXT = PROJECT_DIR / "data" / "Domain" / "output_model_info.txt"

OUT_DIR_204_ASC = SCRIPT_DIR / "result_fireline" / "out_asc_204"
OUT_TS_TXT = SCRIPT_DIR / "result_fireline" / "fire_intensity_timeseries.txt"
OUT_TS_META_TXT = SCRIPT_DIR / "result_fireline" / "fire_intensity_timeseries_info.txt"
#GEOJSON_DIR = Path("../data/Geojson")
#GRID_HEADER_TXT = Path("../data/Domain/output_model_info.txt")

#OUT_DIR_204_ASC = Path("./result_fireline/out_asc_204")
#OUT_TS_TXT = Path("./result_fireline/fire_intensity_timeseries.txt")

EPSG_MODEL = 5179
INTENSITY_FIELD_PREFERRED = "Intensity"
INTENSITY_UNIT = "KW/m"

SIMPLIFY_TOL_M = 0.0
NODATA_VALUE = 0.0
FIRE_INTERIOR_VALUE = -9999.0
FIRE_INTERIOR_MIN_AREA_FRACTION = 0.10
FIRE_ZERO_TOLERANCE = 0.005
WRITE_204_ASC_EACH = False

OUTPUT_ORIENTATION = "north_first"
N_WORKERS = 8


def intensity_to_KW_per_m(val: float, unit: str) -> float:
    """Convert line intensity to kW/m."""
    v = float(val)
    if unit.lower() in ["w/m", "w_per_m", "wperm"]:
        return v / 1000.0
    return v


def read_ascii_grid_header(txt_path: Path, max_lines: int = 300) -> Dict[str, float]:
    header: Dict[str, float] = {}

    with txt_path.open("r", encoding="utf-8", errors="ignore") as f:
        for _ in range(max_lines):
            line = f.readline()
            if not line:
                break

            line = line.strip()
            if not line:
                continue

            parts = line.split()
            if len(parts) < 2:
                continue

            if re.fullmatch(r"[-+]?\d+(\.\d+)?([eE][-+]?\d+)?", parts[0]):
                break

            key = parts[0].strip().lower()
            try:
                val = float(parts[1])
            except ValueError:
                continue
            header[key] = val

    for k in ["ncols", "nrows", "cellsize"]:
        if k not in header:
            raise ValueError(f"Missing required header key: {k.upper()}")

    cell = float(header["cellsize"])

    if "xllcorner" in header:
        header["xll"] = float(header["xllcorner"])
    elif "xllcenter" in header:
        header["xll"] = float(header["xllcenter"]) - 0.5 * cell
    else:
        raise ValueError("Missing XLLCORNER or XLLCENTER in header")

    if "yllcorner" in header:
        header["yll"] = float(header["yllcorner"])
    elif "yllcenter" in header:
        header["yll"] = float(header["yllcenter"]) - 0.5 * cell
    else:
        raise ValueError("Missing YLLCORNER or YLLCENTER in header")

    return header


def build_grid_index(nx: int, ny: int, dx: float, dy: float, x0: float, y0: float):
    polys = []
    ij = []

    for j in range(ny):
        y1 = y0 + j * dy
        y2 = y1 + dy
        for i in range(nx):
            x1 = x0 + i * dx
            x2 = x1 + dx
            polys.append(box(x1, y1, x2, y2))
            ij.append((i, j))

    tree = STRtree(polys)
    geom_id_to_index = {id(p): k for k, p in enumerate(polys)}
    return polys, ij, tree, geom_id_to_index


_WORKER_GRID = None


def init_worker_grid(
    nx: int,
    ny: int,
    dx: float,
    dy: float,
    x0: float,
    y0: float,
    grid_bbox: Tuple[float, float, float, float],
):
    """Build the static model grid only once in each worker process."""
    global _WORKER_GRID
    polys, ij, tree, geom_id_to_index = build_grid_index(nx, ny, dx, dy, x0, y0)
    _WORKER_GRID = (
        polys,
        ij,
        tree,
        geom_id_to_index,
        nx,
        ny,
        dx,
        dy,
        x0,
        y0,
        grid_bbox,
    )


def iter_candidate_indices(cand: Any, geom_id_to_index: Dict[int, int]):
    for item in cand:
        if isinstance(item, (int, np.integer)):
            yield int(item)
        else:
            yield geom_id_to_index[id(item)]


def bbox_overlap(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> bool:
    axmin, aymin, axmax, aymax = a
    bxmin, bymin, bxmax, bymax = b
    return not (axmax < bxmin or bxmax < axmin or aymax < bymin or bymax < aymin)


def find_intensity_field(columns: List[str], preferred: str) -> Optional[str]:
    if preferred in columns:
        return preferred

    pref_lower = preferred.lower()
    for c in columns:
        if c.lower() == pref_lower:
            return c

    for c in columns:
        if "intensity" in c.lower():
            return c

    return None


def load_fireline_data(
    geojson_path: Path,
    epsg_model: int,
    simplify_tol: Optional[float] = None,
):
    """
    Read/reproject a GeoJSON only once.

    Returns
    -------
    gdf_for_intensity
        Geometry used for rasterization.
    interior_for_mask
        Polygonized interior used for the fire-interior mask.
    area_m2
        Area from the original reprojected geometry, preserving the old behavior.
    """
    gdf = gpd.read_file(geojson_path)

    if gdf.empty or gdf.geometry.is_empty.all():
        return gdf, None, 0.0

    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=epsg_model)

    if gdf.crs.to_epsg() != epsg_model:
        gdf = gdf.to_crs(epsg=epsg_model)

    # The old code computed area from the original (unsimplified) geometry.
    original_interior = build_fire_interior_polygon(gdf)
    area_m2 = 0.0 if original_interior is None else float(original_interior.area)

    if simplify_tol is not None and simplify_tol > 0.0:
        gdf = gdf.copy()
        gdf["geometry"] = gdf.geometry.simplify(simplify_tol, preserve_topology=True)
        interior_for_mask = build_fire_interior_polygon(gdf)
    else:
        interior_for_mask = original_interior

    return gdf, interior_for_mask, area_m2


def compute_intensity_grid_204(
    gdf: gpd.GeoDataFrame,
    interior,
    polys,
    ij,
    tree: STRtree,
    geom_id_to_index: Dict[int, int],
    nx: int,
    ny: int,
    dx: float,
    dy: float,
    grid_bbox: Tuple[float, float, float, float],
    intensity_field_preferred: str,
    intensity_unit: str,
) -> np.ndarray:
    if gdf.empty or gdf.geometry.is_empty.all():
        return np.zeros((ny, nx), dtype=np.float64)

    cols = list(gdf.columns)
    field = find_intensity_field(cols, intensity_field_preferred)
    if field is None:
        return np.zeros((ny, nx), dtype=np.float64)

    gj_bbox = tuple(gdf.total_bounds.tolist())
    if not bbox_overlap(gj_bbox, grid_bbox):
        return np.zeros((ny, nx), dtype=np.float64)

    power = np.zeros((ny, nx), dtype=np.float64)
    fireline_mask = np.zeros((ny, nx), dtype=bool)
    cell_area = dx * dy

    # Avoid GeoDataFrame.iterrows() overhead.
    geometries = gdf.geometry.to_numpy()
    values = gdf[field].to_numpy()

    for geom, val in zip(geometries, values):
        if geom is None or geom.is_empty:
            continue

        if val is None or (isinstance(val, float) and np.isnan(val)):
            continue

        i_line = intensity_to_KW_per_m(val, intensity_unit)

        cand = tree.query(geom)
        for k in iter_candidate_indices(cand, geom_id_to_index):
            inter = geom.intersection(polys[k])
            if inter.is_empty:
                continue

            length = float(inter.length)
            if length <= 0.0:
                continue

            i, j = ij[k]
            power[j, i] += i_line * length
            fireline_mask[j, i] = True

    intensity = power / cell_area
    apply_fire_interior_polygon_mask(
        intensity,
        fireline_mask,
        interior,
        polys,
        nx,
        ny,
        dx,
        dy,
        grid_bbox[0],
        grid_bbox[1],
    )
    apply_surrounded_zero_fire_interior_mask(intensity, fireline_mask)
    return intensity


def apply_fire_interior_polygon_mask(
    intensity: np.ndarray,
    fireline_mask: np.ndarray,
    interior,
    polys,
    nx: int,
    ny: int,
    dx: float,
    dy: float,
    x0: float,
    y0: float,
) -> None:
    """
    Mark zero-valued cells inside the polygonized fireline.

    Optimization:
    - reuse already-built grid polygons;
    - inspect only cells within the fire-interior bounding box instead of
      scanning the entire model grid.
    """
    if interior is None:
        print("[WARN] Could not build fireline interior polygon; interior mask skipped.")
        return

    prepared = prep(interior)
    min_area = dx * dy * FIRE_INTERIOR_MIN_AREA_FRACTION

    xmin, ymin, xmax, ymax = interior.bounds

    # One-cell padding makes the bounds conservative and preserves edge cases.
    i_start = max(0, int(np.floor((xmin - x0) / dx)) - 1)
    i_end = min(nx - 1, int(np.floor((xmax - x0) / dx)) + 1)
    j_start = max(0, int(np.floor((ymin - y0) / dy)) - 1)
    j_end = min(ny - 1, int(np.floor((ymax - y0) / dy)) + 1)

    if i_start > i_end or j_start > j_end:
        return

    for j in range(j_start, j_end + 1):
        row_offset = j * nx
        for i in range(i_start, i_end + 1):
            if fireline_mask[j, i]:
                continue
            if abs(intensity[j, i]) > FIRE_ZERO_TOLERANCE:
                continue

            cell = polys[row_offset + i]

            if not prepared.intersects(cell):
                continue

            if interior.intersection(cell).area >= min_area:
                intensity[j, i] = FIRE_INTERIOR_VALUE


def build_fire_interior_polygon(gdf: gpd.GeoDataFrame):
    """Build polygon area enclosed by fireline geometry."""
    geoms = [geom for geom in gdf.geometry if geom is not None and not geom.is_empty]
    if not geoms:
        return None

    linework = unary_union(geoms)
    polygons = list(polygonize(linework))
    if not polygons:
        return None

    interior = unary_union(polygons)
    if interior.is_empty:
        return None
    if not interior.is_valid:
        interior = interior.buffer(0)
    if interior.is_empty:
        return None
    return interior


def apply_surrounded_zero_fire_interior_mask(
    intensity: np.ndarray,
    fireline_mask: np.ndarray,
) -> None:
    """Mark zero cells whose four direct neighbors are all non-zero."""
    if intensity.shape[0] < 3 or intensity.shape[1] < 3:
        return

    # This is equivalent to the old two-pass Python loop:
    # first determine every cell to mark, then apply all marks together.
    center = intensity[1:-1, 1:-1]
    to_mark = (
        (np.abs(center) <= FIRE_ZERO_TOLERANCE)
        & (np.abs(intensity[:-2, 1:-1]) > FIRE_ZERO_TOLERANCE)
        & (np.abs(intensity[2:, 1:-1]) > FIRE_ZERO_TOLERANCE)
        & (np.abs(intensity[1:-1, :-2]) > FIRE_ZERO_TOLERANCE)
        & (np.abs(intensity[1:-1, 2:]) > FIRE_ZERO_TOLERANCE)
    )
    center[to_mark] = FIRE_INTERIOR_VALUE


def write_ascii_grid(out_path: Path, arr: np.ndarray, x0: float, y0: float, cell: float, nodata: float):
    ny, nx = arr.shape
    out_path.parent.mkdir(parents=True, exist_ok=True)

    arr_out = np.flipud(arr)

    with out_path.open("w", encoding="utf-8") as f:
        f.write(f"NCOLS {nx}\n")
        f.write(f"NROWS {ny}\n")
        f.write(f"XLLCORNER {x0:.6f}\n")
        f.write(f"YLLCORNER {y0:.6f}\n")
        f.write(f"CELLSIZE {cell:.6f}\n")
        f.write(f"NODATA_VALUE {nodata}\n")
        for row in arr_out:
            f.write(" ".join(f"{v:.6f}" for v in row) + "\n")


def crop_outer_to_model(intensity_outer: np.ndarray, expected_outer_npix: int) -> np.ndarray:
    expected = (expected_outer_npix, expected_outer_npix)
    if intensity_outer.shape != expected:
        raise ValueError(f"Expected outer grid {expected}, got {intensity_outer.shape}")
    return intensity_outer[1:-1, 1:-1]


def write_timeseries_one_file(
    out_txt: Path,
    blocks: List[Tuple[str, int, float, np.ndarray]],
    expected_model_npix: int,
    orientation: str = "north_first",
):
    out_txt.parent.mkdir(parents=True, exist_ok=True)

    with out_txt.open("w", encoding="utf-8") as f:
        for time_label, seconds, area_m2, arr in blocks:
            expected = (expected_model_npix, expected_model_npix)
            if arr.shape != expected:
                raise ValueError(f"{seconds}: Expected model grid {expected}, got {arr.shape}")

            f.write(f"{time_label}, {seconds:04d}, A={area_m2:.3f}\n")

            if orientation == "north_first":
                arr_out = np.flipud(arr)
            elif orientation == "south_first":
                arr_out = arr
            else:
                raise ValueError("orientation must be 'north_first' or 'south_first'")

            for row in arr_out:
                f.write(" ".join(f"{v:.2f}" for v in row) + "\n")


def write_timeseries_meta(
    out_txt: Path,
    *,
    ncols: int,
    nrows: int,
    cellsize: float,
    xll: float,
    yll: float,
    vertical_resolution_m: float,
    kmax: int,
    ntime: int,
    start_seconds: int,
    end_seconds: int,
    model_end_seconds: int,
    orientation: str,
) -> None:
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    if ntime > 1:
        time_interval_seconds = (end_seconds - start_seconds) / (ntime - 1)
    else:
        time_interval_seconds = 0.0

    with out_txt.open("w", encoding="utf-8") as f:
        f.write(f"NCOLS {ncols}\n")
        f.write(f"NROWS {nrows}\n")
        f.write(f"XLLCORNER {xll:.6f}\n")
        f.write(f"YLLCORNER {yll:.6f}\n")
        f.write(f"CELLSIZE {cellsize:.6f}\n")
        f.write(f"VERTICAL_RESOLUTION_M {vertical_resolution_m:.6f}\n")
        f.write(f"KMAX {kmax}\n")
        f.write(f"NTIME {ntime}\n")
        f.write(f"START_SECONDS {start_seconds}\n")
        f.write(f"END_SECONDS {end_seconds}\n")
        f.write(f"DURATION_SECONDS {end_seconds - start_seconds}\n")
        f.write(f"MODEL_END_SECONDS {model_end_seconds}\n")
        f.write(f"MODEL_DURATION_SECONDS {model_end_seconds}\n")
        f.write(f"TIME_INTERVAL_SECONDS {time_interval_seconds:.6f}\n")
        f.write(f"ORIENTATION {orientation}\n")


def process_fireline_file(
    args,
) -> Tuple[str, int, float, np.ndarray, Optional[Tuple[Path, np.ndarray]]]:
    fp, fireline_time, time_zero, outer_npix = args

    if _WORKER_GRID is None:
        raise RuntimeError("Worker grid is not initialized.")

    (
        polys,
        ij,
        tree,
        geom_id_to_index,
        nx,
        ny,
        dx,
        dy,
        x0,
        y0,
        grid_bbox,
    ) = _WORKER_GRID

    seconds = int(round((fireline_time - time_zero).total_seconds()))
    time_label = fireline_time.strftime("%HH%MM")

    gdf, interior, area_m2 = load_fireline_data(
        geojson_path=fp,
        epsg_model=EPSG_MODEL,
        simplify_tol=(SIMPLIFY_TOL_M if SIMPLIFY_TOL_M > 0 else None),
    )

    intensity_outer = compute_intensity_grid_204(
        gdf=gdf,
        interior=interior,
        polys=polys,
        ij=ij,
        tree=tree,
        geom_id_to_index=geom_id_to_index,
        nx=nx,
        ny=ny,
        dx=dx,
        dy=dy,
        grid_bbox=grid_bbox,
        intensity_field_preferred=INTENSITY_FIELD_PREFERRED,
        intensity_unit=INTENSITY_UNIT,
    )

    asc_output = None
    if WRITE_204_ASC_EACH:
        asc_output = (OUT_DIR_204_ASC / f"fire_intensity_{fp.stem}.asc", intensity_outer)

    intensity_model = crop_outer_to_model(intensity_outer, outer_npix)
    return time_label, seconds, area_m2, intensity_model, asc_output


def main():
    start_time_runtime = time.perf_counter()

    if not GRID_HEADER_TXT.exists():
        raise FileNotFoundError(f"Grid header file not found: {GRID_HEADER_TXT.resolve()}")

    cfg = load_domain_config(PROJECT_DIR)
    header = read_ascii_grid_header(GRID_HEADER_TXT)

    nx = int(round(header["ncols"]))
    ny = int(round(header["nrows"]))
    cell = float(header["cellsize"])
    x0 = float(header["xll"])
    y0 = float(header["yll"])
    dx = dy = cell

    if nx != cfg.outer_npix or ny != cfg.outer_npix:
        raise ValueError(
            f"Domain header grid {ny}x{nx} does not match config outer grid "
            f"{cfg.outer_npix}x{cfg.outer_npix}"
        )
    if abs(cell - cfg.resolution_m) > 1.0e-6:
        raise ValueError(f"Domain header cellsize {cell} does not match config resolution {cfg.resolution_m}")
    header_vertical_resolution = header.get("vertical_resolution_m")
    if header_vertical_resolution is None:
        raise ValueError("Domain header is missing VERTICAL_RESOLUTION_M. Run 0_TOPO first.")
    if abs(header_vertical_resolution - cfg.vertical_resolution_m) > 1.0e-6:
        raise ValueError(
            "Domain header vertical resolution "
            f"{header_vertical_resolution} does not match config {cfg.vertical_resolution_m}"
        )
    header_kmax = header.get("kmax")
    if header_kmax is None:
        raise ValueError("Domain header is missing KMAX. Run 0_TOPO first.")
    if int(round(header_kmax)) != cfg.kmax:
        raise ValueError(f"Domain header KMAX {int(round(header_kmax))} does not match config {cfg.kmax}")

    grid_bbox = (x0, y0, x0 + nx * dx, y0 + ny * dy)

    schedule = build_fireline_schedule(GEOJSON_DIR, cfg)
    fireline_files: List[Tuple[Path, datetime]] = [
        (entry.path, entry.fireline_time) for entry in schedule.entries
    ]
    time_zero = schedule.first_fireline_time
    model_end_seconds = schedule.model_duration_seconds
    work_items = [
        (
            fp,
            fireline_time,
            time_zero,
            cfg.outer_npix,
        )
        for fp, fireline_time in fireline_files
    ]

    n_workers = min(N_WORKERS, len(work_items), os.cpu_count() or 1)
    with ProcessPoolExecutor(
        max_workers=n_workers,
        initializer=init_worker_grid,
        initargs=(nx, ny, dx, dy, x0, y0, grid_bbox),
    ) as executor:
        results = list(executor.map(process_fireline_file, work_items))

    results.sort(key=lambda item: item[1])
    blocks_202: List[Tuple[str, int, float, np.ndarray]] = []

    if WRITE_204_ASC_EACH:
        OUT_DIR_204_ASC.mkdir(parents=True, exist_ok=True)

    for time_label, seconds, area_m2, intensity_model, asc_output in results:
        if asc_output is not None:
            out_asc, intensity_outer = asc_output
            write_ascii_grid(out_asc, intensity_outer, x0, y0, cell, nodata=NODATA_VALUE)
        blocks_202.append((time_label, seconds, area_m2, intensity_model))

    if not blocks_202:
        raise RuntimeError("No valid time blocks were collected. Check filenames.")

    write_timeseries_one_file(
        OUT_TS_TXT,
        blocks_202,
        expected_model_npix=cfg.model_npix,
        orientation=OUTPUT_ORIENTATION,
    )
    write_timeseries_meta(
        OUT_TS_META_TXT,
        ncols=cfg.model_npix,
        nrows=cfg.model_npix,
        cellsize=cell,
        xll=x0 + cfg.resolution_m,
        yll=y0 + cfg.resolution_m,
        vertical_resolution_m=cfg.vertical_resolution_m,
        kmax=cfg.kmax,
        ntime=len(blocks_202),
        start_seconds=blocks_202[0][1],
        end_seconds=blocks_202[-1][1],
        model_end_seconds=model_end_seconds,
        orientation=OUTPUT_ORIENTATION,
    )
    print(
        "[OK] Saved fire intensity data: "
        f"forecast_base={schedule.forecast_base_time:%Y-%m-%d %H:%M}, "
        f"forecast_end={schedule.forecast_end_time:%Y-%m-%d %H:%M}, "
        f"used_firelines={len(blocks_202)}"
    )

    elapsed = time.perf_counter() - start_time_runtime
    minutes = int(elapsed // 60)
    seconds = elapsed % 60

    print(f"[RUNTIME] Total elapsed time: {elapsed:.2f} s")
    print(f"[RUNTIME] Total elapsed time: {minutes} min {seconds:.2f} sec")


if __name__ == "__main__":
    main()
