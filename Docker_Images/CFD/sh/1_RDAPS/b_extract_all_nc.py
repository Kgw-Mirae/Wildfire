#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from rdaps_nc_utils import date_valid_tag, extract_profile, find_nc_file_for_valid_time, open_nc, parse_rdaps_date


OUT_DIR = SCRIPT_DIR / "1_nc"
VERTICAL_INFO = SCRIPT_DIR / "rdaps_vertical_config.txt"
VARS = ("u", "v", "tmp", "hgt")


def read_extraction_counts(path: Path, date_tag: str) -> dict[tuple[int, int], tuple[int, int]]:
    counts = {}
    current_date = None
    current = None
    needed = None
    version = None
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "RDAPS_VERTICAL_PLAN_VERSION":
                version = int(parts[1])
            elif parts[0] == "DATE_VALID":
                current_date = parts[1]
                current = None
                needed = None
            elif parts[0] == "POINT" and len(parts) >= 3:
                current = (int(parts[1]), int(parts[2]))
                needed = None
            elif parts[0] == "RDAPS_VERTICAL_LEVEL_COUNT":
                needed = int(parts[1])
            elif parts[0] == "RDAPS_EXTRACTION_LEVEL_COUNT" and current_date == date_tag:
                if current is None or needed is None:
                    raise ValueError(f"Incomplete hourly vertical plan in {path}")
                count = int(parts[1])
                if not 2 <= needed <= count:
                    raise ValueError(f"Invalid vertical counts for {date_tag} point {current}")
                counts[current] = (needed, count)
    if version != 2:
        raise ValueError("Regenerate the hourly vertical plan with prepare_vertical_levels.py")
    if not counts:
        raise ValueError(f"No vertical plan for valid_kst={date_tag} in {path}")
    return counts


def selected_indices(count: int, date_index: int, role: str, needed: int) -> range:
    if date_index == 1 or role == "boundary":
        return range(0, count)
    # The two HGT levels bracketing CFD top, not the last safety levels.
    return range(needed - 2, needed)


def write_profile(path: Path, values) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as f:
        for value in values:
            f.write(f"{float(value):.8f}\n")
    tmp.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("date", help="Valid KST date in YYYY.MM.DD.HH")
    parser.add_argument("date_index", type=int)
    parser.add_argument("x", type=int)
    parser.add_argument("y", type=int)
    parser.add_argument("lon", type=float)
    parser.add_argument("lat", type=float)
    parser.add_argument("role", nargs="?", default="interior")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    valid_kst = parse_rdaps_date(args.date)
    date_tag = date_valid_tag(valid_kst)
    nc_path, init, fhr = find_nc_file_for_valid_time(valid_kst, prefer="prs")
    valid_utc = valid_kst - timedelta(hours=9)
    counts = read_extraction_counts(VERTICAL_INFO, date_tag)
    level_info = counts.get((args.x, args.y))
    if level_info is None:
        raise KeyError(f"No extraction count for point {args.x}_{args.y} in {VERTICAL_INFO}")

    needed, count = level_info
    ix0 = args.x - 1
    iy0 = args.y - 1
    keep = list(selected_indices(count, args.date_index, args.role, needed))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with open_nc(nc_path) as ds:
        for var in VARS:
            _height, values = extract_profile(ds, var, ix0, iy0)
            if len(values) < count:
                raise ValueError(
                    f"{nc_path.name} {args.x}_{args.y} {var}: "
                    f"profile has {len(values)} levels, expected at least {count}"
                )
            out_file = OUT_DIR / f"{args.x}_{args.y}_{date_tag}_{var}.txt"
            write_profile(out_file, [values[idx] for idx in keep])

    print(
        f"[OK] Extracted NC point {args.x}_{args.y} {date_tag} "
        f"valid_utc={valid_utc:%Y%m%d%H} cycle={init} ft{fhr:03d} "
        f"from {nc_path.name}"
    )


if __name__ == "__main__":
    main()
