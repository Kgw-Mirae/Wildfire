#!/usr/bin/env python3
"""
fire_rave_emitimes.py

Python counterpart of the EMITIMES portion of the current IDL
rd_firepm_rave.pro.

RAVE -> HYSPLIT conversion follows the latest IDL routine:

    PM25_scaled * 1e3  -> RATE [g/h]   (default)
    PM25        * 1e3  -> RATE [g/h]   (--unscaled)
    FRP_MEAN    * 1e6  -> FRP/heat [W]
    AREA                 = 1 m2
    source height        = 1 m
    duration             = 0100

Typical use:

    python fire_rave_emitimes.py 20260725 --domain nca12 --odir ./20260725

Python:

    from fire.fire_rave_emitimes import fire_rave_emitimes

    out = fire_rave_emitimes(
        20260725,
        name="3km",
        domain="nca12",
        odir="./20260725",
    )
"""

from __future__ import annotations

import argparse
import os
from datetime import date, datetime
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

try:
    from .fire_rave import fire_rave
except ImportError:
    from fire_rave import fire_rave

try:
    from hysp.hysp_emitimes import EmitimesRecord, hysp_emitimes_write
except ImportError as exc:
    raise ImportError(
        "fire_rave_emitimes.py requires ~/lib/python/hysp/hysp_emitimes.py "
        "and the hysp directory must be a Python package."
    ) from exc


PM_TO_GH = 1.0e3
FRP_MW_TO_W = 1.0e6
DURATION = "0100"
SOURCE_HEIGHT_M = 1.0
SOURCE_AREA_M2 = 1.0


def _to_datetime(value: np.datetime64 | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    s = np.datetime_as_string(np.datetime64(value, "m"), unit="m")
    return datetime.strptime(s, "%Y-%m-%dT%H:%M")


def _group_start(time: Any, records: Sequence[EmitimesRecord]) -> datetime:
    if not records:
        raise ValueError("No RAVE records")

    # IDL uses group=list(time,24).  For a scalar day/hour input preserve that
    # start; for broader/list input use the earliest actual record.
    if isinstance(time, (str, bytes, Integral, Real, datetime, date)):
        if isinstance(time, datetime):
            return time.replace(tzinfo=None)
        if isinstance(time, date):
            return datetime(time.year, time.month, time.day)

        digits = "".join(ch for ch in str(time) if ch.isdigit())
        if len(digits) == 8:
            return datetime.strptime(digits, "%Y%m%d")
        if len(digits) == 10:
            return datetime.strptime(digits, "%Y%m%d%H")
        if len(digits) == 12:
            return datetime.strptime(digits, "%Y%m%d%H%M")

    return min(x.time for x in records)


def fire_rave_emitimes(
    time: Any,
    *,
    name: str = "3km",
    version: str = "v2r0",
    domain: str | None = None,
    minfo: Mapping[str, Any] | None = None,
    bbox: Sequence[float] | None = None,
    scaled: bool = True,
    renew: bool = False,
    renew_raw: bool = False,
    odir: str | os.PathLike[str] = ".",
    ofile: str = "EMITIMES",
    nosave: bool = False,
    data_root: str | os.PathLike[str] | None = None,
    verbose: bool = True,
) -> list[EmitimesRecord]:
    """
    Create HYSPLIT EMITIMES records from RAVE.

    scaled=True matches the IDL default and uses PM25_scaled.
    """
    rr = fire_rave(
        time,
        name=name,
        version=version,
        domain=domain,
        minfo=minfo,
        bbox=bbox,
        renew=renew,
        renew_raw=renew_raw,
        data_root=data_root,
        verbose=verbose,
    )

    if not rr or len(np.asarray(rr.get("LON", []))) == 0:
        if verbose:
            print("NO RAVE EMISSION")
        return []

    lat = np.asarray(rr["LAT"], dtype=float)
    lon = np.asarray(rr["LON"], dtype=float)
    pm = np.asarray(rr["PMS" if scaled else "PM"], dtype=float)
    frp = np.asarray(rr["FRP"], dtype=float)
    utc = np.asarray(rr["UTC"]).astype("datetime64[m]")

    good = (
        np.isfinite(lat)
        & np.isfinite(lon)
        & np.isfinite(pm)
        & np.isfinite(frp)
    )

    records: list[EmitimesRecord] = []
    for t, la, lo, em, fp in zip(
        utc[good], lat[good], lon[good], pm[good], frp[good]
    ):
        records.append(
            EmitimesRecord(
                time=_to_datetime(t),
                duration=DURATION,
                lat=float(la),
                lon=float(lo),
                hgt=SOURCE_HEIGHT_M,
                rate=float(em) * PM_TO_GH,
                area=SOURCE_AREA_M2,
                heat=float(fp) * FRP_MW_TO_W,
            )
        )

    if not records:
        if verbose:
            print("NO RAVE EMISSION")
        return []

    save = Path(odir).expanduser() / ofile

    if not nosave:
        hysp_emitimes_write(
            records,
            filename=save,
            group=[_group_start(time, records), 24],
            record="RATE(g/h) AREA(m2) FRP(W)",
            overwrite=True,
            verbose=verbose,
        )

        if verbose:
            print(f"EMITIMES: {save}")

    return records


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Create HYSPLIT EMITIMES from NOAA RAVE")
    p.add_argument("time", help="normally YYYYMMDD; YYYYMMDDHH is also supported")
    p.add_argument("--name", default="3km", choices=("3km", "13km"))
    p.add_argument("--version", default="v2r0")
    p.add_argument("--domain", default=None)
    p.add_argument("--bbox", default=None, help="south,west,north,east")
    p.add_argument("--odir", default=".")
    p.add_argument("--ofile", default="EMITIMES")
    p.add_argument("--data-root", default=None)
    p.add_argument(
        "--unscaled",
        action="store_true",
        help="use PM25 instead of default PM25_scaled",
    )
    p.add_argument("--renew", action="store_true", help="rebuild daily RAVE NPZ")
    p.add_argument(
        "--renew-raw",
        action="store_true",
        help="also refresh raw NOAA RAVE NetCDF",
    )
    p.add_argument("--nosave", action="store_true")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    bbox = None
    if args.bbox:
        bbox = [float(x) for x in args.bbox.split(",")]

    try:
        rr = fire_rave_emitimes(
            args.time,
            name=args.name,
            version=args.version,
            domain=args.domain,
            bbox=bbox,
            scaled=not args.unscaled,
            renew=args.renew,
            renew_raw=args.renew_raw,
            odir=args.odir,
            ofile=args.ofile,
            nosave=args.nosave,
            data_root=args.data_root,
            verbose=not args.quiet,
        )
        if not args.quiet:
            print(f"RAVE EMITIMES RECORDS = {len(rr)}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
