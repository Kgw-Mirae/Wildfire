#!/usr/bin/env python3
"""
NAME
    hygv_spark.py

PURPOSE
    Convert merged HYSPLIT CDUMP concentration fields to daily NetCDF using
    the existing hysp_cdump direct binary reader. The default output raster
    dimensions match native CDUMP NX and NY, as in the latest (2026-10-07)
    IDL regrd_grd2wm.pro implementation.

USAGE
    python -m hysp.hygv_spark 20250428 20250502 --renew
    python -m hysp.hygv_spark 20250428 --epsg 5179
    python -m hysp.hygv_spark 20250428 --epsg 3857 --dim 1000 1000
    python -m hysp.hygv_spark 20250428 --epsg 3857 --res 1000

VERSION
    20261012-001

AUTHOR
    2026-10-12 Hyun Cheol Kim (hyun.kim@noaa.gov)

DEPENDENCIES
    hysp.hysp_cdump, numpy, pyproj, netCDF4.

NOTES
    PM2P5  = vmean(xlevel=[1]) * 1e6
    PM2P5_2 = vmean(xlevel=[1,2]) * 1e6
    AOD     = vmean(xlevel=[1,2,3,4]) * 1e6 * 0.04
    The legacy AOD scaling is an empirical concentration proxy, not physical AOD.
    By default the projected output preserves native CDUMP array dimensions,
    but not necessarily the exact IDL pixel registration: hysp_cdump uses
    pixel centers within the bounding box; the IDL regrd_grd2wm routine uses
    inclusive grid points at the transformed bounding-box endpoints.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping, Sequence

import numpy as np

if __package__:
    from . import hysp_cdump
else:
    import hysp_cdump  # type: ignore[no-redef]

__version__ = "20261012-001"
__author__ = "Hyun Cheol Kim"

DEFAULT_RUN_ROOT = Path("/homes/metogra/blutouch/work/model/fire-nsfs/hysp.run")
DEFAULT_BBOX = (32.5, 122.0, 42.55, 132.05)


@dataclass(frozen=True)
class SparkCase:
    name: str
    experiment: str


def _day(value: str) -> datetime:
    try:
        return datetime.strptime(str(value), "%Y%m%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYYMMDD date, received {value!r}") from exc


def _case(value: str) -> SparkCase:
    name, sep, experiment = value.partition(":")
    if not sep or not name or not experiment or any(c in name for c in "/\\") or any(
        c in experiment for c in "/\\"
    ):
        raise argparse.ArgumentTypeError("--case must be NAME:EXPERIMENT (e.g. spark8:GFS0P25-KUFS)")
    return SparkCase(name, experiment)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Convert SPARK cdump3 series to daily, three-variable HYGV/CF NetCDF",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("start", type=_day, help="first archive day (YYYYMMDD), inclusive")
    p.add_argument("end", nargs="?", type=_day, help="last archive day, inclusive (default: start)")
    p.add_argument("--group", default="NSFS-2025kr", help="HYSPLIT run group")
    p.add_argument("--name", default="spark8", help="output dataset name (single-case mode)")
    p.add_argument("--experiment", default="GFS0P25-KUFS", help="run experiment (single-case mode)")
    p.add_argument("--case", dest="cases", type=_case, action="append", default=None,
                   metavar="NAME:EXPERIMENT", help="repeat to process multiple cases")
    p.add_argument("--run-root", type=Path,
                   default=Path(os.environ.get("HYSP_RUN_ROOT", DEFAULT_RUN_ROOT)),
                   help="directory containing GROUP/EXPERIMENT")
    p.add_argument("--archive-root", type=Path,
                   default=Path(os.environ.get("HYSP_ARCHIVE_ROOT", Path.home() / "data" / "hysp.archive")),
                   help="directory containing NAME/YYYY/NAME.YYYYMMDD.nc")
    p.add_argument("--cdump", default="cdump3", help="cdump filename in each daily run")
    p.add_argument("--lookback", type=int, default=4,
                   help="previous run days to include, in addition to archive day")
    p.add_argument("--flat-dates", action="store_true",
                   help="use EXPERIMENT/YYYYMMDD instead of EXPERIMENT/YYYY/YYYYMMDD")
    p.add_argument("--require-all", action="store_true",
                   help="fail a day if any expected cdump file is missing")
    p.add_argument("--renew", action="store_true", help="replace existing daily NetCDF files")
    p.add_argument("--dry-run", action="store_true", help="print input/output plans without reading files")

    p.add_argument("--xptype", type=int, default=0, help="zero-based pollutant index")
    p.add_argument("--ptype", default=None, help="pollutant name instead of --xptype")
    p.add_argument("--pm1-levels", nargs="+", type=int, default=[1], metavar="IDX")
    p.add_argument("--pm2-levels", nargs="+", type=int, default=[1, 2], metavar="IDX")
    p.add_argument("--aod-levels", nargs="+", type=int, default=[1, 2, 3, 4], metavar="IDX")
    p.add_argument("--conc-factor", type=float, default=1.e6,
                   help="multiplier for all three fields before AOD-specific factor")
    p.add_argument("--aod-factor", type=float, default=0.04,
                   help="legacy empirical AOD multiplier after concentration factor")
    p.add_argument("--factor", type=float, nargs="+", default=None,
                   help="HYSPLIT source coefficients; one value applies to all files, or one per found file")
    p.add_argument("--decay", type=float, default=None, help="radioactive half-life in days")
    p.add_argument("--zero-to-nan", action="store_true", help="convert exact zeros to NaN")

    p.add_argument("--epsg", type=int, default=3857, help="target EPSG projection code")
    p.add_argument("--bbox", nargs=4, type=float, default=list(DEFAULT_BBOX),
                   metavar=("LAT_MIN", "LON_MIN", "LAT_MAX", "LON_MAX"),
                   help="target geographic bounding box")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dim", nargs=2, type=int, metavar=("NX", "NY"), default=None,
                   help="target dimensions (default: native CDUMP NX NY)")
    g.add_argument("--res", type=float, default=None,
                   help="target resolution in target EPSG units (typically meters)")
    p.add_argument("--max-dim", type=int, default=2000,
                   help="cap grid dimension when computing dimensions from --res or source grid")
    p.add_argument("--flip-y", action="store_true", help="store north-to-south rows")
    p.add_argument("--cf", action="store_true", help="CF-1.10 output with numeric time/coordinates")
    p.add_argument("--no-gzip", action="store_true", help="disable NetCDF compression")
    p.add_argument("--compression-level", type=int, default=4, help="NetCDF deflate level 0..9")
    p.add_argument("--quiet", action="store_true", help="show errors only")
    return p


def _validate_args(args: argparse.Namespace) -> None:
    args.end = args.end or args.start
    if args.end < args.start:
        raise ValueError("end date precedes start date")
    if args.lookback < 0:
        raise ValueError("lookback cannot be negative")
    if args.epsg <= 0:
        raise ValueError("EPSG must be positive")
    if len(args.bbox) != 4 or not (args.bbox[0] < args.bbox[2] and args.bbox[1] < args.bbox[3]):
        raise ValueError("invalid --bbox; expected LAT_MIN LON_MIN LAT_MAX LON_MAX")
    if args.res is not None and args.res <= 0:
        raise ValueError("--res must be positive")
    if args.dim is not None and min(args.dim) < 1:
        raise ValueError("--dim must contain two positive integers")
    if args.max_dim < 0:
        raise ValueError("--max-dim must be >= 0")
    if not (0 <= args.compression_level <= 9):
        raise ValueError("compression level must be 0..9")
    if args.ptype is not None and args.xptype != 0:
        raise ValueError("use --ptype OR --xptype, not both")
    for option in ("pm1_levels", "pm2_levels", "aod_levels"):
        if any(i < 0 for i in getattr(args, option)):
            raise ValueError(f"{option} must be zero-based nonnegative indices")
    if not (np.isfinite(args.conc_factor) and np.isfinite(args.aod_factor)):
        raise ValueError("scaling factors must be finite")
    if args.factor is not None and not all(np.isfinite(x) for x in args.factor):
        raise ValueError("--factor values must be finite")
    args.cases = args.cases or [SparkCase(args.name, args.experiment)]
    if len({c.name for c in args.cases}) != len(args.cases):
        raise ValueError("duplicate --case output dataset names")


def _iter_days(start: datetime, end: datetime):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _daily_inputs(
    run_root: Path,
    group: str,
    experiment: str,
    day: datetime,
    *,
    lookback: int,
    cdump: str,
    flat_dates: bool,
) -> tuple[list[Path], list[Path]]:
    present: list[Path] = []
    missing: list[Path] = []
    for back in range(lookback, -1, -1):
        run_day = day - timedelta(days=back)
        parent = run_root / group / experiment
        if not flat_dates:
            parent /= run_day.strftime("%Y")
        path = parent / run_day.strftime("%Y%m%d") / cdump
        (present if path.is_file() else missing).append(path)
    return present, missing


def _out_path(archive_root: Path, name: str, day: datetime) -> Path:
    return archive_root / name / day.strftime("%Y") / f"{name}.{day:%Y%m%d}.nc"


def _same_info(base: Mapping[str, Any], current: Mapping[str, Any]) -> None:
    if tuple(str(x) for x in base["tflag"]) != tuple(str(x) for x in current["tflag"]):
        raise ValueError("fields do not have matching UTC time axes")
    for key in ("nx", "ny", "x0", "y0", "dx", "dy"):
        a = float(base["minfo"][key]); b = float(current["minfo"][key])
        if not np.isclose(a, b, rtol=0, atol=1.e-6):
            raise ValueError(f"inconsistent input cdump grid: {key} = {a} vs {b}")


def _read_field(
    files: Sequence[Path], times: Sequence[datetime], levels: Sequence[int],
    args: argparse.Namespace, *, scale: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    selected = {"ptype": args.ptype} if args.ptype is not None else {"xptype": args.xptype}
    values, info = hysp_cdump.process_cdump(
        [str(f) for f in files], tflag=times, xlevel=list(levels), vmean=True,
        factor=args.factor, decay=args.decay, nan=args.zero_to_nan,
        dtype=np.float32, order="tyx", **selected,
    )
    if values is None or info is None:
        raise ValueError(f"no selected concentration data for levels {list(levels)}")
    data = np.asarray(values, dtype=np.float32)
    if data.ndim != 3 or data.shape[0] != len(times):
        raise ValueError(f"unexpected data dimensions {data.shape}; expected {len(times)} times")
    # Match legacy FLOAT output, and avoid holding another large copy in memory.
    np.multiply(data, np.float32(scale), out=data)
    return data, info


def _project_kwargs(args: argparse.Namespace, info: Mapping[str, Any]) -> dict[str, Any]:
    """Use the CDUMP's native NX/NY unless the user explicitly overrides them.

    The October 7 IDL regrd_grd2wm.pro uses [minfo.nx, minfo.ny] by default.
    Passing dim=None to hysp_cdump would instead *estimate* resolution and
    calculate a potentially different target shape. Supply the actual native
    dimensions to prevent that behavior.
    """
    source_grid = info["minfo"]
    if args.dim is not None:
        dim = tuple(int(x) for x in args.dim)
    elif args.res is not None:
        dim = None
    else:
        nx = int(source_grid["nx"])
        ny = int(source_grid["ny"])
        if nx <= 0 or ny <= 0:
            raise ValueError(f"Invalid native CDUMP grid dimensions: NX={nx}, NY={ny}")
        dim = (nx, ny)
    return {
        "target_epsg": args.epsg,
        "bbox": args.bbox,
        "dim": dim,
        "res": args.res,
        "max_dim": args.max_dim,
        "flip_y": args.flip_y,
        "fill_value": np.nan,
    }


def _set_extra_attrs(
    variable: Any, *, name: str, info: Mapping[str, Any], scale: float,
    source_aod_factor: float | None = None,
) -> None:
    variable.setncattr("XLEVEL", np.asarray(info["xlevel"], dtype=np.int32))
    variable.setncattr("LEVEL_M", np.asarray(info["level"], dtype=np.int32))
    variable.setncattr("VMEAN", "thickness_weighted")
    variable.setncattr("SOURCE_MULTIPLIER", float(scale))
    if source_aod_factor is not None:
        variable.setncattr("AOD_EMPIRICAL_FACTOR", float(source_aod_factor))
        variable.setncattr("AOD_METHOD", "legacy concentration proxy; not physical column AOD integration")


def _append_field(
    path: Path, name: str, data: np.ndarray, info: Mapping[str, Any],
    args: argparse.Namespace, *, units: str, long_name: str, scale: float,
    aod_factor: float | None = None,
) -> None:
    from netCDF4 import Dataset

    projected, _grid = hysp_cdump.reproject_tyx(data, info, **_project_kwargs(args, info))
    with Dataset(path, "a") as nc:
        primary = nc.variables["PM2P5"]
        if tuple(projected.shape) != tuple(primary.shape):
            raise ValueError(f"{name} grid/time shape {projected.shape} differs from {primary.shape}")
        if name in nc.variables:
            raise ValueError(f"variable {name} already exists")
        encoding = ({} if args.no_gzip else {"zlib": True, "complevel": args.compression_level, "shuffle": True})
        _, ny, nx = projected.shape
        var = nc.createVariable(
            name, "f4", primary.dimensions, fill_value=np.float32(np.nan),
            chunksizes=(1, min(ny, 256), min(nx, 256)), **encoding,
        )
        var[:, :, :] = projected.astype(np.float32, copy=False)
        var.setncattr("long_name", long_name)
        var.setncattr("units", units)
        for key in primary.ncattrs():
            # Share spatial metadata from the primary field, never its semantics.
            if key in {"_FillValue", "long_name", "units", "XLEVEL", "LEVEL_M", "VMEAN",
                       "SOURCE_MULTIPLIER", "AOD_EMPIRICAL_FACTOR", "AOD_METHOD"}:
                continue
            var.setncattr(key, primary.getncattr(key))
        _set_extra_attrs(var, name=name, info=info, scale=scale, source_aod_factor=aod_factor)


def _write_day(
    output: Path, files: Sequence[Path], day: datetime, args: argparse.Namespace,
) -> None:
    """Write a temporary complete daily file, then atomically replace output."""
    from netCDF4 import Dataset

    times = [day + timedelta(hours=h) for h in range(24)]
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp.nc", dir=output.parent)
    os.close(fd)
    temporary = Path(temp_name)
    try:
        scale_pm = float(args.conc_factor)
        scale_aod = float(args.conc_factor) * float(args.aod_factor)
        fields = (
            ("PM2P5", args.pm1_levels, scale_pm, "Fine particulate matter, layer 1", "ug m-3", None),
            ("PM2P5_2", args.pm2_levels, scale_pm, "Fine particulate matter, layers 1-2", "ug m-3", None),
            ("AOD", args.aod_levels, scale_aod, "Aerosol optical depth proxy (legacy scaling)", "1", args.aod_factor),
        )
        reference_info: Mapping[str, Any] | None = None
        for index, (name, levels, scale, long_name, units, aod_factor) in enumerate(fields):
            data, info = _read_field(files, times, levels, args, scale=scale)
            if reference_info is None:
                reference_info = info
            else:
                _same_info(reference_info, info)

            if index == 0:
                saver = hysp_cdump.save_cf_netcdf if args.cf else hysp_cdump.save_compact_netcdf
                saver_kwargs = dict(_project_kwargs(args, info))
                if not args.cf:
                    saver_kwargs["hygv"] = args.epsg == 3857
                saver(
                    temporary, data, info, var_name=name, units=units,
                    long_name=long_name, gzip=not args.no_gzip,
                    compression_level=args.compression_level, **saver_kwargs,
                )
                with Dataset(temporary, "a") as nc:
                    nc.setncattr("SPARK_ARCHIVE", "hygv_spark.py")
                    nc.setncattr("SPARK_ARCHIVE_VERSION", __version__)
                    nc.setncattr("SPARK_NATIVE_GRID_NX", int(info["minfo"]["nx"]))
                    nc.setncattr("SPARK_NATIVE_GRID_NY", int(info["minfo"]["ny"]))
                    nc.setncattr("SPARK_OUTPUT_DIMENSION_SOURCE",
                                 "explicit_dim" if args.dim is not None else
                                 "explicit_res" if args.res is not None else "native_cdump")
                    nc.setncattr("SPARK_DAY", day.strftime("%Y%m%d"))
                    nc.setncattr("SPARK_INPUT_FILES", "\n".join(str(f) for f in files))
                    nc.setncattr("SPARK_AOD_NOTE", "AOD is a legacy empirical proxy, not a physically integrated optical depth")
                    _set_extra_attrs(nc.variables[name], name=name, info=info, scale=scale)
            else:
                _append_field(
                    temporary, name, data, info, args,
                    units=units, long_name=long_name, scale=scale, aod_factor=aod_factor,
                )
            del data
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def run(args: argparse.Namespace) -> int:
    _validate_args(args)
    made = skipped = failed = planned = 0
    for case in args.cases:
        for day in _iter_days(args.start, args.end):
            output = _out_path(args.archive_root.expanduser(), case.name, day)
            files, missing = _daily_inputs(
                args.run_root.expanduser(), args.group, case.experiment, day,
                lookback=args.lookback, cdump=args.cdump, flat_dates=args.flat_dates,
            )
            label = f"{case.name} {day:%Y%m%d}"
            if output.is_file() and not args.renew and not args.dry_run:
                skipped += 1
                if not args.quiet:
                    print(f"SKIP {label}: existing {output} (use --renew to replace)")
                continue
            if args.dry_run:
                planned += 1
                print(f"PLAN {label}: {len(files)} present / {len(missing)} missing -> {output}")
                for file in files:
                    print(f"  + {file}")
                for file in missing:
                    print(f"  - {file}")
                continue
            if not files or (args.require_all and missing):
                skipped += 1
                print(f"SKIP {label}: {len(files)} available, {len(missing)} missing cdumps", file=sys.stderr)
                continue
            if not args.quiet:
                print(f"READ {label}: {len(files)} cdumps, {len(missing)} missing; EPSG:{args.epsg}")
            try:
                _write_day(output, files, day, args)
            except (Exception, SystemExit) as exc:
                failed += 1
                print(f"ERROR {label}: {exc}", file=sys.stderr)
                continue
            made += 1
            if not args.quiet:
                print(f"SAVE {output}")
    if not args.quiet:
        print(f"SUMMARY saved={made}, skipped={skipped}, failed={failed}, planned={planned}")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
