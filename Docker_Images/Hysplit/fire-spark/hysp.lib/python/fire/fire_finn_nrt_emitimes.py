#!/usr/bin/env python3
"""
fire_finn_nrt_emitimes.py

Create a HYSPLIT EMITIMES file from FINN NRT dayfiles.

This routine is intentionally separate from fire_finn_nrt.py:

    fire_finn_nrt.py
        raw FINN -> daily dayfile -> FINN data reader

    fire_finn_nrt_emitimes.py
        FINN NRT data -> HYSPLIT EMITIMES

The conversion follows the user's IDL FINN/HYSPLIT workflow:

    PM2.5 [kg/day] * 1000 / 24  -> RATE [g/h]
    FRP   [MW]     * 1e6        -> HEAT [W]
    AREA                          -> AREA [m2]
    source height                 -> 0 m
    duration                      -> 2400 (24 h)

Typical command-line use:

    python fire_finn_nrt_emitimes.py 20260725 --domain nca12 --odir ./20260725

Python use:

    from fire_finn_nrt_emitimes import fire_finn_nrt_emitimes

    rr = fire_finn_nrt_emitimes(
        20260725,
        domain="nca12",
        odir="./20260725",
    )
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

try:
    from .fire_finn_nrt import fire_finn_nrt
except ImportError:
    from fire_finn_nrt import fire_finn_nrt

try:
    from hysp.hysp_emitimes import EmitimesRecord, hysp_emitimes_write
except ImportError as exc:
    raise ImportError(
        "fire_finn_nrt_emitimes.py requires "
        "~/lib/python/hysp/hysp_emitimes.py"
    ) from exc


PM25_KGDAY_TO_GH = 1.0e3 / 24.0
FRP_MW_TO_W = 1.0e6
DURATION = "2400"
SOURCE_HEIGHT_M = 0.0


def _parse_day(value: Any) -> datetime:
    """Convert a YYYYMMDD-like value to a day-resolution datetime."""
    if isinstance(value, datetime):
        return datetime(value.year, value.month, value.day)

    if isinstance(value, Integral):
        text = str(int(value))
    elif isinstance(value, Real):
        if not float(value).is_integer():
            raise ValueError(f"Non-integer day: {value}")
        text = str(int(value))
    else:
        text = str(value).strip()

    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) != 8:
        raise ValueError(
            f"fire_finn_nrt_emitimes requires YYYYMMDD daily input; got {value!r}"
        )
    return datetime.strptime(digits, "%Y%m%d")


def _as_days(value: Any) -> list[datetime]:
    if isinstance(value, (str, bytes, Integral, Real, datetime)):
        vals = [value]
    else:
        vals = list(value)
    return [_parse_day(x) for x in vals]


def _required_array(data: Mapping[str, Any], name: str) -> np.ndarray:
    if name not in data:
        raise KeyError(
            f"FINN dayfile does not contain {name!r}. "
            f"Available fields: {', '.join(data.keys())}"
        )
    return np.asarray(data[name], dtype=float)


def fire_finn_nrt_emitimes(
    cday: Any,
    *,
    domain: str | Mapping[str, Any] | None = None,
    minfo: Mapping[str, Any] | None = None,
    bbox: Sequence[float] | str | None = None,
    renew: bool = False,
    renew_raw: bool = False,
    odir: str | os.PathLike[str] = ".",
    ofile: str = "EMITIMES",
    data_root: str | os.PathLike[str] | None = None,
    verbose: bool = True,
) -> list[EmitimesRecord]:
    """
    Create HYSPLIT EMITIMES from one or more FINN NRT daily dayfiles.

    Parameters
    ----------
    cday
        YYYYMMDD or an iterable of YYYYMMDD values.
    domain, minfo, bbox
        Geographic filtering passed directly to fire_finn_nrt().
    renew
        Rebuild the FINN daily dayfile(s) before reading.
    renew_raw
        Also refresh the raw FINN download when rebuilding dayfiles.
    odir
        Output directory.
    ofile
        EMITIMES filename, default ``EMITIMES``.
    data_root
        FINN data root passed to fire_finn_nrt().

    Returns
    -------
    list[EmitimesRecord]
        Records written to the EMITIMES file.
    """
    days = _as_days(cday)
    if not days:
        return []

    records: list[EmitimesRecord] = []

    for day in days:
        day_int = int(day.strftime("%Y%m%d"))

        # Read through fire_finn_nrt so the normal raw -> dayfile -> read
        # workflow remains centralized in fire_finn_nrt.py.
        data = fire_finn_nrt(
            day_int,
            domain=domain,
            minfo=minfo,
            bbox=bbox,
            extract=True,
            renew=renew,
            renew_raw=renew_raw,
            data_root=data_root,
            verbose=verbose,
        )

        if not isinstance(data, dict):
            raise TypeError(
                f"Unexpected fire_finn_nrt result for {day_int}: {type(data).__name__}"
            )
        if not data:
            if verbose:
                print(f"NO FINN EMISSION {day_int}")
            continue

        lat = _required_array(data, "LAT")
        lon = _required_array(data, "LON")
        area = _required_array(data, "AREA")
        pm25 = _required_array(data, "PM25")
        frp = _required_array(data, "FRP")

        n = len(lat)
        if not all(len(x) == n for x in (lon, area, pm25, frp)):
            raise ValueError(f"Inconsistent FINN array lengths for {day_int}")

        good = (
            np.isfinite(lat)
            & np.isfinite(lon)
            & np.isfinite(area)
            & np.isfinite(pm25)
            & np.isfinite(frp)
        )

        for la, lo, ar, pm, fp in zip(
            lat[good], lon[good], area[good], pm25[good], frp[good]
        ):
            records.append(
                EmitimesRecord(
                    time=day,
                    duration=DURATION,
                    lat=float(la),
                    lon=float(lo),
                    hgt=SOURCE_HEIGHT_M,
                    rate=float(pm) * PM25_KGDAY_TO_GH,
                    area=float(ar),
                    heat=float(fp) * FRP_MW_TO_W,
                )
            )

    if not records:
        if verbose:
            print("NO FINN EMISSION")
        return []

    out = Path(odir).expanduser() / ofile

    # Same basic grouping concept as the IDL routine.  For one daily run this
    # is exactly 24 h.  If several daily inputs are supplied, span the whole
    # interval from the first day through the end of the last day.
    first_day = min(days)
    last_day = max(days)
    group_hours = int((last_day - first_day).total_seconds() / 3600.0) + 24

    hysp_emitimes_write(
        records,
        filename=out,
        group=[first_day, group_hours],
        record="RATE(g/h) AREA(m2) FRP(W)",
        overwrite=True,
        verbose=verbose,
    )

    if verbose:
        total_rate = sum(x.rate for x in records)
        print(f"EMITIMES: PM2.5 in [g/h] TOTAL = {total_rate:.6g}")
        print(f"EMITIMES: {out}")

    return records


def _daily_range(start: Any, end: Any) -> list[int]:
    d0 = _parse_day(start)
    d1 = _parse_day(end)
    if d1 < d0:
        raise ValueError("--end must be on or after the start date")
    out: list[int] = []
    d = d0
    while d <= d1:
        out.append(int(d.strftime("%Y%m%d")))
        d += timedelta(days=1)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Create HYSPLIT EMITIMES from FINN NRT dayfiles"
    )
    p.add_argument("date", help="YYYYMMDD")
    p.add_argument("--end", default=None, help="optional ending YYYYMMDD")
    p.add_argument("--domain", default=None)
    p.add_argument("--bbox", default=None, help="south,west,north,east")
    p.add_argument("--odir", default=".")
    p.add_argument("--ofile", default="EMITIMES")
    p.add_argument("--data-root", default=None)
    p.add_argument("--renew", action="store_true", help="rebuild FINN dayfile")
    p.add_argument(
        "--renew-raw",
        action="store_true",
        help="also refresh raw FINN download",
    )
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    try:
        cday: Any = (
            _daily_range(args.date, args.end) if args.end is not None else args.date
        )
        rr = fire_finn_nrt_emitimes(
            cday,
            domain=args.domain,
            bbox=args.bbox,
            renew=args.renew,
            renew_raw=args.renew_raw,
            odir=args.odir,
            ofile=args.ofile,
            data_root=args.data_root,
            verbose=not args.quiet,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"records={len(rr)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
