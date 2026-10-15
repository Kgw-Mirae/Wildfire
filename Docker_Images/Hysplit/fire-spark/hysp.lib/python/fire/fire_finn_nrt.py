#!/usr/bin/env python3
"""
fire_finn_nrt.py

Python counterpart of the current IDL fire_finn_nrt.pro.

Design mirrors the IDL routine hierarchy:

    fire_finn_nrt_d1(YYYYMMDD)
        -> create/read one daily intermediate dayfile

    fire_finn_nrt_d(day or days, extract=False)
        -> read daily data

    fire_finn_nrt_m(YYYYMM or months, extract=False)
        -> expand month(s) to days and read FINN NRT

    fire_finn_nrt_y(YYYY or years, extract=False)
        -> expand year(s) to days and read FINN NRT

    fire_finn_nrt(time, ...)
        -> dispatch from the input length: YYYY, YYYYMM, or YYYYMMDD

The raw FINN files are downloaded by fire_finn_nrt_dn.py.  The daily reader
then merges the SAPRC table with FRP from base_FRP, renames LATI/LONGI to
LAT/LON, and saves the full merged daily record before any geographic filter.

Default dayfile location:
    ~/data/fire-finn/nrt/dayfile/YYYY/fire-finn-nrt.YYYYMMDD.npz

The NPZ file is the Python analogue of the IDL SAVE dayfile.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import os
import sys
from datetime import date, datetime, timedelta, timezone
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

try:
    from .fire_finn_nrt_dn import fire_finn_nrt_dn
except ImportError:
    from fire_finn_nrt_dn import fire_finn_nrt_dn


# -----------------------------------------------------------------------------
# Date handling
# -----------------------------------------------------------------------------

def _digits(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, Real):
        if not float(value).is_integer():
            raise ValueError(f"Non-integer FINN time value: {value!r}")
        return str(int(value))
    return "".join(ch for ch in str(value).strip() if ch.isdigit())


def _as_values(value: Any) -> list[Any]:
    if isinstance(value, (str, bytes, Integral, Real, datetime, date)):
        return [value]
    return list(value)


def _granularity(value: Any) -> int:
    values = _as_values(value)
    lengths = {len(_digits(v)) for v in values}
    if len(lengths) != 1:
        raise ValueError("FINN time values must have the same YYYY/YYYYMM/YYYYMMDD precision")
    n = lengths.pop()
    if n not in (4, 6, 8):
        raise ValueError(f"FINN time must be YYYY, YYYYMM, or YYYYMMDD: {value!r}")
    return n


def _parse_day(value: Any) -> datetime:
    s = _digits(value)
    if len(s) != 8:
        raise ValueError(f"YYYYMMDD required: {value!r}")
    return datetime.strptime(s, "%Y%m%d")


def _parse_month(value: Any) -> tuple[int, int]:
    s = _digits(value)
    if len(s) != 6:
        raise ValueError(f"YYYYMM required: {value!r}")
    y, m = int(s[:4]), int(s[4:6])
    if not 1 <= m <= 12:
        raise ValueError(f"Invalid month: {value!r}")
    return y, m


def _parse_year(value: Any) -> int:
    s = _digits(value)
    if len(s) != 4:
        raise ValueError(f"YYYY required: {value!r}")
    return int(s)


def _days_for_day_input(value: Any) -> list[datetime]:
    return [_parse_day(v) for v in _as_values(value)]


def _days_for_month(value: Any) -> list[datetime]:
    out: list[datetime] = []
    for v in _as_values(value):
        y, m = _parse_month(v)
        nday = calendar.monthrange(y, m)[1]
        out.extend(datetime(y, m, d) for d in range(1, nday + 1))
    return out


def _days_for_year(value: Any) -> list[datetime]:
    out: list[datetime] = []
    for v in _as_values(value):
        y = _parse_year(v)
        d = datetime(y, 1, 1)
        end = datetime(y + 1, 1, 1)
        while d < end:
            out.append(d)
            d += timedelta(days=1)
    return out


# -----------------------------------------------------------------------------
# Paths / dayfile
# -----------------------------------------------------------------------------

def _data_root(data_root: str | os.PathLike[str] | None = None) -> Path:
    if data_root is not None:
        return Path(data_root).expanduser()
    env = os.environ.get("DATA_PATH") or os.environ.get("BLUTOUCH_DATA")
    return Path(env).expanduser() if env else Path("~/data").expanduser()


def _dayfile(day: datetime, data_root: str | os.PathLike[str] | None = None) -> Path:
    return (
        _data_root(data_root)
        / "fire-finn"
        / "nrt"
        / "dayfile"
        / day.strftime("%Y")
        / f"fire-finn-nrt.{day:%Y%m%d}.npz"
    )


def _save_dayfile(path: Path, data: Mapping[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    # Passing an open file keeps NumPy from appending another .npz suffix.
    with tmp.open("wb") as f:
        np.savez_compressed(f, **{k.upper(): np.asarray(v) for k, v in data.items()})
    tmp.replace(path)


def _read_dayfile(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as z:
        return {k.upper(): np.asarray(z[k]) for k in z.files}


# -----------------------------------------------------------------------------
# Raw FINN table handling
# -----------------------------------------------------------------------------

def _norm(name: str) -> str:
    return (
        str(name)
        .strip()
        .upper()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
        .replace(".", "")
    )


def _canonical_name(name: str) -> str:
    key = _norm(name)
    if key in ("LAT", "LATI", "LATITUDE"):
        return "LAT"
    if key in ("LON", "LONGI", "LONGITUDE"):
        return "LON"
    return str(name).strip().upper().replace(".", "")


def _read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        return [x.strip() for x in next(csv.reader(f))]


def _read_full_table(path: Path) -> dict[str, np.ndarray]:
    """Read a complete FINN text table and normalize LATI/LONGI -> LAT/LON."""
    header0 = _read_header(path)
    header = [_canonical_name(x) for x in header0]
    if len(set(header)) != len(header):
        raise ValueError(f"Duplicate FINN field after normalization: {path}")

    arr = np.genfromtxt(
        path,
        delimiter=",",
        skip_header=1,
        dtype=np.float64,
        ndmin=2,
        filling_values=np.nan,
        invalid_raise=False,
    )

    if arr.size == 0:
        arr = np.empty((0, len(header)), dtype=np.float64)

    if arr.ndim != 2:
        arr = np.atleast_2d(arr)
    if arr.shape[1] != len(header):
        if arr.shape[0] == len(header):
            arr = arr.T
        else:
            raise ValueError(
                f"FINN table shape mismatch: {path}: {arr.shape}; "
                f"header has {len(header)} columns"
            )

    int_fields = {"DAY", "POLYID", "FIREID", "GENVEG"}
    out: dict[str, np.ndarray] = {}
    for i, name in enumerate(header):
        col = np.asarray(arr[:, i])
        if name in int_fields and np.all(np.isfinite(col)):
            out[name] = col.astype(np.int64)
        else:
            out[name] = col.astype(np.float64)
    return out


def _find_product(files: Sequence[Path], token: str) -> Path:
    hits = [Path(p) for p in files if token.upper() in Path(p).name.upper()]
    if len(hits) != 1:
        raise FileNotFoundError(
            f"Expected one FINN {token} file; found {len(hits)}: "
            + ", ".join(str(x) for x in files)
        )
    return hits[0]


def _build_dayfile(
    day: datetime,
    *,
    data_root: str | os.PathLike[str] | None = None,
    renew_raw: bool = False,
    verbose: bool = True,
) -> dict[str, np.ndarray]:
    files = fire_finn_nrt_dn(
        int(day.strftime("%Y%m%d")),
        data_root=data_root,
        renew=renew_raw,
        verbose=verbose,
    )
    if not files:
        return {}

    # Downloader returns one list for one day.
    if isinstance(files, (tuple, list)) and files and isinstance(files[0], (tuple, list)):
        if len(files) != 1:
            raise ValueError("Unexpected multi-day result from fire_finn_nrt_dn")
        files = files[0]

    paths = [Path(p) for p in files]
    f_frp = _find_product(paths, "FRP")
    f_saprc = _find_product(paths, "SAPRC")

    # IDL logic: complete SAPRC table + the FRP column from base_FRP.
    saprc = _read_full_table(f_saprc)
    frp_table = _read_full_table(f_frp)

    for field in ("LAT", "LON"):
        if field not in saprc:
            raise KeyError(f"{field} not found in SAPRC file {f_saprc}")
    if "FRP" not in frp_table:
        raise KeyError(f"FRP not found in base_FRP file {f_frp}")

    n1 = len(saprc["LAT"])
    n2 = len(frp_table["FRP"])
    if n1 != n2:
        raise ValueError(
            f"FINN SAPRC/base_FRP record mismatch for {day:%Y%m%d}: {n1} != {n2}"
        )

    # The IDL routine assumes row alignment.  Verify coordinates when possible.
    if n1 and "LAT" in frp_table and "LON" in frp_table:
        if not (
            np.allclose(saprc["LAT"], frp_table["LAT"], atol=1e-5, rtol=0, equal_nan=True)
            and np.allclose(saprc["LON"], frp_table["LON"], atol=1e-5, rtol=0, equal_nan=True)
        ):
            raise ValueError(
                f"FINN SAPRC/base_FRP rows are not aligned for {day:%Y%m%d}"
            )

    data = dict(saprc)
    data["FRP"] = np.asarray(frp_table["FRP"], dtype=np.float64)
    return data


# -----------------------------------------------------------------------------
# Geographic filtering.  Filtering happens after the unfiltered dayfile is read,
# matching the IDL routine.
# -----------------------------------------------------------------------------

def _bbox_mask(lon: np.ndarray, lat: np.ndarray, bbox: Sequence[float] | str) -> np.ndarray:
    if isinstance(bbox, str):
        vals = [float(x.strip()) for x in bbox.split(",") if x.strip()]
    else:
        vals = [float(x) for x in bbox]
    if len(vals) != 4:
        raise ValueError("bbox must be [south, west, north, east]")
    south, west, north, east = vals
    if west <= east:
        mlon = (lon >= west) & (lon <= east)
    else:
        # Dateline crossing.
        mlon = (lon >= west) | (lon <= east)
    return mlon & (lat >= south) & (lat <= north)


def _filter_data(
    data: Mapping[str, np.ndarray],
    *,
    domain: str | Mapping[str, Any] | None = None,
    minfo: Mapping[str, Any] | None = None,
    bbox: Sequence[float] | str | None = None,
    data_root: str | os.PathLike[str] | None = None,
) -> dict[str, np.ndarray]:
    if not data:
        return {}

    lon = np.asarray(data["LON"], dtype=float)
    lat = np.asarray(data["LAT"], dtype=float)
    mask = np.isfinite(lon) & np.isfinite(lat)

    if domain is not None or minfo is not None:
        try:
            from grdinfo import grdinfo_mask
        except ImportError as exc:
            raise ImportError(
                "Domain/minfo filtering requires ~/lib/python/grdinfo.py."
            ) from exc
        mask &= grdinfo_mask(
            lon,
            lat,
            domain=domain,
            minfo=minfo,
            data_root=data_root,
        )

    if bbox is not None:
        mask &= _bbox_mask(lon, lat, bbox)

    return {k: np.asarray(v)[mask] for k, v in data.items()}


def _concat(records: Iterable[Mapping[str, np.ndarray]]) -> dict[str, np.ndarray]:
    valid = [dict(x) for x in records if x]
    if not valid:
        return {}
    # Daily FINN files should have the same schema.  Keep the first-day order.
    keys = list(valid[0].keys())
    missing = [k for r in valid for k in keys if k not in r]
    if missing:
        raise KeyError(f"FINN dayfile schema mismatch; missing field {missing[0]}")
    return {k: np.concatenate([np.asarray(r[k]) for r in valid]) for k in keys}


# -----------------------------------------------------------------------------
# Public API: direct counterparts of fire_finn_nrt.pro
# -----------------------------------------------------------------------------

def fire_finn_nrt_d1(
    cday: Any,
    *,
    domain: str | Mapping[str, Any] | None = None,
    minfo: Mapping[str, Any] | None = None,
    bbox: Sequence[float] | str | None = None,
    renew: bool = False,
    renew_raw: bool = False,
    data_root: str | os.PathLike[str] | None = None,
    verbose: bool = True,
) -> dict[str, np.ndarray]:
    """Create/read one FINN NRT dayfile, then apply optional geographic filter."""
    day = _parse_day(cday)
    save = _dayfile(day, data_root)

    if renew or not save.is_file():
        rr = _build_dayfile(
            day,
            data_root=data_root,
            renew_raw=renew_raw,
            verbose=verbose,
        )
        if not rr:
            return {}
        if verbose:
            print(f"SAVE {save}")
        _save_dayfile(save, rr)

    if verbose:
        print(f"READ {save}")
    rr = _read_dayfile(save)

    return _filter_data(
        rr,
        domain=domain,
        minfo=minfo,
        bbox=bbox,
        data_root=data_root,
    )


def fire_finn_nrt_d(
    time: Any,
    *,
    domain: str | Mapping[str, Any] | None = None,
    minfo: Mapping[str, Any] | None = None,
    bbox: Sequence[float] | str | None = None,
    extract: bool = False,
    renew: bool = False,
    renew_raw: bool = False,
    data_root: str | os.PathLike[str] | None = None,
    verbose: bool = True,
) -> list[dict[str, np.ndarray]] | dict[str, np.ndarray]:
    """Daily reader.  extract=True concatenates all requested days."""
    rr: list[dict[str, np.ndarray]] = []
    for day in _days_for_day_input(time):
        rr1 = fire_finn_nrt_d1(
            day,
            domain=domain,
            minfo=minfo,
            bbox=bbox,
            renew=renew,
            renew_raw=renew_raw,
            data_root=data_root,
            verbose=verbose,
        )
        rr.append(rr1)
    return _concat(rr) if extract else rr


def fire_finn_nrt_m(
    mon: Any,
    *,
    domain: str | Mapping[str, Any] | None = None,
    minfo: Mapping[str, Any] | None = None,
    bbox: Sequence[float] | str | None = None,
    extract: bool = False,
    renew: bool = False,
    renew_raw: bool = False,
    data_root: str | os.PathLike[str] | None = None,
    verbose: bool = True,
) -> list[dict[str, np.ndarray]] | dict[str, np.ndarray]:
    """Monthly reader.  Each month is assembled from its daily dayfiles."""
    monthly: list[dict[str, np.ndarray]] = []
    for value in _as_values(mon):
        days = _days_for_month(value)
        rr1 = fire_finn_nrt_d(
            [int(d.strftime("%Y%m%d")) for d in days],
            domain=domain,
            minfo=minfo,
            bbox=bbox,
            extract=True,
            renew=renew,
            renew_raw=renew_raw,
            data_root=data_root,
            verbose=verbose,
        )
        assert isinstance(rr1, dict)
        monthly.append(rr1)
    return _concat(monthly) if extract else monthly


def fire_finn_nrt_y(
    year: Any,
    *,
    domain: str | Mapping[str, Any] | None = None,
    minfo: Mapping[str, Any] | None = None,
    bbox: Sequence[float] | str | None = None,
    extract: bool = False,
    renew: bool = False,
    renew_raw: bool = False,
    data_root: str | os.PathLike[str] | None = None,
    verbose: bool = True,
) -> list[dict[str, np.ndarray]] | dict[str, np.ndarray]:
    """Yearly reader.  Each year is assembled from its daily dayfiles."""
    yearly: list[dict[str, np.ndarray]] = []
    for value in _as_values(year):
        days = _days_for_year(value)
        rr1 = fire_finn_nrt_d(
            [int(d.strftime("%Y%m%d")) for d in days],
            domain=domain,
            minfo=minfo,
            bbox=bbox,
            extract=True,
            renew=renew,
            renew_raw=renew_raw,
            data_root=data_root,
            verbose=verbose,
        )
        assert isinstance(rr1, dict)
        yearly.append(rr1)
    return _concat(yearly) if extract else yearly


def fire_finn_nrt(
    time: Any,
    *,
    domain: str | Mapping[str, Any] | None = None,
    minfo: Mapping[str, Any] | None = None,
    bbox: Sequence[float] | str | None = None,
    extract: bool = False,
    renew: bool = False,
    renew_raw: bool = False,
    data_root: str | os.PathLike[str] | None = None,
    verbose: bool = True,
) -> list[dict[str, np.ndarray]] | dict[str, np.ndarray]:
    """Dispatch FINN NRT reader by YYYY / YYYYMM / YYYYMMDD input precision."""
    n = _granularity(time)
    if n == 4:
        rr = fire_finn_nrt_y(
            time, domain=domain, minfo=minfo, bbox=bbox, extract=extract,
            renew=renew, renew_raw=renew_raw, data_root=data_root, verbose=verbose,
        )
    elif n == 6:
        rr = fire_finn_nrt_m(
            time, domain=domain, minfo=minfo, bbox=bbox, extract=extract,
            renew=renew, renew_raw=renew_raw, data_root=data_root, verbose=verbose,
        )
    else:
        rr = fire_finn_nrt_d(
            time, domain=domain, minfo=minfo, bbox=bbox, extract=extract,
            renew=renew, renew_raw=renew_raw, data_root=data_root, verbose=verbose,
        )

    if verbose:
        print("FINN UNIT: KG/DAY MOLES/DAY W")
    return rr


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def _nrecords(rr: Any) -> int:
    if isinstance(rr, dict):
        if "LAT" in rr:
            return int(len(rr["LAT"]))
        return 0
    if isinstance(rr, list):
        return sum(_nrecords(x) for x in rr)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Create/read FINN NRT dayfiles for YYYY, YYYYMM, or YYYYMMDD"
    )
    p.add_argument("time", help="YYYY, YYYYMM, or YYYYMMDD")
    p.add_argument("--domain", default=None)
    p.add_argument("--bbox", default=None, help="south,west,north,east")
    p.add_argument("--data-root", default=None)
    p.add_argument("--extract", action="store_true", help="concatenate requested period")
    p.add_argument("--renew", action="store_true", help="rebuild daily dayfile(s)")
    p.add_argument("--renew-raw", action="store_true", help="also refresh raw FINN download")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    try:
        rr = fire_finn_nrt(
            args.time,
            domain=args.domain,
            bbox=args.bbox,
            extract=args.extract,
            renew=args.renew,
            renew_raw=args.renew_raw,
            data_root=args.data_root,
            verbose=not args.quiet,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"records={_nrecords(rr)}")
    return 0


__all__ = [
    "fire_finn_nrt_d1",
    "fire_finn_nrt_d",
    "fire_finn_nrt_m",
    "fire_finn_nrt_y",
    "fire_finn_nrt",
]


if __name__ == "__main__":
    raise SystemExit(main())
