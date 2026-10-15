#!/usr/bin/env python3
"""
fire_spread_emitimes.py

HYSPLIT EMITIMES writer for the "spread" fire-emission module.

Data flow:
    fire_spread.py
        GeoJSON fire-line snapshots -> hourly UTC 1-km activity grid

    fire_spread_emitimes.py
        hourly activity grid -> daily HYSPLIT EMITIMES

The default source parameters preserve the earlier fire-line workflow:

    RATE = 3E6 g/h  per active cell-hour
    AREA = 1E6 m2
    HEAT = 5E6 W
    HGT  = 1 m AGL
    DURATION = 0100

The numeric spread intensity is used only to determine whether a cell-hour
is active (>0); it is NOT multiplied into RATE or HEAT.
"""

from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timedelta
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .fire_spread import SpreadRecord, fire_spread, fire_spread_read
except ImportError:
    from fire_spread import SpreadRecord, fire_spread, fire_spread_read

try:
    from hysp.hysp_emitimes import EmitimesRecord, hysp_emitimes_write
except ImportError as exc:
    raise ImportError(
        "fire_spread_emitimes.py requires ~/lib/python/hysp/hysp_emitimes.py"
    ) from exc


DEFAULT_RATE_GPH = 3.0e6
DEFAULT_AREA_M2 = 1.0e6
DEFAULT_HEAT_W = 5.0e6
DEFAULT_HEIGHT_M = 1.0
DURATION = "0100"


def _parse_day(value: Any) -> datetime:
    if isinstance(value, datetime):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)

    if isinstance(value, Integral):
        s = str(int(value))
    elif isinstance(value, Real):
        if not float(value).is_integer():
            raise ValueError(f"Non-integer day: {value!r}")
        s = str(int(value))
    else:
        s = "".join(ch for ch in str(value) if ch.isdigit())

    if len(s) < 8:
        raise ValueError(f"Expected YYYYMMDD: {value!r}")
    return datetime.strptime(s[:8], "%Y%m%d")


def _domain_mask(
    records: Sequence[SpreadRecord],
    *,
    domain: str | None,
    minfo: Mapping[str, Any] | None,
    bbox: Sequence[float] | None,
    data_root: str | os.PathLike[str] | None,
) -> list[bool]:
    n = len(records)
    keep = [True] * n
    if n == 0:
        return keep

    lon = [x.lon for x in records]
    lat = [x.lat for x in records]

    if domain is not None or minfo is not None:
        try:
            from grdinfo import grdinfo_mask
        except ImportError as exc:
            raise ImportError(
                "Spread domain/minfo filtering requires ~/lib/python/grdinfo.py"
            ) from exc
        m = grdinfo_mask(
            lon,
            lat,
            domain=domain,
            minfo=minfo,
            data_root=data_root,
        )
        keep = [a and bool(b) for a, b in zip(keep, m)]

    if bbox is not None:
        if len(bbox) != 4:
            raise ValueError("bbox must be [south, west, north, east]")
        south, west, north, east = [float(x) for x in bbox]
        for i, (la, lo) in enumerate(zip(lat, lon)):
            lon_ok = west <= lo <= east if west <= east else (lo >= west or lo <= east)
            keep[i] = keep[i] and south <= la <= north and lon_ok

    return keep


def fire_spread_emitimes(
    time: Any,
    *,
    inputs: Sequence[str | os.PathLike[str]] | str | os.PathLike[str] | None = None,
    hourly_file: str | os.PathLike[str] | None = None,
    grid_m: float = 1000.0,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
    input_timezone: str = "Asia/Seoul",
    domain: str | None = None,
    minfo: Mapping[str, Any] | None = None,
    bbox: Sequence[float] | None = None,
    rate_gph: float = DEFAULT_RATE_GPH,
    area_m2: float = DEFAULT_AREA_M2,
    heat_w: float = DEFAULT_HEAT_W,
    height_m: float = DEFAULT_HEIGHT_M,
    renew: bool = False,
    odir: str | os.PathLike[str] = ".",
    ofile: str = "EMITIMES",
    nosave: bool = False,
    data_root: str | os.PathLike[str] | None = None,
    verbose: bool = True,
) -> list[EmitimesRecord]:
    """
    Create one daily EMITIMES file from spread GeoJSON/hourly activity.

    If hourly_file exists and renew=False, it is reused.  Otherwise inputs are
    converted to the hourly ASCII file first.
    """
    day = _parse_day(time)

    if hourly_file is None:
        # Standalone default; nsfs_prep supplies a shared experiment-level path.
        hourly = Path(odir).expanduser() / "spread_hourly.txt"
    else:
        hourly = Path(hourly_file).expanduser()

    if renew or not hourly.is_file():
        if inputs is None:
            raise ValueError(
                "Spread hourly file does not exist; provide inputs=... "
                "or --spread-input."
            )
        if verbose:
            print(f"SPREAD BUILD {hourly}")
        fire_spread(
            inputs,
            grid_m=grid_m,
            origin_x=origin_x,
            origin_y=origin_y,
            input_timezone=input_timezone,
            output=hourly,
            verbose=verbose,
        )
    else:
        if verbose:
            print(f"SPREAD READY {hourly}")

    rr = fire_spread_read(hourly)
    start = day
    end = day + timedelta(days=1)
    rr = [x for x in rr if start <= x.time < end and x.intensity > 0]

    if rr:
        keep = _domain_mask(
            rr,
            domain=domain,
            minfo=minfo,
            bbox=bbox,
            data_root=data_root,
        )
        rr = [x for x, ok in zip(rr, keep) if ok]

    records = [
        EmitimesRecord(
            time=x.time,
            duration=DURATION,
            lat=float(x.lat),
            lon=float(x.lon),
            hgt=float(height_m),
            rate=float(rate_gph),
            area=float(area_m2),
            heat=float(heat_w),
        )
        for x in rr
    ]

    if not records:
        if verbose:
            print(f"NO SPREAD EMISSION {day:%Y%m%d}")
        return []

    save = Path(odir).expanduser() / ofile
    if not nosave:
        hysp_emitimes_write(
            records,
            filename=save,
            group=[day, 24],
            record="RATE(g/h) AREA(m2) HEAT(W)",
            overwrite=True,
            verbose=verbose,
        )
        if verbose:
            print(f"SPREAD EMITIMES: {save}")

    return records


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Create HYSPLIT EMITIMES from fire spread.")
    p.add_argument("date", help="UTC YYYYMMDD")
    p.add_argument("--spread-input", nargs="+", default=None)
    p.add_argument("--hourly-file", default=None)
    p.add_argument("--grid-m", type=float, default=1000.0)
    p.add_argument("--origin-x", type=float, default=0.0)
    p.add_argument("--origin-y", type=float, default=0.0)
    p.add_argument("--input-timezone", default="Asia/Seoul")
    p.add_argument("--domain", default=None)
    p.add_argument("--bbox", default=None, help="south,west,north,east")
    p.add_argument("--rate-gph", type=float, default=DEFAULT_RATE_GPH)
    p.add_argument("--area-m2", type=float, default=DEFAULT_AREA_M2)
    p.add_argument("--heat-w", type=float, default=DEFAULT_HEAT_W)
    p.add_argument("--height-m", type=float, default=DEFAULT_HEIGHT_M)
    p.add_argument("--odir", default=".")
    p.add_argument("--ofile", default="EMITIMES")
    p.add_argument("--data-root", default=None)
    p.add_argument("--renew", action="store_true")
    p.add_argument("--nosave", action="store_true")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    bbox = [float(x) for x in args.bbox.split(",")] if args.bbox else None

    try:
        records = fire_spread_emitimes(
            args.date,
            inputs=args.spread_input,
            hourly_file=args.hourly_file,
            grid_m=args.grid_m,
            origin_x=args.origin_x,
            origin_y=args.origin_y,
            input_timezone=args.input_timezone,
            domain=args.domain,
            bbox=bbox,
            rate_gph=args.rate_gph,
            area_m2=args.area_m2,
            heat_w=args.heat_w,
            height_m=args.height_m,
            renew=args.renew,
            odir=args.odir,
            ofile=args.ofile,
            nosave=args.nosave,
            data_root=args.data_root,
            verbose=not args.quiet,
        )
        if not args.quiet:
            print(f"SPREAD EMITIMES RECORDS = {len(records)}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
