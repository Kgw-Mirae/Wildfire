#!/usr/bin/env python3
"""
fire_finn_nrt_dn.py

Python counterpart of fire_finn_nrt_dn.pro.

Downloads the two FINN NRT text products required by the HYSPLIT fire-emission
workflow:

    * base_FRP
    * SAPRC

Default local directory:
    ~/data/fire-finn/nrt/raw/YYYY/YYYYMMDD/

The URL/file-name transitions follow the current IDL routine:
    2024-01-01 ... 2024-12-31 : FINN2nrt_2024, FINNv2.5.1...
    2025-01-01 ... 2025-12-31 : FINN2nrt_2025, FINNv2.5.1...
    2026-01-01 ... 2026-04-30 : FINN2nrt_2026, FINNv2.5.1...
    2026-05-01 onward         : FINN2.9/txt, FINNv2.9.1...

A small "dn_complete" manifest is used in the same spirit as the IDL library.
For recent target days, a manifest older than refresh_days is refreshed until
settle_days have passed after the target day.
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Iterable, Sequence

BASE = "https://www.acom.ucar.edu/acresp/MODELING/finn_emis_txt"


class FinnDataUnavailable(FileNotFoundError):
    """FINN source inventory cannot be retrieved for the requested day."""


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
    if len(digits) >= 8:
        return datetime.strptime(digits[:8], "%Y%m%d")
    return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)


def _as_days(time: Any) -> list[datetime]:
    if isinstance(time, (str, bytes, Integral, Real, datetime)):
        values = [time]
    else:
        values = list(time)
    return [
        datetime((d := _parse_time(x)).year, d.month, d.day)
        for x in values
    ]


def _data_root(data_root: str | os.PathLike[str] | None = None) -> Path:
    if data_root is not None:
        return Path(data_root).expanduser()
    env = os.environ.get("DATA_PATH") or os.environ.get("BLUTOUCH_DATA")
    return Path(env).expanduser() if env else Path("~/data").expanduser()


def _remote_files(day: datetime) -> tuple[str, list[str]]:
    ds = day.strftime("%Y%m%d")

    if day >= datetime(2026, 5, 1):
        base = f"{BASE}/FINN2.9/txt"
        prefix = "FINNv2.9.1_NRTmodvrs"
    elif day >= datetime(2026, 1, 1):
        base = f"{BASE}/FINN2nrt_2026"
        prefix = "FINNv2.5.1_modvrs_nrt"
    elif day >= datetime(2025, 1, 1):
        base = f"{BASE}/FINN2nrt_2025"
        prefix = "FINNv2.5.1_modvrs_nrt"
    elif day >= datetime(2024, 1, 1):
        base = f"{BASE}/FINN2nrt_2024"
        prefix = "FINNv2.5.1_modvrs_nrt"
    else:
        raise ValueError(
            f"FINN NRT downloader is defined for 2024-01-01 and later: {ds}"
        )

    names = [
        f"{prefix}_base_FRP_{ds}.txt.gz",
        f"{prefix}_SAPRC_{ds}.txt.gz",
    ]
    return base, names


def _manifest_file(sdir: Path) -> Path:
    return sdir / "dn_complete"


def _read_manifest(sdir: Path) -> list[Path]:
    file = _manifest_file(sdir)
    if not file.is_file():
        return []
    names = [
        line.strip()
        for line in file.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    files = [sdir / Path(name).name for name in names]
    if not files:
        return []
    if not all(p.is_file() and p.stat().st_size > 0 for p in files):
        return []
    return files


def _manifest_needs_refresh(
    sdir: Path,
    day: datetime,
    *,
    refresh_days: float = 1.0,
    settle_days: float = 5.0,
) -> bool:
    """
    Practical Python equivalent of dn_complete(...,renew=[1,cday,5]).

    For recent data (within settle_days of the target day), refresh a completed
    download when the manifest is older than refresh_days.  Old dates are kept.
    """
    file = _manifest_file(sdir)
    if not file.is_file():
        return True

    now = datetime.now()
    age = now - datetime.fromtimestamp(file.stat().st_mtime)
    target_age = now - day
    return target_age < timedelta(days=settle_days) and age > timedelta(days=refresh_days)


def _write_manifest(sdir: Path, files: Sequence[Path]) -> None:
    _manifest_file(sdir).write_text(
        "".join(f"{p.name}\n" for p in files),
        encoding="utf-8",
    )


def _download_wget(url: str, target: Path, *, verbose: bool) -> None:
    wget = shutil.which("wget")
    if wget is None:
        raise FileNotFoundError("wget")
    cmd = [wget, "-c", url, "-O", str(target)]
    if verbose:
        print(" ".join(cmd))
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        # wget -O may leave a zero-length or partial archive after HTTP 404.
        # Never allow a later call to mistake it for a successful download.
        target.unlink(missing_ok=True)
        raise RuntimeError(f"wget failed ({result.returncode}): {url}")


def _download_urllib(url: str, target: Path, *, verbose: bool) -> None:
    part = target.with_suffix(target.suffix + ".part")
    if verbose:
        print(f"DOWNLOAD {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as src, part.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        part.replace(target)
    except Exception:
        try:
            part.unlink()
        except FileNotFoundError:
            pass
        raise


def _download(url: str, target: Path, *, verbose: bool = True) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size > 0:
        return

    if shutil.which("wget"):
        _download_wget(url, target, verbose=verbose)
    else:
        _download_urllib(url, target, verbose=verbose)

    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"Download failed: {url}")


def _gunzip(file: Path, *, overwrite: bool = False, verbose: bool = True) -> Path:
    if file.suffix.lower() != ".gz":
        return file
    out = file.with_suffix("")
    if out.is_file() and out.stat().st_size > 0 and not overwrite:
        try:
            file.unlink()
        except OSError:
            pass
        return out

    tmp = out.with_suffix(out.suffix + ".part")
    if verbose:
        print(f"GUNZIP {file} -> {out}")
    try:
        with gzip.open(file, "rb") as src, tmp.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        tmp.replace(out)
        file.unlink()
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise
    return out


def fire_finn_nrt_dn1(
    cday: Any,
    *,
    data_root: str | os.PathLike[str] | None = None,
    renew: bool = False,
    refresh_days: float = 1.0,
    settle_days: float = 5.0,
    verbose: bool = True,
) -> list[Path]:
    day = _parse_time(cday)
    day = datetime(day.year, day.month, day.day)
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    if day > today:
        if verbose:
            print(f"FINN NRT: future day, skip {day:%Y%m%d}")
        return []

    sdir = (
        _data_root(data_root)
        / "fire-finn"
        / "nrt"
        / "raw"
        / day.strftime("%Y")
        / day.strftime("%Y%m%d")
    )
    sdir.mkdir(parents=True, exist_ok=True)

    existing = _read_manifest(sdir)
    refresh = renew or _manifest_needs_refresh(
        sdir,
        day,
        refresh_days=refresh_days,
        settle_days=settle_days,
    )
    if existing and not refresh:
        if verbose:
            print(f"FINN NRT READY {sdir}")
        return existing

    base, names = _remote_files(day)
    out: list[Path] = []

    for name in names:
        url = f"{base}/{name}"
        gz = sdir / name
        txt = gz.with_suffix("")

        # On /renew, force a fresh compressed download, but keep the old txt
        # until the new .gz has downloaded successfully.
        if renew or refresh:
            if gz.exists():
                gz.unlink()

        if not txt.is_file() or txt.stat().st_size == 0 or renew or refresh:
            try:
                _download(url, gz, verbose=verbose)
            except (RuntimeError, urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                raise FinnDataUnavailable(
                    f"FINN input unavailable for {day:%Y%m%d}: {url} ({exc})"
                ) from exc
            new_txt = _gunzip(gz, overwrite=(renew or refresh), verbose=verbose)
            if new_txt != txt:
                raise RuntimeError(f"Unexpected gunzip output: {new_txt}")
        out.append(txt)

    if not all(p.is_file() and p.stat().st_size > 0 for p in out):
        raise RuntimeError(f"Incomplete FINN NRT download: {sdir}")

    _write_manifest(sdir, out)
    if verbose:
        for p in out:
            print(f"FINN NRT {p}")
    return out


def fire_finn_nrt_dn(
    time: Any,
    *,
    data_root: str | os.PathLike[str] | None = None,
    renew: bool = False,
    refresh_days: float = 1.0,
    settle_days: float = 5.0,
    verbose: bool = True,
) -> list[Path] | list[list[Path]]:
    days = _as_days(time)
    rr = [
        fire_finn_nrt_dn1(
            day,
            data_root=data_root,
            renew=renew,
            refresh_days=refresh_days,
            settle_days=settle_days,
            verbose=verbose,
        )
        for day in days
    ]
    return rr[0] if len(rr) == 1 else rr


def _date_range(start: Any, end: Any) -> list[int]:
    d1 = _parse_time(start)
    d2 = _parse_time(end)
    step = 1 if d2 >= d1 else -1
    out: list[int] = []
    d = datetime(d1.year, d1.month, d1.day)
    stop = datetime(d2.year, d2.month, d2.day)
    while True:
        out.append(int(d.strftime("%Y%m%d")))
        if d == stop:
            break
        d += timedelta(days=step)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Download FINN NRT FRP + SAPRC text files")
    p.add_argument("date", help="YYYYMMDD")
    p.add_argument("--end", help="optional inclusive end date")
    p.add_argument("--data-root", default=None, help="default: $DATA_PATH or ~/data")
    p.add_argument("--renew", action="store_true")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    dates = _date_range(args.date, args.end) if args.end else [args.date]
    try:
        result = fire_finn_nrt_dn(
            dates,
            data_root=args.data_root,
            renew=args.renew,
            verbose=not args.quiet,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if isinstance(result, list):
        for item in result:
            if isinstance(item, list):
                for f in item:
                    print(f)
            else:
                print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
