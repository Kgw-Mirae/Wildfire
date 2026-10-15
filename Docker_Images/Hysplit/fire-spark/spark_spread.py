#!/usr/bin/env python3
"""
NAME
    spark_spread.py

PURPOSE
    Prepare and run daily HYSPLIT fire-spread simulations from timestamped
    GeoJSON files, reusing the existing fire_spread_emitimes, nsfs_prep1,
    nsfs_chk1, and nsfs_run1 routines. Preparation precedes validation.

USAGE
    python spark_spread.py 20250321 --prepare-only
    python spark_spread.py 20250321 --check-only
    python spark_spread.py 20250321
    python spark_spread.py 20250321 --renew
    python spark_spread.py 20250321 --input /path/to/geojson
    python spark_spread.py 20250321 --input-timezone Asia/Seoul --dry-run

VERSION
    20261012-002

AUTHOR
    2026-10-12 Hyun Cheol Kim (hyun.kim@noaa.gov)

DEPENDENCIES
    spark_daily.py (same directory); existing hysp and fire libraries,
    especially fire.fire_spread and fire.fire_spread_emitimes; pyproj.

INPUTS
    Default: hysp.data/fire-spread/geojson/YYYY/YYYYMMDD/{*.geojson,*.zip}
    Explicit --input accepts GeoJSON files, ZIP files, or directories.

OUTPUTS
    hysp.data/fire-spread/hourly/YYYY/YYYYMMDD/spread_hourly.txt
    hysp.run/GROUP/{gfs0p25,gfs0p25.f}-spread/YYYY/YYYYMMDD/

NOTES
    HYSPLIT start is specified on the command line. Duration is read from
    the selected group's CONTROL template unless --duration is supplied.
    Existing prepared files are preserved unless --renew is specified.
    Source GeoJSON filename timestamps are converted to UTC by the existing
    fire_spread module (default input timezone Asia/Seoul).
    One day's source directory is not automatically extended to adjacent
    dates. Supply --input paths spanning dates when a fire case requires it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
import traceback
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import spark_daily as sd

__version__ = "20261012-002"

STATUS_FILE = "spark_spread.status.json"
CACHE_MANIFEST = "spread_hourly.source.json"
SOURCE_EXTENSIONS = {".geojson", ".zip"}

# These deliberately match the existing fire.fire_spread_emitimes defaults.
DEFAULT_GRID_M = 1000.0
DEFAULT_RATE_GPH = 3.0e6
DEFAULT_AREA_M2 = 1.0e6
DEFAULT_HEAT_W = 5.0e6
DEFAULT_HEIGHT_M = 1.0


class SpreadError(sd.SparkError):
    """A SPARK fire-spread input or workflow error."""


class SpreadNotReady(SpreadError):
    """An nsfs_chk1 NOT READY result. Keep run diagnostics intact."""


def input_directory(root: Path, day: datetime) -> Path:
    return (root / "hysp.data" / "fire-spread" / "geojson" /
            day.strftime("%Y") / day.strftime("%Y%m%d"))


def hourly_path(root: Path, day: datetime) -> Path:
    return (root / "hysp.data" / "fire-spread" / "hourly" /
            day.strftime("%Y") / day.strftime("%Y%m%d") / "spread_hourly.txt")


def run_dir(root: Path, cfg: Mapping[str, Any], day: datetime,
            arl: str | Sequence[str]) -> Path:
    names = sd.arl_names(arl)
    exp = ("gfs0p25.f-spread" if "gfs0p25.f" in names
           else "-".join([*names, "spread"]))
    return (root / "hysp.run" / sd.name_component(cfg["group"], "group") /
            exp / day.strftime("%Y") / day.strftime("%Y%m%d"))


def _input_paths(root: Path, day: datetime,
                 override: Sequence[str | Path] | None) -> list[Path]:
    values = list(override) if override is not None else [input_directory(root, day)]
    paths: list[Path] = []
    for raw in values:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (root / p).resolve()
        else:
            p = p.resolve()
        if not p.exists():
            if override is None:
                continue  # Optional spread input: not every day has one.
            raise FileNotFoundError(f"No spread input: {p}")
        if not p.is_dir() and (not p.is_file() or p.suffix.lower() not in SOURCE_EXTENSIONS):
            raise SpreadError(f"Spread input must be a GeoJSON, ZIP, or directory: {p}")
        if p not in paths:
            paths.append(p)
    return paths


def source_files(paths: Sequence[Path]) -> list[Path]:
    """Discover files for provenance without parsing or rewriting GeoJSON."""
    seen: set[Path] = set()
    found: list[Path] = []
    for p in paths:
        members = (sorted(x for x in p.rglob("*") if x.is_file())
                   if p.is_dir() else [p])
        for member in members:
            if member.suffix.lower() not in SOURCE_EXTENSIONS:
                continue
            resolved = member.resolve()
            if resolved not in seen:
                seen.add(resolved)
                found.append(resolved)
    return sorted(found)


def source_signature(files: Sequence[Path]) -> str:
    """Fingerprint file identity, size and mtime; detect changed source sets."""
    digest = hashlib.sha256()
    for p in files:
        stat = p.stat()
        digest.update(f"{p}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode("utf-8"))
    return digest.hexdigest()


def spread_options(args: argparse.Namespace) -> dict[str, Any]:
    values = dict(
        spread_grid_m=args.grid_m,
        spread_origin_x=args.origin_x,
        spread_origin_y=args.origin_y,
        spread_input_timezone=args.input_timezone,
        spread_rate_gph=args.rate_gph,
        spread_area_m2=args.area_m2,
        spread_heat_w=args.heat_w,
        spread_height_m=args.height_m,
    )
    try:
        ZoneInfo(str(args.input_timezone))
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise SpreadError(f"Invalid input timezone {args.input_timezone!r}") from exc
    for key in ("spread_grid_m", "spread_rate_gph", "spread_area_m2",
                "spread_heat_w", "spread_height_m"):
        val = float(values[key])
        if not (0 < val < float("inf")):
            raise SpreadError(f"{key} must be finite and > 0")
    for key in ("spread_origin_x", "spread_origin_y"):
        val = float(values[key])
        if not float("-inf") < val < float("inf"):
            raise SpreadError(f"{key} must be finite")
    return values


def _cache_input_settings(options: Mapping[str, Any]) -> dict[str, Any]:
    return {key: options[key] for key in
            ("spread_grid_m", "spread_origin_x", "spread_origin_y",
             "spread_input_timezone")}


def _cache_manifest_path(hourly: Path) -> Path:
    return hourly.parent / CACHE_MANIFEST


def _check_cache(hourly: Path, sig: str,
                 options: Mapping[str, Any], renew: bool) -> None:
    if renew or not hourly.is_file():
        return
    meta = sd.load_status(_cache_manifest_path(hourly))
    if not meta or meta.get("input_signature") != sig or meta.get("settings") != _cache_input_settings(options):
        raise SpreadError(f"Hourly spread cache cannot be verified: {hourly}. "
                          "Preserved for inspection; use --renew to regenerate "
                          "from the selected GeoJSON inputs")


def _save_cache_manifest(hourly: Path, sig: str, files: Sequence[Path],
                         options: Mapping[str, Any]) -> None:
    if hourly.is_file():
        sd.write_json_atomic(_cache_manifest_path(hourly), {
            "input_signature": sig,
            "source_files": [str(p) for p in files],
            "settings": _cache_input_settings(options),
            "created_utc": sd.utc_stamp(),
            "hourly_file": str(hourly),
        })


def _status(rd: Path, day: datetime, cfg: Mapping[str, Any],
            phase: str, arl: Sequence[str], hours: int,
            met_files: Sequence[str], *, source: str, files: Sequence[Path],
            sig: str, hourly: Path, options: Mapping[str, Any], **extra: Any) -> None:
    old = sd.load_status(rd / STATUS_FILE)
    sd.write_json_atomic(rd / STATUS_FILE, {
        "status": phase,
        "run_date": day.strftime("%Y%m%d"),
        "start_utc": day.strftime("%Y%m%d%H"),
        "simulation_hours": hours,
        "duration_source": source,
        "group": cfg["group"],
        "experiment": rd.parent.parent.name,
        "emissions": "spread",
        "emission_domain": cfg["emission_domain"],
        "geojson_sources": [str(p) for p in files],
        "geojson_signature": sig,
        "spread_options": dict(options),
        "spread_hourly": str(hourly),
        "meteorology": list(arl),
        "meteorological_files": list(met_files),
        "run_dir": str(rd),
        "started_utc": old.get("started_utc") or sd.utc_stamp(),
        "updated_utc": sd.utc_stamp(),
        **extra,
    })


def _inputs_changed(record: Mapping[str, Any], sig: str,
                    cfg: Mapping[str, Any], options: Mapping[str, Any]) -> bool:
    return (bool(record) and
            (record.get("geojson_signature") not in (None, sig) or
             record.get("emission_domain") not in (None, cfg["emission_domain"]) or
             (record.get("spread_options") not in (None, dict(options)))))


def print_plan(root: Path, cfg: Mapping[str, Any], day: datetime, hours: int,
               duration_source: str, files: Sequence[Path], hourly: Path) -> None:
    print(f"SPARK SPREAD {day:%Y%m%d%H} UTC")
    print(f"  project        {root}")
    print(f"  templates      {root / 'hysp.in' / str(cfg['group'])}")
    print(f"  simulation     {hours} h ({duration_source})")
    print(f"  geojson dir    {input_directory(root, day)}")
    print(f"  source files   {len(files)}")
    print(f"  hourly cache   {hourly}")
    print(f"  emission domain {cfg['emission_domain']}")
    print(f"  analysis ARL   {cfg['analysis_arl']}")
    print(f"  fallback ARL   {cfg['forecast_arl']} (if recent and needed)")
    print(f"  forecast cycle {cfg['forecast_cycle']}")
    print(f"  run root       {root / 'hysp.run' / str(cfg['group'])}")
    print("  steps          GeoJSON -> nsfs_prep1 -> nsfs_chk1 -> nsfs_run1")
    print("  dry-run        no input conversion, ARL download, or simulation")


def _existing_run_dirs(root: Path, cfg: Mapping[str, Any], day: datetime,
                       met_file: Sequence[str] | None = None) -> list[Path]:
    arl_choices: list[Sequence[str]] = [sd.arl_names(cfg["analysis_arl"]),
                                        sd.arl_names(cfg["forecast_arl"])]
    if met_file and any(sd.is_forecast_file(x) for x in met_file):
        arl_choices = [["gfs0p25.f"]]
    return list(dict.fromkeys(run_dir(root, cfg, day, arl)
                              for arl in arl_choices))


def check_prepared(root: Path, cfg: Mapping[str, Any], day: datetime,
                   ini: Path, *, verbose: bool,
                   met_file: Sequence[str] | None = None) -> str:
    _, checker, _ = sd.load_routines()
    mode = "any" if cfg["cpu_mode"] == "auto" else cfg["cpu_mode"]
    found = [rd for rd in _existing_run_dirs(root, cfg, day, met_file) if rd.is_dir()]
    if not found:
        raise SpreadError("No SPREAD run directory to check; run --prepare-only first")
    ready: list[Path] = []
    failures: list[str] = []
    for rd in found:
        report = checker(rd, mode=mode, ini=str(ini), verbose=verbose)
        if report.get("ok"):
            ready.append(rd)
            if verbose:
                print(f"READY {rd}")
        else:
            message = sd.nsfs_failure_text(report)
            failures.append(f"{rd}: {message}")
            if verbose:
                print(f"NOT READY {rd}: {message}")
    if ready:
        return "ready"
    raise SpreadNotReady("No READY SPREAD run: " + " | ".join(failures))


def _source_files_for_run(root: Path, day: datetime, override: Sequence[str | Path] | None
                          ) -> tuple[list[Path], list[Path]]:
    paths = _input_paths(root, day, override)
    return paths, source_files(paths)


def spread_emitimes_callback(*, renew: bool, verbose: bool):
    """Use the existing spread converter via nsfs_prep's original extension API.

    This deliberately bypasses nsfs_prep's inventory-name dispatch, which may
    only recognize finn/rave3/rave13 in older installed HYSP/NSFS releases.
    Its standard run['emitimes'] callback interface is available in those
    releases.  Leave responsibility for all other HYSPLIT files in nsfs_prep.
    """
    def build(*, emis: str, cday: int, domain: str | None,
              odir: str | Path, run: Mapping[str, Any]) -> Any:
        if str(emis).lower() != "spread":
            raise SpreadError(f"Unexpected emission module for spread callback: {emis}")
        try:
            from fire.fire_spread_emitimes import fire_spread_emitimes
        except ImportError as exc:
            raise SpreadError(
                "Cannot import fire.fire_spread_emitimes. This existing fire "
                "converter (and fire.fire_spread) must be accessible in the "
                "active Python environment; no changes to nsfs_prep are needed."
            ) from exc
        return fire_spread_emitimes(
            cday,
            inputs=run.get("spread_input"),
            hourly_file=run.get("spread_hourly"),
            grid_m=float(run.get("spread_grid_m", DEFAULT_GRID_M)),
            origin_x=float(run.get("spread_origin_x", 0.0)),
            origin_y=float(run.get("spread_origin_y", 0.0)),
            input_timezone=str(run.get("spread_input_timezone", "Asia/Seoul")),
            domain=domain,
            minfo=run.get("minfo"),
            bbox=run.get("bbox"),
            rate_gph=float(run.get("spread_rate_gph", DEFAULT_RATE_GPH)),
            area_m2=float(run.get("spread_area_m2", DEFAULT_AREA_M2)),
            heat_w=float(run.get("spread_heat_w", DEFAULT_HEAT_W)),
            height_m=float(run.get("spread_height_m", DEFAULT_HEIGHT_M)),
            renew=renew,
            odir=odir,
            ofile="EMITIMES",
            data_root=run.get("data_root"),
            verbose=verbose,
        )

    return build


def run_one(root: Path, cfg: Mapping[str, Any], day: datetime, *,
            ini: Path, options: Mapping[str, Any], inputs: Sequence[str | Path] | None = None,
            duration: int | None = None, renew: bool = False,
            dry_run: bool = False, prepare_only: bool = False,
            check_only: bool = False, verbose: bool = True,
            met_file: Sequence[str] | None = None) -> str:
    """Prepare a SPREAD run before checking ARL or HYSPLIT executables."""
    if check_only:
        return check_prepared(root, cfg, day, ini, verbose=verbose, met_file=met_file)

    hours, duration_source = sd.control_duration(root, cfg, duration)
    paths, files = _source_files_for_run(root, day, inputs)
    hourly = hourly_path(root, day)
    if dry_run:
        print_plan(root, cfg, day, hours, duration_source, files, hourly)
        return "planned"

    signature = source_signature(files) if files else ""
    analysis = sd.arl_names(cfg["analysis_arl"])
    forecast = sd.arl_names(cfg["forecast_arl"])
    use_forecast = bool(met_file and any(sd.is_forecast_file(p) for p in met_file))
    if met_file:
        if use_forecast:
            sd.forecast_cycle_from_files(met_file)
        candidates = [["gfs0p25.f"] if use_forecast else analysis]
    else:
        candidates = [analysis]
        if forecast != analysis and sd.forecast_fallback_eligible(day):
            candidates.append(forecast)
        elif forecast != analysis and verbose:
            print("HISTORICAL RUN: forecast fallback is not considered")

    if not files:
        # A completed run remains inspectable even if the original GeoJSON
        # inputs have subsequently been moved from the import directory.
        if inputs is None and any(all((rd / x).is_file() for x in sd.PREPARED_FILES)
                                  for rd in _existing_run_dirs(root, cfg, day, met_file)):
            if verbose:
                print("GeoJSON input no longer present; using existing prepared HYSPLIT inputs")
        else:
            if inputs is not None:
                raise SpreadError("The explicit --input paths contain no GeoJSON or ZIP files")
            if verbose:
                print(f"NO SPREAD INPUT {day:%Y%m%d}: {input_directory(root, day)}")
            return "no_input"

    sd.require_inputs(root, cfg, ini)
    prep, chk, exe = sd.load_routines()
    mode = "any" if cfg["cpu_mode"] == "auto" else cfg["cpu_mode"]
    failures: list[str] = []

    for index, arl in enumerate(candidates):
        rd = run_dir(root, cfg, day, arl)
        cdump = rd / sd.name_component(cfg["cdump"], "cdump")
        prev = sd.load_status(rd / STATUS_FILE)
        if not files and prev.get("geojson_sources"):
            recorded_files = [Path(x) for x in prev["geojson_sources"]]
            recorded_signature = str(prev.get("geojson_signature", ""))
        else:
            recorded_files = files
            recorded_signature = signature
        existing = sd.existing_prepared_files(rd) if not renew else []
        prepared = len(existing) == len(sd.PREPARED_FILES)
        if existing and not prepared:
            raise SpreadError(f"Partial HYSPLIT inputs preserved at {rd}: "
                              f"{', '.join(existing)}. Use --check-only, "
                              "repair manually, or --renew")
        if prepared:
            if files and _inputs_changed(prev, signature, cfg, options):
                raise SpreadError(f"GeoJSON input or spread settings changed at {rd}; "
                                  "preserving prepared operator files. Use --renew")
            met_files = sd.control_meteorology(rd)
            if met_file is not None:
                requested = [str(Path(x).expanduser().resolve()) for x in met_file]
                if requested != met_files:
                    raise SpreadError(f"Existing CONTROL at {rd} has different "
                                      "ARL files; use --renew to rebuild")
            if verbose:
                print(f"KEEP prepared SPREAD inputs {rd}")
        else:
            if not files:
                raise SpreadError("Cannot regenerate missing SPREAD inputs without GeoJSON")
            try:
                met_files = sd.gather_meteorology(day, hours, arl, cfg, ini,
                                                  verbose=verbose, explicit_files=met_file)
            except (OSError, ValueError, RuntimeError) as exc:
                failures.append(f"{'-'.join(arl)} ARL gathering: {exc}")
                if index + 1 < len(candidates) and met_file is None:
                    print(f"ARL gather failed: {exc}; attempting next candidate")
                    continue
                raise SpreadError("ARL gathering failed: " + " | ".join(failures)) from exc

        with sd.day_lock(rd):
            if cdump.is_file() and cdump.stat().st_size > 0 and not renew:
                if not prepared:
                    raise SpreadError(f"cdump exists but HYSPLIT input files are incomplete: {rd}. "
                                      "Preserving output; inspect manually or use --renew")
                if prev.get("status") in {"failed", "preparing", "checking", "running"}:
                    raise SpreadError(f"Existing {cdump} may be incomplete; "
                                      "inspect and use --renew if needed")
                if verbose:
                    print(f"SKIP existing {cdump}")
                return "existing"

            try:
                previous_cdump: str | None = None
                _status(rd, day, cfg, "preparing", arl, hours, met_files,
                        source=duration_source, files=recorded_files, sig=recorded_signature,
                        hourly=hourly, options=options)
                if not prepared:
                    _check_cache(hourly, signature, options, renew)
                    domain, bbox = sd.emission_selection(cfg["emission_domain"])
                    params: dict[str, Any] = {
                        "name": cfg["group"],
                        "arl": arl,
                        "emis": "spread",
                        "emitimes": spread_emitimes_callback(renew=renew, verbose=verbose),
                        "domain": domain,
                        "bbox": bbox,
                        "sdir": str(root / "hysp.in"),
                        "rdir": str(root / "hysp.run"),
                        "met_file": met_files,
                        "data_root": str(root / "hysp.data"),
                        "spread_input": [str(x) for x in paths],
                        "spread_hourly": str(hourly),
                        "skip_no_emission": True,
                        **options,
                    }
                    if duration is not None:
                        params["run_time"] = duration
                    if day.hour:
                        params["control_update"] = {"starting_time": f"{day:%y %m %d %H}"}
                    prepared_paths = prep(params, cday=day.strftime("%Y%m%d"),
                                          ini=str(ini), renew=renew, verbose=verbose)
                    if len(prepared_paths) != 1 or Path(prepared_paths[0]).resolve() != rd.resolve():
                        raise SpreadError(f"Unexpected NSFS preparation output: {prepared_paths}; expected {rd}")
                    _save_cache_manifest(hourly, signature, files, options)
                    if hourly.exists():
                        alias = rd / "spread_hourly.txt"
                        if not alias.exists() and not alias.is_symlink():
                            alias.symlink_to(hourly)

                # A renewed run's old concentration is incompatible with the
                # regenerated emissions, even if --prepare-only is selected.
                # Keep the old output as a named backup rather than silently
                # treating it as the output of the new preparation.
                if renew and cdump.is_file():
                    previous_cdump = sd._archive_cdump(rd, cdump)

                if not (rd / "EMITIMES").is_file():
                    _status(rd, day, cfg, "no_emission", arl, hours, met_files,
                            source=duration_source, files=recorded_files, sig=recorded_signature,
                            hourly=hourly, options=options,
                            previous_cdump=previous_cdump,
                            note="No active UTC spread emission cells in selected day/domain")
                    if verbose:
                        print(f"NO SPREAD EMISSION {day:%Y%m%d} UTC. "
                              "Check GeoJSON timestamps/time zone and emission_domain")
                    return "no_emission"

                # The remaining steps examine files prepared by nsfs_prep1.
                if not prepared or not prepare_only:
                    sd.verify_control_run(rd, day, hours,
                                          met_files if not prepared else None)
                cycle = sd.forecast_cycle_from_files(met_files)
                extra = dict(forecast_cycle=cycle,
                             forecast_cycle_strategy=(cfg["forecast_cycle"] if cycle else None))
                if prepare_only:
                    _status(rd, day, cfg, "prepared", arl, hours, met_files,
                            source=duration_source, files=recorded_files, sig=recorded_signature,
                            hourly=hourly, options=options,
                            previous_cdump=previous_cdump, **extra)
                    return "prepared"

                _status(rd, day, cfg, "checking", arl, hours, met_files,
                        source=duration_source, files=recorded_files, sig=recorded_signature,
                        hourly=hourly, options=options, **extra)
                report = chk(rd, mode=mode, ini=str(ini), verbose=verbose)
                if not report.get("ok"):
                    diagnostic = sd.nsfs_failure_text(report)
                    _status(rd, day, cfg, "not_ready", arl, hours, met_files,
                            source=duration_source, files=recorded_files, sig=recorded_signature,
                            hourly=hourly, options=options,
                            validation_failures=diagnostic, **extra)
                    if index + 1 < len(candidates) and met_file is None and sd.is_arl_only_failure(report):
                        failures.append(f"{'-'.join(arl)}: {diagnostic}")
                        if verbose:
                            print(f"ARCHIVE NOT READY ({diagnostic}); attempting forecast")
                        continue
                    raise SpreadNotReady("NSFS validation failed: " + diagnostic)

                backup = previous_cdump
                _status(rd, day, cfg, "running", arl, hours, met_files,
                        source=duration_source, files=recorded_files, sig=recorded_signature,
                        hourly=hourly, options=options, previous_cdump=backup, **extra)
                result = exe(rd, mode=cfg["cpu_mode"], cpu=cfg.get("cpu_n"),
                             ini=str(ini), logfile=str(cfg["logfile"]),
                             renew=bool(renew or (rd / cfg["logfile"]).exists()),
                             dry_run=False, verbose=verbose)
                if result.get("returncode") != 0:
                    raise SpreadError(f"HYSPLIT returned {result.get('returncode')}")
                if not cdump.is_file() or cdump.stat().st_size == 0:
                    raise SpreadError(f"HYSPLIT produced no valid {cdump}")
                _status(rd, day, cfg, "completed", arl, hours, met_files,
                        source=duration_source, files=recorded_files, sig=recorded_signature,
                        hourly=hourly, options=options, previous_cdump=backup,
                        cdump=str(cdump), cdump_bytes=cdump.stat().st_size,
                        execution_mode=result.get("mode"), **extra)
                return "completed"
            except SpreadNotReady:
                raise
            except Exception as exc:
                _status(rd, day, cfg, "failed", arl, hours, met_files,
                        source=duration_source, files=recorded_files, sig=recorded_signature,
                        hourly=hourly, options=options, error=f"{type(exc).__name__}: {exc}")
                raise
    raise SpreadError("No meteorological candidate succeeded: " + " | ".join(failures))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SPARK: timestamped GeoJSON fire spread -> HYSPLIT")
    p.add_argument("start", help="UTC start YYYYMMDD[HH]; 00 UTC if hour omitted")
    p.add_argument("end", nargs="?", help="optional final run date")
    p.add_argument("--root", type=Path, help="SPARK project directory; default script directory")
    p.add_argument("--ini", type=Path, help="HYSPLIT shared hysp.ini in project root")
    p.add_argument("--spark-ini", type=Path, help="SPARK defaults spark.ini in project root")
    p.add_argument("--input", nargs="+", metavar="PATH",
                   help="override automatic date directory with GeoJSON/ZIP files or directories")
    p.add_argument("--group", help="CONTROL/SETUP group under hysp.in")
    p.add_argument("--emission-domain", help="named domain or 'south,west,north,east'")
    p.add_argument("--arl", nargs="+", help="preferred archived meteorology")
    p.add_argument("--forecast-cycle", choices=("00z", "latest"))
    p.add_argument("--met-file", nargs="+", type=Path, help="explicit meteorological files")
    p.add_argument("--duration", type=int, help="HYSPLIT runtime override, hours")
    p.add_argument("--cpu-mode", choices=("auto", "serial", "mpi"))
    p.add_argument("--cpu-n", type=int)
    p.add_argument("--input-timezone", default="Asia/Seoul",
                   help="timezone of timestamps encoded in spread GeoJSON filenames")
    p.add_argument("--grid-m", type=float, default=DEFAULT_GRID_M)
    p.add_argument("--origin-x", type=float, default=0.0)
    p.add_argument("--origin-y", type=float, default=0.0)
    p.add_argument("--rate-gph", type=float, default=DEFAULT_RATE_GPH)
    p.add_argument("--area-m2", type=float, default=DEFAULT_AREA_M2)
    p.add_argument("--heat-w", type=float, default=DEFAULT_HEAT_W)
    p.add_argument("--height-m", type=float, default=DEFAULT_HEIGHT_M)
    p.add_argument("--prepare-only", action="store_true")
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--renew", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--debug", action="store_true")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser0 = parser()
    args = parser0.parse_args(argv)
    try:
        root = sd.resolve_root(args.root)
        ini = (root / args.ini).resolve() if args.ini else root / "hysp.ini"
        spark_ini = (root / args.spark_ini).resolve() if args.spark_ini else root / "spark.ini"
        if sum((args.check_only, args.prepare_only, args.status, args.dry_run)) > 1:
            raise SpreadError("Choose only one of --check-only, --prepare-only, --status, --dry-run")
        if args.duration is not None and args.duration <= 0:
            raise SpreadError("--duration must be > 0")
        if not ini.is_file() or not spark_ini.is_file():
            hint = args.group
            if hint is None and spark_ini.is_file():
                hint = sd.read_config(spark_ini)["group"]
            sd.init_project(root, hint or "SPARK", None, ini=ini, spark_ini=spark_ini)
        else:
            sd.load_hysp_init()(ini)
        cfg = sd.read_config(spark_ini)
        for key in ("group", "emission_domain", "cpu_mode", "cpu_n"):
            val = getattr(args, key)
            if val is not None:
                cfg[key] = val
        if args.arl:
            cfg["analysis_arl"] = args.arl
        if args.forecast_cycle is not None:
            cfg["forecast_cycle"] = args.forecast_cycle
        cfg["group"] = sd.name_component(cfg["group"], "group")
        cfg["analysis_arl"] = sd.arl_names(cfg["analysis_arl"])
        cfg["forecast_arl"] = sd.arl_names(cfg["forecast_arl"])
        sd.validate_spark_config(cfg, spark_ini)
        opts = spread_options(args)
        first = sd.parse_start(args.start)
        last = sd.parse_start(args.end) if args.end else first
        if args.end and first.hour and not last.hour:
            last = last.replace(hour=first.hour)
        met_files = ([str((root / p).resolve()) if not p.is_absolute() else str(p)
                      for p in args.met_file] if args.met_file else None)
        for day in sd.dates(first, last):
            if args.status:
                for rd in _existing_run_dirs(root, cfg, day, met_files):
                    status = sd.load_status(rd / STATUS_FILE)
                    print(json.dumps(status or {"status": "unknown", "run_dir": str(rd)}, indent=2))
                continue
            try:
                result = run_one(root, cfg, day, ini=ini, options=opts,
                                 inputs=args.input, duration=args.duration,
                                 renew=args.renew, dry_run=args.dry_run,
                                 prepare_only=args.prepare_only,
                                 check_only=args.check_only, verbose=not args.quiet,
                                 met_file=met_files)
                print(f"{day:%Y%m%d%H} {result}")
            except Exception as exc:
                print(f"ERROR {day:%Y%m%d%H}: {exc}", file=sys.stderr)
                if args.debug:
                    traceback.print_exc()
                return 1
        return 0
    except (OSError, sd.SparkError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
