#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from data.Domain.domain_utils import load_domain_config
from rdaps_source_utils import read_source_plan
from rdaps_vertical_hourly import choose_levels, write_hourly_plan

POINT_FILE = SCRIPT_DIR / "RDAPS_point.txt"
DATES_FILE = SCRIPT_DIR / "rdaps_dates.txt"
DATA_ROOT = PROJECT_DIR / "data" / "RDAPS-KIM"
OUT_ENV = SCRIPT_DIR / "rdaps_vertical_config.env"
OUT_INFO = SCRIPT_DIR / "rdaps_vertical_config.txt"
WORK_DIR = SCRIPT_DIR / "1_gb2"

TMP_START = 1
U_START = 79
V_START = 118
HGT_START = 196
HGT_PROBE_COUNT = 15
SAFETY_EXTRA_LEVELS = 3


def configure_grib_record_layout(source_type: str, product: str) -> None:
    global TMP_START, U_START, V_START, HGT_START, HGT_PROBE_COUNT

    if source_type == "grib_pres" or product == "pres":
        # PRES GRIB inventory:
        # TMP 1-24, RH 25-48, UGRD 49-72, VGRD 73-96, HGT 121-144.
        # PRES GRIB provides air temperature as TMP.
        TMP_START = 1
        U_START = 49
        V_START = 73
        HGT_START = 121
        HGT_PROBE_COUNT = 24
    else:
        # ETAS GRIB inventory used by the original workflow:
        # ETAS GRIB TMP starts at 1, U/V/HGT at these fixed message positions.
        TMP_START = 1
        U_START = 79
        V_START = 118
        HGT_START = 196
        HGT_PROBE_COUNT = 15


def read_dates(path: Path) -> list[datetime]:
    dates = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            dates.append(datetime.strptime(text, "%Y.%m.%d.%H"))
    if not dates:
        raise ValueError(f"No valid dates found in {path}")
    return dates


def rdaps_file_for_valid_time(valid_kst: datetime) -> tuple[Path, str]:
    planned = read_source_plan().get(valid_kst.strftime("%Y%m%d%H"))
    if planned is not None:
        return planned.path, valid_kst.strftime("%Y%m%d%H")

    valid_utc = valid_kst - timedelta(hours=9)
    base_hour = (valid_utc.hour // 6) * 6
    hhh = valid_utc.hour - base_hour
    base_utc = valid_utc.replace(hour=base_hour)

    if hhh == 0:
        base_utc = base_utc - timedelta(hours=6)
        hhh = 6

    product = "etas"
    filename = f"r030_v040_ne36_{product}_h{hhh:03d}.{base_utc:%Y%m%d%H}.gb2"
    return DATA_ROOT / filename, valid_kst.strftime("%Y%m%d%H")


def read_points(path: Path) -> list[tuple[str, str, str, str, str]]:
    points: list[tuple[str, str, str, str, str]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 4 or parts[0].startswith("#"):
                continue
            role = parts[4] if len(parts) >= 5 else "interior"
            points.append((parts[0], parts[1], parts[2], parts[3], role))

    if not points:
        raise ValueError(f"No usable points in {path}")
    return points


def parse_wgrib_value(line: str) -> float:
    match = re.search(r"(?:^|[, :])val=([^,\s]+)", line)
    if not match:
        raise ValueError(f"Cannot parse wgrib2 val= field from: {line}")
    return float(match.group(1))


def build_hgt_probe_minigrib(grib_path: Path, out_path: Path) -> None:
    """Copy only the HGT probe records into a small temporary GRIB2 file."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    record_end = HGT_START + HGT_PROBE_COUNT - 1
    cmd = [
        "wgrib2",
        str(grib_path),
        "-for",
        f"{HGT_START}:{record_end}",
        "-grib",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, text=True, capture_output=True)

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"Failed to create HGT probe mini-GRIB: {out_path}")


def run_wgrib_hgt_profile(grib_path: Path, lon: str, lat: str) -> list[float]:
    """Read all HGT probe levels for one point with a single wgrib2 call."""
    cmd = [
        "wgrib2",
        str(grib_path),
        "-for",
        f"1:{HGT_PROBE_COUNT}",
        "-lon",
        lon,
        lat,
    ]
    proc = subprocess.run(cmd, check=True, text=True, capture_output=True)
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    heights = [parse_wgrib_value(line) for line in lines]

    if len(heights) != HGT_PROBE_COUNT:
        raise RuntimeError(
            f"Unexpected HGT profile line count at lon={lon}, lat={lat}: "
            f"got={len(heights)}, expected={HGT_PROBE_COUNT}"
        )

    return heights


def probe_point(
    point: tuple[str, str, str, str, str],
    grib_path: Path,
    target_height: float,
) -> tuple[str, str, str, str, str, int, int, list[float]]:
    xxx, yyy, lon, lat, role = point
    heights = run_wgrib_hgt_profile(grib_path, lon, lat)

    needed, extraction_count = choose_levels(heights, target_height, SAFETY_EXTRA_LEVELS)
    return xxx, yyy, lon, lat, role, needed, extraction_count, heights


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workers",
        type=int,
        help="Number of RDAPS points to probe in parallel.",
    )
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
    points = read_points(POINT_FILE)
    plan = read_source_plan()
    hourly = []
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    # Hours are sequential; probe points within one hour in parallel.
    # Record-layout globals stay fixed until that hour's workers finish.
    for valid_kst in dates:
        grib_path, date_valid = rdaps_file_for_valid_time(valid_kst)
        planned = plan.get(date_valid)
        if planned is not None:
            if not planned.source_type.startswith("grib_"):
                raise ValueError(f"Expected GRIB for {date_valid}, got {planned.source_type}")
            configure_grib_record_layout(planned.source_type, planned.product)
        else:
            configure_grib_record_layout("grib_etas", "etas")
        print(f"[INFO] Probing RDAPS GRIB: valid_kst={date_valid} "
              f"file={grib_path} probe_count={HGT_PROBE_COUNT}")
        if not grib_path.exists():
            raise FileNotFoundError(f"RDAPS GRIB2 not found for {date_valid}: {grib_path}")
        probe_grib = WORK_DIR / f".rdaps_hgt_probe_{date_valid}.gb2"
        indexed_results = []
        try:
            build_hgt_probe_minigrib(grib_path, probe_grib)
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                future_to_idx = {
                    executor.submit(probe_point, point, probe_grib, target_height): idx
                    for idx, point in enumerate(points)
                }
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    try:
                        indexed_results.append((idx, future.result()))
                    except (ValueError, RuntimeError) as exc:
                        point = points[idx]
                        raise ValueError(f"valid_kst={date_valid} file={grib_path} "
                                         f"point={point[0]}_{point[1]}: {exc}") from exc
        finally:
            if probe_grib.exists():
                probe_grib.unlink()
        point_results = [result for _idx, result in sorted(indexed_results)]
        hourly.append({"date": valid_kst, "path": grib_path,
                       "results": point_results,
                       "starts": {"TMP": TMP_START, "U": U_START,
                                  "V": V_START, "HGT": HGT_START}})
    write_hourly_plan(hourly, cfg, target_height, SAFETY_EXTRA_LEVELS, OUT_ENV, OUT_INFO)
    print(f"[OK] RDAPS GRIB hourly probe completed: times={len(hourly)}, "
          f"points={len(points)}, total_probes={len(hourly) * len(points)}, "
          f"workers={args.workers}")


if __name__ == "__main__":
    main()
