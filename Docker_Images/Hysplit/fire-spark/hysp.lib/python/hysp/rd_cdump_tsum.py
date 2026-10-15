#!/usr/bin/env python3
"""
rd_cdump_tsum-260708-008.py

Direct Python implementation of the IDL-style rd_cdump_tsum workflow for
HYSPLIT cdump concentration files, with optional HYGV NetCDF saving.

This version does not use NOAA hysplitdata.  It reads the HYSPLIT binary cdump
records directly, then follows the IDL-style behavior:

- merge one or more cdump files by sample-start timestamp;
- apply one source/file coefficient per input cdump file;
- optionally apply radioactive decay;
- select pollutant(s) and vertical level(s);
- sum selected levels/pollutants or compute thickness-weighted vertical mean;
- optionally convert exact zeros to NaN;
- return IDL order [x, y, time] by default;
- optionally save directly to a compact HYGV NetCDF file.

Basic use as Python routine
---------------------------
    from rd_cdump_tsum import rd_cdump_tsum

    data, info = rd_cdump_tsum(
        ["run01/cdump", "run02/cdump"],
        xlevel=[0, 1, 2],
        xptype=0,
        factor=[1.0, 0.5],  # source/file coefficients: 1.0*file0 + 0.5*file1
        decay=30.17,
        vmean=True,
        nan=True,
    )

Command-line examples
---------------------
Save IDL-style compressed NPZ:
    python rd_cdump_tsum-260708-008.py cdump -o cdump_tsum.nc

Save HYGV/Web-Mercator NetCDF:
    python rd_cdump_tsum-260708-008.py cdump -o out.nc

Save HYGV/Web-Mercator NetCDF at 1 km display grid:
    python rd_cdump_tsum-260708-008.py cdump --hygv --wm-res-km 1 --output out_1km.nc

Merge three source cdump files with inverse-modeling coefficients:
    python rd_cdump_tsum-260708-008.py src1/cdump src2/cdump src3/cdump \
        --factor 1.0 1.5 1.3 --hygv --var-name PM2P5 --output PM2P5.nc

Read input cdump paths from a text file:
    python rd_cdump_tsum-260708-008.py --file-list cdump_files.txt \
        --factor 1.0 1.5 1.3 --hygv --output merged.nc

The list file should contain one cdump path per line. Blank lines and lines
starting with # are ignored. Relative paths are resolved relative to the list file.

Select layers/pollutant and write variable PM2P5:
    python rd_cdump_tsum-260708-008.py cdump --xlevel 0 1 2 --ptype P001 \
        --zero-to-nan --hygv --var-name PM2P5 --output PM2P5.nc
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import struct
import sys
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

import numpy as np
from numpy.typing import DTypeLike, NDArray

APP_VERSION = "260708-008"
WEB_MERCATOR_EPSG = 3857
WEB_MERCATOR_R = 6378137.0
WEB_MERCATOR_LAT_LIMIT = 85.0511287798066
DEFAULT_COMPRESSION_LEVEL = 4
DEFAULT_WM_MAX_DIM = 2000
DEFAULT_FILL_VALUE = np.float32(np.nan)
DEGREE_QUANTUM = 1.0e-6
METER_QUANTUM = 1.0e-3
INTEGER_SNAP_TOL = 1.0e-9

__all__ = [
    "CdumpFormatError",
    "GridInfo",
    "ReleaseInfo",
    "CdumpHeader",
    "read_cdump_header",
    "read_cdump_file_list",
    "rd_cdump_tsum",
    "save_hygv_netcdf",
]


class CdumpFormatError(RuntimeError):
    """Raised when a cdump file is malformed or incompatible."""


@dataclass(frozen=True, slots=True)
class GridInfo:
    """IDL minfo-like horizontal grid definition for a lat/lon cdump grid.

    x0/y0 are the first HYSPLIT grid-node coordinates read from the cdump file.
    For bbox/image coverage, the edge extent is x0/y0 +/- half grid spacing.
    """

    x0: float
    y0: float
    dx: float
    dy: float
    nx: int
    ny: int
    proj: str = "ll"

    @property
    def lon(self) -> NDArray[np.float64]:
        return self.x0 + np.arange(self.nx, dtype=np.float64) * self.dx

    @property
    def lat(self) -> NDArray[np.float64]:
        return self.y0 + np.arange(self.ny, dtype=np.float64) * self.dy

    @property
    def edge_bbox(self) -> tuple[float, float, float, float]:
        """Return source-image edge bbox as [south, west, north, east]."""
        west = self.x0 - 0.5 * self.dx
        east = self.x0 + (self.nx - 1) * self.dx + 0.5 * self.dx
        south = self.y0 - 0.5 * self.dy
        north = self.y0 + (self.ny - 1) * self.dy + 0.5 * self.dy
        return (min(south, north), min(west, east), max(south, north), max(west, east))


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    """One source-location record from cdump record 2."""

    time: datetime
    latitude: float
    longitude: float
    height_m: float


@dataclass(frozen=True, slots=True)
class CdumpHeader:
    """Metadata read from cdump records 1--5."""

    path: str
    endian: str
    model: str
    meteorology_start: datetime
    forecast_hour: int
    packing_flag: int
    releases: tuple[ReleaseInfo, ...]
    grid: GridInfo
    levels_m: tuple[int, ...]
    pollutants: tuple[str, ...]
    pollutants_raw: tuple[str, ...]


class _FortranSequentialReader:
    """Reader for 4-byte-marker Fortran sequential unformatted records."""

    __slots__ = ("path", "fh", "endian", "_int")

    def __init__(self, path: os.PathLike[str] | str) -> None:
        self.path = os.fspath(path)
        self.fh = open(self.path, "rb", buffering=1024 * 1024)

        marker = self.fh.read(4)
        if len(marker) != 4:
            self.fh.close()
            raise CdumpFormatError(f"{self.path}: empty or truncated file")

        n_be = struct.unpack(">i", marker)[0]
        n_le = struct.unpack("<i", marker)[0]
        # Standard cdump record 1 is exactly 32 bytes.
        if n_be == 32:
            self.endian = ">"
        elif n_le == 32:
            self.endian = "<"
        else:
            self.fh.close()
            raise CdumpFormatError(
                f"{self.path}: cannot identify cdump byte order; "
                f"first record markers decode as {n_be} (big) and {n_le} (little)"
            )

        self._int = struct.Struct(self.endian + "i")
        self.fh.seek(0)

    def close(self) -> None:
        self.fh.close()

    def __enter__(self) -> "_FortranSequentialReader":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def _read_marker(self, *, allow_eof: bool) -> int | None:
        raw = self.fh.read(4)
        if raw == b"" and allow_eof:
            return None
        if len(raw) != 4:
            raise CdumpFormatError(
                f"{self.path}: truncated Fortran record marker at byte {self.fh.tell()}"
            )
        n = self._int.unpack(raw)[0]
        if n < 0:
            raise CdumpFormatError(f"{self.path}: negative record length {n}")
        return n

    def read_record(self, *, allow_eof: bool = False) -> bytes | None:
        n = self._read_marker(allow_eof=allow_eof)
        if n is None:
            return None
        payload = self.fh.read(n)
        if len(payload) != n:
            raise CdumpFormatError(
                f"{self.path}: truncated record payload; expected {n}, got {len(payload)}"
            )
        trailer_raw = self.fh.read(4)
        if len(trailer_raw) != 4:
            raise CdumpFormatError(f"{self.path}: missing trailing record marker")
        trailer = self._int.unpack(trailer_raw)[0]
        if trailer != n:
            raise CdumpFormatError(
                f"{self.path}: record marker mismatch ({n} != {trailer})"
            )
        return payload

    def skip_record(self, *, allow_eof: bool = False) -> int | None:
        """Skip a record without allocating its payload; return payload length."""
        n = self._read_marker(allow_eof=allow_eof)
        if n is None:
            return None
        self.fh.seek(n, os.SEEK_CUR)
        trailer_raw = self.fh.read(4)
        if len(trailer_raw) != 4:
            raise CdumpFormatError(f"{self.path}: missing trailing record marker")
        trailer = self._int.unpack(trailer_raw)[0]
        if trailer != n:
            raise CdumpFormatError(
                f"{self.path}: record marker mismatch ({n} != {trailer})"
            )
        return n


def _decode_char4(raw: bytes, *, strip: bool) -> str:
    text = raw.decode("ascii", errors="replace")
    return text.rstrip() if strip else text


def _expand_year(year: int) -> int:
    """Match the IDL pivot: YY > 40 -> 19YY, otherwise 20YY."""
    if year >= 100:
        return year
    return 1900 + year if year > 40 else 2000 + year


def _datetime_from_six(values: Sequence[int]) -> datetime:
    year, month, day, hour, minute, _forecast = values
    return datetime(_expand_year(year), month, day, hour, minute)


def _read_header_from_open(reader: _FortranSequentialReader) -> CdumpHeader:
    e = reader.endian
    path = reader.path

    rec1 = reader.read_record()
    if rec1 is None or len(rec1) != 32:
        raise CdumpFormatError(
            f"{path}: record 1 should contain 32 bytes, got {0 if rec1 is None else len(rec1)}"
        )

    model_raw, iyr, imo, ida, ihr, ich, nloc, cpack = struct.unpack(e + "4s7i", rec1)
    try:
        met_start = datetime(_expand_year(iyr), imo, ida, ihr)
    except ValueError as exc:
        raise CdumpFormatError(f"{path}: invalid meteorology timestamp") from exc

    releases: list[ReleaseInfo] = []
    release_struct = struct.Struct(e + "4i3fi")
    for _ in range(nloc):
        payload = reader.read_record()
        if payload is None or len(payload) != release_struct.size:
            raise CdumpFormatError(
                f"{path}: invalid release record length {0 if payload is None else len(payload)}"
            )
        by, bm, bd, bh, lat, lon, height, minute = release_struct.unpack(payload)
        try:
            release_time = datetime(_expand_year(by), bm, bd, bh, minute)
        except ValueError as exc:
            raise CdumpFormatError(f"{path}: invalid release timestamp") from exc
        releases.append(
            ReleaseInfo(
                time=release_time,
                latitude=float(lat),
                longitude=float(lon),
                height_m=float(height),
            )
        )

    rec3 = reader.read_record()
    if rec3 is None or len(rec3) != 24:
        raise CdumpFormatError(
            f"{path}: grid record should contain 24 bytes, got {0 if rec3 is None else len(rec3)}"
        )
    nlat, nlon, dlat, dlon, clat, clon = struct.unpack(e + "2i4f", rec3)
    if nlat <= 0 or nlon <= 0:
        raise CdumpFormatError(f"{path}: invalid grid size ({nlon}, {nlat})")
    grid = GridInfo(
        x0=float(clon),
        y0=float(clat),
        dx=float(dlon),
        dy=float(dlat),
        nx=int(nlon),
        ny=int(nlat),
    )

    rec4 = reader.read_record()
    if rec4 is None or len(rec4) < 4:
        raise CdumpFormatError(f"{path}: invalid vertical-level record")
    nlev = struct.unpack_from(e + "i", rec4, 0)[0]
    expected = 4 + 4 * nlev
    if nlev <= 0 or len(rec4) != expected:
        raise CdumpFormatError(
            f"{path}: vertical-level record length {len(rec4)} does not match "
            f"NLVL={nlev} (expected {expected})"
        )
    levels = tuple(struct.unpack_from(e + f"{nlev}i", rec4, 4))

    rec5 = reader.read_record()
    if rec5 is None or len(rec5) < 4:
        raise CdumpFormatError(f"{path}: invalid pollutant record")
    ntyp = struct.unpack_from(e + "i", rec5, 0)[0]
    expected = 4 + 4 * ntyp
    if ntyp <= 0 or len(rec5) != expected:
        raise CdumpFormatError(
            f"{path}: pollutant record length {len(rec5)} does not match "
            f"NTYP={ntyp} (expected {expected})"
        )
    pollutants_raw = tuple(
        _decode_char4(rec5[4 + 4 * i : 8 + 4 * i], strip=False) for i in range(ntyp)
    )
    pollutants = tuple(p.rstrip() for p in pollutants_raw)

    if cpack not in (0, 1):
        raise CdumpFormatError(f"{path}: unsupported packing flag CPACK={cpack}")

    return CdumpHeader(
        path=path,
        endian=e,
        model=_decode_char4(model_raw, strip=True),
        meteorology_start=met_start,
        forecast_hour=int(ich),
        packing_flag=int(cpack),
        releases=tuple(releases),
        grid=grid,
        levels_m=tuple(int(v) for v in levels),
        pollutants=pollutants,
        pollutants_raw=pollutants_raw,
    )


def read_cdump_header(path: os.PathLike[str] | str) -> CdumpHeader:
    """Read cdump records 1--5 without loading any concentration data."""
    with _FortranSequentialReader(path) as reader:
        return _read_header_from_open(reader)


def read_cdump_file_list(path: os.PathLike[str] | str) -> list[str]:
    """Read a text file containing cdump paths.

    Rules are intentionally simple and shell-friendly:

    - one cdump path or wildcard per line;
    - blank lines are ignored;
    - lines whose first nonblank character is ``#`` are ignored;
    - paths relative to the list file are resolved relative to that list file;
    - nested list files are allowed with ``@other_list.txt``.

    The returned paths are not checked here; wildcard expansion and existence
    checks are done by :func:`_normalize_files`.
    """
    list_path = os.path.abspath(os.path.expanduser(os.path.expandvars(os.fspath(path))))
    base_dir = os.path.dirname(list_path)
    if not os.path.isfile(list_path):
        raise FileNotFoundError(list_path)

    items: list[str] = []
    with open(list_path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue

            # Allow simple quoted paths, while preserving spaces inside the path.
            if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
                text = text[1:-1]

            if text.startswith("@"):
                nested = text[1:].strip()
                if not nested:
                    raise ValueError(f"{list_path}:{lineno}: empty nested list reference")
                nested = os.path.expanduser(os.path.expandvars(nested))
                if not os.path.isabs(nested):
                    nested = os.path.join(base_dir, nested)
                items.extend(read_cdump_file_list(nested))
                continue

            text = os.path.expanduser(os.path.expandvars(text))
            if not os.path.isabs(text):
                text = os.path.join(base_dir, text)
            items.append(text)

    return items


def _normalize_files(
    files: os.PathLike[str] | str | Sequence[os.PathLike[str] | str] | None,
    *,
    file_lists: os.PathLike[str] | str | Sequence[os.PathLike[str] | str] | None = None,
) -> list[str]:
    if files is None:
        raw_files: list[os.PathLike[str] | str] = []
    elif isinstance(files, (str, os.PathLike)):
        raw_files = [files]
    else:
        raw_files = list(files)

    if file_lists is None:
        raw_lists: list[os.PathLike[str] | str] = []
    elif isinstance(file_lists, (str, os.PathLike)):
        raw_lists = [file_lists]
    else:
        raw_lists = list(file_lists)

    expanded_inputs: list[str] = []
    for item in raw_files:
        text = os.fspath(item)
        if text.startswith("@"):
            list_name = text[1:].strip()
            if not list_name:
                raise ValueError("empty @file-list reference")
            expanded_inputs.extend(read_cdump_file_list(list_name))
        else:
            expanded_inputs.append(text)

    for list_item in raw_lists:
        expanded_inputs.extend(read_cdump_file_list(list_item))

    if not expanded_inputs:
        raise ValueError("at least one cdump file or --file-list is required")

    expanded: list[str] = []
    for item in expanded_inputs:
        text = os.path.expanduser(os.path.expandvars(os.fspath(item)))
        if glob.has_magic(text):
            matches = sorted(glob.glob(text))
            if not matches:
                raise FileNotFoundError(f"no files match {text!r}")
            expanded.extend(matches)
        else:
            expanded.append(text)

    result: list[str] = []
    seen: set[str] = set()
    for item in expanded:
        path = os.path.abspath(os.path.expanduser(os.path.expandvars(item)))
        if path not in seen:
            if not os.path.isfile(path):
                raise FileNotFoundError(path)
            result.append(path)
            seen.add(path)
    return result


def _normalize_source_factors(
    factor: float | Sequence[float] | NDArray[np.floating[Any]] | None,
    nfiles: int,
) -> NDArray[np.float64]:
    """Return one source/file coefficient for each expanded input cdump file.

    The rd_cdump_tsum convention is:

        output = sum_i factor[i] * cdump_file[i]

    This is intended for source/emission inverse modeling.  It is deliberately
    not a vertical-layer multiplier.  A single factor is broadcast to all files;
    otherwise the number of factors must match the number of expanded files.
    """
    if factor is None:
        return np.ones(nfiles, dtype=np.float64)
    values = np.asarray(factor, dtype=np.float64).reshape(-1)
    if values.size == 0:
        raise ValueError("factor cannot be empty")
    if values.size == 1:
        return np.full(nfiles, float(values[0]), dtype=np.float64)
    if values.size != nfiles:
        raise ValueError(
            f"factor is a source/file coefficient. After wildcard expansion there are "
            f"{nfiles} input file(s), but {values.size} factor value(s) were given. "
            "Use one factor for all files or exactly one factor per file."
        )
    return values.astype(np.float64, copy=False)


def _validate_compatible(reference: CdumpHeader, other: CdumpHeader) -> None:
    rg = reference.grid
    og = other.grid
    if (rg.nx, rg.ny) != (og.nx, og.ny):
        raise ValueError(
            f"incompatible grid size: {other.path} has {(og.nx, og.ny)}, "
            f"expected {(rg.nx, rg.ny)}"
        )
    if not np.allclose(
        [rg.x0, rg.y0, rg.dx, rg.dy],
        [og.x0, og.y0, og.dx, og.dy],
        rtol=0.0,
        atol=1.0e-6,
    ):
        raise ValueError(f"incompatible horizontal grid in {other.path}")
    if reference.levels_m != other.levels_m:
        raise ValueError(
            f"incompatible vertical levels in {other.path}: {other.levels_m} != {reference.levels_m}"
        )
    if reference.pollutants_raw != other.pollutants_raw:
        raise ValueError(
            f"incompatible pollutant identifiers in {other.path}: "
            f"{other.pollutants_raw} != {reference.pollutants_raw}"
        )


def _as_index_list(values: Any, *, default: int, size: int, name: str) -> list[int]:
    if values is None:
        result = [default]
    elif np.isscalar(values):
        result = [int(values)]
    else:
        result = [int(v) for v in np.asarray(values).reshape(-1)]
    if not result:
        raise ValueError(f"{name} cannot be empty")
    bad = [v for v in result if v < 0 or v >= size]
    if bad:
        raise IndexError(f"{name} contains out-of-range indices {bad}; valid range is 0..{size-1}")
    return result


def _as_name_list(values: str | Sequence[str]) -> list[str]:
    if isinstance(values, str):
        raw = re.split(r"[,+\s]+", values.strip())
        return [v for v in raw if v]
    return [str(v).strip() for v in values if str(v).strip()]


def _resolve_selections(
    header: CdumpHeader,
    *,
    xlevel: int | Sequence[int] | NDArray[np.integer[Any]] | None,
    level: int | Sequence[int] | NDArray[np.integer[Any]] | None,
    xptype: int | Sequence[int] | NDArray[np.integer[Any]] | None,
    ptype: str | Sequence[str] | None,
) -> tuple[list[int], list[int]]:
    if level is not None:
        req = [int(v) for v in np.asarray(level).reshape(-1)]
        level_map = {int(v): i for i, v in enumerate(header.levels_m)}
        missing = [v for v in req if v not in level_map]
        if missing:
            raise ValueError(f"requested level(s) {missing} not found; available={header.levels_m}")
        level_indices = [level_map[v] for v in req]
    else:
        level_indices = _as_index_list(
            xlevel,
            default=0,
            size=len(header.levels_m),
            name="xlevel",
        )

    if ptype is not None:
        requested_names = _as_name_list(ptype)
        ptype_map = {value.rstrip(): i for i, value in enumerate(header.pollutants)}
        missing = [value for value in requested_names if value not in ptype_map]
        if missing:
            raise ValueError(f"requested pollutant(s) {missing} not found; available={header.pollutants}")
        ptype_indices = [ptype_map[value] for value in requested_names]
    else:
        ptype_indices = _as_index_list(
            xptype,
            default=0,
            size=len(header.pollutants),
            name="xptype",
        )

    return level_indices, ptype_indices


def _parse_tflag_one(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None, second=0, microsecond=0)
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            raise ValueError("tflag contains NaT")
        minute = value.astype("datetime64[m]")
        text = np.datetime_as_string(minute, unit="m")
        return datetime.fromisoformat(text)

    text = str(value).strip()
    if not text:
        raise ValueError("empty timestamp")
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 8:
        raise ValueError(f"timestamp {value!r} needs at least YYYYMMDD")
    compact = (digits + "0000")[:12]
    try:
        return datetime.strptime(compact, "%Y%m%d%H%M")
    except ValueError as exc:
        raise ValueError(f"invalid timestamp {value!r}") from exc


def _normalize_tflag(tflag: Any | Sequence[Any] | None) -> list[datetime] | None:
    if tflag is None:
        return None
    if isinstance(tflag, (str, datetime, np.datetime64)) or np.isscalar(tflag):
        values = [tflag]
    else:
        values = list(tflag)
    if not values:
        raise ValueError("tflag cannot be empty")
    return [_parse_tflag_one(value) for value in values]


def _parse_date_key(value: Any) -> str:
    """Return YYYYMMDD for a user-supplied date token."""
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            raise ValueError("date contains NaT")
        text = np.datetime_as_string(value.astype("datetime64[D]"), unit="D")
        return text.replace("-", "")

    text = str(value).strip()
    if not text:
        raise ValueError("empty date")
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 8:
        raise ValueError(f"date {value!r} needs YYYYMMDD")
    key = digits[:8]
    try:
        datetime.strptime(key, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"invalid date {value!r}") from exc
    return key


def _normalize_dates(date: Any | Sequence[Any] | None) -> list[str] | None:
    if date is None:
        return None
    if isinstance(date, (str, datetime, np.datetime64)) or np.isscalar(date):
        values = [date]
    else:
        values = list(date)
    if not values:
        raise ValueError("date cannot be empty")
    # Preserve user order but remove duplicates.
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = _parse_date_key(value)
        if key not in seen:
            result.append(key)
            seen.add(key)
    return result


def _normalize_time_bound(value: Any | None, *, name: str) -> datetime | None:
    if value is None:
        return None
    try:
        return _parse_tflag_one(value)
    except ValueError as exc:
        raise ValueError(f"invalid {name}: {value!r}") from exc


def _select_times_by_filter(
    observed: Iterable[datetime],
    *,
    dates: Sequence[str] | None,
    stime: datetime | None,
    etime: datetime | None,
) -> list[datetime]:
    """Filter observed sample-start times by date list or start/end bounds."""
    work = sorted(set(observed))
    if dates is not None:
        date_set = set(dates)
        return [t for t in work if t.strftime("%Y%m%d") in date_set]
    if stime is not None:
        work = [t for t in work if t >= stime]
    if etime is not None:
        work = [t for t in work if t <= etime]
    return work


def _time_filter_description(
    *,
    tflag: Any | Sequence[Any] | None,
    dates: Sequence[str] | None,
    stime: datetime | None,
    etime: datetime | None,
) -> dict[str, Any]:
    if tflag is not None:
        return {"mode": "tflag", "requested": [v.strftime("%Y%m%d%H%M") for v in (_normalize_tflag(tflag) or [])]}
    if dates is not None:
        return {"mode": "date", "dates": list(dates), "time_basis": "sample_start"}
    if stime is not None or etime is not None:
        return {
            "mode": "range",
            "stime": None if stime is None else stime.strftime("%Y%m%d%H%M"),
            "etime": None if etime is None else etime.strftime("%Y%m%d%H%M"),
            "time_basis": "sample_start",
        }
    return {"mode": "all_observed_nonempty", "time_basis": "sample_start"}


def _date_spacing(times: Sequence[datetime], *, sort_unique: bool, max_steps: int) -> list[datetime]:
    """Python equivalent of the IDL date_spacing behavior."""
    work = sorted(set(times)) if sort_unique else list(times)
    if not work:
        return []
    if len(work) == 1:
        return [work[0]]
    deltas = [work[i + 1] - work[i] for i in range(len(work) - 1)]
    if any(delta.total_seconds() <= 0.0 for delta in deltas):
        raise ValueError("tflag must be strictly increasing for IDL date_spacing behavior")
    step = min(deltas)
    total = work[-1] - work[0]
    nsteps = int(total // step) + 1
    if nsteps <= 0 or nsteps > max_steps:
        raise ValueError(f"date_spacing would create {nsteps:,} timestamps")
    return [work[0] + i * step for i in range(nsteps)]


def _read_time_pair(reader: _FortranSequentialReader) -> tuple[datetime, datetime] | None:
    start_payload = reader.read_record(allow_eof=True)
    if start_payload is None:
        return None
    if len(start_payload) != 24:
        raise CdumpFormatError(
            f"{reader.path}: sample-start record should contain 24 bytes, got {len(start_payload)}"
        )
    stop_payload = reader.read_record()
    if stop_payload is None or len(stop_payload) != 24:
        raise CdumpFormatError(
            f"{reader.path}: sample-stop record should contain 24 bytes, got {0 if stop_payload is None else len(stop_payload)}"
        )
    start_values = struct.unpack(reader.endian + "6i", start_payload)
    stop_values = struct.unpack(reader.endian + "6i", stop_payload)
    try:
        return _datetime_from_six(start_values), _datetime_from_six(stop_values)
    except ValueError as exc:
        raise CdumpFormatError(f"{reader.path}: invalid sample timestamp") from exc


def _packed_record_is_nonempty(record_length: int, path: str) -> bool:
    if record_length < 12 or (record_length - 12) % 8 != 0:
        raise CdumpFormatError(f"{path}: invalid packed concentration-record length {record_length}")
    return record_length > 12


def _scan_nonempty_times(path: str, *, selected_levels: set[int], selected_ptypes: set[int]) -> set[datetime]:
    """Fast first pass: seek over concentration payloads and collect timestamps."""
    observed: set[datetime] = set()
    with _FortranSequentialReader(path) as reader:
        header = _read_header_from_open(reader)
        nlev = len(header.levels_m)
        ntyp = len(header.pollutants)

        while True:
            pair = _read_time_pair(reader)
            if pair is None:
                break
            start, _stop = pair
            has_selected_nonempty = False
            for iptype in range(ntyp):
                p_selected = iptype in selected_ptypes
                for ilevel in range(nlev):
                    nbytes = reader.skip_record()
                    assert nbytes is not None
                    if p_selected and ilevel in selected_levels:
                        if header.packing_flag == 1:
                            if _packed_record_is_nonempty(nbytes, path):
                                has_selected_nonempty = True
                        else:
                            expected = 8 + 4 * header.grid.nx * header.grid.ny
                            if nbytes != expected:
                                raise CdumpFormatError(
                                    f"{path}: unpacked record length {nbytes}; expected {expected}"
                                )
                            has_selected_nonempty = True
            if has_selected_nonempty:
                observed.add(start)
    return observed


def _release_reference(
    header: CdumpHeader,
    mode: Literal["idl", "exact", "first", "earliest"],
) -> datetime:
    if not header.releases:
        raise CdumpFormatError(f"{header.path}: no release records available for decay")
    if mode == "idl":
        t = header.releases[-1].time
        return t.replace(minute=0, second=0, microsecond=0)
    if mode == "exact":
        return header.releases[-1].time
    if mode == "first":
        return header.releases[0].time
    if mode == "earliest":
        return min(item.time for item in header.releases)
    raise ValueError(f"unknown decay_reference={mode!r}")


def _scatter_packed(
    payload: bytes,
    *,
    endian: str,
    expected_pollutant_raw: str,
    expected_level: int,
    destination_flat: NDArray[np.floating[Any]],
    nx: int,
    ny: int,
    scale: np.floating[Any] | float,
    strict: bool,
) -> int:
    if len(payload) < 12:
        raise CdumpFormatError("packed concentration record is shorter than 12 bytes")

    pollutant_raw = _decode_char4(payload[:4], strip=False)
    level, count = struct.unpack_from(endian + "2i", payload, 4)
    expected_length = 12 + count * 8
    if count < 0 or len(payload) != expected_length:
        raise CdumpFormatError(
            f"packed record length {len(payload)} does not match NXYP={count} (expected {expected_length})"
        )
    if strict:
        if pollutant_raw != expected_pollutant_raw:
            raise CdumpFormatError(f"pollutant record order mismatch: {pollutant_raw!r} != {expected_pollutant_raw!r}")
        if level != expected_level:
            raise CdumpFormatError(f"level record order mismatch: {level} != {expected_level}")
    if count == 0:
        return 0

    ip = np.ndarray(shape=(count,), dtype=endian + "i2", buffer=payload, offset=12, strides=(8,)).astype(np.int32)
    jp = np.ndarray(shape=(count,), dtype=endian + "i2", buffer=payload, offset=14, strides=(8,)).astype(np.int32)
    values = np.ndarray(shape=(count,), dtype=endian + "f4", buffer=payload, offset=16, strides=(8,))

    if strict and (np.any(ip < 1) or np.any(ip > nx) or np.any(jp < 1) or np.any(jp > ny)):
        raise CdumpFormatError("packed concentration record contains out-of-grid indices")

    flat_index = (jp - 1) * nx + (ip - 1)
    destination_flat[flat_index] += values * scale
    return count


def _add_unpacked(
    payload: bytes,
    *,
    endian: str,
    expected_pollutant_raw: str,
    expected_level: int,
    destination_yx: NDArray[np.floating[Any]],
    nx: int,
    ny: int,
    scale: np.floating[Any] | float,
    strict: bool,
) -> bool:
    expected_length = 8 + 4 * nx * ny
    if len(payload) != expected_length:
        raise CdumpFormatError(f"unpacked record length {len(payload)}; expected {expected_length}")
    pollutant_raw = _decode_char4(payload[:4], strip=False)
    level = struct.unpack_from(endian + "i", payload, 4)[0]
    if strict:
        if pollutant_raw != expected_pollutant_raw:
            raise CdumpFormatError(f"pollutant record order mismatch: {pollutant_raw!r} != {expected_pollutant_raw!r}")
        if level != expected_level:
            raise CdumpFormatError(f"level record order mismatch: {level} != {expected_level}")

    values = np.frombuffer(payload, dtype=endian + "f4", count=nx * ny, offset=8)
    values_yx = values.reshape(ny, nx)
    destination_yx += values_yx * scale
    return bool(np.any(values_yx != 0.0))


def _accumulate_file(
    path: str,
    *,
    factor: float,
    selected_levels: set[int],
    selected_ptypes: set[int],
    level_weights: NDArray[np.float64],
    time_to_index: Mapping[datetime, int],
    output_tyx: NDArray[np.floating[Any]],
    decay_days: float | None,
    decay_reference: Literal["idl", "exact", "first", "earliest"],
    strict: bool,
) -> bool:
    """Stream one file into the final output; return whether selected data exist."""
    any_selected_nonempty = False
    with _FortranSequentialReader(path) as reader:
        header = _read_header_from_open(reader)
        nlev = len(header.levels_m)
        ntyp = len(header.pollutants)
        nx, ny = header.grid.nx, header.grid.ny
        release_ref = _release_reference(header, decay_reference) if decay_days is not None else None

        scalar_type = output_tyx.dtype.type
        file_factor = scalar_type(factor)

        while True:
            pair = _read_time_pair(reader)
            if pair is None:
                break
            start, _stop = pair
            out_index = time_to_index.get(start)

            if decay_days is None:
                decay_scale = scalar_type(1.0)
            else:
                assert release_ref is not None
                age_days = scalar_type((start - release_ref).total_seconds() / 86400.0)
                decay_scale = scalar_type(0.5) ** (age_days / scalar_type(decay_days))

            base_scale = file_factor * decay_scale

            for iptype in range(ntyp):
                p_selected = iptype in selected_ptypes
                for ilevel in range(nlev):
                    selected = p_selected and ilevel in selected_levels
                    if selected and out_index is not None:
                        payload = reader.read_record()
                        assert payload is not None
                        scale = base_scale * scalar_type(level_weights[ilevel])
                        if header.packing_flag == 1:
                            count = _scatter_packed(
                                payload,
                                endian=reader.endian,
                                expected_pollutant_raw=header.pollutants_raw[iptype],
                                expected_level=header.levels_m[ilevel],
                                destination_flat=output_tyx[out_index].reshape(-1),
                                nx=nx,
                                ny=ny,
                                scale=scale,
                                strict=strict,
                            )
                            if count > 0:
                                any_selected_nonempty = True
                        else:
                            _nonzero = _add_unpacked(
                                payload,
                                endian=reader.endian,
                                expected_pollutant_raw=header.pollutants_raw[iptype],
                                expected_level=header.levels_m[ilevel],
                                destination_yx=output_tyx[out_index],
                                nx=nx,
                                ny=ny,
                                scale=scale,
                                strict=strict,
                            )
                            any_selected_nonempty = True
                    else:
                        nbytes = reader.skip_record()
                        assert nbytes is not None
                        if selected:
                            if header.packing_flag == 1:
                                if _packed_record_is_nonempty(nbytes, path):
                                    any_selected_nonempty = True
                            else:
                                expected = 8 + 4 * nx * ny
                                if nbytes != expected:
                                    raise CdumpFormatError(
                                        f"{path}: unpacked record length {nbytes}; expected {expected}"
                                    )
                                any_selected_nonempty = True
    return any_selected_nonempty


def _header_to_ini(header: CdumpHeader) -> dict[str, Any]:
    if header.releases:
        last = header.releases[-1].time
        rel_time = last.strftime("%Y%m%d%H")
    else:
        rel_time = ""
    return {
        "model": header.model,
        "iyr": header.meteorology_start.year % 100,
        "imo": header.meteorology_start.month,
        "ida": header.meteorology_start.day,
        "ihr": header.meteorology_start.hour,
        "ich": header.forecast_hour,
        "nloc": len(header.releases),
        "cpack": header.packing_flag,
        "nlat": header.grid.ny,
        "nlon": header.grid.nx,
        "dlat": header.grid.dy,
        "dlon": header.grid.dx,
        "clat": header.grid.y0,
        "clon": header.grid.x0,
        "nlvl": len(header.levels_m),
        "height": np.asarray(header.levels_m, dtype=np.int32),
        "ntyp": len(header.pollutants),
        "ident": header.pollutants_raw,
        "meto_time": header.meteorology_start.strftime("%Y%m%d%H"),
        "rel_time": rel_time,
    }


def _release_dict(item: ReleaseInfo) -> dict[str, Any]:
    return {
        "time": item.time,
        "ibyr": item.time.year % 100,
        "ibmo": item.time.month,
        "ibda": item.time.day,
        "ibhr": item.time.hour,
        "imn": item.time.minute,
        "olat": item.latitude,
        "olon": item.longitude,
        "olvl": item.height_m,
    }


def rd_cdump_tsum(
    files: os.PathLike[str] | str | Sequence[os.PathLike[str] | str],
    *,
    xlevel: int | Sequence[int] | NDArray[np.integer[Any]] | None = None,
    level: int | Sequence[int] | NDArray[np.integer[Any]] | None = None,
    xptype: int | Sequence[int] | NDArray[np.integer[Any]] | None = None,
    ptype: str | Sequence[str] | None = None,
    tflag: Any | Sequence[Any] | None = None,
    date: Any | Sequence[Any] | None = None,
    stime: Any | None = None,
    etime: Any | None = None,
    factor: float | Sequence[float] | NDArray[np.floating[Any]] | None = None,
    decay: float | None = None,
    vmean: bool = False,
    nan: bool = False,
    order: Literal["idl", "tyx"] = "idl",
    dtype: DTypeLike = np.float32,
    decay_reference: Literal["idl", "exact", "first", "earliest"] = "idl",
    strict: bool = True,
    max_time_steps: int = 10_000_000,
) -> tuple[NDArray[np.floating[Any]], dict[str, Any]] | tuple[None, None]:
    """Read, merge, decay, and vertically aggregate multiple cdump files.

    Default output order is IDL-compatible [x, y, time].  Use order="tyx" for
    C-contiguous [time, y, x], which is the order used by save_hygv_netcdf.
    """
    paths = _normalize_files(files)
    factors = _normalize_source_factors(factor, len(paths))

    out_dtype = np.dtype(dtype)
    if out_dtype.kind != "f":
        raise TypeError("dtype must be a floating-point dtype")
    if decay is not None and (not np.isfinite(decay) or decay <= 0.0):
        raise ValueError("decay must be a finite, positive half-life in days")
    if order not in ("idl", "tyx"):
        raise ValueError("order must be 'idl' or 'tyx'")

    dates = _normalize_dates(date)
    stime_dt = _normalize_time_bound(stime, name="stime")
    etime_dt = _normalize_time_bound(etime, name="etime")
    if dates is not None and (stime_dt is not None or etime_dt is not None):
        raise ValueError("do not combine date with stime/etime; use one time-selection mode")
    if tflag is not None and (dates is not None or stime_dt is not None or etime_dt is not None):
        raise ValueError("do not combine tflag with date/stime/etime; use one time-selection mode")
    if stime_dt is not None and etime_dt is not None and stime_dt > etime_dt:
        raise ValueError("stime must be earlier than or equal to etime")

    reference = read_cdump_header(paths[0])
    selected_level_list, selected_ptype_list = _resolve_selections(
        reference, xlevel=xlevel, level=level, xptype=xptype, ptype=ptype
    )
    selected_levels = set(selected_level_list)
    selected_ptypes = set(selected_ptype_list)

    headers: list[CdumpHeader] = []
    active_indices: list[int] = []
    for i, path in enumerate(paths):
        header = reference if i == 0 else read_cdump_header(path)
        headers.append(header)
        if factors[i] != 0.0:
            _validate_compatible(reference, header)
            active_indices.append(i)

    if not active_indices:
        return None, None

    heights = np.asarray(reference.levels_m, dtype=np.float64)
    depths = np.empty_like(heights)
    if heights.size == 1:
        depths[0] = heights[0]
    else:
        depths[0] = heights[0]
        depths[1:] = np.diff(heights)

    if vmean:
        level_weights = depths.copy()
        denominator = float(np.sum(depths[np.asarray(selected_level_list, dtype=int)]))
        if denominator == 0.0:
            warnings.warn(
                "selected vertical depth sums to zero; vertical mean will produce NaN/Inf",
                RuntimeWarning,
                stacklevel=2,
            )
    else:
        level_weights = np.ones_like(depths)
        denominator = 1.0

    requested_times = _normalize_tflag(tflag)
    if requested_times is None:
        observed: set[datetime] = set()
        for i in active_indices:
            observed.update(
                _scan_nonempty_times(
                    paths[i],
                    selected_levels=selected_levels,
                    selected_ptypes=selected_ptypes,
                )
            )
        if not observed:
            return None, None
        if dates is not None or stime_dt is not None or etime_dt is not None:
            times = _select_times_by_filter(
                observed,
                dates=dates,
                stime=stime_dt,
                etime=etime_dt,
            )
        else:
            times = _date_spacing(sorted(observed), sort_unique=True, max_steps=max_time_steps)
        if not times:
            return None, None
    else:
        times = _date_spacing(requested_times, sort_unique=False, max_steps=max_time_steps)

    time_to_index = {value: i for i, value in enumerate(times)}
    grid = reference.grid
    output_tyx = np.zeros((len(times), grid.ny, grid.nx), dtype=out_dtype)

    any_selected_nonempty = False
    last_active_header = headers[active_indices[-1]]
    for i in active_indices:
        has_data = _accumulate_file(
            paths[i],
            factor=float(factors[i]),
            selected_levels=selected_levels,
            selected_ptypes=selected_ptypes,
            level_weights=level_weights,
            time_to_index=time_to_index,
            output_tyx=output_tyx,
            decay_days=decay,
            decay_reference=decay_reference,
            strict=strict,
        )
        any_selected_nonempty = any_selected_nonempty or has_data

    if not any_selected_nonempty:
        return None, None

    if vmean:
        with np.errstate(divide="ignore", invalid="ignore"):
            output_tyx /= out_dtype.type(denominator)

    if nan:
        output_tyx[output_tyx == 0.0] = np.nan

    tflag_strings = np.asarray([value.strftime("%Y%m%d%H%M") for value in times], dtype="U12")
    locations_by_file = {
        path: [_release_dict(item) for item in header.releases]
        for path, header in zip(paths, headers)
    }
    headers_by_file = {path: header for path, header in zip(paths, headers)}

    loc = [_release_dict(item) for item in last_active_header.releases]
    ini = _header_to_ini(last_active_header)
    minfo = asdict(reference.grid)

    info: dict[str, Any] = {
        "tflag": tflag_strings,
        "times": np.asarray(times, dtype="datetime64[m]"),
        "times_py": tuple(times),
        "time_filter": _time_filter_description(tflag=tflag, dates=dates, stime=stime_dt, etime=etime_dt),
        "minfo": minfo,
        "loc": loc,
        "ini": ini,
        "files": tuple(paths),
        "source_factor": factors.copy(),
        "factor": factors.copy(),  # compatibility alias; means source/file coefficient
        "factor_meaning": "source/file coefficient: output = sum_i factor[i] * cdump_file[i]",
        "file_factor_mapping": tuple(
            {"file": paths[i], "factor": float(factors[i]), "active": bool(factors[i] != 0.0)}
            for i in range(len(paths))
        ),
        "active_files": tuple(paths[i] for i in active_indices),
        "headers_by_file": headers_by_file,
        "locations_by_file": locations_by_file,
        "xlevel": np.asarray(selected_level_list, dtype=np.int32),
        "level": np.asarray([reference.levels_m[i] for i in selected_level_list], dtype=np.int32),
        "xptype": np.asarray(selected_ptype_list, dtype=np.int32),
        "ptype": tuple(reference.pollutants[i] for i in selected_ptype_list),
        "ptype_raw": tuple(reference.pollutants_raw[i] for i in selected_ptype_list),
        "height": np.asarray(reference.levels_m, dtype=np.int32),
        "depth": depths.astype(np.float64, copy=False),
        "vertical_denominator": denominator,
        "vmean": bool(vmean),
        "nan": bool(nan),
        "decay_days": decay,
        "decay_reference": decay_reference,
        "lon": reference.grid.lon,
        "lat": reference.grid.lat,
        "packing_flags": tuple(header.packing_flag for header in headers),
        "array_order": order,
        "version": APP_VERSION,
    }

    if order == "idl":
        data = output_tyx.transpose(2, 1, 0)
    else:
        data = output_tyx
    return data, info


# -----------------------------------------------------------------------------
# HYGV / NetCDF saving helpers
# -----------------------------------------------------------------------------


def qround(x: float, q: float) -> float:
    x = float(x)
    q = float(q)
    if q <= 0.0:
        return x
    sgn = 1.0 if x >= 0.0 else -1.0
    return sgn * q * math.floor(abs(x) / q + 0.5)


def clean_float(x: Any, q: float = DEGREE_QUANTUM) -> float:
    y = qround(float(x), q)
    nearest_int = round(y)
    if abs(y - nearest_int) < INTEGER_SNAP_TOL:
        y = float(nearest_int)
    if q > 0.0:
        digits = int(round(-math.log10(q))) if q < 1.0 else 0
        if 0 <= digits <= 12:
            y = round(y, digits)
    return float(y)


def _jsonable(x: Any) -> Any:
    if isinstance(x, datetime):
        return x.isoformat(timespec="seconds")
    if isinstance(x, np.datetime64):
        if np.isnat(x):
            return None
        return np.datetime_as_string(x.astype("datetime64[s]"), unit="s")
    if isinstance(x, np.ndarray):
        return _jsonable(x.tolist())
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        value = float(x)
        return None if not math.isfinite(value) else value
    if isinstance(x, float):
        return None if not math.isfinite(x) else x
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, CdumpHeader):
        d = asdict(x)
        d.pop("endian", None)
        return _jsonable(d)
    if isinstance(x, (str, int)) or x is None or isinstance(x, bool):
        return x
    return str(x)


def _json_attr(x: Any) -> str:
    return json.dumps(_jsonable(x), ensure_ascii=False, separators=(",", ":"))


def _set_ncattr(obj: Any, name: str, value: Any) -> None:
    """Set a NetCDF attribute using only NetCDF-supported scalar types.

    netCDF4 does not accept Python bool attributes directly.  Store bools
    as 0/1 integers so flags such as VMEAN and ZERO_TO_NAN are portable.
    """
    if value is None:
        obj.setncattr(name, "")
    elif isinstance(value, (list, tuple, dict, np.ndarray, CdumpHeader)):
        obj.setncattr(name, _json_attr(value))
    elif isinstance(value, datetime):
        obj.setncattr(name, value.isoformat(timespec="seconds"))
    elif isinstance(value, (bool, np.bool_)):
        obj.setncattr(name, int(value))
    elif isinstance(value, np.integer):
        obj.setncattr(name, int(value))
    elif isinstance(value, np.floating):
        obj.setncattr(name, float(value))
    else:
        obj.setncattr(name, value)


def _set_varattr(var: Any, name: str, value: Any) -> None:
    if isinstance(value, (list, tuple, np.ndarray)):
        arr = np.asarray(value)
        if arr.dtype.kind in "iuf" and arr.ndim <= 1:
            var.setncattr(name, arr.astype(np.float64))
        elif arr.dtype.kind == "b" and arr.ndim <= 1:
            var.setncattr(name, arr.astype(np.int8))
        else:
            _set_ncattr(var, name, value)
    elif isinstance(value, (bool, np.bool_)):
        var.setncattr(name, int(value))
    elif isinstance(value, np.integer):
        var.setncattr(name, int(value))
    elif isinstance(value, np.floating):
        var.setncattr(name, float(value))
    else:
        _set_ncattr(var, name, value)


def sanitize_nc_name(name: Any, default: str = "CONC") -> str:
    label = str(name).strip()
    label = re.sub(r"[^0-9A-Za-z_]", "_", label)
    label = re.sub(r"_+", "_", label).strip("_")
    if not label:
        label = default
    if label[0].isdigit():
        label = f"V_{label}"
    return label


def lonlat_to_wm(lon: Any, lat: Any) -> tuple[np.ndarray, np.ndarray]:
    lon_arr = np.asarray(lon, dtype=np.float64)
    lat_arr = np.asarray(lat, dtype=np.float64)
    lat_clip = np.clip(lat_arr, -WEB_MERCATOR_LAT_LIMIT, WEB_MERCATOR_LAT_LIMIT)
    x = WEB_MERCATOR_R * np.deg2rad(lon_arr)
    y = WEB_MERCATOR_R * np.log(np.tan(np.pi / 4.0 + np.deg2rad(lat_clip) / 2.0))
    return x, y


def wm_to_lonlat(x: Any, y: Any) -> tuple[np.ndarray, np.ndarray]:
    x_arr = np.asarray(x, dtype=np.float64)
    y_arr = np.asarray(y, dtype=np.float64)
    lon = np.rad2deg(x_arr / WEB_MERCATOR_R)
    lat = np.rad2deg(2.0 * np.arctan(np.exp(y_arr / WEB_MERCATOR_R)) - np.pi / 2.0)
    return lon, lat


def round_bbox_outer(bbox: Sequence[float], ndigits: int = 2) -> tuple[float, float, float, float]:
    south, west, north, east = [float(v) for v in bbox]
    q = 10.0 ** (-int(ndigits))
    return (
        math.floor(south / q) * q,
        math.floor(west / q) * q,
        math.ceil(north / q) * q,
        math.ceil(east / q) * q,
    )


def source_outer_bbox_from_minfo(minfo: Mapping[str, Any], *, ndigits: int = 2) -> tuple[float, float, float, float]:
    grid = GridInfo(
        x0=float(minfo["x0"]),
        y0=float(minfo["y0"]),
        dx=float(minfo["dx"]),
        dy=float(minfo["dy"]),
        nx=int(minfo["nx"]),
        ny=int(minfo["ny"]),
    )
    return round_bbox_outer(grid.edge_bbox, ndigits)


def _make_wm_grid(
    source_grid: GridInfo,
    bbox_ll: Sequence[float],
    *,
    wm_dim: Sequence[int] | None,
    wm_res_m: float | None,
    wm_res_km: float | None,
    wm_max_dim: int,
) -> dict[str, Any]:
    south, west, north, east = [float(v) for v in bbox_ll]
    x0, y0 = lonlat_to_wm(west, south)
    x1, y1 = lonlat_to_wm(east, north)
    x0f, y0f, x1f, y1f = map(float, [x0, y0, x1, y1])
    if x1f < x0f:
        x0f, x1f = x1f, x0f
    if y1f < y0f:
        y0f, y1f = y1f, y0f
    width = x1f - x0f
    height = y1f - y0f
    if width <= 0 or height <= 0:
        raise ValueError("invalid bbox for Web Mercator output")

    if wm_dim is not None:
        nx, ny = int(wm_dim[0]), int(wm_dim[1])
        if nx < 2 or ny < 2:
            raise ValueError("--wm-dim requires NX NY both >= 2")
        res_m = max(width / (nx - 1), height / (ny - 1))
        source = "manual_dimension"
    else:
        if wm_res_km is not None:
            res_m = float(wm_res_km) * 1000.0
            source = "manual_resolution_km"
        elif wm_res_m is not None:
            res_m = float(wm_res_m)
            source = "manual_resolution_m"
        else:
            # Native-ish Web Mercator spacing estimated from full source grid bbox.
            s_south, s_west, s_north, s_east = source_grid.edge_bbox
            sx0, sy0 = lonlat_to_wm(s_west, s_south)
            sx1, sy1 = lonlat_to_wm(s_east, s_north)
            source_width = abs(float(sx1) - float(sx0))
            source_height = abs(float(sy1) - float(sy0))
            source_dx = source_width / max(1, source_grid.nx - 1)
            source_dy = source_height / max(1, source_grid.ny - 1)
            res_m = max(source_dx, source_dy)
            source = "auto_from_source_grid"
        if res_m <= 0 or not math.isfinite(res_m):
            raise ValueError("invalid Web Mercator resolution")
        nx = int(round(width / res_m)) + 1
        ny = int(round(height / res_m)) + 1

        if wm_max_dim and max(nx, ny) > wm_max_dim:
            scale_res = max(width, height) / max(1, wm_max_dim - 1)
            res_m = max(res_m, scale_res)
            nx = int(round(width / res_m)) + 1
            ny = int(round(height / res_m)) + 1
            source = source + "_capped"

        nx = max(2, nx)
        ny = max(2, ny)

    x = np.linspace(x0f, x1f, nx, dtype=np.float64)
    y = np.linspace(y0f, y1f, ny, dtype=np.float64)
    dx = float((x1f - x0f) / (nx - 1))
    dy = float((y1f - y0f) / (ny - 1))
    return {
        "x": x,
        "y": y,
        "nx": nx,
        "ny": ny,
        "x0": clean_float(x0f, METER_QUANTUM),
        "y0": clean_float(y0f, METER_QUANTUM),
        "x1": clean_float(x1f, METER_QUANTUM),
        "y1": clean_float(y1f, METER_QUANTUM),
        "dx": clean_float(dx, METER_QUANTUM),
        "dy": clean_float(dy, METER_QUANTUM),
        "res_m": clean_float(res_m, METER_QUANTUM),
        "resolution_source": source,
    }


def _make_wm_lookup(source_grid: GridInfo, wm_grid: Mapping[str, Any]) -> dict[str, Any]:
    x = wm_grid["x"]
    y = wm_grid["y"]
    xx, yy = np.meshgrid(x, y)
    lon, lat = wm_to_lonlat(xx, yy)
    ix = np.rint((lon - source_grid.x0) / source_grid.dx).astype(np.int64)
    iy = np.rint((lat - source_grid.y0) / source_grid.dy).astype(np.int64)
    valid = (ix >= 0) & (ix < source_grid.nx) & (iy >= 0) & (iy < source_grid.ny)
    ix_safe = np.where(valid, ix, 0)
    iy_safe = np.where(valid, iy, 0)
    return {"ix": ix_safe, "iy": iy_safe, "valid": valid}


def _resample_tyx_to_wm(
    data_tyx: NDArray[np.floating[Any]],
    source_grid: GridInfo,
    bbox_ll: Sequence[float],
    *,
    wm_dim: Sequence[int] | None = None,
    wm_res_m: float | None = None,
    wm_res_km: float | None = None,
    wm_max_dim: int = DEFAULT_WM_MAX_DIM,
    fill_value: float = np.nan,
    flip_y: bool = False,
) -> tuple[NDArray[np.floating[Any]], dict[str, Any]]:
    wm_grid = _make_wm_grid(
        source_grid,
        bbox_ll,
        wm_dim=wm_dim,
        wm_res_m=wm_res_m,
        wm_res_km=wm_res_km,
        wm_max_dim=wm_max_dim,
    )
    lookup = _make_wm_lookup(source_grid, wm_grid)
    ix = lookup["ix"]
    iy = lookup["iy"]
    valid = lookup["valid"]
    nt = data_tyx.shape[0]
    out = np.full((nt, wm_grid["ny"], wm_grid["nx"]), fill_value, dtype=data_tyx.dtype)
    for it in range(nt):
        src = data_tyx[it]
        frame = np.full((wm_grid["ny"], wm_grid["nx"]), fill_value, dtype=data_tyx.dtype)
        frame[valid] = src[iy[valid], ix[valid]]
        if flip_y:
            frame = frame[::-1, :]
        out[it] = frame
    info = dict(wm_grid)
    info.pop("x", None)
    info.pop("y", None)
    info["flip_y"] = bool(flip_y)
    info["row_order"] = "north_to_south" if flip_y else "south_to_north"
    return out, info


def _require_netcdf4() -> Any:
    try:
        from netCDF4 import Dataset
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing netCDF4 package. Install it in the same Python environment:\n"
            "  python -m pip install netCDF4\n"
        ) from exc
    return Dataset


def _global_attrs_from_info(info: Mapping[str, Any]) -> dict[str, Any]:
    minfo = dict(info.get("minfo", {}))
    # Clean small floating-point noise before storing map metadata.
    for key in ("x0", "y0", "dx", "dy"):
        if key in minfo:
            minfo[key] = clean_float(minfo[key], DEGREE_QUANTUM)
    for key in ("nx", "ny"):
        if key in minfo:
            minfo[key] = int(minfo[key])

    return {
        "APP": "rd_cdump_tsum.py",
        "VERSION": APP_VERSION,
        "SOURCE_TYPE": "HYSPLIT cdump",
        "FILES": info.get("files"),
        "ACTIVE_FILES": info.get("active_files"),
        "TFLAG": info.get("tflag"),
        "TIME_STAMPS_ISO": [str(t).replace("T", " ") for t in info.get("times", [])],
        "TIME_FILTER": info.get("time_filter"),
        "MINFO": minfo,
        "LOC": info.get("loc"),
        "INI": info.get("ini"),
        "SOURCE_FACTOR": info.get("source_factor", info.get("factor")),
        "FACTOR": info.get("factor"),
        "FACTOR_MEANING": info.get("factor_meaning"),
        "FILE_FACTOR_MAPPING": info.get("file_factor_mapping"),
        "XLEVEL": info.get("xlevel"),
        "LEVEL": info.get("level"),
        "XPTYPE": info.get("xptype"),
        "PTYPE": info.get("ptype"),
        "PTYPE_RAW": info.get("ptype_raw"),
        "HEIGHT": info.get("height"),
        "DEPTH": info.get("depth"),
        "VMEAN": bool(info.get("vmean", False)),
        "VERTICAL_DENOMINATOR": info.get("vertical_denominator"),
        "DECAY_DAYS": info.get("decay_days"),
        "DECAY_REFERENCE": info.get("decay_reference"),
        "ZERO_TO_NAN": bool(info.get("nan", False)),
        "ARRAY_ORDER_WRITTEN": "tyx",
    }


def _format_utc12(value: Any) -> str:
    """Return a HYGV timestamp string, YYYYMMDDHHMM, from several time types."""
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d%H%M")
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            return "".ljust(12)
        text = np.datetime_as_string(value.astype("datetime64[m]"), unit="m")
        digits = re.sub(r"\D", "", text)
        return (digits + "0" * 12)[:12]

    text = str(value).strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 12:
        return digits[:12]
    if len(digits) == 10:
        return digits + "00"
    if len(digits) == 8:
        return digits + "0000"
    if digits:
        return (digits + "0" * 12)[:12]
    return text[:12].ljust(12)


def _utc_strings_from_info(info: Mapping[str, Any], nt: int) -> list[str]:
    """Return one UTC timestamp string per time step.

    HYGV's original NetCDF convention stores timestamps as a character variable:
        UTC(t, UTC_strlen)
    where UTC_strlen is 12 and the format is YYYYMMDDHHMM.  These timestamps
    are the sample-start times used by rd_cdump_tsum for time selection.
    """
    values: Any = info.get("tflag")
    if values is None:
        values = info.get("times_py")
    if values is None:
        values = info.get("times")
    if values is None:
        strings = ["".ljust(12) for _ in range(nt)]
    else:
        if isinstance(values, np.ndarray):
            seq = values.tolist()
        elif isinstance(values, (list, tuple)):
            seq = list(values)
        else:
            seq = [values]
        strings = [_format_utc12(v) for v in seq]

    if len(strings) != nt:
        raise ValueError(
            f"UTC timestamp count ({len(strings)}) does not match time dimension ({nt})"
        )
    return strings


def _strings_to_s1_matrix(strings: Sequence[str], strlen: int = 12) -> NDArray[np.bytes_]:
    """Convert fixed-length ASCII strings to a NetCDF char matrix."""
    out = np.full((len(strings), strlen), b" ", dtype="S1")
    for i, value in enumerate(strings):
        raw = str(value).encode("ascii", "replace")[:strlen].ljust(strlen, b" ")
        out[i, :] = np.frombuffer(raw, dtype="S1")
    return out


def save_hygv_netcdf(
    output: os.PathLike[str] | str,
    data_tyx: NDArray[np.floating[Any]],
    info: Mapping[str, Any],
    *,
    var_name: str = "CONC",
    hygv_proj: Literal["wm", "ll"] = "wm",
    bbox: Sequence[float] | None = None,
    bbox_round: int = 2,
    wm_dim: Sequence[int] | None = None,
    wm_res_m: float | None = None,
    wm_res_km: float | None = None,
    wm_max_dim: int = DEFAULT_WM_MAX_DIM,
    wm_flip_y: bool = False,
    fill_value: float = np.nan,
    gzip: bool = True,
    compression_level: int = DEFAULT_COMPRESSION_LEVEL,
) -> str:
    """Save a [time, y, x] array to a compact HYGV NetCDF file.

    The NetCDF file has one concentration variable plus a HYGV UTC character
    variable.  Most HYSPLIT/IDL metadata are stored in global attributes, and
    spatial display metadata are stored in the concentration variable attributes.
    """
    Dataset = _require_netcdf4()

    if data_tyx.ndim != 3:
        raise ValueError("save_hygv_netcdf expects data_tyx with shape [time, y, x]")

    minfo = info["minfo"]
    source_grid = GridInfo(
        x0=float(minfo["x0"]),
        y0=float(minfo["y0"]),
        dx=float(minfo["dx"]),
        dy=float(minfo["dy"]),
        nx=int(minfo["nx"]),
        ny=int(minfo["ny"]),
    )
    if bbox is None:
        bbox_ll = source_outer_bbox_from_minfo(minfo, ndigits=bbox_round)
        bbox_source = "auto_outer_source_image_edges"
    else:
        if len(bbox) != 4:
            raise ValueError("bbox must be LAT_MIN LON_MIN LAT_MAX LON_MAX")
        bbox_ll = tuple(float(v) for v in bbox)  # type: ignore[assignment]
        bbox_source = "manual"

    if hygv_proj == "wm":
        out_tyx, proj_info = _resample_tyx_to_wm(
            data_tyx,
            source_grid,
            bbox_ll,
            wm_dim=wm_dim,
            wm_res_m=wm_res_m,
            wm_res_km=wm_res_km,
            wm_max_dim=wm_max_dim,
            fill_value=fill_value,
            flip_y=wm_flip_y,
        )
        row_order = proj_info["row_order"]
        proj_attrs = {
            "PROJ": "wm",
            "EPSG": WEB_MERCATOR_EPSG,
            "BBOX": bbox_ll,
            "BBOX_LL": bbox_ll,
            "BBOX_ORDER": "LAT_MIN LON_MIN LAT_MAX LON_MAX",
            "BBOX_SOURCE": bbox_source,
            "WM_X0": proj_info["x0"],
            "WM_Y0": proj_info["y0"],
            "WM_X1": proj_info["x1"],
            "WM_Y1": proj_info["y1"],
            "WM_DX": proj_info["dx"],
            "WM_DY": proj_info["dy"],
            "WM_NX": proj_info["nx"],
            "WM_NY": proj_info["ny"],
            "WM_RES_M": proj_info["res_m"],
            "WM_RESOLUTION_SOURCE": proj_info["resolution_source"],
            "ROW_ORDER": row_order,
            "RESAMPLE_METHOD": "nearest",
        }
    elif hygv_proj == "ll":
        out_tyx = data_tyx
        row_order = "south_to_north" if source_grid.dy >= 0 else "north_to_south"
        proj_attrs = {
            "PROJ": "ll",
            "EPSG": 4326,
            "BBOX": bbox_ll,
            "BBOX_LL": bbox_ll,
            "BBOX_ORDER": "LAT_MIN LON_MIN LAT_MAX LON_MAX",
            "BBOX_SOURCE": bbox_source,
            "X0": clean_float(source_grid.x0, DEGREE_QUANTUM),
            "Y0": clean_float(source_grid.y0, DEGREE_QUANTUM),
            "DX": clean_float(source_grid.dx, DEGREE_QUANTUM),
            "DY": clean_float(source_grid.dy, DEGREE_QUANTUM),
            "NX": source_grid.nx,
            "NY": source_grid.ny,
            "ROW_ORDER": row_order,
            "RESAMPLE_METHOD": "none",
        }
    else:
        raise ValueError("hygv_proj must be 'wm' or 'll'")

    nt, ny, nx = out_tyx.shape
    output = os.fspath(output)
    Path(output).parent.mkdir(parents=True, exist_ok=True)

    encoding: dict[str, Any] = {}
    if gzip:
        encoding.update(zlib=True, complevel=int(compression_level), shuffle=True)

    with Dataset(output, "w", format="NETCDF4") as nc:
        nc.createDimension("TSTEP", nt)
        nc.createDimension("ROW", ny)
        nc.createDimension("COL", nx)
        nc.createDimension("UTC_strlen", 12)

        for key, value in _global_attrs_from_info(info).items():
            _set_ncattr(nc, key, value)
        _set_ncattr(nc, "HYGV", "true")
        _set_ncattr(nc, "HYGV_PROJ", hygv_proj)
        _set_ncattr(nc, "FILL_VALUE", "NaN" if math.isnan(float(fill_value)) else float(fill_value))

        utc_strings = _utc_strings_from_info(info, nt)
        utc_var = nc.createVariable("UTC", "S1", ("TSTEP", "UTC_strlen"))
        utc_var[:, :] = _strings_to_s1_matrix(utc_strings, 12)
        _set_varattr(utc_var, "long_name", "sample start time in UTC")
        _set_varattr(utc_var, "format", "YYYYMMDDHHMM")
        _set_varattr(utc_var, "time_basis", "sample_start")

        chunksizes = (1, min(ny, 256), min(nx, 256))
        vname = sanitize_nc_name(var_name, "CONC")
        if vname == "UTC":
            vname = "UTC_CONC"
        var = nc.createVariable(
            vname,
            "f4",
            ("TSTEP", "ROW", "COL"),
            fill_value=np.float32(fill_value),
            chunksizes=chunksizes,
            **encoding,
        )
        var[:, :, :] = out_tyx.astype(np.float32, copy=False)
        _set_varattr(var, "long_name", "HYSPLIT concentration processed by rd_cdump_tsum")
        _set_varattr(var, "units", "unknown")
        _set_varattr(var, "source_array_order", "TSTEP,ROW,COL")
        for key, value in proj_attrs.items():
            _set_varattr(var, key, value)

    return output


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def _parse_cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read/merge HYSPLIT cdump files like rd_cdump_tsum.pro and save NetCDF by default."
    )
    parser.add_argument("files", nargs="*", help="cdump paths, wildcards, or @list.txt references")
    parser.add_argument(
        "--file-list", "--files-from",
        dest="file_list",
        action="append",
        default=None,
        help=(
            "text file containing cdump paths to merge; one path or wildcard per line. "
            "Blank lines and lines starting with # are ignored. Paths are resolved "
            "relative to the list file. This option may be repeated."
        ),
    )
    parser.add_argument("-o", "--output", default=None, help="output file. Default: cdump_tsum.nc")
    parser.add_argument("--npz", action="store_true", help="save old/debug NPZ output instead of NetCDF")
    parser.add_argument("--hygv", action="store_true", help="compatibility flag: NetCDF/HYGV-style output is now the default")
    parser.add_argument("--hygv-proj", choices=("wm", "ll"), default=None, help="NetCDF projection: wm Web Mercator or ll lon/lat. Default: ll unless --hygv is used, then wm.")
    parser.add_argument("--var-name", default="CONC", help="NetCDF variable name for HYGV output")

    parser.add_argument("--xlevel", nargs="+", type=int, default=None, help="zero-based vertical level index/indices")
    parser.add_argument("--level", nargs="+", type=int, default=None, help="vertical level height(s) in meters")
    parser.add_argument("--xptype", nargs="+", type=int, default=None, help="zero-based pollutant index/indices")
    parser.add_argument("--ptype", nargs="+", default=None, help="pollutant name(s), e.g. P001")
    parser.add_argument("--tflag", nargs="+", default=None, help="requested sample-start timestamps YYYYMMDD[HH[MM]]")
    parser.add_argument("--date", nargs="+", default=None, help="extract one or more UTC dates YYYYMMDD, based on sample-start time")
    parser.add_argument("--stime", "--start", dest="stime", default=None, help="start time YYYYMMDD[HH[MM]], inclusive, based on sample-start time")
    parser.add_argument("--etime", "--end", dest="etime", default=None, help="end time YYYYMMDD[HH[MM]], inclusive, based on sample-start time")
    parser.add_argument(
        "--factor", "--source-factor",
        dest="factor",
        nargs="+",
        type=float,
        default=None,
        help=(
            "source/file coefficient(s), not layer factors. "
            "For files f0 f1 f2 and --factor a b c, output = a*f0 + b*f1 + c*f2. "
            "Give one value to use the same coefficient for all files."
        ),
    )
    parser.add_argument("--decay", type=float, default=None, help="half-life in days")
    parser.add_argument("--decay-reference", choices=("idl", "exact", "first", "earliest"), default="idl")
    parser.add_argument("--vmean", action="store_true", help="thickness-weighted vertical mean")
    parser.add_argument("--nan", action="store_true", help="replace exact output zeros with NaN")
    parser.add_argument("--zero-to-nan", action="store_true", help="alias for --nan")
    parser.add_argument("--order", choices=("idl", "tyx"), default="idl", help="NPZ output array order. NetCDF always writes TSTEP,ROW,COL")
    parser.add_argument("--dtype", choices=("float32", "float64"), default="float32")
    parser.add_argument("--no-strict", action="store_true", help="disable pollutant/level label validation in records")

    parser.add_argument("--bbox", nargs=4, type=float, default=None, metavar=("LAT_MIN", "LON_MIN", "LAT_MAX", "LON_MAX"), help="manual HYGV bbox")
    parser.add_argument("--bbox-round", type=int, default=2, help="automatic bbox decimal places. Default: 2")
    parser.add_argument("--wm-dim", nargs=2, type=int, default=None, metavar=("NX", "NY"), help="manual Web Mercator output dimension")
    parser.add_argument("--wm-res-m", type=float, default=None, help="manual Web Mercator resolution in meters")
    parser.add_argument("--wm-res-km", type=float, default=None, help="manual Web Mercator resolution in kilometers")
    parser.add_argument("--wm-max-dim", type=int, default=DEFAULT_WM_MAX_DIM, help="cap automatic Web Mercator dimension. 0 disables cap. Default: 2000")
    parser.add_argument("--wm-flip-y", action="store_true", help="flip Web Mercator rows to north-to-south order")

    parser.add_argument("--no-gzip", action="store_true", help="write uncompressed NetCDF")
    parser.add_argument("-c", "--compression-level", type=int, default=DEFAULT_COMPRESSION_LEVEL, help="NetCDF deflate level 0-9. Default: 4")
    parser.add_argument("--quiet", action="store_true", help="suppress progress messages")
    return parser.parse_args()


def _main() -> int:
    args = _parse_cli()
    output = args.output
    if output is None:
        output = "cdump_tsum.npz" if args.npz else "cdump_tsum.nc"

    # NetCDF writer wants [time,y,x].  NPZ uses requested order.
    read_order = args.order if args.npz else "tyx"
    nan = bool(args.nan or args.zero_to_nan)

    # Projection default:
    #   - plain NetCDF output uses original lon/lat grid (ll)
    #   - --hygv means HYGV/Web-Mercator-ready output unless explicitly overridden
    hygv_proj = args.hygv_proj if args.hygv_proj is not None else ("wm" if args.hygv else "ll")

    try:
        input_files = _normalize_files(args.files, file_lists=args.file_list)
    except Exception as exc:
        print(f"Input-file error: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(f"Starting rd_cdump_tsum.py {APP_VERSION} ...")
        print(f"Files : {len(input_files)} expanded input file(s)")
        if args.file_list:
            print("File list(s): " + ", ".join(os.fspath(x) for x in args.file_list))
        if args.factor is not None:
            print(f"Source factors: {args.factor}")
        if args.date is not None:
            print("Date filter: " + ", ".join(str(x) for x in args.date))
        elif args.stime is not None or args.etime is not None:
            print(f"Time filter: stime={args.stime or ''} etime={args.etime or ''}")
        elif args.tflag is not None:
            print("TFLAG filter: " + ", ".join(str(x) for x in args.tflag))
        print(f"Output: {output}")
        print(f"Mode  : {'NPZ' if args.npz else 'NetCDF'}")
        if not args.npz:
            print(f"Projection: {hygv_proj}")
            if hygv_proj == "wm":
                print("WM row order:", "north_to_south" if args.wm_flip_y else "south_to_north")
        print("Reading and accumulating cdump data. This may take a while...")

    data, info = rd_cdump_tsum(
        input_files,
        xlevel=args.xlevel,
        level=args.level,
        xptype=args.xptype,
        ptype=args.ptype,
        tflag=args.tflag,
        date=args.date,
        stime=args.stime,
        etime=args.etime,
        factor=args.factor,
        decay=args.decay,
        vmean=args.vmean,
        nan=nan,
        order=read_order,
        dtype=np.float32 if args.dtype == "float32" else np.float64,
        decay_reference=args.decay_reference,
        strict=not args.no_strict,
    )
    if data is None or info is None:
        print("No selected non-empty concentration records were found.", file=sys.stderr)
        return 2

    if not args.npz:
        created = save_hygv_netcdf(
            output,
            data,  # type: ignore[arg-type]
            info,
            var_name=args.var_name,
            hygv_proj=hygv_proj,
            bbox=args.bbox,
            bbox_round=args.bbox_round,
            wm_dim=args.wm_dim,
            wm_res_m=args.wm_res_m,
            wm_res_km=args.wm_res_km,
            wm_max_dim=args.wm_max_dim,
            wm_flip_y=args.wm_flip_y,
            fill_value=float("nan"),
            gzip=not args.no_gzip,
            compression_level=args.compression_level,
        )
        if not args.quiet:
            print(f"Wrote {created}: variable={sanitize_nc_name(args.var_name)} shape={data.shape}")
    else:
        np.savez_compressed(
            output,
            data=data,
            tflag=info["tflag"],
            lon=info["lon"],
            lat=info["lat"],
            level=info["level"],
            xlevel=info["xlevel"],
            xptype=info["xptype"],
            factor=info["factor"],
            source_factor=info["source_factor"],
            file_factor_mapping=np.asarray(info["file_factor_mapping"], dtype=object),
            minfo=info["minfo"],
        )
        if not args.quiet:
            print(f"Wrote {output}: shape={data.shape}, dtype={data.dtype}, order={read_order}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
