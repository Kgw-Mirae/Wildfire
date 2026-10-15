#!/usr/bin/env python3
"""
fire_rave_dn.py

Python counterpart of the current IDL dn_rave_noaa.pro.

Downloads NOAA RAVE hourly-emission NetCDF files.

Default product:
    name    = "3km"
    version = "v2r0"

Local directory follows the IDL layout exactly:

    ~/data/fire-rave/raw/3km-v2r0/YYYY/YYYYMMDD/
    ~/data/fire-rave/raw/13km-v2r0/YYYY/YYYYMMDD/

Current NOAA source used by the IDL routine:

    https://www.ospo.noaa.gov/pub/Blended/RAVE/
        RAVE-HrlyEmiss-3km/YYYY/MM/
        RAVE-HrlyEmiss-13km/YYYY/MM/

The current IDL dn_rave_noaa2() supports dates after 2024-09-19.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Iterable, Sequence


BASE_URL = "https://www.ospo.noaa.gov/pub/Blended/RAVE"
VALID_NAMES = ("3km", "13km")
DEFAULT_VERSION = "v2r0"
FIRST_DATE = datetime(2024, 9, 20)


def _data_root(data_root: str | os.PathLike[str] | None = None) -> Path:
    if data_root is not None:
        return Path(data_root).expanduser()
    env = os.environ.get("DATA_PATH") or os.environ.get("BLUTOUCH_DATA")
    return Path(env).expanduser() if env else Path("~/data").expanduser()


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


def _parse_day(value: Any) -> datetime:
    s = _digits(value)
    if len(s) < 8:
        raise ValueError(f"RAVE date must contain YYYYMMDD: {value!r}")
    return datetime.strptime(s[:8], "%Y%m%d")


def _as_values(value: Any) -> list[Any]:
    if isinstance(value, (str, bytes, Integral, Real, datetime, date)):
        return [value]
    return list(value)


def _raw_dir(
    day: datetime,
    *,
    name: str,
    version: str,
    data_root: str | os.PathLike[str] | None = None,
) -> Path:
    return (
        _data_root(data_root)
        / "fire-rave"
        / "raw"
        / f"{name}-{version}"
        / day.strftime("%Y")
        / day.strftime("%Y%m%d")
    )


def _hour_from_name(path: str | Path) -> str | None:
    """
    Extract YYYYMMDDHH from the `_sYYYYMMDDHH...` token used by RAVE files.
    """
    m = re.search(r"_s(\d{10})", Path(path).name)
    return m.group(1) if m else None


def _select_day_files(files: Iterable[Path], day: datetime) -> list[Path]:
    """
    Match the IDL post-download behavior: at most one file for each hourly
    timestamp of the target day, ordered 00 ... 23.  Files without an `_s`
    timestamp are kept afterward as a fallback.
    """
    target = day.strftime("%Y%m%d")
    by_hour: dict[str, Path] = {}
    fallback: list[Path] = []

    for p in sorted(Path(x) for x in files):
        hh = _hour_from_name(p)
        if hh is None:
            fallback.append(p)
            continue
        if hh.startswith(target):
            # When duplicates occur, the lexically latest file normally has
            # the later creation/version token.
            by_hour[hh] = p

    ordered = [by_hour[f"{target}{h:02d}"] for h in range(24)
               if f"{target}{h:02d}" in by_hour]

    if ordered:
        return ordered

    return fallback


def _directory_listing(url: str, *, timeout: int = 60) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 fire_rave_dn.py"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _remote_names(listing: str, day: datetime) -> list[str]:
    """
    The IDL code extracts entries beginning with sYYYYMMDD and then prepends
    RAVE-HrlyEmiss-{resolution}_{version}_blend_ for the local filename.
    """
    text = html.unescape(listing)
    ymd = day.strftime("%Y%m%d")

    # Capture plain directory entries such as
    # sYYYYMMDDHH...nc, whether they occur inside href or text.
    pats = re.findall(
        rf"(s{ymd}\d{{2}}[^\"'<>/\s]*?\.nc)",
        text,
        flags=re.IGNORECASE,
    )
    return sorted(set(Path(x).name for x in pats))


def _download(
    url: str,
    outfile: Path,
    *,
    timeout: int = 180,
    verbose: bool = True,
) -> None:
    outfile.parent.mkdir(parents=True, exist_ok=True)
    part = outfile.with_name(outfile.name + ".part")

    if verbose:
        print(f"DOWNLOAD {url}")
        print(f"      -> {outfile}")

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 fire_rave_dn.py"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as src, part.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        part.replace(outfile)
    except Exception:
        if part.exists():
            part.unlink()
        raise


def fire_rave_dn1(
    cday: Any,
    *,
    name: str = "3km",
    version: str = DEFAULT_VERSION,
    renew: bool = False,
    data_root: str | os.PathLike[str] | None = None,
    timeout: int = 180,
    verbose: bool = True,
) -> list[Path]:
    """
    Download/read RAVE files for one YYYYMMDD day.

    Returns a list of local NetCDF files ordered by hour.
    """
    day = _parse_day(cday)
    name = str(name).lower()
    version = str(version)

    if name not in VALID_NAMES:
        raise ValueError(f"Wrong RAVE name {name!r}; use one of {VALID_NAMES}")

    today = datetime.now(timezone.utc).replace(tzinfo=None)
    if day < FIRST_DATE or day.date() > today.date():
        if verbose:
            print(f"NO RAVE DATA DATE {day:%Y%m%d}")
        return []

    sdir = _raw_dir(day, name=name, version=version, data_root=data_root)
    sdir.mkdir(parents=True, exist_ok=True)

    pattern = f"RAVE-HrlyEmiss-{name}*.nc"
    local = sorted(sdir.glob(pattern))
    selected = _select_day_files(local, day)

    if len(selected) >= 24 and not renew:
        if verbose:
            print(f"RAVE READY {sdir} ({len(selected)} files)")
        return selected

    if verbose:
        print(f"FOUND {len(selected)} RAVE files at {day:%Y%m%d}")

    url = f"{BASE_URL}/RAVE-HrlyEmiss-{name}/{day:%Y/%m}/"
    try:
        listing = _directory_listing(url, timeout=min(timeout, 60))
    except Exception as exc:
        # If the server cannot be reached but local data exist, return them.
        if selected:
            if verbose:
                print(f"WARNING: cannot refresh NOAA listing: {exc}")
            return selected
        raise RuntimeError(f"Cannot read RAVE directory listing: {url}: {exc}") from exc

    remote = _remote_names(listing, day)
    if not remote:
        if selected:
            return selected
        if verbose:
            print(f"NO RAVE FILES LISTED {day:%Y%m%d}")
        return []

    existing_by_remote: dict[str, Path] = {}
    for p in local:
        # Local IDL-style filename is prefix + remote s*.nc.
        m = re.search(r"(s\d{10}.*\.nc)$", p.name)
        if m:
            existing_by_remote[m.group(1)] = p

    for rname in remote:
        local_name = f"RAVE-HrlyEmiss-{name}_{version}_blend_{rname}"
        outfile = sdir / local_name

        if outfile.exists() and not renew:
            continue

        # NOAA directory uses the complete IDL-style filename, not the
        # bare sYYYYMMDD...nc suffix returned by the file-list grep.
        remote_file = local_name
        _download(
            urllib.parse.urljoin(url, urllib.parse.quote(remote_file)),
            outfile,
            timeout=timeout,
            verbose=verbose,
        )

    files = sorted(sdir.glob(pattern))
    selected = _select_day_files(files, day)

    if verbose:
        print(f"RAVE READY {sdir} ({len(selected)} files)")

    return selected


def fire_rave_dn(
    time: Any,
    *,
    name: str = "3km",
    version: str = DEFAULT_VERSION,
    renew: bool = False,
    data_root: str | os.PathLike[str] | None = None,
    timeout: int = 180,
    verbose: bool = True,
) -> list[Path]:
    """
    Download RAVE for one or more input times.

    Input may be YYYYMMDD, YYYYMMDDHH, datetime, or an iterable.  Downloads are
    deduplicated by day, matching date(time,/daily) in the IDL routine.
    """
    days: list[datetime] = []
    seen: set[str] = set()

    for value in _as_values(time):
        day = _parse_day(value)
        key = day.strftime("%Y%m%d")
        if key not in seen:
            seen.add(key)
            days.append(day)

    out: list[Path] = []
    for day in days:
        out.extend(
            fire_rave_dn1(
                day,
                name=name,
                version=version,
                renew=renew,
                data_root=data_root,
                timeout=timeout,
                verbose=verbose,
            )
        )
    return out


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
    p = argparse.ArgumentParser(description="Download NOAA RAVE hourly emissions")
    p.add_argument("date", help="YYYYMMDD")
    p.add_argument("--end", default=None, help="optional ending YYYYMMDD")
    p.add_argument("--name", default="3km", choices=VALID_NAMES)
    p.add_argument("--version", default=DEFAULT_VERSION)
    p.add_argument("--data-root", default=None)
    p.add_argument("--renew", action="store_true")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    try:
        target: Any = (
            _daily_range(args.date, args.end)
            if args.end is not None
            else args.date
        )
        files = fire_rave_dn(
            target,
            name=args.name,
            version=args.version,
            renew=args.renew,
            data_root=args.data_root,
            verbose=not args.quiet,
        )
        if not args.quiet:
            for f in files:
                print(f)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
