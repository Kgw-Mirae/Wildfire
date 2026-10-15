#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from data.Domain.domain_utils import load_domain_config
from fireline_schedule import build_fireline_schedule


PROJECT_DIR = Path(__file__).resolve().parent
DOMAIN_DIR = PROJECT_DIR / "data" / "Domain"
MOMENT_NAMELIST = PROJECT_DIR / "2_moment" / "input.namelist"
EVENT_DATE_FILE = PROJECT_DIR / "data" / "Event" / "date.txt"
GEOJSON_DIR = PROJECT_DIR / "data" / "Geojson"
FIRELINE_INFO_FILE = PROJECT_DIR / "0_fireline" / "result_fireline" / "fire_intensity_timeseries_info.txt"
FIRELINE_TIMESERIES_FILE = PROJECT_DIR / "0_fireline" / "result_fireline" / "fire_intensity_timeseries.txt"


def f_real(value: int | float) -> str:
    text = f"{float(value):.6g}"
    if "." in text or "e" in text.lower():
        return text
    return f"{text}."


def write_text_if_changed(path: Path, text: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8")


def read_domain_info(path: Path) -> dict[str, float]:
    values: dict[str, float] = {}
    if not path.exists():
        return values

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                values[parts[0].upper()] = float(parts[1])
            except ValueError:
                continue

    return values


def read_domain_info_shape(path: Path) -> tuple[int | None, int | None, float | None]:
    ncols = None
    nrows = None
    cellsize = None
    info = read_domain_info(path)
    if "NCOLS" in info:
        ncols = int(info["NCOLS"])
    if "NROWS" in info:
        nrows = int(info["NROWS"])
    if "CELLSIZE" in info:
        cellsize = info["CELLSIZE"]

    return ncols, nrows, cellsize


def read_first_event_yyyymmdd(path: Path) -> int | None:
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            parts = text.split(".")
            if len(parts) < 3:
                raise ValueError(f"Invalid event date format in {path}: {text}")
            year = int(parts[0])
            month = int(parts[1])
            day = int(parts[2])
            return (year * 10000) + (month * 100) + day

    return None


def read_fireline_end_seconds(info_path: Path, timeseries_path: Path) -> int | None:
    if info_path.exists():
        info = read_domain_info(info_path)
        if "MODEL_END_SECONDS" in info:
            return int(round(info["MODEL_END_SECONDS"]))
        if "MODEL_DURATION_SECONDS" in info:
            return int(round(info["MODEL_DURATION_SECONDS"]))
        if "END_SECONDS" in info:
            return int(round(info["END_SECONDS"]))
        if "DURATION_SECONDS" in info:
            return int(round(info["DURATION_SECONDS"]))

    if not timeseries_path.exists():
        return None

    last_seconds = None
    with timeseries_path.open("r", encoding="utf-8-sig", errors="ignore") as f:
        for line in f:
            text = line.strip()
            if not text or "," not in text:
                continue
            parts = [part.strip() for part in text.split(",")]
            if len(parts) < 2:
                continue
            try:
                last_seconds = int(parts[1])
            except ValueError:
                continue

    return last_seconds


def read_fireline_interval_seconds(info_path: Path, timeseries_path: Path) -> float | None:
    if info_path.exists():
        info = read_domain_info(info_path)
        if "TIME_INTERVAL_SECONDS" in info:
            return info["TIME_INTERVAL_SECONDS"]
        if "DURATION_SECONDS" in info and "NTIME" in info and info["NTIME"] > 1:
            return info["DURATION_SECONDS"] / (info["NTIME"] - 1)
        if (
            "START_SECONDS" in info
            and "END_SECONDS" in info
            and "NTIME" in info
            and info["NTIME"] > 1
        ):
            return (info["END_SECONDS"] - info["START_SECONDS"]) / (info["NTIME"] - 1)

    if not timeseries_path.exists():
        return None

    seconds_values: list[int] = []
    with timeseries_path.open("r", encoding="utf-8-sig", errors="ignore") as f:
        for line in f:
            text = line.strip()
            if not text or "," not in text:
                continue
            parts = [part.strip() for part in text.split(",")]
            if len(parts) < 2:
                continue
            try:
                seconds_values.append(int(parts[1]))
            except ValueError:
                continue

    if len(seconds_values) < 2:
        return None

    return float(seconds_values[1] - seconds_values[0])


def domain_info_matches_config(path: Path) -> bool:
    cfg = load_domain_config(PROJECT_DIR)
    info = read_domain_info(path)
    ncols, nrows, cellsize = read_domain_info_shape(path)
    return (
        ncols == cfg.outer_npix
        and nrows == cfg.outer_npix
        and cellsize is not None
        and abs(cellsize - cfg.resolution_m) <= 1.0e-6
        and "VERTICAL_RESOLUTION_M" in info
        and abs(info["VERTICAL_RESOLUTION_M"] - cfg.vertical_resolution_m) <= 1.0e-6
        and "KMAX" in info
        and int(info["KMAX"]) == cfg.kmax
    )


def write_fortran_includes() -> None:
    cfg = load_domain_config(PROJECT_DIR)

    write_text_if_changed(
        DOMAIN_DIR / "topo_domain.inc",
        "\n".join(
            [
                f"        INTEGER,PARAMETER :: out_col={cfg.outer_npix},out_row={cfg.outer_npix},out_kmax={cfg.kmax}",
                f"        REAL,PARAMETER :: odx={f_real(cfg.resolution_m)},ody={f_real(cfg.resolution_m)},odz={f_real(cfg.vertical_resolution_m)}",
                f"        INTEGER,PARAMETER :: new_col={cfg.topo_outer_npix}, new_row={cfg.topo_outer_npix}",
                f"        REAL,PARAMETER :: idx={f_real(cfg.topo_source_res_m)},idy={f_real(cfg.topo_source_res_m)}",
                "",
            ]
        ),
    )

    write_text_if_changed(
        DOMAIN_DIR / "tree_domain.inc",
        "\n".join(
            [
                f"        Integer ,Parameter :: imax={cfg.inner_npix}, jmax={cfg.inner_npix}, kmax={cfg.kmax}",
                f"        Real ,Parameter :: dz={f_real(cfg.vertical_resolution_m)}",
                f"        Integer ,Parameter :: topo_col={cfg.topo_outer_npix}, topo_row={cfg.topo_outer_npix}",
                f"        Integer ,Parameter :: topo_inner_col={cfg.topo_inner_npix}, topo_inner_row={cfg.topo_inner_npix}",
                f"        Integer ,Parameter :: topo_ratio={cfg.topo_ratio}, topo_halo_src={cfg.topo_halo_cells}",
                "",
            ]
        ),
    )

    write_text_if_changed(
        DOMAIN_DIR / "moment_domain.inc",
        "\n".join(
            [
                f"      integer,parameter::imax={cfg.inner_npix},jmax={cfg.inner_npix},kmax={cfg.kmax},ktop1={cfg.kmax},ktop2={cfg.kmax}",
                "",
            ]
        ),
    )

    write_text_if_changed(
        DOMAIN_DIR / "postproc_domain.inc",
        "\n".join(
            [
                f"      integer,parameter :: imax={cfg.inner_npix},jmax={cfg.inner_npix},kmax={cfg.kmax}",
                f"      integer,parameter :: ktop1={cfg.kmax}",
                f"      real,parameter :: cfd_dx={f_real(cfg.resolution_m)},cfd_dy={f_real(cfg.resolution_m)},cfd_dz={f_real(cfg.vertical_resolution_m)}",
                "",
            ]
        ),
    )

    write_text_if_changed(
        DOMAIN_DIR / "rdaps_domain.inc",
        "\n".join(
            [
               f"   integer, parameter :: cfd_dx={cfg.resolution_m}, cfd_dy={cfg.resolution_m}",
               f"   integer, parameter :: cfd_ilmax={cfg.model_npix}, cfd_jlmax={cfg.model_npix}",
               f"   integer, parameter :: cfd_kmax={cfg.kmax}, cfd_kmax1={cfg.kmax + 1}, cfd_kmax2={cfg.kmax + 2}",
               f"   real, parameter :: cfd_dz={f_real(cfg.vertical_resolution_m)}",
               f"   real, parameter :: cfd_zmax={f_real(cfg.kmax * cfg.vertical_resolution_m)}",
                "",
            ]
        ),
    )


def update_moment_namelist_domain_info() -> None:
    if not MOMENT_NAMELIST.exists():
        return

    cfg = load_domain_config(PROJECT_DIR)
    text = MOMENT_NAMELIST.read_text(encoding="utf-8")
    updates = {
        "N_delt": f_real(cfg.time_step_s),
        "N_winter": f_real(cfg.output_interval_s),
        "N_xint": f_real(cfg.resolution_m),
        "N_yint": f_real(cfg.resolution_m),
        "N_zint": f_real(cfg.vertical_resolution_m),
    }
    event_yyyymmdd = read_first_event_yyyymmdd(EVENT_DATE_FILE)
    if event_yyyymmdd is not None:
        updates["N_YYDD"] = str(event_yyyymmdd)
    fireline_end_seconds = None
    fireline_interval_seconds = None
    try:
        schedule = build_fireline_schedule(GEOJSON_DIR, cfg)
        fireline_end_seconds = schedule.model_duration_seconds
        fireline_interval_seconds = schedule.interval.total_seconds()
    except Exception as exc:
        print(f"[WARN] Could not compute fireline schedule from GeoJSON: {exc}")
        fireline_end_seconds = read_fireline_end_seconds(
            FIRELINE_INFO_FILE,
            FIRELINE_TIMESERIES_FILE,
        )
        fireline_interval_seconds = read_fireline_interval_seconds(
            FIRELINE_INFO_FILE,
            FIRELINE_TIMESERIES_FILE,
        )
    if fireline_interval_seconds is not None:
        updates["N_fire"] = f_real(fireline_interval_seconds)
    if fireline_end_seconds is not None:
        updates["N_tend"] = f_real(fireline_end_seconds + cfg.time_step_s)

    for key, value in updates.items():
        pattern = rf"(?im)^(\s*{key}\s*=\s*).*$"
        replacement = rf"\g<1>{value}"
        if re.search(pattern, text):
            text = re.sub(pattern, replacement, text, count=1)

    write_text_if_changed(MOMENT_NAMELIST, text)


def ensure_domain_info_alias() -> None:
    target = DOMAIN_DIR / "output_model_info.txt"

    if target.exists() and not domain_info_matches_config(target):
        print(f"[WARN] Existing {target.name} does not match domain_config.json. Run 0_TOPO first.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true", help="Apply config without printing the OK summary.")
    args = parser.parse_args()

    cfg = load_domain_config(PROJECT_DIR)
    write_fortran_includes()
    update_moment_namelist_domain_info()
    ensure_domain_info_alias()
    if not args.quiet and os.environ.get("DOMAIN_CONFIG_QUIET") != "1":
        print(
            "[OK] Domain config applied: "
            f"resolution={cfg.resolution_m}m, "
            f"vertical_resolution={cfg.vertical_resolution_m}m, "
            f"kmax={cfg.kmax}, "
            f"time_step={cfg.time_step_s}s, "
            f"output_interval={cfg.output_interval_s}s, "
            f"forecast_duration={cfg.forecast_duration_h:02d}h{cfg.forecast_duration_m:02d}m, "
            f"domain={cfg.domain_size_m}m, "
            f"number of grid cells={cfg.inner_npix} "
#            f"topo_outer={cfg.topo_outer_npix}"
        )


if __name__ == "__main__":
    main()
