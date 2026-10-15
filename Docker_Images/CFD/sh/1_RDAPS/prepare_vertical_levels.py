#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from data.Domain.domain_utils import load_domain_config
from rdaps_nc_utils import (
    extract_profile,
    open_nc,
    read_dates,
    read_points,
    write_nc_file_plan,
)
from rdaps_source_utils import select_source, write_source_plan
from rdaps_vertical_hourly import choose_levels, write_hourly_plan


POINT_FILE = SCRIPT_DIR / "RDAPS_point.txt"
DATES_FILE = SCRIPT_DIR / "rdaps_dates.txt"
OUT_ENV = SCRIPT_DIR / "rdaps_vertical_config.env"
OUT_INFO = SCRIPT_DIR / "rdaps_vertical_config.txt"
SAFETY_EXTRA_LEVELS = 3


def probe_point(
    point: tuple[int, int, float, float, str],
    ds,
    target_height: float,
) -> tuple[int, int, float, float, str, int, int, list[float]]:
    x, y, lon, lat, role = point
    ix0 = x - 1
    iy0 = y - 1

    _height, hgt = extract_profile(ds, "hgt", ix0, iy0)

    heights = [float(v) for v in hgt]
    needed, extraction_count = choose_levels(heights, target_height, SAFETY_EXTRA_LEVELS)
    return x, y, lon, lat, role, needed, extraction_count, heights


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, help="Number of RDAPS points to probe in parallel.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.workers is None:
        raise ValueError("--workers must be set by 0_run_all.sh")
    if args.workers <= 0:
        raise ValueError("--workers must be positive")

    cfg = load_domain_config(PROJECT_DIR)
    target_height = cfg.kmax * cfg.vertical_resolution_m
    dates = read_dates(DATES_FILE)
    source_selections = select_source(dates)
    write_source_plan(source_selections)
    if not source_selections:
        raise ValueError("No RDAPS valid hours selected")
    source_type = source_selections[0].source_type
    source_label = {
        "nc_pres": "NC PRES",
        "grib_etas": "GRIB ETAS",
        "grib_pres": "GRIB PRES",
    }.get(source_type, source_type)
    print(f"[OK] Weather input source selected: {source_label}")
    print(
        "[INFO] Selected RDAPS source: "
        f"{source_type}, product={source_selections[0].product}, "
        "cycle/lead selected per valid time"
    )
    for item in source_selections:
        print(
            "[INFO] RDAPS source file: "
            f"valid_kst={item.valid_kst:%Y%m%d%H} "
            f"valid_utc={item.valid_utc:%Y%m%d%H} "
            f"source={item.source_type} "
            f"cycle={item.cycle_utc:%Y%m%d%H} "
            f"h/ft{item.fhr:03d} file={item.path.name}"
        )

    if source_type != "nc_pres":
        cmd = [sys.executable, str(SCRIPT_DIR / "prepare_vertical_levels_grib.py"), "--workers", str(args.workers)]
        subprocess.run(cmd, check=True)
        return

    selections = source_selections
    write_nc_file_plan(selections)
    points = read_points(POINT_FILE)
    hourly = []
    for item in selections:
        tag = item.valid_kst.strftime("%Y%m%d%H")
        print(f"[INFO] Probing RDAPS NetCDF: valid_kst={tag} "
              f"cycle={item.cycle_utc:%Y%m%d%H} ft{item.fhr:03d} file={item.path.name}")
        point_results = []
        with open_nc(item.path) as ds:
            for point in points:
                try:
                    point_results.append(probe_point(point, ds, target_height))
                except (ValueError, RuntimeError) as exc:
                    raise ValueError(f"valid_kst={tag} file={item.path} "
                                     f"point={point[0]}_{point[1]}: {exc}") from exc
        hourly.append({"date": item.valid_kst, "path": item.path,
                       "results": point_results,
                       "starts": {"TMP": 1, "U": 1, "V": 1, "HGT": 1}})
    write_hourly_plan(hourly, cfg, target_height, SAFETY_EXTRA_LEVELS, OUT_ENV, OUT_INFO)
    print(f"[OK] RDAPS NetCDF hourly probe completed: times={len(hourly)}, "
          f"points={len(points)}, total_probes={len(hourly) * len(points)}")


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        message = str(exc)
        if "No weather input data found" in message:
            print(f"[ERROR] {message}", file=sys.stderr)
            sys.exit(1)
        raise
