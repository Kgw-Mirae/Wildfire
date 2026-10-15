#!/usr/bin/env python3
"""
hysp_arl.py

Python ARL finder/downloader following the current IDL HYSP routines.

IDL routines mirrored here:
    hysp_arl_find.pro
    dn_arl_gdas1.pro
    dn_arl_gdas0p5.pro
    dn_arl_gfs0p25.pro
    dn_arl_gfs0p25_fcst.pro
    dn_arl_gfs1_fcst.pro
    dn_arl_nam12.pro
    dn_arl_narr.pro
    dn_arl_nams.pro
    dn_arl_hrrr.pro
    hysp_init_arl_path.pro

Important conventions kept from the IDL package:

* ARL names and directory names are lower case: gdas1, gfs0p25, hrrr, ...
* gdas1 archive:
      ARL_PATH/gdas1/YYYY/gdas1.mmmyy.wN
* gfs0p25 archive:
      ARL_PATH/gfs0p25/YYYY/MM/YYYYMMDD_gfs0p25
* gdas0p5, nam12, narr, nams, hrrr:
      ARL_PATH/<name>/<file>
* forecast files:
      /pub/forecast/YYYYMMDD/...        if /pub/forecast exists
      otherwise ARL_PATH/forecast/YYYYMMDD/...
* ARL_DOWN from hysp.ini controls whether missing files may be downloaded.
* zero-length archive files are removed and are not treated as valid data.
* the rolling GDAS1 current7days file is reused when younger than one day;
  when older than one day it is refreshed if ARL_DOWN == 1.
* no meteorological-data conversion is performed.

Typical use
-----------
    from hysp_arl import hysp_arl_find

    time = [2026072500, 2026072600, 2026072700]
    files = hysp_arl_find('gfs0p25', time=time)

    files = hysp_arl_find('gfs0p25.f', time=[2026100700, 2026100900])
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import shutil
import subprocess
import sys
import time as time_module
from datetime import datetime, timedelta, timezone
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    from .hysp_init import hysp_init
except ImportError:
    # Allow direct execution: python hysp_arl.py ...
    from hysp_init import hysp_init


ARCHIVE_FTP = "ftp://arlftp.arlhq.noaa.gov/pub/archives"
FORECAST_FTP = "ftp://arlftp.arlhq.noaa.gov/pub/forecast"
CURRENT7DAYS_FTP = "ftp://ftp.arl.noaa.gov/pub/archives/gdas1/current7days"


# -----------------------------------------------------------------------------
# basic helpers
# -----------------------------------------------------------------------------


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray)):
        value = value.tolist()
    if _is_sequence(value):
        out: list[Any] = []
        for item in value:
            if _is_sequence(item) or (
                hasattr(item, "tolist")
                and not isinstance(item, (str, bytes, bytearray))
            ):
                out.extend(_as_list(item))
            else:
                out.append(item)
        return out
    return [value]


def _parse_time(value: Any) -> datetime:
    """Parse common HYSP/IDL times as naive UTC datetime."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
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
    if len(digits) == 8:
        return datetime.strptime(digits, "%Y%m%d")
    if len(digits) == 6:
        return datetime.strptime(digits, "%Y%m")

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError as exc:
        raise ValueError(f"Cannot parse time: {value!r}") from exc


def _time_values(time: Any) -> list[datetime]:
    values = _as_list(time)
    if not values:
        raise ValueError('"time" required')
    return [_parse_time(x) for x in values]


def _time_bounds(time: Any) -> tuple[datetime, datetime]:
    values = _time_values(time)
    return min(values), max(values)


def _days(start: datetime, end: datetime) -> Iterable[datetime]:
    day = datetime(start.year, start.month, start.day)
    stop = datetime(end.year, end.month, end.day)
    while day <= stop:
        yield day
        day += timedelta(days=1)


def _months(start: datetime, end: datetime) -> Iterable[datetime]:
    month = datetime(start.year, start.month, 1)
    stop = datetime(end.year, end.month, 1)
    while month <= stop:
        yield month
        if month.month == 12:
            month = datetime(month.year + 1, 1, 1)
        else:
            month = datetime(month.year, month.month + 1, 1)


def _unique(paths: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def _exists(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _rmzero(paths: Iterable[Path], *, verbose: bool = True) -> None:
    """Equivalent of IDL file_rmzero for the supplied file list."""
    for path in paths:
        try:
            if path.is_file() and path.stat().st_size == 0:
                if verbose:
                    print(f"DELETE {path}")
                path.unlink()
        except OSError:
            pass


def _existing(paths: Iterable[Path]) -> list[Path]:
    return [p for p in paths if _exists(p)]


def _wget(url: str, target: Path, *, verbose: bool = True) -> bool:
    """Run the same basic wget -c download used by the IDL routines."""
    wget = shutil.which("wget")
    if wget is None:
        raise RuntimeError("wget is required for ARL downloading but was not found")

    target.parent.mkdir(parents=True, exist_ok=True)

    cmd = [wget, "-c", url, "-O", str(target)]
    if verbose:
        print(" ".join(cmd))

    result = subprocess.run(cmd, check=False)
    if result.returncode != 0 or not _exists(target):
        # A failed wget -O can leave a zero-length file.  Match file_rmzero.
        try:
            if target.is_file() and target.stat().st_size == 0:
                target.unlink()
        except OSError:
            pass
        return False

    return True


def _download_missing(
    files: Sequence[Path],
    urls: Sequence[str],
    *,
    allow_download: bool,
    verbose: bool,
) -> None:
    if len(files) != len(urls):
        raise ValueError("files/urls length mismatch")

    _rmzero(files, verbose=verbose)

    if not allow_download:
        return

    for path, url in zip(files, urls):
        if _exists(path):
            continue
        _wget(url, path, verbose=verbose)


# -----------------------------------------------------------------------------
# ARL binary time information -- small Python port of ii_arl_time.pro
# -----------------------------------------------------------------------------


def _label_time(label: bytes) -> datetime:
    text = label.decode("ascii", errors="ignore")
    yy = int(text[0:2])
    mm = int(text[2:4])
    dd = int(text[4:6])
    hh = int(text[6:8])
    year = 1900 + yy if yy > 40 else 2000 + yy
    return datetime(year, mm, dd, hh)


def _arl_time_bounds(path: Path) -> tuple[datetime, datetime] | None:
    """Return first/last valid times using the logic in ii_arl_time.pro."""
    if not _exists(path):
        return None

    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            label = f.read(50)
            header = f.read(108)
            if len(label) < 50 or len(header) < 108:
                return None

            start = _label_time(label)

            # IDL format: A4,I3,I2,12F7.0,3I3,I2,I4
            nx = int(header[93:96].decode("ascii", errors="ignore").strip())
            ny = int(header[96:99].decode("ascii", errors="ignore").strip())

            # Large-grid encoding from ii_arl_time.pro.
            cgrid = label[12:14]
            if len(cgrid) >= 2:
                knx = cgrid[0]
                kny = cgrid[1]
                if knx >= 64:
                    nx += (knx - 64) * 1000
                if kny >= 64:
                    ny += (kny - 64) * 1000

            reclen = nx * ny + 50
            if reclen <= 50 or reclen > size:
                return None

            f.seek(size - reclen)
            last_label = f.read(50)
            if len(last_label) < 50:
                return None
            end = _label_time(last_label)

        return start, end
    except (OSError, ValueError, TypeError):
        return None


# -----------------------------------------------------------------------------
# shared configuration
# -----------------------------------------------------------------------------


def _arl_config(ini: str | Path = "hysp.ini") -> tuple[Path, bool]:
    opt = hysp_init(ini)
    root = Path(str(opt["ARL_PATH"])).expanduser()
    allow_download = int(opt["ARL_DOWN"]) != 0
    return root, allow_download


def _forecast_root(root: Path) -> Path:
    public = Path("/pub/forecast")
    return public if public.is_dir() else root / "forecast"


# -----------------------------------------------------------------------------
# individual dn_arl_* routines
# -----------------------------------------------------------------------------


def dn_arl_gdas0p5(
    time: Any,
    *,
    root: Path,
    allow_download: bool,
    verbose: bool = True,
) -> list[Path]:
    name = "gdas0p5"
    start, end = _time_bounds(time)
    files = [root / name / f"{day:%Y%m%d}_gdas0p5" for day in _days(start, end)]
    urls = [f"{ARCHIVE_FTP}/{name}/{p.name}" for p in files]
    _download_missing(files, urls, allow_download=allow_download, verbose=verbose)
    out = _existing(files)
    if verbose:
        for p in files:
            print(f"{p}  {int(_exists(p))}")
    return out


def dn_arl_gfs0p25(
    time: Any,
    *,
    root: Path,
    allow_download: bool,
    verbose: bool = True,
) -> list[Path]:
    name = "gfs0p25"
    start, end = _time_bounds(time)
    files: list[Path] = []
    urls: list[str] = []

    for day in _days(start, end):
        path = root / name / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y%m%d}_gfs0p25"
        files.append(path)
        urls.append(
            f"{ARCHIVE_FTP}/{name}/{day:%Y}/{day:%m}/{path.name}"
        )

    _download_missing(files, urls, allow_download=allow_download, verbose=verbose)
    out = _existing(files)
    if verbose:
        for p in files:
            print(f"{p}  {int(_exists(p))}")
    return out


def dn_arl_nam12(
    time: Any,
    *,
    root: Path,
    allow_download: bool,
    verbose: bool = True,
) -> list[Path]:
    name = "nam12"
    start, end = _time_bounds(time)
    files = [root / name / f"{day:%Y%m%d}_nam12" for day in _days(start, end)]
    urls = [f"{ARCHIVE_FTP}/{name}/{p.name}" for p in files]
    _download_missing(files, urls, allow_download=allow_download, verbose=verbose)
    out = _existing(files)
    if verbose:
        for p in files:
            print(f"{p}  {int(_exists(p))}")
    return out


def dn_arl_narr(
    time: Any,
    *,
    root: Path,
    allow_download: bool,
    verbose: bool = True,
) -> list[Path]:
    name = "narr"
    start, end = _time_bounds(time)
    files = [root / name / f"NARR{month:%Y%m}" for month in _months(start, end)]
    urls = [f"{ARCHIVE_FTP}/{name}/{p.name}" for p in files]
    _download_missing(files, urls, allow_download=allow_download, verbose=verbose)
    out = _existing(files)
    if verbose:
        for p in files:
            print(f"{p}  {int(_exists(p))}")
    return out


def dn_arl_nams(
    time: Any,
    *,
    root: Path,
    allow_download: bool,
    verbose: bool = True,
) -> list[Path]:
    name = "nams"
    start, end = _time_bounds(time)
    files = [
        root / name / f"{day:%Y%m%d}_hysplit.t00z.namsa"
        for day in _days(start, end)
    ]
    urls = [f"{ARCHIVE_FTP}/{name}/{p.name}" for p in files]
    _download_missing(files, urls, allow_download=allow_download, verbose=verbose)
    out = _existing(files)
    if verbose:
        for p in files:
            print(f"{p}  {int(_exists(p))}")
    return out


def dn_arl_hrrr(
    time: Any,
    *,
    root: Path,
    allow_download: bool,
    verbose: bool = True,
) -> list[Path]:
    name = "hrrr"
    start, end = _time_bounds(time)

    tags = ["00-05", "06-11", "12-17", "18-23"]
    cur = start.replace(minute=0, second=0, microsecond=0)
    stop = end.replace(minute=0, second=0, microsecond=0)

    files: list[Path] = []
    while cur <= stop:
        tag = tags[cur.hour // 6]
        files.append(root / name / f"{cur:%Y%m%d}_{tag}_hrrr")
        cur += timedelta(hours=1)

    files = _unique(files)
    urls = [f"{ARCHIVE_FTP}/{name}/{p.name}" for p in files]
    _download_missing(files, urls, allow_download=allow_download, verbose=verbose)
    out = _existing(files)
    if verbose:
        for p in files:
            print(f"{p}  {int(_exists(p))}")
    return out


def _forecast_tags(stime: datetime, end: datetime) -> list[int]:
    nhour = int((end - stime).total_seconds() // 3600)
    # IDL: [0:date(stime,max(time),/count)+1:24]
    return list(range(0, max(nhour, 0) + 2, 24))


def dn_arl_gfs0p25_fcst(
    time: Any,
    *,
    root: Path,
    allow_download: bool,
    stime: Any | None = None,
    verbose: bool = True,
) -> list[Path]:
    values = _time_values(time)
    end = max(values)

    if stime is None:
        first = min(values)
        start = datetime(first.year, first.month, first.day, 0)
    else:
        start = _parse_time(stime)

    daytag = start.strftime("%Y%m%d")
    htag = start.strftime("%H")
    sdir = _forecast_root(root) / daytag

    leads = _forecast_tags(start, end)
    files = [sdir / f"hysplit.t{htag}z.gfs0p25f{lead:03d}" for lead in leads]
    urls = [f"{FORECAST_FTP}/{daytag}/{p.name}" for p in files]

    _download_missing(files, urls, allow_download=allow_download, verbose=verbose)

    # The IDL dn_arl_gfs0p25_fcst returns the requested file list rather than
    # filtering it with file_test().  Keep that behavior.
    if verbose:
        for p in files:
            print(f"{p}  {int(_exists(p))}")
    return files


def dn_arl_gfs1_fcst(
    time: Any,
    *,
    root: Path,
    allow_download: bool,
    stime: Any | None = None,
    verbose: bool = True,
) -> list[Path]:
    values = _time_values(time)

    if stime is None:
        first = min(values)
        start = datetime(first.year, first.month, first.day, 0)
    else:
        start = _parse_time(stime)

    daytag = start.strftime("%Y%m%d")
    sdir = _forecast_root(root) / daytag
    files = [
        sdir / "hysplit.t00z.gfsa",
        sdir / "hysplit.t00z.gfsf",
        sdir / "hysplit.t00z.gfslrf",
    ]
    urls = [f"{FORECAST_FTP}/{daytag}/{p.name}" for p in files]

    _download_missing(files, urls, allow_download=allow_download, verbose=verbose)

    if verbose:
        for p in files:
            print(f"{p}  {int(_exists(p))}")
    return files


def _current7days_needed(start: datetime, end: datetime) -> bool:
    """Old dn_arl_gdas1 behavior: use current7days for recent requests."""
    today = datetime.now(timezone.utc).replace(tzinfo=None)
    today = datetime(today.year, today.month, today.day)
    return end >= today - timedelta(days=7)


def _current7days(
    *,
    root: Path,
    allow_download: bool,
    verbose: bool,
) -> Path | None:
    path = root / "gdas1" / "current7days"
    _rmzero([path], verbose=verbose)

    if _exists(path):
        age_hours = (time_module.time() - path.stat().st_mtime) / 3600.0
        if age_hours < 24.0:
            if verbose:
                print(f"{path}  1  ({age_hours:.1f} h old)")
            return path

        if not allow_download:
            # ARL_DOWN=0 means use what already exists but do not replace it.
            if verbose:
                print(f"{path}  1  ({age_hours:.1f} h old; ARL_DOWN=0)")
            return path

        if verbose:
            print(f"REFRESH {path} ({age_hours:.1f} h old)")
        try:
            path.unlink()
        except OSError:
            pass

    if not allow_download:
        return path if _exists(path) else None

    if _wget(CURRENT7DAYS_FTP, path, verbose=verbose):
        return path
    return None


def dn_arl_gdas1(
    time: Any,
    *,
    root: Path,
    allow_download: bool,
    verbose: bool = True,
) -> list[Path]:
    """
    Current IDL gdas1 archive layout plus the agreed one-day current7days cache.

    Archive files follow the latest package:
        ARL_PATH/gdas1/YYYY/gdas1.mmmyy.wN

    For recent data, current7days is stored at:
        ARL_PATH/gdas1/current7days

    If requested times extend beyond available GDAS1 coverage, the GFS1
    forecast files are appended, matching current dn_arl_gdas1.pro behavior.
    """
    name = "gdas1"
    start, end = _time_bounds(time)

    files: list[Path] = []
    urls: list[str] = []
    seen: set[str] = set()

    for day in _days(start, end):
        week = (day.day - 1) // 7 + 1
        fname = f"gdas1.{day.strftime('%b').lower()}{day:%y}.w{week}"
        path = root / name / f"{day:%Y}" / fname
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        files.append(path)
        urls.append(f"{ARCHIVE_FTP}/{name}/{day:%Y}/{fname}")

    _download_missing(files, urls, allow_download=allow_download, verbose=verbose)
    archives = _existing(files)

    out: list[Path] = list(archives)

    # Preserve the rolling recent-data behavior discussed for current7days.
    if _current7days_needed(start, end):
        current = _current7days(
            root=root,
            allow_download=allow_download,
            verbose=verbose,
        )
        if current is not None and _exists(current):
            # Old IDL dn_arl_gdas1 prepended current7days.
            out = [current] + out

    # Current modular IDL dn_arl_gdas1 appends GFS1 forecast data when the
    # requested end time is beyond the actual ARL end time.
    coverage_end: datetime | None = None
    for path in out:
        info = _arl_time_bounds(path)
        if info is not None:
            _, etime = info
            if coverage_end is None or etime > coverage_end:
                coverage_end = etime

    if coverage_end is None:
        # No usable GDAS1 data: same intent as current IDL, use forecast.
        out.extend(
            dn_arl_gfs1_fcst(
                time,
                root=root,
                allow_download=allow_download,
                verbose=verbose,
            )
        )
    elif end > coverage_end:
        # Use the first uncovered time as the forecast day selector.
        first_uncovered = coverage_end + timedelta(hours=1)
        out.extend(
            dn_arl_gfs1_fcst(
                [first_uncovered, end],
                root=root,
                allow_download=allow_download,
                verbose=verbose,
            )
        )

    out = _unique(out)
    if verbose:
        for p in files:
            print(f"{p}  {int(_exists(p))}")
    return out


# -----------------------------------------------------------------------------
# hysp_arl_find -- public interface
# -----------------------------------------------------------------------------


def _names(name: str | Sequence[str]) -> list[str]:
    if isinstance(name, str):
        # IDL uses strsplit(_name,/extract), so preserve whitespace-separated
        # multiple names.
        return [x.lower() for x in name.split() if x.strip()]

    out: list[str] = []
    for item in name:
        out.extend(_names(str(item)))
    return out


def hysp_arl_find(
    name: str | Sequence[str],
    *,
    time: Any,
    ini: str | Path = "hysp.ini",
    verbose: bool = True,
) -> list[str]:
    """
    Find/download HYSPLIT ARL files, following hysp_arl_find.pro.

    Parameters
    ----------
    name
        ARL name or whitespace-separated names.  Matching is case-insensitive,
        but all archive directory names follow the IDL lower-case convention.
        Supported names: gdas1, gdas0p5, gfs0p25, gfs0p25.f,
                         nam12, narr, nams, hrrr.
    time
        Scalar or time array.  File coverage is based on min(time), max(time).
    ini
        Shared IDL/Python hysp.ini file.
    verbose
        Print the same kind of file/download status useful in the IDL routines.
    """
    # Validate time before doing any file work.
    start, end = _time_bounds(time)
    root, allow_download = _arl_config(ini)

    if verbose:
        print(f"ARL_PATH : {root}")
        print(f"ARL_DOWN : {int(allow_download)}")
        print(f"TIME     : {start:%Y%m%d%H} - {end:%Y%m%d%H}")

    out: list[Path] = []

    for item in _names(name):
        if item == "gdas1":
            files = dn_arl_gdas1(
                time,
                root=root,
                allow_download=allow_download,
                verbose=verbose,
            )
        elif item == "gdas0p5":
            files = dn_arl_gdas0p5(
                time,
                root=root,
                allow_download=allow_download,
                verbose=verbose,
            )
        elif item == "gfs0p25":
            files = dn_arl_gfs0p25(
                time,
                root=root,
                allow_download=allow_download,
                verbose=verbose,
            )
        elif item == "gfs0p25.f":
            files = dn_arl_gfs0p25_fcst(
                time,
                root=root,
                allow_download=allow_download,
                verbose=verbose,
            )
        elif item == "nam12":
            files = dn_arl_nam12(
                time,
                root=root,
                allow_download=allow_download,
                verbose=verbose,
            )
        elif item == "narr":
            files = dn_arl_narr(
                time,
                root=root,
                allow_download=allow_download,
                verbose=verbose,
            )
        elif item == "nams":
            files = dn_arl_nams(
                time,
                root=root,
                allow_download=allow_download,
                verbose=verbose,
            )
        elif item == "hrrr":
            files = dn_arl_hrrr(
                time,
                root=root,
                allow_download=allow_download,
                verbose=verbose,
            )
        else:
            raise ValueError(f"WRONG ARL NAME: {item}")

        out.extend(files)

    return [str(p) for p in _unique(out)]


# -----------------------------------------------------------------------------
# command line
# -----------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find/download HYSPLIT ARL files using hysp.ini"
    )
    parser.add_argument(
        "name",
        help="gdas1, gdas0p5, gfs0p25, gfs0p25.f, nam12, narr, nams, hrrr",
    )
    parser.add_argument(
        "time",
        nargs="+",
        help="time array; min/max define the requested period",
    )
    parser.add_argument("--ini", default="hysp.ini")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args()

    files = hysp_arl_find(
        args.name,
        time=args.time,
        ini=args.ini,
        verbose=not args.quiet,
    )

    for path in files:
        print(path)


if __name__ == "__main__":
    main()
