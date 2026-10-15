#!/usr/bin/env python3
"""
fire_rave.py

Python counterpart of the current IDL rd_rave_noaa.pro.

Workflow:

    fire_rave_dn.py
        -> raw NOAA RAVE NetCDF files

    fire_rave_d1()
        -> read all hourly files for one day
        -> save Python daily intermediate file

    fire_rave()
        -> read daily intermediate file(s)
        -> select requested time(s)
        -> optional grdinfo domain/minfo filtering

IDL-compatible directory layout:

    raw:
      ~/data/fire-rave/raw/3km-v2r0/YYYY/YYYYMMDD/

    daily:
      ~/data/fire-rave/daily/3km/YYYY/rave.3km.YYYYMMDD.npz

Daily fields correspond to the IDL structure:

    LON, LAT, PM, PMS, FRP, FRE, AREA, UTC

where PM is PM25 and PMS is PM25_scaled.
"""

from __future__ import annotations

import argparse
import calendar
import os
import re
from datetime import date, datetime, timedelta
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

try:
    from .fire_rave_dn import fire_rave_dn
except ImportError:
    from fire_rave_dn import fire_rave_dn


VALID_NAMES = ("3km", "13km")
DEFAULT_VERSION = "v2r0"
FIELDS = ("LON", "LAT", "PM", "PMS", "FRP", "FRE", "AREA", "UTC")


# -----------------------------------------------------------------------------
# Time handling
# -----------------------------------------------------------------------------

def _digits(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d%H%M")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, Real):
        if not float(value).is_integer():
            raise ValueError(f"Non-integer RAVE time: {value!r}")
        return str(int(value))
    return "".join(ch for ch in str(value).strip() if ch.isdigit())


def _as_values(value: Any) -> list[Any]:
    if isinstance(value, (str, bytes, Integral, Real, datetime, date, np.datetime64)):
        return [value]
    return list(value)


def _datetime_from_value(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, np.datetime64):
        # minute precision is sufficient for RAVE.
        return datetime.strptime(
            np.datetime_as_string(value.astype("datetime64[m]"), unit="m"),
            "%Y-%m-%dT%H:%M",
        )

    s = _digits(value)
    fmts = {
        4: "%Y",
        6: "%Y%m",
        8: "%Y%m%d",
        10: "%Y%m%d%H",
        12: "%Y%m%d%H%M",
    }
    if len(s) not in fmts:
        raise ValueError(
            f"RAVE time must be YYYY, YYYYMM, YYYYMMDD, YYYYMMDDHH, "
            f"or YYYYMMDDHHMM: {value!r}"
        )
    return datetime.strptime(s, fmts[len(s)])


def _granularity(value: Any) -> int:
    if isinstance(value, np.datetime64):
        return 12
    if isinstance(value, datetime):
        return 12 if value.minute else 10
    if isinstance(value, date):
        return 8
    n = len(_digits(value))
    if n not in (4, 6, 8, 10, 12):
        raise ValueError(f"Unsupported RAVE time: {value!r}")
    return n


def _days_for_request(value: Any) -> list[datetime]:
    values = _as_values(value)
    out: list[datetime] = []
    seen: set[str] = set()

    for v in values:
        n = _granularity(v)
        dt = _datetime_from_value(v)

        days: list[datetime]
        if n == 4:
            d = datetime(dt.year, 1, 1)
            end = datetime(dt.year + 1, 1, 1)
            days = []
            while d < end:
                days.append(d)
                d += timedelta(days=1)
        elif n == 6:
            nd = calendar.monthrange(dt.year, dt.month)[1]
            days = [datetime(dt.year, dt.month, d) for d in range(1, nd + 1)]
        else:
            days = [datetime(dt.year, dt.month, dt.day)]

        for d in days:
            key = d.strftime("%Y%m%d")
            if key not in seen:
                seen.add(key)
                out.append(d)

    return out


# -----------------------------------------------------------------------------
# Paths / NPZ dayfile
# -----------------------------------------------------------------------------

def _data_root(data_root: str | os.PathLike[str] | None = None) -> Path:
    if data_root is not None:
        return Path(data_root).expanduser()
    env = os.environ.get("DATA_PATH") or os.environ.get("BLUTOUCH_DATA")
    return Path(env).expanduser() if env else Path("~/data").expanduser()


def _dayfile(
    day: datetime,
    *,
    name: str = "3km",
    data_root: str | os.PathLike[str] | None = None,
) -> Path:
    # Mirrors:
    # path_chk(data_path(),'fire-rave','daily',name,YYYY)
    # file_save('rave',name,cday)
    return (
        _data_root(data_root)
        / "fire-rave"
        / "daily"
        / name
        / day.strftime("%Y")
        / f"rave.{name}.{day:%Y%m%d}.npz"
    )


def _save_dayfile(path: Path, data: Mapping[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as f:
        np.savez_compressed(f, **{k.upper(): np.asarray(v) for k, v in data.items()})
    tmp.replace(path)


def _read_dayfile(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as z:
        return {k.upper(): np.asarray(z[k]) for k in z.files}


def _empty() -> dict[str, np.ndarray]:
    return {
        "LON": np.array([], dtype=float),
        "LAT": np.array([], dtype=float),
        "PM": np.array([], dtype=float),
        "PMS": np.array([], dtype=float),
        "FRP": np.array([], dtype=float),
        "FRE": np.array([], dtype=float),
        "AREA": np.array([], dtype=float),
        "UTC": np.array([], dtype="datetime64[m]"),
    }


def _concat(items: Sequence[Mapping[str, np.ndarray]]) -> dict[str, np.ndarray]:
    good = [x for x in items if x and len(np.asarray(x.get("LON", []))) > 0]
    if not good:
        return _empty()

    out: dict[str, np.ndarray] = {}
    for key in FIELDS:
        arrs = [np.asarray(x[key]) for x in good if key in x]
        if not arrs:
            out[key] = _empty()[key]
        else:
            out[key] = np.concatenate(arrs)
    return out


# -----------------------------------------------------------------------------
# NetCDF handling
# -----------------------------------------------------------------------------

def _require_netcdf4():
    try:
        import netCDF4
    except ImportError as exc:
        raise ImportError(
            "fire_rave.py requires netCDF4. Install it in the active environment, "
            "for example: pip install netCDF4"
        ) from exc
    return netCDF4


def _filled(value: Any) -> np.ndarray:
    if np.ma.isMaskedArray(value):
        value = value.filled(np.nan)
    return np.asarray(value)


def _read_var(ds: Any, name: str) -> np.ndarray:
    if name not in ds.variables:
        raise KeyError(
            f"Variable {name!r} not found. Available: {', '.join(ds.variables.keys())}"
        )
    return _filled(ds.variables[name][:])


def _start_time(ds: Any, file: Path) -> datetime:
    """
    Match the latest IDL reader: prefer global RangeBeginningDate and
    RangeBeginningTime.  Fall back to the `_sYYYYMMDDHH` filename token.
    """
    d = getattr(ds, "RangeBeginningDate", None)
    t = getattr(ds, "RangeBeginningTime", None)

    if d is not None and t is not None:
        ds0 = d.decode() if isinstance(d, bytes) else str(d)
        ts0 = t.decode() if isinstance(t, bytes) else str(t)
        dd = "".join(ch for ch in ds0 if ch.isdigit())
        tt = "".join(ch for ch in ts0 if ch.isdigit())
        if len(dd) >= 8 and len(tt) >= 2:
            return datetime.strptime(dd[:8] + tt[:2], "%Y%m%d%H")

    m = re.search(r"_s(\d{10})", file.name)
    if m:
        return datetime.strptime(m.group(1), "%Y%m%d%H")

    raise ValueError(
        f"Cannot determine RAVE starting time from global attributes or filename: {file}"
    )


def _time_axis(var: Any, shape: tuple[int, ...], spatial_shape: tuple[int, ...]) -> int | None:
    """
    Determine the time dimension robustly for Python's NetCDF dimension order.
    """
    dims = tuple(str(x).lower() for x in getattr(var, "dimensions", ()))

    for i, d in enumerate(dims):
        if "time" in d:
            return i

    if len(shape) == len(spatial_shape):
        return None

    if len(shape) == len(spatial_shape) + 1:
        for i in range(len(shape)):
            rest = shape[:i] + shape[i + 1 :]
            if tuple(rest) == tuple(spatial_shape):
                return i
            if tuple(rest) == tuple(reversed(spatial_shape)):
                return i

        # RAVE hourly files commonly have a singleton/hour dimension.
        one = [i for i, n in enumerate(shape) if n <= 24]
        if len(one) == 1:
            return one[0]

        return 0

    raise ValueError(
        f"Cannot infer RAVE time axis: variable shape={shape}, spatial={spatial_shape}"
    )


def _spatial_array(
    arr: np.ndarray,
    spatial_shape: tuple[int, ...],
    *,
    kind: str,
) -> np.ndarray:
    a = np.asarray(arr, dtype=float).squeeze()

    if tuple(a.shape) == tuple(spatial_shape):
        return a

    if a.ndim == 2 and tuple(a.T.shape) == tuple(spatial_shape):
        return a.T

    if a.ndim == 1 and len(spatial_shape) == 2:
        ny, nx = spatial_shape
        if kind == "lon" and a.size == nx:
            return np.broadcast_to(a.reshape(1, nx), spatial_shape)
        if kind == "lat" and a.size == ny:
            return np.broadcast_to(a.reshape(ny, 1), spatial_shape)

    try:
        return np.broadcast_to(a, spatial_shape).astype(float)
    except ValueError as exc:
        raise ValueError(
            f"Cannot conform RAVE {kind} shape {a.shape} to {spatial_shape}"
        ) from exc


def _to_time_first(arr: np.ndarray, axis: int | None) -> np.ndarray:
    a = np.asarray(arr, dtype=float)
    if axis is None:
        return a[np.newaxis, ...]
    return np.moveaxis(a, axis, 0)


def fire_rave_file1(file: str | os.PathLike[str], *, verbose: bool = True) -> dict[str, np.ndarray]:
    """
    Read one RAVE NetCDF file into flattened fire-emission records.

    This follows the latest rd_rave_noaa_file1() in rd_firepm_rave.pro:
      PM25, PM25_scaled, FRP_MEAN, FRE, grid_lont, grid_latt, area
      one UTC timestamp per hourly layer
      keep PM25 != -1
    """
    path = Path(file)
    if not path.exists():
        if verbose:
            print(f"NOFILE {path}")
        return _empty()

    if verbose:
        print(f"READ {path}")

    netCDF4 = _require_netcdf4()

    with netCDF4.Dataset(path, "r") as ds:
        pm_var = ds.variables["PM25"]

        pm = _filled(pm_var[:])
        pms = _read_var(ds, "PM25_scaled")
        frp = _read_var(ds, "FRP_MEAN")
        fre = _read_var(ds, "FRE")
        lon0 = _read_var(ds, "grid_lont")
        lat0 = _read_var(ds, "grid_latt")
        area0 = _read_var(ds, "area")
        stime = _start_time(ds, path)

        # Infer the spatial shape from lon/lat first; normally both are 2-D.
        ls = tuple(np.asarray(lon0).squeeze().shape)
        ats = tuple(np.asarray(lat0).squeeze().shape)

        if len(ls) == 2:
            spatial_shape = ls
        elif len(ats) == 2:
            spatial_shape = ats
        elif pm.ndim >= 2:
            # Temporarily infer from PM after identifying time-like dimension.
            dims = tuple(str(x).lower() for x in getattr(pm_var, "dimensions", ()))
            taxis0 = next((i for i, d in enumerate(dims) if "time" in d), None)
            if taxis0 is None and pm.ndim == 3:
                taxis0 = 0
            if taxis0 is None:
                spatial_shape = tuple(pm.shape)
            else:
                spatial_shape = tuple(n for i, n in enumerate(pm.shape) if i != taxis0)
        else:
            raise ValueError(f"Unexpected RAVE PM25 shape: {pm.shape}")

        taxis = _time_axis(pm_var, tuple(pm.shape), tuple(spatial_shape))

        pm_t = _to_time_first(pm, taxis)
        pms_t = _to_time_first(pms, taxis)
        frp_t = _to_time_first(frp, taxis)
        fre_t = _to_time_first(fre, taxis)

        spatial_shape = tuple(pm_t.shape[1:])

        lon = _spatial_array(lon0, spatial_shape, kind="lon")
        lat = _spatial_array(lat0, spatial_shape, kind="lat")
        area = _spatial_array(area0, spatial_shape, kind="area")

        # Longitude convention used in the IDL routines: [-180, 180].
        lon = ((lon + 180.0) % 360.0) - 180.0

        nt = pm_t.shape[0]
        if not (pms_t.shape[0] == frp_t.shape[0] == fre_t.shape[0] == nt):
            raise ValueError(f"Inconsistent RAVE time dimensions in {path}")

        out = {k: [] for k in FIELDS}

        for i in range(nt):
            if verbose:
                print(f"STIME = {stime:%Y%m%d%H} HOUR-ADDED {i}")

            pmi = np.asarray(pm_t[i], dtype=float)
            pmsi = np.asarray(pms_t[i], dtype=float)
            frpi = np.asarray(frp_t[i], dtype=float)
            frei = np.asarray(fre_t[i], dtype=float)

            good = np.isfinite(pmi) & (pmi != -1.0)
            if not np.any(good):
                continue

            n = int(np.count_nonzero(good))
            out["LON"].append(lon[good])
            out["LAT"].append(lat[good])
            out["PM"].append(pmi[good])
            out["PMS"].append(pmsi[good])
            out["FRP"].append(frpi[good])
            out["FRE"].append(frei[good])
            out["AREA"].append(area[good])
            out["UTC"].append(
                np.full(
                    n,
                    np.datetime64(stime + timedelta(hours=i), "m"),
                    dtype="datetime64[m]",
                )
            )

    ans: dict[str, np.ndarray] = {}
    for key in FIELDS:
        if out[key]:
            ans[key] = np.concatenate(out[key])
        else:
            ans[key] = _empty()[key]

    return ans


def fire_rave_file(
    files: Sequence[str | os.PathLike[str]],
    *,
    verbose: bool = True,
) -> dict[str, np.ndarray]:
    rr = [fire_rave_file1(f, verbose=verbose) for f in files]
    return _concat(rr)


# -----------------------------------------------------------------------------
# Daily database
# -----------------------------------------------------------------------------

def fire_rave_d1(
    cday: Any,
    name: str = "3km",
    *,
    version: str = DEFAULT_VERSION,
    renew: bool = False,
    renew_raw: bool = False,
    data_root: str | os.PathLike[str] | None = None,
    verbose: bool = True,
) -> dict[str, np.ndarray]:
    day = _datetime_from_value(cday)
    day = datetime(day.year, day.month, day.day)
    name = str(name).lower()

    if name not in VALID_NAMES:
        raise ValueError(f"Wrong RAVE name {name!r}; use one of {VALID_NAMES}")

    save = _dayfile(day, name=name, data_root=data_root)

    if renew or not save.exists():
        files = fire_rave_dn(
            int(day.strftime("%Y%m%d")),
            name=name,
            version=version,
            renew=renew_raw,
            data_root=data_root,
            verbose=verbose,
        )
        if not files:
            if verbose:
                print(f"NO RAVE {day:%Y%m%d}")
            return _empty()

        rr = fire_rave_file(files, verbose=verbose)
        if len(rr["LON"]) == 0:
            return rr

        if verbose:
            print(f"SAVE {save}")
        _save_dayfile(save, rr)

    if verbose:
        print(f"READ {save}")
    return _read_dayfile(save)


def fire_rave_d(
    cday: Any,
    name: str = "3km",
    *,
    version: str = DEFAULT_VERSION,
    renew: bool = False,
    renew_raw: bool = False,
    data_root: str | os.PathLike[str] | None = None,
    verbose: bool = True,
) -> dict[str, np.ndarray]:
    days = _days_for_request(cday)
    rr = [
        fire_rave_d1(
            d,
            name,
            version=version,
            renew=renew,
            renew_raw=renew_raw,
            data_root=data_root,
            verbose=verbose,
        )
        for d in days
    ]
    return _concat(rr)


# -----------------------------------------------------------------------------
# Selection/filtering
# -----------------------------------------------------------------------------

def _time_mask(utc: np.ndarray, request: Any) -> np.ndarray:
    u = np.asarray(utc).astype("datetime64[m]")
    keep = np.zeros(u.shape, dtype=bool)

    for v in _as_values(request):
        n = _granularity(v)
        dt = _datetime_from_value(v)

        if n == 4:
            a = np.datetime64(datetime(dt.year, 1, 1), "m")
            b = np.datetime64(datetime(dt.year + 1, 1, 1), "m")
        elif n == 6:
            a = np.datetime64(datetime(dt.year, dt.month, 1), "m")
            if dt.month == 12:
                bdt = datetime(dt.year + 1, 1, 1)
            else:
                bdt = datetime(dt.year, dt.month + 1, 1)
            b = np.datetime64(bdt, "m")
        elif n == 8:
            a = np.datetime64(datetime(dt.year, dt.month, dt.day), "m")
            b = a + np.timedelta64(1, "D")
        elif n == 10:
            a = np.datetime64(datetime(dt.year, dt.month, dt.day, dt.hour), "m")
            b = a + np.timedelta64(1, "h")
        else:
            a = np.datetime64(
                datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute), "m"
            )
            b = a + np.timedelta64(1, "m")

        keep |= (u >= a) & (u < b)

    return keep


def _subset(data: Mapping[str, np.ndarray], mask: np.ndarray) -> dict[str, np.ndarray]:
    return {k: np.asarray(v)[mask] for k, v in data.items()}


def fire_rave(
    time: Any,
    *,
    name: str = "3km",
    version: str = DEFAULT_VERSION,
    domain: str | None = None,
    minfo: Mapping[str, Any] | None = None,
    bbox: Sequence[float] | None = None,
    renew: bool = False,
    renew_raw: bool = False,
    data_root: str | os.PathLike[str] | None = None,
    verbose: bool = True,
) -> dict[str, np.ndarray]:
    """
    Read RAVE emissions for day/month/year/hour selections.

    Examples
    --------
    fire_rave(20260725)
        all RAVE records on 2026-07-25

    fire_rave(2026072506)
        records for 06 UTC only

    fire_rave(20260725, name="3km", domain="nca12")
        daily RAVE records inside the NCA12 model grid
    """
    name = str(name).lower()

    days = _days_for_request(time)
    rr = _concat(
        [
            fire_rave_d1(
                d,
                name,
                version=version,
                renew=renew,
                renew_raw=renew_raw,
                data_root=data_root,
                verbose=verbose,
            )
            for d in days
        ]
    )

    if len(rr["LON"]) == 0:
        return rr

    mask = _time_mask(rr["UTC"], time)

    lon = np.asarray(rr["LON"], dtype=float)
    lat = np.asarray(rr["LAT"], dtype=float)
    mask &= np.isfinite(lon) & np.isfinite(lat)

    if domain is not None or minfo is not None:
        try:
            from grdinfo import grdinfo_mask
        except ImportError as exc:
            raise ImportError(
                "RAVE domain/minfo filtering requires grdinfo.py in ~/lib/python."
            ) from exc

        mask &= grdinfo_mask(
            lon,
            lat,
            domain=domain,
            minfo=minfo,
            data_root=data_root,
        )

    if bbox is not None:
        if len(bbox) != 4:
            raise ValueError("bbox must be [south, west, north, east]")
        south, west, north, east = [float(x) for x in bbox]
        if west <= east:
            mlo = (lon >= west) & (lon <= east)
        else:
            mlo = (lon >= west) | (lon <= east)
        mask &= (lat >= south) & (lat <= north) & mlo

    return _subset(rr, mask)


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Read NOAA RAVE fire emissions")
    p.add_argument("time", help="YYYY, YYYYMM, YYYYMMDD, or YYYYMMDDHH")
    p.add_argument("--name", default="3km", choices=VALID_NAMES)
    p.add_argument("--version", default=DEFAULT_VERSION)
    p.add_argument("--domain", default=None)
    p.add_argument("--bbox", default=None, help="south,west,north,east")
    p.add_argument("--data-root", default=None)
    p.add_argument("--renew", action="store_true", help="rebuild RAVE daily NPZ")
    p.add_argument(
        "--renew-raw",
        action="store_true",
        help="also refresh raw RAVE NetCDF files",
    )
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    bbox = None
    if args.bbox:
        bbox = [float(x) for x in args.bbox.split(",")]

    try:
        rr = fire_rave(
            args.time,
            name=args.name,
            version=args.version,
            domain=args.domain,
            bbox=bbox,
            renew=args.renew,
            renew_raw=args.renew_raw,
            data_root=args.data_root,
            verbose=not args.quiet,
        )
        n = len(rr["LON"])
        print(f"RAVE RECORDS = {n}")
        if n:
            u = np.asarray(rr["UTC"]).astype("datetime64[m]")
            print(f"UTC = {u.min()} ... {u.max()}")
            print("FIELDS =", ", ".join(rr.keys()))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
