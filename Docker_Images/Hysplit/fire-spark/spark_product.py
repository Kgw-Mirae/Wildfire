#!/usr/bin/env python3
"""
NAME
    spark_product.py

PURPOSE
    Generate one 24-hour SPARK smoke product from one or more explicitly
    selected HYSPLIT experiment directories. Combine available CDUMPs from
    the target day and preceding run dates, then write NetCDF in EPSG:5179
    and EPSG:3857 using the established hygv_spark/hysp_cdump library.

USAGE
    python spark_product.py 20250428 --source gdas1-finn
    python spark_product.py 20250428 --source gdas1-spread
    python spark_product.py 20250428 --source gdas1-finn gdas1-spread
    python spark_product.py 20250428 --source gfs0p25-finn gdas1-spread --dry-run
    python spark_product.py 20250428 --source gdas1-finn gdas1-spread --status
    python spark_product.py 20250428 20250502 --source gdas1-finn --renew

VERSION
    20261012-004

AUTHOR
    2026-10-12 Hyun Cheol Kim (hyun.kim@noaa.gov)

DEPENDENCIES
    spark_daily.py at the project root; hysp.hygv_spark and
    hysp.hysp_cdump in the existing Python library; numpy, pyproj, netCDF4.

INPUTS
    hysp.run/GROUP/EXPERIMENT/YYYY/YYYYMMDD/cdump3 (or spark.ini cdump).
    EXPERIMENT is an exact --source value, not an emission-module nickname.

OUTPUTS
    hysp.out/GROUP/EXPERIMENT[-EXPERIMENT...]/YYYY/YYYYMMDD/
        spark.EXPERIMENT[-EXPERIMENT...].YYYYMMDD.epsg5179.nc
        spark.EXPERIMENT[-EXPERIMENT...].YYYYMMDD.epsg3857.nc
        product.json
        spark_product.status.json

NOTES
    The order of --source values is preserved in the product name and input
    selection. There is no automatic substitution between meteorological
    experiments. Missing individual input CDUMPs do not stop generation if
    any usable CDUMP remains. Missing FINN days are nonfatal *errors* kept
    in monitoring metadata; SPREAD days may be absent when no GeoJSON exists.
    A requested source with no CDUMPs produces a partial status when other
    sources are available. No inputs at all => missing status, no NetCDF.
    The combination is an uncorrected sum: duplicate fire emissions are NOT
    removed. AOD remains the legacy empirical concentration proxy.
    By default output dimensions follow native HYSPLIT CDUMP NX and NY,
    matching the October 7, 2026 IDL regrd_grd2wm.pro behavior.
    Explicit --dim and --res settings override native dimensions.
    This controller never alters or runs HYSPLIT simulations.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Mapping, Sequence

import spark_daily as sd

__version__ = "20261012-004"
EPSGS = (5179, 3857)
DEFAULT_BBOX = (32.5, 122.0, 42.55, 132.05)
STATUS_FILE = "spark_product.status.json"


class ProductError(RuntimeError):
    """An invalid SPARK product request or unavailable input."""


def _parse_day(text: str) -> datetime:
    if not re.fullmatch(r"[0-9]{8}", text):
        raise argparse.ArgumentTypeError("date must be UTC YYYYMMDD")
    try:
        return datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid UTC date: {text}") from exc


def _days(start: datetime, end: datetime):
    if end < start:
        raise ProductError("end date must be on or after start date")
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _clean_component(value: str, label: str) -> str:
    """A literal experiment/group name, never a relative or absolute path."""
    item = str(value)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", item) or item in {".", ".."}:
        raise ProductError(f"Invalid {label}: {item!r}; expected a directory name")
    return item


def _sources(raw: Sequence[str]) -> tuple[str, ...]:
    if not raw:
        raise ProductError("Supply at least one --source experiment name")
    result = tuple(_clean_component(x, "source experiment") for x in raw)
    if len(set(result)) != len(result):
        raise ProductError("Duplicate --source experiments would double-count input CDUMPs")
    return result


def _module(experiment: str) -> str:
    """Informational emission-type hint; never used to choose an experiment."""
    return experiment.rsplit("-", 1)[-1].lower() if "-" in experiment else "other"


def _product_key(sources: Sequence[str]) -> str:
    return "-".join(_sources(sources))


def _source_path(root: Path, group: str, experiment: str,
                 run_day: datetime, cdump: str) -> Path:
    return (root / "hysp.run" / group / experiment /
            run_day.strftime("%Y") / run_day.strftime("%Y%m%d") / cdump)


def select_inputs(root: Path, day: datetime, *, sources: Sequence[str],
                  lookback: int, group: str, cdump: str) -> dict[str, Any]:
    """Use only requested experiment directories, never implicit alternatives."""
    sources = _sources(sources)
    if lookback < 0:
        raise ProductError("--lookback must be >= 0")
    chosen: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    counts = {exp: 0 for exp in sources}
    for offset in range(lookback, -1, -1):
        run_day = day - timedelta(days=offset)
        date8 = run_day.strftime("%Y%m%d")
        for experiment in sources:
            path = _source_path(root, group, experiment, run_day, cdump)
            item = {"experiment": experiment, "emission": _module(experiment),
                    "run_date": date8}
            if path.is_file() and path.stat().st_size > 0:
                chosen.append({**item, "path": str(path),
                               "size_bytes": path.stat().st_size})
                counts[experiment] += 1
            else:
                missing.append({**item, "tried": [str(path)]})
    return {"sources": list(sources), "files": chosen,
            "missing": missing, "counts": counts}


def _product_dir(root: Path, day: datetime, group: str,
                 sources: Sequence[str]) -> Path:
    return (root / "hysp.out" / _clean_component(group, "group") /
            _product_key(sources) / day.strftime("%Y") /
            day.strftime("%Y%m%d"))


def _output_paths(root: Path, day: datetime, group: str,
                  sources: Sequence[str], name: str = "spark") -> dict[int, Path]:
    folder = _product_dir(root, day, group, sources)
    key = _product_key(sources)
    return {epsg: folder / f"{name}.{key}.{day:%Y%m%d}.epsg{epsg}.nc"
            for epsg in EPSGS}


def _hygv_args(args: argparse.Namespace, epsg: int) -> argparse.Namespace:
    """Adapt the existing HYGV converter's private _write_day interface."""
    return argparse.Namespace(
        epsg=epsg,
        bbox=list(args.bbox) if args.bbox is not None else list(DEFAULT_BBOX),
        dim=list(args.dim) if args.dim is not None else None,
        res=args.res, max_dim=args.max_dim, flip_y=False,
        cf=bool(args.cf), no_gzip=False,
        compression_level=args.compression_level,
        xptype=args.xptype, ptype=None,
        pm1_levels=[1], pm2_levels=[1, 2], aod_levels=[1, 2, 3, 4],
        conc_factor=1e6, aod_factor=0.04, factor=None, decay=None,
        zero_to_nan=False,
    )


def _converter():
    try:
        from hysp import hygv_spark
    except ImportError as exc:
        raise ProductError(
            "Missing hysp.hygv_spark; install the included hygv_spark.py "
            "alongside hysp_cdump.py in your HYSP Python library"
        ) from exc
    return hygv_spark


def _issues(selection: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Missing FINN is an error; absent SPREAD dates may be expected."""
    issues: list[dict[str, Any]] = []
    for item in selection["missing"]:
        module, date8, exp = item["emission"], item["run_date"], item["experiment"]
        if module == "finn":
            code, severity = "MISSING_FINN_RUN", "error"
            message = f"FINN CDUMP missing: {exp} on {date8}; using available contributions"
        elif module == "spread":
            code, severity = "SPREAD_NOT_AVAILABLE", "info"
            message = f"No SPREAD CDUMP: {exp} on {date8}; GeoJSON may not exist"
        else:
            code, severity = "MISSING_SOURCE_RUN", "error"
            message = f"Requested CDUMP missing: {exp} on {date8}; using available contributions"
        issues.append({"code": code, "severity": severity, "module": module,
                       "experiment": exp, "run_date": date8,
                       "message": message, "tried": item["tried"]})
    for experiment, count in selection["counts"].items():
        if not count:
            issues.append({
                "code": "NO_SOURCE_CONTRIBUTION", "severity": "warning",
                "module": _module(experiment), "experiment": experiment,
                "run_date": None,
                "message": f"No CDUMPs found for requested experiment {experiment} in the lookback window",
            })
    if not selection["files"]:
        issues.append({"code": "NO_USABLE_CDUMP", "severity": "error",
                       "module": None, "experiment": None, "run_date": None,
                       "message": "No usable HYSPLIT CDUMPs; cannot generate any NetCDF product"})
    return issues


def _completeness(selection: Mapping[str, Any]) -> str:
    if not selection["files"]:
        return "missing"
    if any(x["severity"] == "error" for x in _issues(selection)):
        return "partial"
    if any(count == 0 for count in selection["counts"].values()):
        return "partial"
    return "complete"


def _missing_dates(selection: Mapping[str, Any], module: str) -> list[str]:
    return list(dict.fromkeys(x["run_date"] for x in selection["missing"]
                              if x["emission"] == module))


def _status_payload(day: datetime, sources: Sequence[str], group: str,
                    selection: Mapping[str, Any], issues: Sequence[Mapping[str, Any]],
                    outputs: Mapping[int, Path], status: str,
                    *, lookback: int) -> dict[str, Any]:
    """Persistent standalone monitoring status, independent of NetCDF."""
    return {
        "generator": "spark_product.py", "version": __version__,
        "updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "day": day.strftime("%Y%m%d"), "group": group,
        "source_experiments": list(sources), "product": _product_key(sources),
        "status": status, "usable": status in {"complete", "partial"},
        "has_errors": any(issue["severity"] == "error" for issue in issues),
        "error_count": sum(issue["severity"] == "error" for issue in issues),
        "warning_count": sum(issue["severity"] == "warning" for issue in issues),
        "errors": [issue["message"] for issue in issues if issue["severity"] == "error"],
        "warnings": [issue["message"] for issue in issues if issue["severity"] == "warning"],
        "issues": list(issues),
        "lookback_days": lookback,
        "coverage": {
            exp: {"expected": lookback + 1, "available": selection["counts"][exp],
                  "missing_dates": [x["run_date"] for x in selection["missing"]
                                    if x["experiment"] == exp]}
            for exp in sources
        },
        "missing_finn_dates": _missing_dates(selection, "finn"),
        "missing_spread_dates": _missing_dates(selection, "spread"),
        "used": selection["files"], "missing": selection["missing"],
        "outputs": {f"EPSG:{epsg}": str(path) for epsg, path in outputs.items()},
    }


def _annotate(path: Path, *, sources: Sequence[str], day: datetime,
              group: str, selection: Mapping[str, Any],
              status: str) -> None:
    from netCDF4 import Dataset
    count_present = sum(n > 0 for n in selection["counts"].values())
    with Dataset(path, "a") as nc:
        nc.setncattr("SPARK_PRODUCT", "spark_product.py")
        nc.setncattr("SPARK_PRODUCT_VERSION", __version__)
        nc.setncattr("SPARK_PRODUCT_NAME", _product_key(sources))
        nc.setncattr("SPARK_SOURCE_EXPERIMENTS", ",".join(sources))
        nc.setncattr("SPARK_PRODUCT_STATUS", status)
        nc.setncattr("SPARK_GROUP", group)
        nc.setncattr("SPARK_PRODUCT_DAY", day.strftime("%Y%m%d"))
        nc.setncattr("SPARK_REQUESTED_MODULES", ",".join(_module(exp) for exp in sources))
        nc.setncattr("SPARK_AVAILABLE_EXPERIMENTS", ",".join(
            exp for exp in sources if selection["counts"][exp] > 0))
        nc.setncattr("SPARK_MISSING_FINN_DATES", ",".join(_missing_dates(selection, "finn")))
        nc.setncattr("SPARK_MISSING_SPREAD_DATES", ",".join(_missing_dates(selection, "spread")))
        nc.setncattr("SPARK_SOURCE_FILE_COUNT", len(selection["files"]))
        nc.setncattr("SPARK_SOURCE_FILES", "\n".join(item["path"] for item in selection["files"]))
        nc.setncattr("SPARK_SUM_METHOD", "uncorrected sum of compatible HYSPLIT CDUMP concentrations")
        nc.setncattr("SPARK_DUPLICATE_EMISSIONS_REMOVED", "no" if count_present > 1 else "not_applicable")
        if count_present > 1:
            nc.setncattr("SPARK_OVERLAP_WARNING", "Emissions may overlap across selected experiments; duplicate emissions were NOT removed")


def _atomic_json(path: Path, contents: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", suffix=".tmp", delete=False) as fp:
        temp = Path(fp.name)
        json.dump(contents, fp, indent=2, ensure_ascii=False)
        fp.write("\n")
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _print_issues(issues: Sequence[Mapping[str, Any]], *, has_inputs: bool) -> None:
    for issue in issues:
        if issue["severity"] == "info":
            continue
        if issue["severity"] == "error":
            prefix = "ERROR (nonfatal)" if has_inputs else "ERROR"
        else:
            prefix = "WARNING"
        print(f"{prefix} {issue['code']}: {issue['message']}", file=sys.stderr)


def _show_existing_status(root: Path, day: datetime, group: str,
                          sources: Sequence[str], *, json_format: bool) -> str:
    folder = _product_dir(root, day, group, sources)
    status_file = folder / STATUS_FILE
    manifest_file = folder / "product.json"
    if status_file.is_file():
        data = json.loads(status_file.read_text(encoding="utf-8"))
    elif manifest_file.is_file():
        data = {"day": day.strftime("%Y%m%d"), "group": group,
                "source_experiments": list(sources), "status": "legacy_unverified",
                "issues": [], "note": "Legacy product has no monitoring status; use --renew"}
    else:
        data = {"day": day.strftime("%Y%m%d"), "group": group,
                "source_experiments": list(sources), "status": "unavailable",
                "issues": [], "note": "No product status file exists"}
    if json_format:
        print(json.dumps(data, sort_keys=True))
    else:
        print(f"STATUS {data['day']} group={group} source={_product_key(sources)} status={data['status']}")
        for exp, cov in data.get("coverage", {}).items():
            print(f"  {exp} available={cov['available']}/{cov['expected']} "
                  f"missing={','.join(cov['missing_dates']) or 'none'}")
        for issue in data.get("issues", []):
            if issue.get("severity") in {"error", "warning"}:
                print(f"  {issue['severity'].upper()}: {issue['message']}")
        if data.get("note"):
            print(f"  {data['note']}")
    return str(data["status"])


def run_day(root: Path, cfg: Mapping[str, Any], day: datetime,
            args: argparse.Namespace) -> str:
    sources = _sources(args.source)
    group = _clean_component(args.group or cfg["group"], "group")
    cdump = _clean_component(args.cdump or cfg["cdump"], "cdump")
    outputs = _output_paths(root, day, group, sources, args.name)
    folder = _product_dir(root, day, group, sources)
    manifest_path = folder / "product.json"
    status_path = folder / STATUS_FILE

    existing = [p for p in (*outputs.values(), manifest_path) if p.exists()]
    if existing and not args.renew and not args.dry_run:
        if (len(existing) == len(outputs) + 1 and
                all(path.stat().st_size > 0 for path in existing)):
            print(f"SKIP {day:%Y%m%d} source={_product_key(sources)}: product exists (use --renew)")
            old = _show_existing_status(root, day, group, sources, json_format=False)
            if old == "partial":
                print("WARNING: existing product has monitored data gaps; regenerate with --renew", file=sys.stderr)
            return "skipped"
        raise ProductError("Partial product files already exist: " +
                           ", ".join(str(p) for p in existing) + "; use --renew")

    selection = select_inputs(root, day, sources=sources, lookback=args.lookback,
                              group=group, cdump=cdump)
    issues = _issues(selection)
    completeness = _completeness(selection)
    print(f"{'PLAN' if args.dry_run else 'PRODUCT'} {day:%Y%m%d} "
          f"group={group} source={_product_key(sources)} "
          f"cdumps={len(selection['files'])} missing_inputs={len(selection['missing'])} "
          f"completeness={completeness}")
    for item in selection["files"]:
        print(f"  + {item['experiment']} {item['run_date']}: {item['path']}")
    for item in selection["missing"]:
        print(f"  - {item['experiment']} {item['run_date']}: missing {item['tried'][0]}")
    for epsg, out in outputs.items():
        print(f"  EPSG:{epsg} -> {out}")
    _print_issues(issues, has_inputs=bool(selection["files"]))
    if sum(x > 0 for x in selection["counts"].values()) > 1:
        print("WARNING: uncorrected additive merging; duplicate emissions may occur")
    if args.dim is None and args.res is None:
        print("  GRID: native CDUMP dimensions (NX, NY); use --dim/--res to override")
    elif args.dim is not None:
        print(f"  GRID: explicit {args.dim[0]} x {args.dim[1]}")
    else:
        print(f"  GRID: explicit target resolution {args.res}")
    if args.dry_run:
        return "planned" if selection["files"] else "missing"

    base = _status_payload(day, sources, group, selection, issues,
                           outputs, completeness, lookback=args.lookback)
    if not selection["files"]:
        _atomic_json(status_path, base)
        print(f"ERROR {day:%Y%m%d}: no usable CDUMP, status saved to {status_path}", file=sys.stderr)
        return "missing"

    _atomic_json(status_path, {**base, "status": "running", "usable": False})
    try:
        hygv = _converter()
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".spark_product.", dir=folder) as tmpdir:
            tmp = Path(tmpdir)
            for epsg, output in outputs.items():
                staged = tmp / output.name
                try:
                    hygv._write_day(staged, [Path(x["path"]) for x in selection["files"]],
                                    day, _hygv_args(args, epsg))
                except Exception as exc:
                    raise ProductError(f"Failed merging CDUMPs for EPSG:{epsg}: {exc}. "
                                       "Check source grids, layers, pollutants, and times") from exc
                _annotate(staged, sources=sources, day=day, group=group,
                          selection=selection, status=completeness)
            for epsg, output in outputs.items():
                os.replace(tmp / output.name, output)

        count_present = sum(v > 0 for v in selection["counts"].values())
        manifest = {
            "generator": "spark_product.py", "version": __version__,
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "day": day.strftime("%Y%m%d"),
            "hours_utc": [f"{day + timedelta(hours=i):%Y%m%d%H}" for i in range(24)],
            "group": group, "product": _product_key(sources),
            "source_experiments": list(sources),
            "status": completeness, "has_errors": base["has_errors"],
            "issues": issues, "errors": base["errors"], "warnings": base["warnings"],
            "coverage": base["coverage"],
            "requested_modules": [_module(x) for x in sources],
            "available_experiments": [x for x in sources if selection["counts"][x] > 0],
            "lookback_days": args.lookback,
            "used": selection["files"], "missing": selection["missing"],
            "grid": {"bbox_latlon": list(args.bbox),
                     "dimensions": list(args.dim) if args.dim is not None else "native_cdump",
                     "dimension_source": ("explicit_dim" if args.dim is not None else
                                          "explicit_res" if args.res is not None else "native_cdump"),
                     "resolution": args.res,
                     "format": "CF-1.10" if args.cf else "HYGV compact"},
            "outputs": {f"EPSG:{epsg}": str(path) for epsg, path in outputs.items()},
            "combination_method": "uncorrected_additive_sum",
            "emission_overlap_removed": False if count_present > 1 else None,
            "overlap_note": ("Selected experiments may overlap; duplicate emissions were not removed"
                             if count_present > 1 else "not applicable with one contributing experiment"),
            "aod_note": "Legacy concentration proxy * 0.04; not physical integrated AOD",
        }
        _atomic_json(manifest_path, manifest)
        _atomic_json(status_path, base)
        print(f"SAVE {manifest_path}")
        print(f"STATUS {completeness.upper()} {status_path}")
        return "partial" if completeness == "partial" else "saved"
    except Exception as exc:
        failed_issue = {"code": "PRODUCT_GENERATION_FAILED", "severity": "error",
                        "experiment": None, "module": None, "run_date": None,
                        "message": str(exc)}
        failed = {**base, "status": "failed", "usable": False,
                  "issues": [*issues, failed_issue],
                  "errors": [*base["errors"], str(exc)],
                  "has_errors": True, "error_count": base["error_count"] + 1}
        _atomic_json(status_path, failed)
        raise


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="SPARK: merge exact HYSPLIT experiment directories into daily NetCDF products",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("start", type=_parse_day, help="first target UTC date YYYYMMDD")
    p.add_argument("end", type=_parse_day, nargs="?", help="last target date, inclusive")
    p.add_argument("--source", nargs="+", required=True, metavar="EXPERIMENT",
                   help="one or more exact hysp.run/GROUP/EXPERIMENT names; order determines product name")
    p.add_argument("--root", type=Path, default=None,
                   help="SPARK project root (default: directory containing script)")
    p.add_argument("--group", help="override group from root spark.ini")
    p.add_argument("--cdump", help="override CDUMP filename from spark.ini")
    p.add_argument("--lookback", type=int, default=4,
                   help="number of previous simulation days (plus target day)")
    p.add_argument("--name", default="spark", help="output NetCDF filename prefix")
    p.add_argument("--bbox", type=float, nargs=4, default=list(DEFAULT_BBOX),
                   metavar=("S", "W", "N", "E"), help="output geographic bounds")
    grid = p.add_mutually_exclusive_group()
    grid.add_argument("--dim", type=int, nargs=2, metavar=("NX", "NY"),
                      default=None, help="explicit output dimensions (default: native CDUMP NX NY)")
    grid.add_argument("--res", type=float,
                      help="target resolution in output CRS units")
    p.add_argument("--cf", action="store_true", help="CF-compliant NetCDF instead of HYGV compact")
    p.add_argument("--xptype", type=int, default=0, help="HYSPLIT pollutant index")
    p.add_argument("--max-dim", type=int, default=2000)
    p.add_argument("--compression-level", type=int, default=4)
    p.add_argument("--renew", action="store_true", help="regenerate existing product")
    p.add_argument("--dry-run", action="store_true", help="show sources and outputs without writing")
    p.add_argument("--status", action="store_true", help="show saved monitoring status without conversion")
    p.add_argument("--json", action="store_true", help="with --status, print JSON Lines")
    return p


def _validate_args(args: argparse.Namespace) -> None:
    _sources(args.source)
    if args.json and not args.status:
        raise ProductError("--json requires --status")
    if args.status and (args.dry_run or args.renew):
        raise ProductError("--status cannot combine with --dry-run or --renew")
    if args.lookback < 0 or args.lookback > 30:
        raise ProductError("--lookback must be 0..30 days")
    if not (0 <= args.compression_level <= 9):
        raise ProductError("--compression-level must be 0..9")
    if args.max_dim < 0:
        raise ProductError("--max-dim must be >= 0")
    if args.bbox is None or len(args.bbox) != 4:
        raise ProductError("--bbox requires south west north east")
    south, west, north, east = args.bbox
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise ProductError("Invalid --bbox; expected south < north and west < east")
    if args.res is not None:
        if args.res <= 0:
            raise ProductError("--res must be positive")
        args.dim = None
    if args.dim is not None and any(x <= 0 for x in args.dim):
        raise ProductError("--dim requires positive NX and NY")
    _clean_component(args.name, "product name")
    if args.group is not None:
        _clean_component(args.group, "group")
    if args.cdump is not None:
        _clean_component(args.cdump, "cdump")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _validate_args(args)
        root = sd.resolve_root(args.root)
        cfg = sd.read_config(root / "spark.ini")
        group = _clean_component(args.group or cfg["group"], "group")
        if args.status:
            bad = 0
            for day in _days(args.start, args.end or args.start):
                state = _show_existing_status(root, day, group, args.source,
                                              json_format=args.json)
                bad += state != "complete"
            return 1 if bad else 0
        states: dict[str, int] = {}
        for day in _days(args.start, args.end or args.start):
            try:
                outcome = run_day(root, cfg, day, args)
            except (Exception, SystemExit) as exc:
                print(f"ERROR {day:%Y%m%d} source={_product_key(args.source)}: {exc}", file=sys.stderr)
                states["failed"] = states.get("failed", 0) + 1
            else:
                states[outcome] = states.get(outcome, 0) + 1
        print("SUMMARY " + " ".join(f"{key}={value}" for key, value in sorted(states.items())))
        return 1 if states.get("failed") or states.get("missing") else 0
    except (ProductError, sd.SparkError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
