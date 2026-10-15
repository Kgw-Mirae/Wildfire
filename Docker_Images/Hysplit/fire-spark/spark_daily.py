#!/usr/bin/env python3
"""
NAME
    spark_daily.py

PURPOSE
    Coordinate the daily FINN -> HYSPLIT workflow using existing NSFS
    routines in the strict order: prepare -> check -> run. The prepared CONTROL
    retains HYSPLIT template settings unless the run start or duration is
    explicitly overridden. Existing prepared operator files are never
    regenerated unless --renew is supplied. Historical meteorology is
    preferred; a recent run can fall back to GFS0P25 forecast after an
    ARL-only check failure.

USAGE
    python spark_daily.py 20250428
    python spark_daily.py 20250428 --prepare-only
    python spark_daily.py 20250428 --check-only
    python spark_daily.py 2026100812 --forecast-cycle latest
    python spark_daily.py 20261008 --duration 48

VERSION
    20261012-002

AUTHOR
    2026-10-12 Hyun Cheol Kim (hyun.kim@noaa.gov)

DEPENDENCIES
    Existing hysp and fire modules (hysp_init, hysp_arl, nsfs_prep,
    nsfs_chk, nsfs_run), and Python standard library.

NOTES
    SPARK defaults are in project-root spark.ini. HYSP settings are in
    project-root hysp.ini. Files are generated in the project-root hysp.*
    directories. No SPARK_HOME variable is required.
    Prefer project-local hysp.lib/python when present; otherwise Python
    uses its existing sys.path (including any site-packages .pth entries).
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import sys
import traceback
from typing import Any, Iterator, Mapping, Sequence


# Prefer the library bundled beside the controller. If absent, leave sys.path
# unchanged so an existing .pth installation (e.g., ~/lib/python) continues
# to work in the active Python environment.
LOCAL_LIB = Path(__file__).resolve().parent / "hysp.lib" / "python"
if LOCAL_LIB.is_dir():
    sys.path.insert(0, str(LOCAL_LIB))


DEFAULT_SPARK: dict[str, Any] = {
    "group": "NSFS",
    "analysis_arl": "gfs0p25",         # first choice, always
    "forecast_arl": "gfs0p25.f",     # automatic fallback, not an operation mode
    "forecast_cycle": "00z",         # 00 UTC of run day or latest eligible 6-hourly cycle
    "emission_domain": "nca12",     # named domain OR "south,west,north,east"
    "cpu_mode": "auto",
    "cpu_n": None,
    "cdump": "cdump3",
    "logfile": "log",
}
STATUS_FILE = "spark_daily.status.json"
LOCK_FILE = ".spark_daily.lock"


class SparkError(RuntimeError):
    """Recoverable SPARK operational failure."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def utc_stamp() -> str:
    return now_utc().isoformat(timespec="seconds")


def parse_start(text: str) -> datetime:
    """Accept YYYYMMDD or YYYYMMDDHH in UTC; default hour is 00."""
    if not re.fullmatch(r"\d{8}(\d{2})?", text):
        raise argparse.ArgumentTypeError("start must be YYYYMMDD or YYYYMMDDHH (UTC)")
    try:
        return datetime.strptime(text, "%Y%m%d%H" if len(text) == 10 else "%Y%m%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid UTC start: {text}") from exc


def dates(first: datetime, last: datetime) -> Iterator[datetime]:
    if last < first:
        raise SparkError("End date/time precedes start date/time")
    # A date range repeats the chosen UTC hour once per calendar day.
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


def resolve_root(value: str | Path | None) -> Path:
    return Path(value).expanduser().resolve() if value else Path(__file__).resolve().parent


def load_hysp_init():
    try:
        from hysp.hysp_init import hysp_init
    except ImportError as exc:
        raise SparkError("Cannot import hysp.hysp_init from your installed HYSP library") from exc
    return hysp_init


def load_control_reader():
    try:
        from hysp.hysp_control import hysp_control_read
    except ImportError as exc:
        raise SparkError("Cannot import hysp.hysp_control.hysp_control_read") from exc
    return hysp_control_read


def load_arl_finder():
    """Obtain filenames/download files; ARL validity belongs to nsfs_chk1."""
    try:
        from hysp.hysp_arl import hysp_arl_find
    except ImportError as exc:
        raise SparkError("Missing hysp.hysp_arl.hysp_arl_find") from exc
    return hysp_arl_find


def load_forecast_backend():
    """Reuse existing HYSP forecast-file naming, checks, and safe downloader.

    These internal HYSP helpers match the current hysp_arl.py implementation.
    Keep all filename conventions and URL/download behavior in that library.
    """
    try:
        from hysp import hysp_arl
    except ImportError as exc:
        raise SparkError("Cannot import hysp.hysp_arl for forecast-cycle selection") from exc
    required = (
        "_forecast_leads", "_forecast_cycle_dir", "_forecast_name",
        "_forecast_url", "_good_file", "_url_exists", "_download",
    )
    missing = [x for x in required if not callable(getattr(hysp_arl, x, None))]
    if missing:
        raise SparkError("Installed hysp.hysp_arl lacks forecast helpers: "
                         + ", ".join(missing))
    return hysp_arl


def load_routines():
    try:
        from fire.nsfs_prep import nsfs_prep1
        from fire.nsfs_chk import nsfs_chk1
        from fire.nsfs_run import nsfs_run1
    except ImportError as exc:
        raise SparkError("Cannot import fire.nsfs_prep/chk/run; check your existing Python library path") from exc
    return nsfs_prep1, nsfs_chk1, nsfs_run1


def emission_selection(value: Any) -> tuple[str | None, list[float] | None]:
    """Map SPARK emission_domain to the existing NSFS domain/bbox arguments.

    A four-value, comma-separated string is a geographic bbox in the order
    south, west, north, east; any other nonempty string is a named domain.
    """
    if not isinstance(value, str) or not value.strip():
        raise SparkError("emission_domain must be a nonempty domain name or 'S,W,N,E' string")
    value = value.strip()
    if "," not in value:
        return value, None
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise SparkError("emission_domain bbox must contain four numbers: south,west,north,east")
    try:
        south, west, north, east = (float(part) for part in parts)
    except ValueError as exc:
        raise SparkError("emission_domain bbox must contain numeric coordinates") from exc
    if not all(map(math.isfinite, (south, west, north, east))):
        raise SparkError("emission_domain bbox coordinates must be finite")
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise SparkError("emission_domain bbox requires -90 <= south < north <= 90 "
                         "and -180 <= west < east <= 180")
    return None, [south, west, north, east]


def _bbox_text(value: Any) -> str:
    """Convert the old list-based bbox setting to the new string form."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise SparkError("legacy bbox must contain exactly four numbers")
    raw = ",".join(str(x) for x in value)
    _, bbox = emission_selection(raw)
    assert bbox is not None
    return ",".join(f"{x:g}" for x in bbox)


def normalize_legacy_spark(block: Mapping[str, Any], source: Path) -> dict[str, Any]:
    """Translate pre-October-9 option names without discarding custom values."""
    data = dict(block)
    legacy_duration = data.pop("run_time", None)
    if legacy_duration is not None:
        print(f"WARNING: ignoring legacy run_time in {source}; CONTROL sets duration",
              file=sys.stderr)

    old_domain = data.pop("domain", None)
    old_bbox = data.pop("bbox", None)
    old_mode = data.pop("mode", None)
    old_cpu = data.pop("cpu", None)

    old_values: dict[str, Any] = {}
    if old_bbox is not None:
        old_values["emission_domain"] = _bbox_text(old_bbox)
    elif old_domain is not None:
        old_values["emission_domain"] = old_domain
    if old_mode is not None:
        old_values["cpu_mode"] = old_mode
    if old_cpu is not None:
        old_values["cpu_n"] = old_cpu

    old_defaults = {"emission_domain": "nca12", "cpu_mode": "auto", "cpu_n": None}
    for new_key, old_value in old_values.items():
        if new_key not in data:
            data[new_key] = old_value
        elif data[new_key] != old_value and old_value != old_defaults[new_key]:
            # A user-adjusted legacy value may replace a *default* new value,
            # but two different user-adjusted values are ambiguous.
            if data[new_key] == DEFAULT_SPARK[new_key]:
                data[new_key] = old_value
            else:
                raise SparkError(f"Conflicting {new_key} and legacy setting in {source}")
    return data


def validate_spark_config(block: Mapping[str, Any], path: Path) -> None:
    unknown = sorted(set(block) - set(DEFAULT_SPARK))
    if unknown:
        raise SparkError(f"Unknown setting(s) in {path}: {', '.join(unknown)}")
    emission_selection(block.get("emission_domain", DEFAULT_SPARK["emission_domain"]))
    if block.get("cpu_mode", DEFAULT_SPARK["cpu_mode"]) not in {"auto", "serial", "mpi"}:
        raise SparkError("cpu_mode must be auto, serial or mpi")
    cpu = block.get("cpu_n")
    if cpu is not None and (type(cpu) is not int or cpu < 1):
        raise SparkError("cpu_n must be null or a positive integer")
    cycle = block.get("forecast_cycle", DEFAULT_SPARK["forecast_cycle"])
    if cycle not in {"00z", "latest"}:
        raise SparkError("forecast_cycle must be '00z' or 'latest'")


def read_config(spark_ini: Path) -> dict[str, Any]:
    """Read/create root spark.ini, translating prior-release options once.

    HYSPLIT CONTROL owns duration and hysp.ini owns system/HYSPLIT settings.
    Existing customized files are never replaced by the default template.
    """
    if not spark_ini.is_file():
        write_json_atomic(spark_ini, DEFAULT_SPARK)
        print(f"CREATE {spark_ini} (SPARK default settings)")
    try:
        raw = json.loads(spark_ini.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SparkError(f"Invalid JSON configuration {spark_ini}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SparkError(f"Expected a JSON object in {spark_ini}")
    block = normalize_legacy_spark(raw, spark_ini)
    validate_spark_config(block, spark_ini)
    if block != raw:
        # A backup protects user overrides during a one-time migration.
        backup = spark_ini.with_name(spark_ini.name + ".legacy.bak")
        if not backup.exists():
            shutil.copy2(spark_ini, backup)
        write_json_atomic(spark_ini, block)
        print(f"MIGRATE {spark_ini} (previous settings backed up in {backup.name})")
    return {**DEFAULT_SPARK, **block}


def arl_names(value: str | Sequence[str]) -> list[str]:
    raw = value.split() if isinstance(value, str) else [str(x) for x in value]
    values = [str(x).strip().lower() for x in raw]
    if not values or any(not x or "/" in x or "\\" in x or x in {".", ".."} for x in values):
        raise SparkError(f"Invalid ARL dataset: {value!r}")
    return values


def name_component(value: Any, label: str) -> str:
    s = str(value)
    if not s or s in {".", ".."} or "/" in s or "\\" in s:
        raise SparkError(f"Invalid {label}: {s!r}")
    return s


def experiment(arl: str | Sequence[str]) -> str:
    names = arl_names(arl)
    # This is an experiment category, not a list of forecast cycles or a
    # declaration that all input grids are forecast grids.
    if any(name in {"gfs0p25.f", "gfs0p25f"} for name in names):
        return "gfs0p25.f-finn"
    return "-".join([*names, "finn"])


def run_dir(root: Path, cfg: Mapping[str, Any], day: datetime, arl: str | Sequence[str]) -> Path:
    return root / "hysp.run" / name_component(cfg["group"], "group") / experiment(arl) / day.strftime("%Y") / day.strftime("%Y%m%d")


def template_file(root: Path, cfg: Mapping[str, Any]) -> Path:
    return root / "hysp.in" / name_component(cfg["group"], "group") / "CONTROL"


def control_duration(root: Path, cfg: Mapping[str, Any], override: int | None) -> tuple[int, str]:
    template = template_file(root, cfg)
    if not template.is_file():
        raise SparkError(f"Missing HYSPLIT CONTROL template: {template}")
    try:
        control = load_control_reader()(template)
        hours = int(float(str(control["run_time"]).strip()))
    except (ValueError, TypeError, KeyError) as exc:
        raise SparkError(f"Invalid run duration in {template}: {exc}") from exc
    if hours <= 0:
        raise SparkError(f"SPARK needs a forward CONTROL duration (>0); got {hours}")
    if override is not None:
        if override <= 0:
            raise SparkError("--duration must be a positive number of hours")
        return override, "--duration"
    return hours, "CONTROL"


def meteorology_window(start: datetime, hours: int) -> tuple[datetime, datetime]:
    """Require actual coverage through the end of the HYSPLIT run."""
    return start, start + timedelta(hours=hours)


def forecast_candidates(start: datetime, strategy: str, *,
                        current_time: datetime | None = None,
                        max_cycles: int = 13) -> list[datetime]:
    """Order eligible forecast cycles, preferring 00Z or the latest 6h cycle.

    The preferred 00Z cycle belongs to the *HYSPLIT start date* (not the
    current calendar date).  If that cycle is unavailable, older 6-hour cycles
    are tried in order, never cycles later than the requested HYSPLIT start.
    """
    if strategy not in {"00z", "latest"}:
        raise SparkError("forecast_cycle must be '00z' or 'latest'")
    if max_cycles < 1:
        raise SparkError("max_cycles must be positive")
    preferred = start.replace(hour=0, minute=0, second=0, microsecond=0)
    if strategy == "latest":
        preferred = start.replace(hour=(start.hour // 6) * 6,
                                  minute=0, second=0, microsecond=0)
    current_time = current_time or now_utc()
    if current_time.tzinfo is not None:
        current_time = current_time.astimezone(timezone.utc).replace(tzinfo=None)
    newest_possible = current_time.replace(hour=(current_time.hour // 6) * 6,
                                            minute=0, second=0, microsecond=0)
    preferred = min(preferred, newest_possible)
    return [preferred - timedelta(hours=6 * index) for index in range(max_cycles)]


def is_forecast_file(value: str | Path) -> bool:
    """Detect operational GFS files, even in an explicit mixed --met-file list."""
    path = Path(value)
    parts = [p.lower() for p in path.parts]
    return ("gfs0p25.f" in parts or
            bool(re.fullmatch(r"hysplit\.t\d{2}z\.gfs0p25f\d{3}",
                              path.name, re.IGNORECASE)))


def find_forecast_files(start: datetime, hours: int, ini: Path, *,
                        strategy: str, verbose: bool) -> list[str]:
    """Gather one GFS forecast cycle for nsfs_prep1; do NOT validate ARL here.

    Use the installed HYSP forecast downloader's cycle helpers when available.
    Older HYSP releases lack these private helpers. For those, delegate to
    the supported hysp_arl_find() interface instead of aborting preparation.
    The fallback's cycle selection follows the installed HYSP routine, which
    may not implement SPARK's 00z/latest preference. The actual cycle is
    determined from the selected filenames and recorded in run status.
    """
    first, last = meteorology_window(start, hours)
    try:
        backend = load_forecast_backend()
    except SparkError as exc:
        if verbose:
            print(f"FORECAST ADAPTER: {exc}")
            print("  Using hysp_arl_find('gfs0p25.f'); cycle strategy depends on installed HYSP")
        return [str(x) for x in load_arl_finder()(
            ["gfs0p25.f"], time=[first, last], ini=str(ini), verbose=verbose)]

    opt = load_hysp_init()(ini)
    arl_root = Path(str(opt["ARL_PATH"])).expanduser()
    can_download = bool(int(opt.get("ARL_DOWN", 0)))
    failures: list[str] = []
    for cycle in forecast_candidates(start, strategy):
        cycle_text = cycle.strftime("%Y%m%d%H")
        try:
            leads = backend._forecast_leads(cycle, first, last)
            if not leads:
                continue
            paths = [backend._forecast_cycle_dir(arl_root, cycle) /
                     backend._forecast_name(cycle, lead) for lead in leads]
            missing = [(lead, path) for lead, path in zip(leads, paths)
                       if not backend._good_file(path)]
            if missing and not can_download:
                failures.append(f"{cycle_text}: missing local forecast blocks")
                continue
            # Only test whether downloads exist; nsfs_chk checks actual ARL data.
            unavailable = [lead for lead, _ in missing
                           if not backend._url_exists(backend._forecast_url(cycle, lead))]
            if unavailable:
                failures.append(f"{cycle_text}: unavailable forecast blocks {unavailable}")
                continue
            if verbose:
                print(f"GATHER forecast cycle {cycle_text} ({strategy})")
            for lead, target in missing:
                backend._download(backend._forecast_url(cycle, lead),
                                  target, verbose=verbose)
            return [str(path.resolve()) for path in paths]
        except (OSError, RuntimeError, ValueError) as exc:
            failures.append(f"{cycle_text}: {type(exc).__name__}: {exc}")
            if verbose:
                print(f"Forecast cycle unavailable: {failures[-1]}")
    raise FileNotFoundError("No GFS0P25.f cycle could be gathered for "
                            f"{first:%Y%m%d%H}-{last:%Y%m%d%H} "
                            f"(preference={strategy}); " + "; ".join(failures[:5]))


def expected_gfs0p25_archive_files(start: datetime, hours: int, ini: Path) -> list[str]:
    """Expected GFS0P25 archive paths, including unavailable/missing files.

    Used only for staging the CONTROL file when the ordinary HYSP archive
    finder has missing inputs. Validity and coverage are checked by nsfs_chk1.
    """
    opt = load_hysp_init()(ini)
    arl_root = Path(str(opt["ARL_PATH"])).expanduser().resolve()
    last = start + timedelta(hours=hours)
    current = start.replace(hour=0, minute=0, second=0, microsecond=0)
    stop = last.replace(hour=0, minute=0, second=0, microsecond=0)
    files: list[str] = []
    while current <= stop:
        files.append(str(arl_root / "gfs0p25" / current.strftime("%Y") /
                         current.strftime("%m") /
                         f"{current:%Y%m%d}_gfs0p25"))
        current += timedelta(days=1)
    return files


def gather_meteorology(start: datetime, hours: int, arl: Sequence[str],
                       cfg: Mapping[str, Any], ini: Path, *,
                       verbose: bool = True,
                       explicit_files: Sequence[str] | None = None) -> list[str]:
    """Find/download meteorological paths; do not validate inputs before prep.

    Missing GFS0P25 archive files are still written into CONTROL as expected
    filenames. nsfs_chk1 will then flag them after NSFS has prepared every
    possible input. An unsuccessful download is not itself a readiness verdict.
    """
    names = arl_names(arl)
    if explicit_files is not None:
        paths = [str(Path(p).expanduser().resolve()) for p in explicit_files]
        if any(is_forecast_file(x) for x in paths):
            forecast_cycle_from_files(paths)  # reject mixed forecast cycles
    elif names == ["gfs0p25.f"]:
        paths = find_forecast_files(start, hours, ini,
                                    strategy=str(cfg["forecast_cycle"]), verbose=verbose)
    else:
        first, last = meteorology_window(start, hours)
        try:
            paths = [str(x) for x in load_arl_finder()(
                names, time=[first, last], ini=str(ini), verbose=verbose)]
        except (OSError, ValueError, RuntimeError) as exc:
            if names != ["gfs0p25"]:
                raise
            if verbose:
                print(f"ARL gather warning: {exc}; will prepare expected GFS paths for nsfs_chk")
            paths = []
        if names == ["gfs0p25"]:
            expected = expected_gfs0p25_archive_files(start, hours, ini)
            # When the normal finder returns paths in the standard archive
            # convention, preserve its ordering and add missing days so that
            # the checker can explicitly diagnose every missing file.
            if not paths or any(re.fullmatch(r"\d{8}_gfs0p25", Path(p).name)
                                for p in paths):
                paths = expected
    if not paths:
        raise FileNotFoundError(f"No ARL filenames gathered for {names}")
    return paths

def forecast_fallback_eligible(start: datetime, *, at: datetime | None = None) -> bool:
    """Operational forecast archives are short-lived, not historical backfills."""
    current = at if at is not None else now_utc()
    if current.tzinfo is not None:
        current = current.astimezone(timezone.utc).replace(tzinfo=None)
    return current - timedelta(days=7) <= start <= current + timedelta(days=10)


def is_arl_only_failure(report: Mapping[str, Any]) -> bool:
    """Forecast fallback is allowed only when nsfs_chk finds ARL problems."""
    failures = [str(x.get("name", "")) for x in report.get("checks", [])
                if not x.get("ok", False)]
    return bool(failures) and all(name.startswith("ARL") for name in failures)


def nsfs_failure_text(report: Mapping[str, Any]) -> str:
    failures = [f"{x.get('name')}: {x.get('detail')}" for x in report.get('checks', [])
                if not x.get('ok', False)]
    return "; ".join(failures) or "nsfs_chk1 returned NOT READY"

def input_emission_file(root: Path, day: datetime) -> Path:
    return (root / "hysp.data" / "fire-finn" / "nrt" / "dayfile" / day.strftime("%Y")
            / f"fire-finn-nrt.{day:%Y%m%d}.npz")


def write_json_atomic(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True, default=str)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load_status(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def update_status(rd: Path, day: datetime, cfg: Mapping[str, Any], phase: str,
                  arl: Sequence[str], duration: int, met_files: Sequence[str], **extra: Any) -> None:
    old = load_status(rd / STATUS_FILE)
    running = old.get("status") in {"preparing", "checking", "running"}
    report = {
        "status": phase,
        "run_date": day.strftime("%Y%m%d"),
        "start_utc": day.strftime("%Y%m%d%H"),
        "simulation_hours": duration,
        "duration_source": extra.pop("duration_source", None),
        "emission_source_day": day.strftime("%Y%m%d"),
        "group": cfg["group"],
        "emission_domain": cfg["emission_domain"],
        "experiment": experiment(arl),
        "meteorology": list(arl),
        "meteorological_files": list(met_files),
        "run_dir": str(rd),
        "started_utc": old.get("started_utc") if running else utc_stamp(),
        "updated_utc": utc_stamp(),
        **extra,
    }
    write_json_atomic(rd / STATUS_FILE, report)


@contextmanager
def day_lock(rd: Path) -> Iterator[None]:
    rd.mkdir(parents=True, exist_ok=True)
    lock = rd / LOCK_FILE
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as exc:
        raise SparkError(f"Run locked: {lock}. Inspect stale lock before removal") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"host={socket.gethostname()} pid={os.getpid()} started={utc_stamp()}\n")
        yield
    finally:
        lock.unlink(missing_ok=True)


def require_inputs(root: Path, cfg: Mapping[str, Any], ini: Path) -> None:
    """Check configuration and source templates, NOT executable readiness.

    Even if hycs_std/hycm_std/mpirun are missing, preparation should run;
    nsfs_chk1 is responsible for reporting unavailable executables.
    """
    if not ini.is_file():
        raise SparkError(f"Missing hysp.ini: {ini}")
    opt = load_hysp_init()(ini)
    # nsfs_prep's existing hysp_init_exelink requires a nonempty HYSPLIT_PATH;
    # whether the actual executables exist is deliberately NOT checked here.
    if not str(opt.get("HYSPLIT_PATH", "")).strip():
        raise SparkError(f"HYSPLIT_PATH must be set in {ini} to prepare executable links")
    if not str(opt.get("ARL_PATH", "")).strip():
        raise SparkError(f"ARL_PATH must be set in {ini}")
    td = template_file(root, cfg).parent
    for name in ("CONTROL", "SETUP.CFG"):
        if not (td / name).is_file():
            raise SparkError(f"Missing HYSPLIT template: {td / name}")


class SparkNotReady(SparkError):
    """Validation outcome; keep status as not_ready rather than failed."""


PREPARED_FILES = ("CONTROL", "SETUP.CFG", "ASCDATA.CFG", "EMITIMES")


def existing_prepared_files(rd: Path) -> list[str]:
    """Run-specific files requiring explicit permission before replacement."""
    return [name for name in PREPARED_FILES if (rd / name).is_file()]


def control_meteorology(rd: Path) -> list[str]:
    """Honor meteorological files in the operator's actual prepared CONTROL."""
    cc = load_control_reader()(rd / "CONTROL")
    return [str(Path(x).expanduser().resolve())
            for x in cc.get("meteorological_data", [])]


def verify_control_run(rd: Path, start: datetime, hours: int,
                       met_files: Sequence[str] | None = None) -> None:
    if not (rd / "CONTROL").is_file():
        raise SparkError(f"Missing CONTROL: {rd / 'CONTROL'}")
    try:
        cc = load_control_reader()(rd / "CONTROL")
        parts = [int(x) for x in str(cc["starting_time"]).split()[:4]]
        yy, mm, dd, hh = parts
        actual = datetime(1900 + yy if yy > 40 else 2000 + yy, mm, dd, hh)
        actual_hours = int(float(cc["run_time"]))
        actual_met = [str(Path(x).expanduser().resolve()) for x in cc.get("meteorological_data", [])]
    except (ValueError, TypeError, IndexError, KeyError) as exc:
        raise SparkError(f"Invalid CONTROL {rd / 'CONTROL'}: {exc}") from exc
    if actual != start or actual_hours != hours:
        raise SparkError(f"CONTROL mismatch: {rd / 'CONTROL'} has {actual:%Y%m%d%H} "
                         f"and {actual_hours} hours; requested {start:%Y%m%d%H} "
                         f"and {hours} hours. Use --renew to rebuild")
    if met_files is not None:
        expected = [str(Path(x).expanduser().resolve()) for x in met_files]
        if expected != actual_met:
            raise SparkError(f"CONTROL meteorological files differ from selected ARL; "
                             "use --renew to rebuild")


def forecast_cycle_from_files(files: Sequence[str]) -> str | None:
    cycles: set[str] = set()
    for x in files:
        p = Path(x)
        if not is_forecast_file(p):
            continue
        if re.fullmatch(r"\d{10}", p.parent.name):
            cycles.add(p.parent.name)
            continue
        if re.fullmatch(r"\d{8}", p.parent.name):
            m = re.match(r"hysplit\.t(\d\d)z\.gfs0p25f\d+", p.name, re.I)
            if m:
                cycles.add(p.parent.name + m.group(1))
    if len(cycles) > 1:
        raise SparkError(f"Mixed forecast cycles: {sorted(cycles)}")
    return next(iter(cycles), None)


def print_plan(root: Path, cfg: Mapping[str, Any], start: datetime,
               duration: int, source: str, ini: Path) -> None:
    print(f"SPARK FINN {start:%Y%m%d%H} UTC")
    print(f"  project        {root}")
    print(f"  hysp.ini       {ini}")
    print(f"  CONTROL        {template_file(root, cfg)}")
    print(f"  simulation     {duration} h (from {source})")
    print(f"  emission day   {start:%Y%m%d} (24-hour FINN inventory)")
    print(f"  meteorology    prefer {cfg['analysis_arl']}, fallback {cfg['forecast_arl']}")
    print(f"  forecast cycle {cfg.get('forecast_cycle', '00z')} (only if forecast needed)")
    t0, t1 = meteorology_window(start, duration)
    print(f"  required ARL   {t0:%Y%m%d%H} through {t1:%Y%m%d%H}")
    domain, bbox = emission_selection(cfg["emission_domain"])
    print(f"  emission domain {cfg['emission_domain']}"
          f" ({'bbox=' + str(bbox) if bbox is not None else 'named domain=' + str(domain)})")
    print(f"  run roots      {root / 'hysp.run' / str(cfg['group'])}")
    print("  steps          gather ARL -> nsfs_prep1 -> nsfs_chk1 -> nsfs_run1")
    print("  dry-run        no downloads or writes")


def run_one(
    root: Path,
    cfg: Mapping[str, Any],
    day: datetime,
    *,
    ini: Path,
    duration: int | None = None,
    renew: bool = False,
    renew_raw: bool = False,
    dry_run: bool = False,
    prepare_only: bool = False,
    check_only: bool = False,
    verbose: bool = True,
    met_file: Sequence[str] | None = None,
) -> str:
    """One run: prepare once, then check, then run; preserve operator edits."""
    nsfs_prep1, nsfs_chk1, nsfs_run1 = load_routines()
    mode = "any" if cfg["cpu_mode"] == "auto" else str(cfg["cpu_mode"])
    analysis = arl_names(cfg["analysis_arl"])
    forecast = arl_names(cfg["forecast_arl"])

    if check_only:
        # Manual diagnostics are intentionally independent of the original
        # template and any later operator edits to the run's CONTROL.
        dirs = list(dict.fromkeys(run_dir(root, cfg, day, names)
                                  for names in (analysis, forecast)))
        found = [rd for rd in dirs if rd.is_dir()]
        if not found:
            raise SparkError("No prepared run for this day; use --prepare-only")
        ready = []
        failures = []
        for rd in found:
            report = nsfs_chk1(rd, mode=mode, ini=str(ini), verbose=verbose)
            if report.get("ok"):
                ready.append(rd)
                if verbose:
                    print(f"READY {rd}")
            else:
                issue = nsfs_failure_text(report)
                failures.append(f"{rd}: {issue}")
                if verbose:
                    print(f"NOT READY {rd}: {issue}")
        if ready:
            return "ready"
        raise SparkNotReady("NSFS check found no READY run: " + " | ".join(failures))

    hours, source = control_duration(root, cfg, duration)
    if dry_run:
        print_plan(root, cfg, day, hours, source, ini)
        return "planned"
    require_inputs(root, cfg, ini)

    use_explicit_forecast = bool(met_file and any(is_forecast_file(x) for x in met_file))
    if met_file is not None:
        # An explicit list can include both analysis and forecast fields.
        # Route it to the forecast experiment whenever any file is forecast.
        if use_explicit_forecast:
            forecast_cycle_from_files(met_file)
        options = [forecast if use_explicit_forecast else analysis]
    else:
        options = [analysis]
        if forecast != analysis and forecast_fallback_eligible(day):
            options.append(forecast)
        elif forecast != analysis and verbose:
            print("HISTORICAL RUN: forecast fallback disabled; use archived meteorology")

    failures: list[str] = []
    for candidate_index, selected_arl in enumerate(options):
        rd = run_dir(root, cfg, day, selected_arl)
        cdump = rd / name_component(cfg["cdump"], "cdump")
        # First honor an already prepared run. Do not gather new meteorology
        # or touch CONTROL/SETUP.CFG/EMITIMES when operators have edited them.
        prepared_files = existing_prepared_files(rd) if not renew else []
        preexisting = len(prepared_files) == len(PREPARED_FILES)
        if prepared_files and not preexisting:
            raise SparkError(
                f"Partial run exists at {rd}: {', '.join(prepared_files)}. "
                "Preserved operator files; use --check-only, repair manually, "
                "or explicitly --renew to regenerate")
        if preexisting:
            met_files = control_meteorology(rd)
            if met_file is not None:
                requested = [str(Path(x).expanduser().resolve()) for x in met_file]
                if requested != met_files:
                    raise SparkError(f"Existing prepared CONTROL at {rd} has different "
                                     "meteorological inputs; preserving it. Use --renew "
                                     "to change the meteorology")
            if verbose:
                print(f"KEEP prepared HYSPLIT inputs {rd} (use --renew to rebuild)")
        else:
            # ARL path gathering is not a readiness verdict. nsfs_chk1 is the
            # first point at which meteorological validity is assessed.
            try:
                if verbose:
                    print(f"GATHER ARL {'+'.join(selected_arl)}: "
                          f"{day:%Y%m%d%H} - {(day + timedelta(hours=hours)):%Y%m%d%H}")
                met_files = gather_meteorology(day, hours, selected_arl, cfg, ini,
                                               verbose=verbose, explicit_files=met_file)
            except (OSError, ValueError, RuntimeError) as exc:
                failures.append(f"{'-'.join(selected_arl)} gathering: {exc}")
                if candidate_index + 1 < len(options) and met_file is None:
                    if verbose:
                        print(f"ARCHIVE GATHER FAILED: {exc}; trying forecast")
                    continue
                raise SparkError("Could not gather meteorology: " + " | ".join(failures)) from exc

        with day_lock(rd):
            prev = load_status(rd / STATUS_FILE)
            if cdump.is_file() and cdump.stat().st_size > 0 and not renew:
                verify_control_run(rd, day, hours)
                if prev.get("stale_existing_cdump"):
                    raise SparkError("Old cdump remains after re-preparation; use --renew")
                if prev.get("status") in {"failed", "preparing", "checking", "running"}:
                    raise SparkError("Existing cdump may be incomplete; use --renew")
                if prev.get("emission_policy") == "persistence":
                    raise SparkError("Existing cdump used FINN persistence; use --renew")
                if verbose:
                    print(f"SKIP existing cdump {cdump}")
                return "existing"

            try:
                update_status(rd, day, cfg, "preparing", selected_arl, hours, met_files,
                              duration_source=source, emission_policy="native_day")
                if not preexisting:
                    domain, bbox = emission_selection(cfg["emission_domain"])
                    params: dict[str, Any] = {
                        "name": cfg["group"],
                        "arl": selected_arl,
                        "emis": "finn",
                        "domain": domain,
                        "bbox": bbox,
                        "data_root": str(root / "hysp.data"),
                        "sdir": str(root / "hysp.in"),
                        "rdir": str(root / "hysp.run"),
                        "met_file": met_files,
                        "skip_no_emission": True,
                        "renew_raw": renew_raw,
                    }
                    if duration is not None:
                        params["run_time"] = duration
                    if day.hour:
                        params["control_update"] = {"starting_time": f"{day:%y %m %d %H}"}

                    # Build before any executable/ARL validity checking.
                    paths = nsfs_prep1(params, cday=day.strftime("%Y%m%d"),
                                       ini=str(ini), renew=renew, verbose=verbose)
                    if len(paths) != 1 or Path(paths[0]).resolve() != rd.resolve():
                        raise SparkError(f"Unexpected nsfs_prep1 result: {paths}; expected {rd}")

                if not (rd / "EMITIMES").is_file():
                    archived = _archive_cdump(rd, cdump) if renew else None
                    if not input_emission_file(root, day).is_file():
                        update_status(rd, day, cfg, "missing_finn", selected_arl, hours, met_files,
                                      duration_source=source, previous_cdump=archived,
                                      note="FINN inventory unavailable; simulation skipped")
                        if verbose:
                            print(f"SKIP FINN INVENTORY {day:%Y%m%d}: "
                                  f"{input_emission_file(root, day)}")
                        return "missing_finn"
                    update_status(rd, day, cfg, "no_emission", selected_arl, hours, met_files,
                                  duration_source=source, previous_cdump=archived,
                                  note="No FINN emissions in domain")
                    if verbose:
                        print(f"NO FINN EMISSIONS IN DOMAIN {day:%Y%m%d}")
                    return "no_emission"

                # Preparation must finish *before* checking CONTROL or ARL.
                if not preexisting or not prepare_only:
                    verify_control_run(rd, day, hours,
                                       met_files if not preexisting else None)
                cycle = forecast_cycle_from_files(met_files)
                strategy = ("explicit" if met_file is not None else cfg["forecast_cycle"]) if cycle else None
                if prepare_only:
                    update_status(rd, day, cfg, "prepared", selected_arl, hours, met_files,
                                  duration_source=source, forecast_cycle=cycle,
                                  forecast_cycle_strategy=strategy,
                                  note="Run files prepared; use --check-only to validate ARL and inputs")
                    return "prepared"

                update_status(rd, day, cfg, "checking", selected_arl, hours, met_files,
                              duration_source=source, forecast_cycle=cycle,
                              forecast_cycle_strategy=strategy)
                report = nsfs_chk1(rd, mode=mode, ini=str(ini), verbose=verbose)
                if not report.get("ok"):
                    diagnostic = nsfs_failure_text(report)
                    update_status(rd, day, cfg, "not_ready", selected_arl, hours, met_files,
                                  duration_source=source, forecast_cycle=cycle,
                                  validation_failures=diagnostic)
                    if (candidate_index + 1 < len(options) and met_file is None
                            and is_arl_only_failure(report)):
                        if verbose:
                            print(f"ARCHIVE NOT READY ({diagnostic}); trying forecast")
                        failures.append(f"{'-'.join(selected_arl)} validation: {diagnostic}")
                        continue
                    raise SparkNotReady("NSFS validation failed after preparation: " + diagnostic)

                archived = _archive_cdump(rd, cdump) if renew else None
                update_status(rd, day, cfg, "running", selected_arl, hours, met_files,
                              duration_source=source, forecast_cycle=cycle,
                              forecast_cycle_strategy=strategy, previous_cdump=archived)
                result = nsfs_run1(
                    rd, mode=str(cfg["cpu_mode"]), cpu=cfg.get("cpu_n"),
                    ini=str(ini), logfile=str(cfg["logfile"]),
                    renew=bool(renew or (rd / name_component(cfg["logfile"], "logfile")).exists()),
                    dry_run=False, verbose=verbose)
                if result.get("returncode") != 0:
                    raise SparkError(f"HYSPLIT failed: returncode={result.get('returncode')}")
                if not cdump.is_file() or cdump.stat().st_size == 0:
                    raise SparkError(f"No valid cdump was produced at {cdump}")
                update_status(rd, day, cfg, "completed", selected_arl, hours, met_files,
                              duration_source=source, forecast_cycle=cycle,
                              forecast_cycle_strategy=strategy,
                              emission_policy="native_day", cdump=str(cdump),
                              cdump_bytes=cdump.stat().st_size, previous_cdump=archived,
                              execution_mode=result.get("mode"))
                if verbose:
                    print(f"DONE: {cdump}")
                return "completed"
            except SparkNotReady:
                # nsfs_chk is authoritative. Preserve its NOT READY status.
                raise
            except Exception as exc:
                update_status(rd, day, cfg, "failed", selected_arl, hours, met_files,
                              duration_source=source, error=f"{type(exc).__name__}: {exc}")
                raise

    raise SparkError("No suitable ARL inputs: " + " | ".join(failures))

def _archive_cdump(rd: Path, cdump: Path) -> str | None:
    if not cdump.exists():
        return None
    backup = rd / f"{cdump.name}.previous.{now_utc():%Y%m%dT%H%M%SZ}"
    if backup.exists():
        raise SparkError(f"Existing backup: {backup}")
    cdump.rename(backup)
    return str(backup)


def init_project(root: Path, group: str, hysplit: str | None,
                 ini: Path | None = None, spark_ini: Path | None = None) -> None:
    """Initialize both configurations, safely migrating older SPARK settings.

    An existing shared hysp.ini is retained except for removing a legacy
    SPARK section after successfully saving those settings to spark.ini.
    """
    root.mkdir(parents=True, exist_ok=True)
    for sub in ("hysp.in", "hysp.data/arl", "hysp.run", "hysp.out"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "hysp.in" / name_component(group, "group")).mkdir(exist_ok=True)
    ini = Path(ini) if ini is not None else root / "hysp.ini"
    spark_ini = Path(spark_ini) if spark_ini is not None else root / "spark.ini"

    # Older development releases accidentally placed hysp.ini in hysp.in/.
    # Relocate it rather than creating an unrelated second configuration.
    previous_ini = root / "hysp.in" / "hysp.ini"
    if ini == root / "hysp.ini" and not ini.exists() and previous_ini.is_file():
        previous_ini.rename(ini)
        print(f"MOVE   {previous_ini} -> {ini}")
    elif ini == root / "hysp.ini" and previous_ini.is_file():
        print(f"WARNING: obsolete {previous_ini} also exists; use {ini} as authoritative",
              file=sys.stderr)

    ini.parent.mkdir(parents=True, exist_ok=True)
    existed = ini.is_file()
    load_hysp_init()(ini)
    raw = json.loads(ini.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SparkError(f"Expected JSON object in {ini}")
    if not existed:
        raw["ARL_PATH"] = str((root / "hysp.data" / "arl").resolve())
        if hysplit:
            raw["HYSPLIT_PATH"] = str(Path(hysplit).expanduser().resolve())

    legacy_raw = raw.get("SPARK", {})
    if "SPARK" in raw and not isinstance(legacy_raw, dict):
        raise SparkError(f"Invalid legacy SPARK section in {ini}")
    legacy = normalize_legacy_spark(legacy_raw, ini)
    validate_spark_config(legacy, ini)

    spark_ini.parent.mkdir(parents=True, exist_ok=True)
    if spark_ini.is_file():
        existing_spark = read_config(spark_ini)
        merged = dict(existing_spark)
        conflicts: list[str] = []
        for key, value in legacy.items():
            if key in merged and merged[key] != value:
                if merged[key] == DEFAULT_SPARK[key]:
                    # A distributed example spark.ini has only defaults.
                    # Prefer existing customized legacy settings over defaults.
                    merged[key] = value
                elif value == DEFAULT_SPARK[key]:
                    # A default legacy key must not override a customized
                    # option in the current root-level spark.ini.
                    continue
                else:
                    conflicts.append(key)
            elif key not in merged:
                merged[key] = value
        if conflicts:
            raise SparkError(f"Conflicting legacy SPARK settings in {ini} and {spark_ini}: "
                             f"{', '.join(conflicts)}; reconcile before --init")
        if legacy:
            read_config_validate(merged, spark_ini)
            write_json_atomic(spark_ini, merged)
    else:
        initial = {**DEFAULT_SPARK, **legacy, "group": legacy.get("group", group)}
        write_json_atomic(spark_ini, initial)

    if "SPARK" in raw:
        del raw["SPARK"]
        write_json_atomic(ini, raw)
        print(f"MIGRATE SPARK defaults from {ini} to {spark_ini}")
    elif not existed:
        write_json_atomic(ini, raw)
    print(f"{'CREATE' if not existed else 'KEEP  '} {ini}")
    print(f"SPARK  {spark_ini}")
    print(f"SUPPLY {root / 'hysp.in' / group / 'CONTROL'} and SETUP.CFG")


def read_config_validate(data: Mapping[str, Any], path: Path) -> None:
    """Compatibility wrapper for validating migrated settings."""
    validate_spark_config(data, path)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SPARK: daily FINN HYSPLIT using CONTROL template duration and automatic ARL fallback")
    p.add_argument("start", nargs="?", type=parse_start,
                   help="UTC start YYYYMMDD[HH]; default is previous UTC day at 00")
    p.add_argument("end", nargs="?", type=parse_start,
                   help="optional inclusive end YYYYMMDD[HH], one run per day")
    p.add_argument("--hour", type=int, metavar="HH", help="starting hour 0..23 (for YYYYMMDD input)")
    p.add_argument("--duration", type=int, metavar="HOURS", help="override simulation duration; default from hysp.in/CONTROL")
    p.add_argument("--root", type=Path, help="project root; defaults to script's directory")
    p.add_argument("--ini", type=Path, help="shared HYSPLIT settings; defaults to root/hysp.ini")
    p.add_argument("--spark-ini", type=Path, help="SPARK defaults; defaults to root/spark.ini")
    p.add_argument("--init", action="store_true", help="initialize project now (normal runs also create missing ini files)")
    p.add_argument("--hysplit", help="HYSPLIT installation path (with --init)")
    p.add_argument("--group", help="run group; defaults from spark.ini")
    p.add_argument("--arl", nargs="+", help="override primary ARL dataset(s); fallback remains gfs0p25.f")
    p.add_argument("--forecast-cycle", choices=("00z", "latest"),
                   help="preferred GFS forecast cycle when archives are incomplete; default from spark.ini")
    p.add_argument("--emission-domain", help="named emission region or 'south,west,north,east' string")
    p.add_argument("--domain", dest="emission_domain", help=argparse.SUPPRESS)
    p.add_argument("--met-file", nargs="+", type=Path,
                   help="explicit ARL files; bypass automatic primary/fallback selection")
    p.add_argument("--cpu-mode", choices=("auto", "serial", "mpi"))
    p.add_argument("--mode", dest="cpu_mode", choices=("auto", "serial", "mpi"), help=argparse.SUPPRESS)
    p.add_argument("--cpu-n", type=int, help="number of MPI processes; default from hysp.ini")
    p.add_argument("--cpu", dest="cpu_n", type=int, help=argparse.SUPPRESS)
    p.add_argument("--renew", action="store_true", help="reprepare/rerun, backing up old cdump")
    p.add_argument("--renew-raw", action="store_true", help="refresh raw FINN data (requires --renew)")
    p.add_argument("--prepare-only", action="store_true")
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="print plan without modifying files or downloading")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--debug", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    try:
        root = resolve_root(args.root)
        ini = (root / args.ini).resolve() if args.ini else root / "hysp.ini"
        spark_ini = (root / args.spark_ini).resolve() if args.spark_ini else root / "spark.ini"
        if args.init:
            if args.start or args.end:
                raise SparkError("--init does not accept run dates")
            init_project(root, args.group or "NSFS", args.hysplit,
                         ini=Path(ini), spark_ini=Path(spark_ini))
            return 0
        if args.renew_raw and not args.renew:
            raise SparkError("--renew-raw requires --renew")
        if sum((args.prepare_only, args.check_only, args.status, args.dry_run)) > 1:
            raise SparkError("--prepare-only, --check-only, --status and --dry-run are mutually exclusive")
        # Normal startup also initializes missing root-level configurations.
        # Existing files are kept; hysp_init performs machine discovery only
        # on first creation, and all downstream routines get this exact ini.
        if not Path(ini).is_file() or not Path(spark_ini).is_file():
            group_hint = args.group
            if group_hint is None and Path(spark_ini).is_file():
                group_hint = read_config(Path(spark_ini))["group"]
            init_project(root, group_hint or "NSFS", None,
                         ini=Path(ini), spark_ini=Path(spark_ini))
        else:
            load_hysp_init()(ini)
        cfg = read_config(Path(spark_ini))
        for name in ("group", "emission_domain", "cpu_mode", "cpu_n"):
            value = getattr(args, name)
            if value is not None:
                cfg[name] = value
        if args.arl:
            cfg["analysis_arl"] = args.arl
        if args.forecast_cycle is not None:
            cfg["forecast_cycle"] = args.forecast_cycle
        cfg["group"] = name_component(cfg["group"], "group")
        cfg["analysis_arl"] = arl_names(cfg["analysis_arl"])
        cfg["forecast_arl"] = arl_names(cfg["forecast_arl"])
        cfg["cdump"] = name_component(cfg["cdump"], "cdump")
        cfg["logfile"] = name_component(cfg["logfile"], "logfile")
        validate_spark_config(cfg, Path(spark_ini))
        if args.duration is not None and args.duration <= 0:
            raise SparkError("--duration must be positive")
        if args.hour is not None and not (0 <= args.hour <= 23):
            raise SparkError("--hour must be between 0 and 23")
        met_file = ([str((root / p).resolve()) if not p.is_absolute() else str(p)
                     for p in args.met_file] if args.met_file else None)
        if args.hour is not None:
            for text_arg, value in (("start", args.start), ("end", args.end)):
                if value is not None and value.hour != 0:
                    raise SparkError(f"--hour conflicts with YYYYMMDDHH {text_arg}; use one")
        today = now_utc().replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        first = args.start or today - timedelta(days=1)
        last = args.end or first
        if args.hour is not None:
            first = first.replace(hour=args.hour)
            last = last.replace(hour=args.hour)
        elif args.end and args.start and args.start.hour and args.end.hour == 0:
            # YYYYMMDD YYYYMMDD -> same hour repeated for the date range.
            last = last.replace(hour=first.hour)
        for day in dates(first, last):
            if args.status:
                for candidate in dict.fromkeys([tuple(cfg["analysis_arl"]), tuple(cfg["forecast_arl"])]):
                    rd = run_dir(root, cfg, day, candidate)
                    record = load_status(rd / STATUS_FILE)
                    print(json.dumps(record or {"status": "unknown", "run_dir": str(rd)}, indent=2))
                continue
            try:
                result = run_one(root, cfg, day, ini=Path(ini), duration=args.duration,
                                 renew=args.renew, renew_raw=args.renew_raw,
                                 dry_run=args.dry_run, prepare_only=args.prepare_only,
                                 check_only=args.check_only, verbose=not args.quiet,
                                 met_file=met_file)
                print(f"{day:%Y%m%d%H} {result}")
            except Exception as exc:
                print(f"ERROR {day:%Y%m%d%H}: {exc}", file=sys.stderr)
                if args.debug:
                    traceback.print_exc()
                return 1
        return 0
    except (OSError, SparkError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
