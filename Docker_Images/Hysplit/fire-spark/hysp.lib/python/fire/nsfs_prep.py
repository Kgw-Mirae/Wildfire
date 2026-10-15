#!/usr/bin/env python3
"""
nsfs_prep.py

Prepare NSFS/HYSPLIT run directories.  This module NEVER runs HYSPLIT.

Prepared in each run directory:
    CONTROL
    SETUP.CFG
    ASCDATA.CFG
    EMITIMES
    hycs_std  -> <HYSPLIT_PATH>/exec/hycs_std
    hycm_std  -> <HYSPLIT_PATH>/exec/hycm_std

Directory convention:
    <rdir>/<name>/<arl-emis>/<YYYY>/<YYYYMMDD>

The CONTROL file is updated with hysp.hysp_control.

Built-in fire-emission dispatch:
    emis='finn'    -> fire.fire_finn_nrt_emitimes
    emis='rave3'   -> fire.fire_rave_emitimes(name='3km')
    emis='rave13'  -> fire.fire_rave_emitimes(name='13km')

An explicit run['emitimes'] path/callback still overrides the built-in
emission handling.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from numbers import Integral, Real
from pathlib import Path
from typing import Any

try:
    from hysp.hysp_init import hysp_init
except ImportError:
    try:
        from .hysp_init import hysp_init  # type: ignore
    except ImportError:
        from hysp_init import hysp_init  # type: ignore

try:
    from hysp.hysp_control import hysp_control_update
except ImportError:
    try:
        from .hysp_control import hysp_control_update  # type: ignore
    except ImportError:
        from hysp_control import hysp_control_update  # type: ignore


# -----------------------------------------------------------------------------
# dates
# -----------------------------------------------------------------------------


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    if isinstance(value, Integral):
        text = str(int(value))
    elif isinstance(value, Real):
        if not float(value).is_integer():
            raise ValueError(f"Non-integer time value: {value}")
        text = str(int(value))
    else:
        text = str(value).strip()

    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 14:
        return datetime.strptime(digits[:14], "%Y%m%d%H%M%S")
    if len(digits) >= 12:
        return datetime.strptime(digits[:12], "%Y%m%d%H%M")
    if len(digits) >= 10:
        return datetime.strptime(digits[:10], "%Y%m%d%H")
    if len(digits) >= 8:
        return datetime.strptime(digits[:8], "%Y%m%d")

    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def daily(start: Any, end: Any | None = None) -> list[int]:
    """Inclusive YYYYMMDD list, similar to IDL date(...,/daily)."""
    d1 = _parse_time(start)
    d2 = _parse_time(end if end is not None else start)
    d1 = datetime(d1.year, d1.month, d1.day)
    d2 = datetime(d2.year, d2.month, d2.day)
    step = 1 if d2 >= d1 else -1

    out: list[int] = []
    d = d1
    while True:
        out.append(int(d.strftime("%Y%m%d")))
        if d == d2:
            break
        d += timedelta(days=step)
    return out


def _as_days(cday: Any | None) -> list[datetime]:
    if cday is None:
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return [today + timedelta(days=i) for i in range(-2, 3)]

    if isinstance(cday, (str, bytes, Integral, Real, datetime)):
        values = [cday]
    else:
        values = list(cday)

    out: list[datetime] = []
    for value in values:
        d = _parse_time(value)
        out.append(datetime(d.year, d.month, d.day))
    return out


# -----------------------------------------------------------------------------
# run-file helpers
# -----------------------------------------------------------------------------


def _norm_key(value: Any) -> str:
    return str(value).strip().lower().replace(" ", "_")


def _ini_value(opt: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    table = {_norm_key(k): v for k, v in opt.items()}
    for name in names:
        if _norm_key(name) in table:
            return table[_norm_key(name)]
    return default


def hysp_init_ascdata(
    odir: str | os.PathLike[str] = ".",
    *,
    ini: str | os.PathLike[str] = "hysp.ini",
    renew: bool = False,
    verbose: bool = True,
) -> Path:
    outdir = Path(odir)
    outdir.mkdir(parents=True, exist_ok=True)
    file = outdir / "ASCDATA.CFG"
    if file.exists() and not renew:
        return file

    opt = hysp_init(ini)
    hysplit_path = str(_ini_value(opt, "HYSPLIT_PATH", default="")).strip()
    if not hysplit_path:
        raise ValueError("HYSPLIT_PATH is empty in hysp.ini")

    bdy = str(Path(hysplit_path).expanduser() / "bdyfiles")
    if not bdy.endswith("/"):
        bdy += "/"

    lines = [
        "-90.0   -180.0  lat/lon of lower left corner",
        "1.0     1.0     lat/lon spacing in degrees",
        "180     360     lat/lon number of data points",
        "2               default land use category",
        "0.2             default roughness length (m)",
        f"'{bdy}'",
    ]
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if verbose:
        print(f"SAVE {file}")
    return file


def hysp_init_setup(
    *,
    sdir: str | os.PathLike[str],
    odir: str | os.PathLike[str],
    verbose: bool = True,
) -> Path:
    src = Path(sdir) / "SETUP.CFG"
    dst = Path(odir) / "SETUP.CFG"
    if not src.is_file():
        raise FileNotFoundError(f"NOFILE {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if verbose:
        print(f"COPY {src} -> {dst}")
    return dst


def hysp_init_exelink(
    files: str | Sequence[str] = ("hycs_std", "hycm_std"),
    *,
    rdir: str | os.PathLike[str] = ".",
    ini: str | os.PathLike[str] = "hysp.ini",
    quiet: bool = False,
) -> list[Path]:
    if isinstance(files, str):
        names = [files]
    else:
        names = list(files)

    opt = hysp_init(ini)
    hysplit_path = str(_ini_value(opt, "HYSPLIT_PATH", default="")).strip()
    if not hysplit_path:
        raise ValueError("HYSPLIT_PATH is empty in hysp.ini")

    run_dir = Path(rdir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []

    for name in names:
        src = Path(hysplit_path).expanduser() / "exec" / name
        dst = run_dir / name
        if not src.is_file():
            if not quiet:
                print(f"NOFILE {src}; NOLINK {run_dir}")
            continue

        if os.path.lexists(dst):
            if dst.is_dir() and not dst.is_symlink():
                raise IsADirectoryError(dst)
            dst.unlink()
        dst.symlink_to(src)
        out.append(dst)
        if not quiet:
            print(f"LINK {src} -> {dst}")

    return out


# -----------------------------------------------------------------------------
# EMITIMES
# -----------------------------------------------------------------------------


def _location_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        p = list(value)
        if len(p) < 2:
            raise ValueError(f"Invalid location: {value!r}")
        return f"{p[0]} {p[1]} {p[2] if len(p) >= 3 else 0}"
    raise TypeError(f"Invalid location: {value!r}")


def hysp_emitimes_locations(file: str | os.PathLike[str]) -> list[str]:
    """Return CONTROL source locations from EMITIMES emission records."""
    path = Path(file)
    if not path.is_file():
        raise FileNotFoundError(path)

    loc: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            p = line.split()
            # YYYY MM DD HH MM DURATION LAT LON HGT RATE AREA HEAT
            if len(p) < 12:
                continue
            try:
                int(p[0]); int(p[1]); int(p[2]); int(p[3]); int(p[4])
                float(p[6]); float(p[7])
            except ValueError:
                continue
            # Match the current IDL nsfs_prep: force CONTROL source height = 0.
            loc.append(f"{p[6]} {p[7]} 0")
    return loc


def _format_emitimes_path(value: str | os.PathLike[str], day: datetime, emis: str) -> Path:
    path = Path(
        str(value).format(
            date=day.strftime("%Y%m%d"),
            yyyy=day.strftime("%Y"),
            mm=day.strftime("%m"),
            dd=day.strftime("%d"),
            emis=emis,
        )
    ).expanduser()

    if path.is_dir():
        candidates = [
            path / day.strftime("%Y") / day.strftime("%Y%m%d") / "EMITIMES",
            path / day.strftime("%Y%m%d") / "EMITIMES",
            path / f"EMITIMES.{day:%Y%m%d}",
            path / f"{day:%Y%m%d}_EMITIMES",
            path / "EMITIMES",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
    return path


def _legacy_emitimes_builder() -> Callable[..., Any] | None:
    """Optional fallback for fire inventories not yet ported to Python."""
    try:
        from hysp.hysp_emitimes_fire import hysp_emitimes_fire  # type: ignore
        return hysp_emitimes_fire
    except ImportError:
        try:
            from hysp_emitimes_fire import hysp_emitimes_fire  # type: ignore
            return hysp_emitimes_fire
        except ImportError:
            return None


def _build_fire_emitimes(
    run: Mapping[str, Any],
    day: datetime,
    rdir: Path,
    *,
    renew: bool,
    verbose: bool,
) -> Any:
    """
    Generate EMITIMES using the inventory-specific Python routine.

    Built-in names match the current IDL hysp_emitimes_fire.pro convention:
        finn
        rave3   -> RAVE 3 km
        rave13  -> RAVE 13 km
    """
    emis = str(run.get("emis", "")).strip().lower()
    cday = int(day.strftime("%Y%m%d"))

    common = dict(
        domain=run.get("domain"),
        minfo=run.get("minfo"),
        bbox=run.get("bbox"),
        renew=renew,
        renew_raw=bool(run.get("renew_raw", False)),
        odir=rdir,
        ofile="EMITIMES",
        data_root=run.get("data_root"),
        verbose=verbose,
    )

    if emis == "finn":
        try:
            from fire.fire_finn_nrt_emitimes import fire_finn_nrt_emitimes
        except ImportError as exc:
            raise ImportError(
                "emis='finn' requires "
                "~/lib/python/fire/fire_finn_nrt_emitimes.py"
            ) from exc

        return fire_finn_nrt_emitimes(cday, **common)

    rave_name = {
        "rave": "3km",
        "rave3": "3km",
        "rave13": "13km",
    }.get(emis)

    if rave_name is not None:
        try:
            from fire.fire_rave_emitimes import fire_rave_emitimes
        except ImportError as exc:
            raise ImportError(
                f"emis={emis!r} requires "
                "~/lib/python/fire/fire_rave_emitimes.py"
            ) from exc

        return fire_rave_emitimes(
            cday,
            name=rave_name,
            version=str(run.get("rave_version", "v2r0")),
            scaled=bool(run.get("rave_scaled", True)),
            **common,
        )

    # Keep the old extension path for GBBEPx, BlueSky, AHI, etc.
    builder = _legacy_emitimes_builder()
    if builder is not None:
        return builder(
            emis,
            tflag=cday,
            domain=run.get("domain"),
            minfo=run.get("minfo"),
            bbox=run.get("bbox"),
            gadm=run.get("gadm"),
            odir=rdir,
            data_root=run.get("data_root"),
            renew=renew,
            verbose=verbose,
        )

    raise ValueError(
        f"No Python EMITIMES handler is available for emis={emis!r}. "
        "Built in: finn, rave3, rave13. "
        "Alternatively provide run['emitimes'] as a file/template or callback."
    )


def _prepare_emitimes(
    run: Mapping[str, Any],
    day: datetime,
    rdir: Path,
    *,
    renew: bool,
    verbose: bool,
) -> list[str]:
    target = rdir / "EMITIMES"

    if target.is_file() and not renew:
        if run.get("locations") is not None:
            return [_location_text(x) for x in run["locations"]]
        return hysp_emitimes_locations(target)

    # /renew means rebuild the emission file.  Remove an old EMITIMES first
    # so a no-emission day can never accidentally reuse a stale file.
    if renew and target.exists():
        target.unlink()

    source = run.get("emitimes")
    result: Any = None

    if callable(source):
        result = source(
            emis=str(run.get("emis", "")),
            cday=int(day.strftime("%Y%m%d")),
            domain=run.get("domain"),
            odir=rdir,
            run=run,
        )
    elif source is not None:
        src = _format_emitimes_path(source, day, str(run.get("emis", "")))
        if not src.is_file():
            raise FileNotFoundError(f"NO EMITIMES {src}")
        if src.resolve() != target.resolve():
            shutil.copy2(src, target)
        if verbose:
            print(f"EMITIMES {src} -> {target}")
    else:
        result = _build_fire_emitimes(
            run,
            day,
            rdir,
            renew=renew,
            verbose=verbose,
        )

    if isinstance(result, (str, os.PathLike)):
        result_path = Path(result).expanduser()
        if result_path.is_file():
            if result_path.resolve() != target.resolve():
                shutil.copy2(result_path, target)
        else:
            result = [result]

    if not target.is_file():
        # Inventory-specific builders return an empty sequence when the input
        # data exist but there are no emissions in the requested domain/day.
        # This is a normal no-emission case, not a file-generation failure.
        if (
            isinstance(result, Sequence)
            and not isinstance(result, (str, bytes, bytearray))
            and len(result) == 0
        ):
            return []

        raise FileNotFoundError(
            f"EMITIMES was not created for {day:%Y%m%d}. "
            "Check the emission handler or an explicit run['emitimes'] source."
        )

    if run.get("locations") is not None:
        return [_location_text(x) for x in run["locations"]]

    if isinstance(result, Sequence) and not isinstance(result, (str, bytes, bytearray)):
        try:
            loc = [_location_text(x) for x in result]
            if loc:
                return loc
        except (TypeError, ValueError):
            pass

    return hysp_emitimes_locations(target)


# -----------------------------------------------------------------------------
# nsfs_prep
# -----------------------------------------------------------------------------


def _arl_names(value: str | Sequence[str]) -> list[str]:
    if isinstance(value, str):
        return [x.lower() for x in value.split() if x.strip()]
    out: list[str] = []
    for item in value:
        out.extend(_arl_names(str(item)))
    return out


def nsfs_prep1(
    run: Mapping[str, Any],
    *,
    cday: Any | None = None,
    renew: bool = False,
    ini: str | os.PathLike[str] = "hysp.ini",
    verbose: bool = True,
    **extra: Any,
) -> list[str]:
    """Prepare one NSFS experiment. HYSPLIT is never executed here."""
    cfg: dict[str, Any] = {"sdir": "hysp.in", "rdir": "hysp.run"}
    cfg.update(dict(run))
    cfg.update(extra)

    for required in ("name", "arl", "emis"):
        if required not in cfg:
            raise KeyError(f"Missing run option: {required}")

    arl = _arl_names(cfg["arl"])
    if not arl:
        raise ValueError("arl is empty")
    cfg["arl"] = arl

    name = str(cfg["name"])
    emis = str(cfg["emis"]).strip().lower()
    cfg["emis"] = emis
    rname = "-".join(arl + [emis])
    sdir = Path(cfg["sdir"]).expanduser() / name
    root = Path(cfg["rdir"]).expanduser()
    days = _as_days(cday)

    if verbose:
        print(f"NAME  = {name}")
        print(f"ARL   = {arl}")
        print(f"EMIS  = {emis}")
        print(f"RNAME = {rname}")
        print(f"SDIR  = {sdir}")
        print("CDAY  =", [int(x.strftime("%Y%m%d")) for x in days])

    out: list[str] = []

    for day in days:
        date8 = day.strftime("%Y%m%d")
        rdir = root / name / rname / day.strftime("%Y") / date8
        rdir.mkdir(parents=True, exist_ok=True)
        out.append(str(rdir))

        # Refresh executable links, but DO NOT execute them.
        hysp_init_exelink(
            ("hycs_std", "hycm_std"),
            rdir=rdir,
            ini=ini,
            quiet=not verbose,
        )

        ready = all(
            (rdir / filename).is_file()
            for filename in ("CONTROL", "SETUP.CFG", "ASCDATA.CFG", "EMITIMES")
        )
        if ready and not renew:
            if verbose:
                print(f"EXISTS {rdir}")
            continue

        try:
            loc = _prepare_emitimes(cfg, day, rdir, renew=renew, verbose=verbose)
        except FileNotFoundError as exc:
            if cfg.get("skip_no_emission", False):
                if verbose:
                    print(f"SKIP MISSING INPUT {emis} {date8}: {exc}")
                continue
            raise

        if not loc:
            if cfg.get("skip_no_emission", True):
                if verbose:
                    print(f"NO EMISSION {emis} {date8}")
                continue
            raise ValueError(f"No source locations in {rdir / 'EMITIMES'}")

        hysp_init_ascdata(rdir, ini=ini, renew=renew, verbose=verbose)
        hysp_init_setup(sdir=sdir, odir=rdir, verbose=verbose)

        hysp_control_update(
            sdir,
            rdir,
            location=loc,
            stime=day.strftime("%Y%m%d") + "00",
            arl=arl,
            met_file=cfg.get("met_file"),
            update=cfg.get("control_update"),
            run_time=cfg.get("run_time"),
            top_of_model=cfg.get("top_of_model"),
            vertical_motion=cfg.get("vertical_motion"),
            ini=ini,
            verbose=verbose,
        )

        if verbose:
            print(f"PREPARED {rdir}")

    return out


def nsfs_prep(
    rlist: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    cday: Any | None = None,
    renew: bool = False,
    ini: str | os.PathLike[str] = "hysp.ini",
    verbose: bool = True,
    **extra: Any,
) -> list[str]:
    """Prepare one or more NSFS experiments. HYSPLIT is never executed."""
    runs = [rlist] if isinstance(rlist, Mapping) else list(rlist)
    out: list[str] = []
    for run in runs:
        out.extend(
            nsfs_prep1(
                run,
                cday=cday,
                renew=renew,
                ini=ini,
                verbose=verbose,
                **extra,
            )
        )
    return out


# -----------------------------------------------------------------------------
# command line
# -----------------------------------------------------------------------------


def _json_update(value: str | None) -> Any:
    if value is None:
        return None
    path = Path(value).expanduser()
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare NSFS/HYSPLIT files and links; never run HYSPLIT."
    )
    parser.add_argument("start", help="start day YYYYMMDD")
    parser.add_argument("end", nargs="?", help="end day YYYYMMDD; default=start")
    parser.add_argument("--name", required=True, help="e.g. NSFS-2025kr")
    parser.add_argument("--arl", nargs="+", required=True, help="e.g. gfs0p25")
    parser.add_argument("--emis", required=True)
    parser.add_argument("--domain", default=None)
    parser.add_argument("--data-root", default=None)
    parser.add_argument(
        "--renew-raw",
        action="store_true",
        help="refresh raw FINN/RAVE data when rebuilding EMITIMES",
    )
    parser.add_argument(
        "--rave-version",
        default="v2r0",
        help="RAVE version for rave3/rave13; default=v2r0",
    )
    parser.add_argument(
        "--rave-unscaled",
        action="store_true",
        help="use RAVE PM25 instead of default PM25_scaled",
    )
    parser.add_argument("--sdir", default="hysp.in")
    parser.add_argument("--rdir", default="hysp.run")
    parser.add_argument(
        "--emitimes",
        default=None,
        help="path/template; supports {date}, {yyyy}, {mm}, {dd}, {emis}",
    )
    parser.add_argument("--met-file", nargs="*", default=None)
    parser.add_argument("--run-time", type=int, default=None)
    parser.add_argument("--top-of-model", default=None)
    parser.add_argument("--vertical-motion", default=None)
    parser.add_argument(
        "--control-update",
        default=None,
        help="JSON string or JSON file for hysp_control_update2-style changes",
    )
    parser.add_argument("--ini", default="hysp.ini")
    parser.add_argument("--renew", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    run: dict[str, Any] = {
        "name": args.name,
        "arl": [x.lower() for x in args.arl],
        "emis": args.emis,
        "domain": args.domain,
        "data_root": args.data_root,
        "renew_raw": args.renew_raw,
        "rave_version": args.rave_version,
        "rave_scaled": not args.rave_unscaled,
        "sdir": args.sdir,
        "rdir": args.rdir,
        "emitimes": args.emitimes,
        "met_file": args.met_file,
        "run_time": args.run_time,
        "top_of_model": args.top_of_model,
        "vertical_motion": args.vertical_motion,
        "control_update": _json_update(args.control_update),
    }

    dirs = nsfs_prep(
        run,
        cday=daily(args.start, args.end or args.start),
        renew=args.renew,
        ini=args.ini,
        verbose=not args.quiet,
    )

    if args.quiet:
        for d in dirs:
            print(d)


if __name__ == "__main__":
    main()
