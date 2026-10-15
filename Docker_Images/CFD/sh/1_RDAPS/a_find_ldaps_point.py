#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UTM-K center -> 20 km domain corners
+ nearest record search + LDAPS_point.txt exporter.

What this script does
---------------------
1) Reads center UTM-K x/y from LOCATION_TXT (line1=x, line2=y).
2) Builds a 20 km x 20 km domain (half width = 10 km) in projected meters.
3) Scans RECORDS_TXT (rows contain '(i,j) lat lon x y' or similar),
   reprojects each row's (lat, lon) to UTMK, and finds the nearest record
   to the SW corner and the nearest record to the NE corner.
   - With REQUIRE_MODE="per_corner":
       SW candidate must be at or southwest of the SW corner (x<=x_sw, y<=y_sw)
       NE candidate must be at or northeast of the NE corner (x>=x_ne, y>=y_ne)
   - With REQUIRE_MODE="none":
       No constraints; pure nearest distance.
4) Uses the (i,j) rectangle between SW and NE indices to export all grid points
   in that box to LDAPS_point.txt with format: "ii jj lon lat".

Notes
-----
- Internally we use GIS convention: x=Easting, y=Northing.
- SWAP_XY_OUTPUT only affects console printing.
"""

import os
import re
import sys
import numpy as np
import csv
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple, Dict, Optional, List
from pyproj import CRS, Transformer

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from data.Domain.domain_utils import load_domain_config
from rdaps_nc_utils import coord_2d, open_nc, read_dates
from rdaps_source_utils import select_source, write_source_plan, SourceSelection

# =========================
# Inputs / Options
# =========================
LOCATION_TXT = "../data/Event/location.txt"          # line1 = UTM-K X, line2 = UTM-K Y
RECORDS_TXT  = "latlon_utmk_output.txt"

REQUIRE_MODE = "per_corner"            # "per_corner" | "none"
SWAP_XY_OUTPUT = False

LDAPS_POINTS_OUT = "./RDAPS_point.txt"
RDAPS_INDEX_BUFFER = 1

UTMK_CRS = CRS.from_epsg(5179)
WGRIB2_BIN = os.environ.get("WGRIB2_BIN", "wgrib2")

# =========================
# Coordinate utilities
# =========================
def read_location(path: str) -> Tuple[float, float]:
    """Read UTM-K x/y from a 2-line text file (x on line 1, y on line 2)."""
    with open(path, "r", encoding="utf-8-sig") as f:
        vals = [ln.strip() for ln in f if ln.strip()]

    if len(vals) < 2:
        raise ValueError(f"Location file must have 2 lines (UTM-K X, Y): {path}")

    x = float(vals[0])
    y = float(vals[1])
    return x, y

def latlon_to_utmk(lat: float, lon: float) -> Tuple[float, float]:
    """Project WGS84 lat/lon to UTM-K meters: returns (x=Easting, y=Northing)."""
    tf = Transformer.from_crs("EPSG:4326", UTMK_CRS, always_xy=True)
    x, y = tf.transform(lon, lat)
    return x, y

def _xy_for_output(x: float, y: float) -> Tuple[float, float]:
    """Return (x_out, y_out) depending on SWAP_XY_OUTPUT flag."""
    return (y, x) if SWAP_XY_OUTPUT else (x, y)

# =========================
# Record parsing & nearest search
# =========================
def parse_record(line: str) -> Optional[Tuple[str, float, float]]:
    """
    Parse a record line.

    Expected examples:
      '(137,51)     33.009367  124.003220    46730.30   106855.62'

    Returns:
      (idx_token, lat, lon) or None
    """
    s = line.strip()
    if not s:
        return None

    lower = s.lower()
    if ("index" in lower and "lat" in lower and "lon" in lower) or s.startswith("#"):
        return None

    parts = s.split()
    if len(parts) < 3:
        return None

    idx_token = parts[0]

    nums: List[float] = []
    for tok in parts[1:]:
        try:
            nums.append(float(tok))
        except ValueError:
            continue

    if len(nums) < 2:
        return None

    latf, lonf = nums[0], nums[1]
    return idx_token, latf, lonf

def parse_idx_token(token: str) -> Tuple[int, int]:
    """Extract integer indices (i,j) from a token like '(137,51)'."""
    m = re.search(r'(-?\d+)\s*,\s*(-?\d+)', token)
    if not m:
        raise ValueError(f"Cannot parse index token: {token}")
    return int(m.group(1)), int(m.group(2))

def find_nearest_in_file(records_path: str,
                         x_sw: float, y_sw: float,
                         x_ne: float, y_ne: float,
                         mode: str = "per_corner"
                         ) -> Dict[str, Optional[Tuple[str, float, float, float, float]]]:
    """
    Find nearest record to SW and NE corners.

    Returns:
      {
        "SW": (idx_token, lat, lon, x_utmk, y_utmk) or None,
        "NE": (idx_token, lat, lon, x_utmk, y_utmk) or None
      }
    """
    tf = Transformer.from_crs("EPSG:4326", UTMK_CRS, always_xy=True)

    best_sw = None
    best_ne = None
    best_sw_d2 = float("inf")
    best_ne_d2 = float("inf")

    with open(records_path, "r", encoding="utf-8-sig") as f:
        for ln in f:
            rec = parse_record(ln)
            if rec is None:
                continue

            idx_token, latf, lonf = rec
            x, y = tf.transform(lonf, latf)

            if mode == "per_corner":
                sw_ok = (x <= x_sw and y <= y_sw)
                ne_ok = (x >= x_ne and y >= y_ne)
            else:
                sw_ok = True
                ne_ok = True

            if sw_ok:
                dx = x - x_sw
                dy = y - y_sw
                d2 = dx * dx + dy * dy
                if d2 < best_sw_d2:
                    best_sw_d2 = d2
                    best_sw = (idx_token, latf, lonf, x, y)

            if ne_ok:
                dx = x - x_ne
                dy = y - y_ne
                d2 = dx * dx + dy * dy
                if d2 < best_ne_d2:
                    best_ne_d2 = d2
                    best_ne = (idx_token, latf, lonf, x, y)

    return {"SW": best_sw, "NE": best_ne}

# =========================
# LDAPS points exporter
# =========================
def build_index_lonlat_map(records_path: str) -> Dict[Tuple[int, int], Tuple[float, float]]:
    """Build mapping: (i,j) -> (lon, lat)."""
    mp: Dict[Tuple[int, int], Tuple[float, float]] = {}
    with open(records_path, "r", encoding="utf-8-sig") as f:
        for ln in f:
            rec = parse_record(ln)
            if rec is None:
                continue
            idx_token, latf, lonf = rec
            i, j = parse_idx_token(idx_token)
            mp[(i, j)] = (lonf, latf)

    if not mp:
        raise RuntimeError(f"No usable rows found in records file: {records_path}")

    return mp

def write_ldaps_points(sw_idx_token: str,
                       ne_idx_token: str,
                       records_path: str,
                       out_path: str) -> None:
    """
    Write all (i,j) within the SW-NE rectangle:
      ii jj lon lat role
    """
    i_sw, j_sw = parse_idx_token(sw_idx_token)
    i_ne, j_ne = parse_idx_token(ne_idx_token)

    i0, i1 = sorted((i_sw, i_ne))
    j0, j1 = sorted((j_sw, j_ne))

    i0 -= RDAPS_INDEX_BUFFER
    i1 += RDAPS_INDEX_BUFFER
    j0 -= RDAPS_INDEX_BUFFER
    j1 += RDAPS_INDEX_BUFFER

    idx2lonlat = build_index_lonlat_map(records_path)

    missing: List[Tuple[int, int]] = []
    n_written = 0

    with open(out_path, "w", encoding="utf-8") as fout:
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                key = (i, j)
                if key not in idx2lonlat:
                    missing.append(key)
                    continue
                lon, lat = idx2lonlat[key]
                if i == i0 or i == i1 or j == j0 or j == j1:
                    role = "boundary"
                else:
                    role = "interior"
                fout.write(f"{i:02d} {j:02d} {lon:.6f} {lat:.6f} {role}\n")
                n_written += 1

    if missing:
        print(f"[WARN] {len(missing)} indices were skipped (first missing: {missing[0]})")

#    print(f"[OK] Wrote {n_written} points to {out_path}")


def find_nearest_in_nc(
    lats: np.ndarray,
    lons: np.ndarray,
    x_sw: float,
    y_sw: float,
    x_ne: float,
    y_ne: float,
    mode: str = "per_corner",
) -> Dict[str, Optional[Tuple[int, int, float, float, float, float]]]:
    tf = Transformer.from_crs("EPSG:4326", UTMK_CRS, always_xy=True)
    xs, ys = tf.transform(lons, lats)

    if mode == "per_corner":
        sw_mask = (xs <= x_sw) & (ys <= y_sw)
        ne_mask = (xs >= x_ne) & (ys >= y_ne)
    else:
        sw_mask = np.isfinite(xs)
        ne_mask = np.isfinite(xs)

    result: Dict[str, Optional[Tuple[int, int, float, float, float, float]]] = {
        "SW": None,
        "NE": None,
    }

    for key, tx, ty, mask in (
        ("SW", x_sw, y_sw, sw_mask),
        ("NE", x_ne, y_ne, ne_mask),
    ):
        if not np.any(mask):
            continue
        dist2 = (xs - tx) ** 2 + (ys - ty) ** 2
        dist2 = np.where(mask, dist2, np.nan)
        iy, ix = np.unravel_index(np.nanargmin(dist2), dist2.shape)
        result[key] = (
            int(ix + 1),
            int(iy + 1),
            float(lats[iy, ix]),
            float(lons[iy, ix]),
            float(xs[iy, ix]),
            float(ys[iy, ix]),
        )
    return result


def write_nc_coordinate_file(lats: np.ndarray, lons: np.ndarray, out_path: str) -> None:
    tf = Transformer.from_crs("EPSG:4326", UTMK_CRS, always_xy=True)
    xs, ys = tf.transform(lons, lats)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write("# index      lat        lon          y_utmk        x_utmk\n")
        ny, nx = lats.shape
        for iy in range(ny):
            for ix in range(nx):
                f.write(
                    f"({ix+1},{iy+1})  {lats[iy, ix]:10.6f}  {lons[iy, ix]:10.6f}  "
                    f"{ys[iy, ix]:12.2f}  {xs[iy, ix]:12.2f}\n"
                )
    tmp.replace(out)


def write_ldaps_points_from_nc(
    sw: Tuple[int, int, float, float, float, float],
    ne: Tuple[int, int, float, float, float, float],
    lats: np.ndarray,
    lons: np.ndarray,
    out_path: str,
) -> None:
    i_sw, j_sw = sw[0], sw[1]
    i_ne, j_ne = ne[0], ne[1]
    i0, i1 = sorted((i_sw, i_ne))
    j0, j1 = sorted((j_sw, j_ne))

    i0 = max(1, i0 - RDAPS_INDEX_BUFFER)
    i1 = min(lons.shape[1], i1 + RDAPS_INDEX_BUFFER)
    j0 = max(1, j0 - RDAPS_INDEX_BUFFER)
    j1 = min(lons.shape[0], j1 + RDAPS_INDEX_BUFFER)

    with open(out_path, "w", encoding="utf-8") as fout:
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                role = "boundary" if i == i0 or i == i1 or j == j0 or j == j1 else "interior"
                fout.write(f"{i} {j} {lons[j-1, i-1]:.6f} {lats[j-1, i-1]:.6f} {role}\n")


def parse_grib_grid_size(grib_path: Path, record: int = 1) -> Tuple[int, int]:
    proc = subprocess.run(
        [WGRIB2_BIN, str(grib_path), "-d", str(record), "-grid"],
        check=True,
        text=True,
        capture_output=True,
    )
    match = re.search(r"\((\d+)\s*x\s*(\d+)\)", proc.stdout)
    if not match:
        raise RuntimeError(f"Cannot parse GRIB grid size from: {grib_path}")
    return int(match.group(1)), int(match.group(2))


def detect_csv_lat_lon(a: float, b: float) -> Tuple[float, float]:
    a_is_lat = abs(a) <= 90.0
    b_is_lat = abs(b) <= 90.0
    if a_is_lat and not b_is_lat:
        return a, b
    if b_is_lat and not a_is_lat:
        return b, a
    return b, a


def write_grib_coordinate_file(grib_path: Path, out_path: str, record: int = 1) -> None:
    nx, ny = parse_grib_grid_size(grib_path, record)
    expected_count = nx * ny
    tf = Transformer.from_crs("EPSG:4326", UTMK_CRS, always_xy=True)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out.with_suffix(out.suffix + ".tmp")

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "grib_grid.csv"
        subprocess.run(
            [WGRIB2_BIN, str(grib_path), "-d", str(record), "-csv", str(csv_path)],
            check=True,
            text=True,
        )

        count = 0
        with csv_path.open("r", encoding="utf-8", newline="") as src, tmp_out.open(
            "w", encoding="utf-8"
        ) as dst:
            dst.write("# index      lat        lon          y_utmk        x_utmk\n")
            reader = csv.reader(src)
            for row in reader:
                if len(row) < 7:
                    continue
                count += 1
                i = ((count - 1) % nx) + 1
                j = ((count - 1) // nx) + 1
                lat, lon = detect_csv_lat_lon(float(row[4]), float(row[5]))
                x, y = tf.transform(lon, lat)
                dst.write(
                    f"({i},{j})   {lat:10.6f}  {lon:10.6f}"
                    f"  {y:12.2f}  {x:12.2f}\n"
                )

        if count != expected_count:
            tmp_out.unlink(missing_ok=True)
            raise RuntimeError(
                f"Unexpected GRIB grid point count: got={count}, expected={expected_count}"
            )

    tmp_out.replace(out)
    print(f"[OK] Wrote GRIB coordinate file from {grib_path.name}: {out}")


def prepare_source_coordinates() -> Optional[SourceSelection]:
    dates = read_dates(SCRIPT_DIR / "rdaps_dates.txt")
    selections = select_source(dates)
    write_source_plan(selections)

    first = selections[0]
    source_label = {
        "nc_pres": "NC PRES",
        "grib_etas": "GRIB ETAS",
        "grib_pres": "GRIB PRES",
    }.get(first.source_type, first.source_type)
    print(
        f"[INFO] Selected RDAPS source for point search: {source_label} "
        f"cycle={first.cycle_utc:%Y%m%d%H} fhr={first.fhr:03d} file={first.path.name}"
    )

    if first.source_type in ("grib_etas", "grib_pres"):
        write_grib_coordinate_file(first.path, RECORDS_TXT)
    return first

# =========================
# Main
# =========================
def main():
    # 1) Read center directly in UTM-K
    cx, cy = read_location(LOCATION_TXT)
    cfg = load_domain_config(PROJECT_DIR)

    # 2) Build configured square domain corners
    hw = cfg.half_width_m
    x_sw, y_sw = cx - hw, cy - hw
    x_nw, y_nw = cx - hw, cy + hw
    x_ne, y_ne = cx + hw, cy + hw
    x_se, y_se = cx + hw, cy - hw

    source = prepare_source_coordinates()
    if source is not None and source.source_type == "nc_pres":
        with open_nc(source.path) as ds:
            lats, lons = coord_2d(ds)

        res_nc = find_nearest_in_nc(
            lats,
            lons,
            x_sw,
            y_sw,
            x_ne,
            y_ne,
            mode=REQUIRE_MODE,
        )
        if res_nc["SW"] is not None and res_nc["NE"] is not None:
            write_ldaps_points_from_nc(res_nc["SW"], res_nc["NE"], lats, lons, LDAPS_POINTS_OUT)
            write_nc_coordinate_file(lats, lons, RECORDS_TXT)
            print("----------------------------------------------------")
            print(f"[OK] Wrote NC-based RDAPS points from {source.path.name}")
            return

        print("[WARN] NC coordinate search failed for SW or NE; falling back to coordinate text file.")

    # 3) Find nearest LDAPS records
    res = find_nearest_in_file(
        RECORDS_TXT,
        x_sw, y_sw,
        x_ne, y_ne,
        mode=REQUIRE_MODE
    )

    # 4) Console output
    cxo, cyo = _xy_for_output(cx, cy)
    x_swo, y_swo = _xy_for_output(x_sw, y_sw)
    x_nwo, y_nwo = _xy_for_output(x_nw, y_nw)
    x_neo, y_neo = _xy_for_output(x_ne, y_ne)
    x_seo, y_seo = _xy_for_output(x_se, y_se)

#    print()
#    print("--- UTM-K (EPSG:5179) Coordinates ---")
#    print(f"Center Easting  (x): {cxo:12.3f}")
#    print(f"Center Northing (y): {cyo:12.3f}")
#    print()
#    print(f"SW corner (x, y): {x_swo:12.2f}, {y_swo:12.2f}")
#    print(f"NW corner (x, y): {x_nwo:12.2f}, {y_nwo:12.2f}")
#    print(f"NE corner (x, y): {x_neo:12.2f}, {y_neo:12.2f}")
#    print(f"SE corner (x, y): {x_seo:12.2f}, {y_seo:12.2f}")
#    print("----------------------------------------------------")

    if res["SW"] is not None:
        idx_token, latf, lonf, x, y = res["SW"]
        xo, yo = _xy_for_output(x, y)
#        print("[SW nearest]")
#        print(f"  idx={idx_token}  lat={latf:.6f}  lon={lonf:.6f}  x={xo:.2f}  y={yo:.2f}")
    else:
        print("[SW nearest] -> (no matching record found under current constraints)")

    if res["NE"] is not None:
        idx_token, latf, lonf, x, y = res["NE"]
        xo, yo = _xy_for_output(x, y)
#        print("[NE nearest]")
#        print(f"  idx={idx_token}  lat={latf:.6f}  lon={lonf:.6f}  x={xo:.2f}  y={yo:.2f}")
    else:
        print("[NE nearest] -> (no matching record found under current constraints)")

    print("----------------------------------------------------")

    # 5) Export LDAPS_point.txt
    if res["SW"] is not None and res["NE"] is not None:
        sw_idx_token = res["SW"][0]
        ne_idx_token = res["NE"][0]
        write_ldaps_points(sw_idx_token, ne_idx_token, RECORDS_TXT, LDAPS_POINTS_OUT)
    else:
        print("[SKIP] Cannot build LDAPS_point.txt because SW or NE is missing.")
        print("       Tip: set REQUIRE_MODE='none' if constraints are too strict.")

if __name__ == "__main__":
    if not os.path.isfile(LOCATION_TXT):
        raise FileNotFoundError(f"Location file not found: {LOCATION_TXT}")
    main()
