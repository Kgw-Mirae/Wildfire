"""Validate HGT and write plans keyed by valid KST hour and RDAPS point."""
from __future__ import annotations

import math
from pathlib import Path


def choose_levels(heights, target_height: float, safety_extra: int) -> tuple[int, int]:
    if not math.isfinite(target_height) or target_height <= 0:
        raise ValueError(f"Invalid CFD target height: {target_height}")
    if len(heights) < 2:
        raise ValueError("At least two HGT levels are required")
    for index, height in enumerate(heights):
        if not math.isfinite(height) or abs(height) > 1.0e6:
            raise ValueError(f"Invalid HGT at level {index + 1}: {height}")
        if index and height <= heights[index - 1]:
            raise ValueError(f"HGT must increase strictly: levels {index}/{index + 1}")
    if heights[0] > target_height or heights[-1] < target_height:
        raise ValueError(
            f"HGT levels do not bracket target height {target_height:g} m; "
            f"sampled range={heights[0]:g}..{heights[-1]:g} m"
        )
    needed = max(2, next(i for i, h in enumerate(heights, 1) if h >= target_height))
    return needed, min(len(heights), needed + safety_extra)


def write_hourly_plan(hourly, cfg, target_height, safety_extra, out_env: Path, out_info: Path):
    """hourly entries contain date, path, results, and variable record starts."""
    if not hourly or any(not hour["results"] for hour in hourly):
        raise ValueError("No valid hours or RDAPS points to probe")
    tags = [hour["date"].strftime("%Y%m%d%H") for hour in hourly]
    if len(tags) != len(set(tags)):
        raise ValueError("Duplicate valid hour in RDAPS date list")
    results = [r for hour in hourly for r in hour["results"]]
    max_needed = max(r[5] for r in results)
    max_count = max(r[6] for r in results)
    env = [
        "# Auto-generated hourly vertical plan; valid time is KST.",
        "# Requires the matching hourly b_extract_all.ksh / b_extract_all_nc.py.",
        "RDAPS_VERTICAL_PLAN_VERSION=2",
        f"RDAPS_TARGET_HEIGHT_M={target_height:.6f}",
        f"RDAPS_MAX_VERTICAL_LEVEL_COUNT={max_needed}",
        f"RDAPS_MAX_EXTRACTION_LEVEL_COUNT={max_count}",
        f"RDAPS_SAFETY_EXTRA_LEVELS={safety_extra}",
        "set_vertical_time() {",
        '  case "${1:-}" in',
    ]
    for hour, tag in zip(hourly, tags):
        count = max(r[6] for r in hour["results"])
        env += [f"    {tag}) RDAPS_TIME_MAX_EXTRACTION_LEVEL_COUNT={count} ;; "]
    env += [
        '    *) echo "ERROR: No vertical plan for valid_kst=${1:-}" >&2; return 1 ;;',
        "  esac", "}", "set_vertical_lists() {",
        '  set_vertical_time "${3:-}" || return 1',
        '  case "${3:-}_${1:-}_${2:-}" in',
    ]
    info = [
        "RDAPS_VERTICAL_PLAN_VERSION 2",
        f"TIMES_PROBED {len(hourly)}",
        f"TARGET_HEIGHT_M {target_height:.6f}",
        f"CFD_KMAX {cfg.kmax}",
        f"CFD_DZ {cfg.vertical_resolution_m:.6f}",
        f"RDAPS_MAX_VERTICAL_LEVEL_COUNT {max_needed}",
        f"RDAPS_MAX_EXTRACTION_LEVEL_COUNT {max_count}",
        f"RDAPS_SAFETY_EXTRA_LEVELS {safety_extra}",
    ]
    for hour, tag in zip(hourly, tags):
        info += [f"DATE_VALID {tag}", f"SOURCE_FILE {hour['path']}"]
        for x, y, lon, lat, role, needed, count, heights in hour["results"]:
            # Normalize numeric indices so Bash and Python use the same keys.
            x, y = int(x), int(y)
            env.append(f"    {tag}_{x}_{y})")
            for variable, start in hour["starts"].items():
                full = range(start, start + count)
                top = range(start + needed - 2, start + needed)
                for kind, values in (("FULL", full), ("TOP", top)):
                    value = " ".join(str(v) for v in values)
                    env.append(f'      {variable}_LIST_{kind}="{value}"')
            env += [f"      RDAPS_VERTICAL_LEVEL_COUNT={count}",
                    f"      RDAPS_NEEDED_LEVEL_COUNT={needed}", "      ;; "]
            info += [
                f"POINT {x} {y} {float(lon):.6f} {float(lat):.6f} {role}",
                f"RDAPS_VERTICAL_LEVEL_COUNT {needed}",
                f"RDAPS_EXTRACTION_LEVEL_COUNT {count}",
                "HGT_SAMPLE_M " + " ".join(f"{v:.6f}" for v in heights),
            ]
        print(f"[OK] Hourly vertical plan: valid_kst={tag} "
              f"points={len(hour['results'])} "
              f"max_needed={max(r[5] for r in hour['results'])} "
              f"max_extracted={max(r[6] for r in hour['results'])}")
    env += [
        '    *) echo "ERROR: No vertical list for ${3:-}_${1:-}_${2:-}" >&2; return 1 ;;',
        "  esac", "}", "",
    ]
    # Publish only after every hour has passed validation.
    for path, lines in ((out_env, env), (out_info, info + [""])):
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(lines), encoding="utf-8")
        tmp.replace(path)
