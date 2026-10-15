#!/usr/bin/env python3
"""
hysp_arl_chk.py

Check HYSPLIT ARL meteorological files.

Python examples
---------------
    from hysp_arl_chk import hysp_arl_chk

    hysp_arl_chk("gdas1", time=[2026072500, 2026072700])
    hysp_arl_chk("/path/to/20260725_gfs0p25")
    hysp_arl_chk("/path/to/gfs0p25/*")

Linux command line
------------------
    python hysp_arl_chk.py gdas1 --time 2026072500 2026072700
    python hysp_arl_chk.py /path/to/20260725_gfs0p25
    python hysp_arl_chk.py "/path/to/gfs0p25/*"

Dataset names and directory conventions follow the current IDL HYSP package:
    gdas1      ARL_PATH/gdas1/YYYY/gdas1.mmmyy.wN
    gdas0p5    ARL_PATH/gdas0p5/YYYYMMDD_gdas0p5
    gfs0p25    ARL_PATH/gfs0p25/YYYY/MM/YYYYMMDD_gfs0p25
    gfs0p25.f  /pub/forecast/YYYYMMDD/... if /pub/forecast exists,
                otherwise ARL_PATH/forecast/YYYYMMDD/...
    nam12      ARL_PATH/nam12/YYYYMMDD_nam12
    narr       ARL_PATH/narr/NARRYYYYMM
    nams       ARL_PATH/nams/YYYYMMDD_hysplit.t00z.namsa
    hrrr       ARL_PATH/hrrr/YYYYMMDD_HH-HH_hrrr

No files are downloaded or modified by this checker.
"""

from __future__ import annotations

import argparse
import glob
import os
from datetime import datetime, timedelta, timezone
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    from .hysp_init import hysp_init
except ImportError:
    # Allow direct execution: python hysp_arl_chk.py ...
    from hysp_init import hysp_init


ARL_NAMES = {
    "gdas1",
    "gdas0p5",
    "gfs0p25",
    "gfs0p25.f",
    "nam12",
    "narr",
    "nams",
    "hrrr",
}


# -----------------------------------------------------------------------------
# Generic helpers
# -----------------------------------------------------------------------------


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, Path)
    )


def _as_files(value: Any) -> list[Path]:
    """Resolve filename(s), including shell-style glob patterns.

    Supports ``*``, ``?``, ``[...]``, and recursive ``**``.
    """
    if value is None:
        return []

    if _is_sequence(value):
        out: list[Path] = []
        for item in value:
            out.extend(_as_files(item))
        return _unique(out)

    raw = os.fspath(value)
    expanded = os.path.expanduser(raw)

    if glob.has_magic(expanded):
        matches = sorted(glob.glob(expanded, recursive=True))
        return _unique(Path(x) for x in matches)

    return [Path(expanded)]


def _as_times(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray)):
        value = value.tolist()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        out: list[Any] = []
        for item in value:
            out.extend(_as_times(item))
        return out
    return [value]


def _parse_time(value: Any) -> datetime:
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

    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _time_bounds(time: Any) -> tuple[datetime, datetime]:
    values = [_parse_time(x) for x in _as_times(time)]
    if not values:
        raise ValueError('"time" required when checking an ARL dataset name')
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


def _forecast_root(root: Path) -> Path:
    public = Path("/pub/forecast")
    return public if public.is_dir() else root / "forecast"


# -----------------------------------------------------------------------------
# Dataset -> expected local files
# -----------------------------------------------------------------------------


def _gfs0p25_forecast_files(root: Path, start: datetime, end: datetime) -> list[Path]:
    # Same default as dn_arl_gfs0p25_fcst.pro:
    # stime = YYYYMMDD00 from min(time), with 24-h ARL blocks.
    stime = datetime(start.year, start.month, start.day, 0)
    nhour = max(0, int((end - stime).total_seconds() // 3600))
    leads = list(range(0, nhour + 2, 24))
    sdir = _forecast_root(root) / stime.strftime("%Y%m%d")
    return [
        sdir / f"hysplit.t{stime:%H}z.gfs0p25f{lead:03d}"
        for lead in leads
    ]


def _gfs1_forecast_files(root: Path, start: datetime) -> list[Path]:
    # Same filenames as dn_arl_gfs1_fcst.pro.
    stime = datetime(start.year, start.month, start.day, 0)
    sdir = _forecast_root(root) / stime.strftime("%Y%m%d")
    return [
        sdir / "hysplit.t00z.gfsa",
        sdir / "hysplit.t00z.gfsf",
        sdir / "hysplit.t00z.gfslrf",
    ]


def _dataset_plan(name: str, time: Any, ini: str | Path) -> dict[str, Any]:
    """Resolve local files without downloading.

    Returns a plan with:
        files    files that currently exist and should be inspected
        expected nominal files for the requested dataset/time
        missing  expected files that are currently absent
        root     ARL_PATH

    For gdas1, missing weekly archive files can be substituted by an existing
    current7days file and/or existing GFS1 forecast files.  Final success is
    therefore determined by structural validity plus continuous time coverage,
    not simply by the presence of every weekly archive filename.
    """
    name = name.lower()
    start, end = _time_bounds(time)
    opt = hysp_init(ini)
    root = Path(str(opt["ARL_PATH"])).expanduser()

    expected: list[Path] = []

    if name == "gdas1":
        seen: set[str] = set()
        for day in _days(start, end):
            week = (day.day - 1) // 7 + 1
            fname = f"gdas1.{day.strftime('%b').lower()}{day:%y}.w{week}"
            path = root / "gdas1" / f"{day:%Y}" / fname
            if str(path) not in seen:
                seen.add(str(path))
                expected.append(path)

        files = [p for p in expected if p.is_file()]
        missing = [p for p in expected if not p.is_file()]

        # current7days is a valid substitute for recent GDAS1 coverage if it
        # already exists.  This checker never refreshes/downloads it.
        today = datetime.now(timezone.utc).replace(tzinfo=None)
        today = datetime(today.year, today.month, today.day)
        current = root / "gdas1" / "current7days"
        if end >= today - timedelta(days=7) and current.is_file():
            files.insert(0, current)

        return {
            "name": name,
            "root": root,
            "start": start,
            "end": end,
            "files": _unique(files),
            "expected": expected,
            "missing": missing,
        }

    if name == "gdas0p5":
        expected = [root / "gdas0p5" / f"{day:%Y%m%d}_gdas0p5" for day in _days(start, end)]
    elif name == "gfs0p25":
        expected = [
            root / "gfs0p25" / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y%m%d}_gfs0p25"
            for day in _days(start, end)
        ]
    elif name == "gfs0p25.f":
        expected = _gfs0p25_forecast_files(root, start, end)
    elif name == "nam12":
        expected = [root / "nam12" / f"{day:%Y%m%d}_nam12" for day in _days(start, end)]
    elif name == "narr":
        expected = [root / "narr" / f"NARR{month:%Y%m}" for month in _months(start, end)]
    elif name == "nams":
        expected = [
            root / "nams" / f"{day:%Y%m%d}_hysplit.t00z.namsa"
            for day in _days(start, end)
        ]
    elif name == "hrrr":
        tags = ["00-05", "06-11", "12-17", "18-23"]
        cur = start.replace(minute=0, second=0, microsecond=0)
        stop = end.replace(minute=0, second=0, microsecond=0)
        while cur <= stop:
            expected.append(root / "hrrr" / f"{cur:%Y%m%d}_{tags[cur.hour // 6]}_hrrr")
            cur += timedelta(hours=1)
        expected = _unique(expected)
    else:
        raise ValueError(f"Unsupported ARL name: {name}")

    return {
        "name": name,
        "root": root,
        "start": start,
        "end": end,
        "files": list(expected),
        "expected": list(expected),
        "missing": [p for p in expected if not p.is_file()],
    }


# -----------------------------------------------------------------------------
# ARL binary parser/checker
# -----------------------------------------------------------------------------


def _decode_ascii(raw: bytes) -> str:
    return raw.decode("ascii", errors="strict")


def _field_int(raw: bytes, name: str) -> int:
    text = _decode_ascii(raw).strip()
    if not text:
        raise ValueError(f"blank {name}")
    return int(text)


def _parse_label(label: bytes) -> dict[str, Any]:
    if len(label) != 50:
        raise ValueError(f"ARL label is {len(label)} bytes; expected 50")

    # Same fixed-width fields as ii_arl_time.pro: (5I2,2X,A2,A4)
    yy = _field_int(label[0:2], "year")
    mo = _field_int(label[2:4], "month")
    da = _field_int(label[4:6], "day")
    hr = _field_int(label[6:8], "hour")
    ic = _field_int(label[8:10], "IC")
    cgrid = _decode_ascii(label[12:14])
    kvar = _decode_ascii(label[14:18]).strip()

    year = 1900 + yy if yy > 40 else 2000 + yy
    t = datetime(year, mo, da, hr)
    return {"time": t, "ic": ic, "cgrid": cgrid, "kvar": kvar}


def _parse_index_header(header: bytes, cgrid: str) -> dict[str, Any]:
    if len(header) != 108:
        raise ValueError(f"ARL index header is {len(header)} bytes; expected 108")

    # Same IDL format: (A4,I3,I2,12F7.0,3I3,I2,I4)
    model_id = _decode_ascii(header[0:4]).strip()
    icx = _field_int(header[4:7], "ICX")
    mn = _field_int(header[7:9], "MN")
    nx = _field_int(header[93:96], "NX")
    ny = _field_int(header[96:99], "NY")
    nz = _field_int(header[99:102], "NZ")
    z_flag = _field_int(header[102:104], "Z_FLAG")
    lenh = _field_int(header[104:108], "LENH")

    cgrid_b = cgrid.encode("ascii", errors="strict")
    if len(cgrid_b) != 2:
        raise ValueError(f"invalid CGRID {cgrid!r}")
    knx, kny = cgrid_b[0], cgrid_b[1]
    if knx >= 64:
        nx += (knx - 64) * 1000
    if kny >= 64:
        ny += (kny - 64) * 1000

    return {
        "model_id": model_id,
        "icx": icx,
        "mn": mn,
        "nx": nx,
        "ny": ny,
        "nz": nz,
        "z_flag": z_flag,
        "lenh": lenh,
    }


def hysp_arl_info(file: str | os.PathLike[str]) -> dict[str, Any]:
    """Inspect one ARL file and return validity and time/grid information."""
    path = Path(file).expanduser()
    info: dict[str, Any] = {
        "file": str(path),
        "valid": False,
        "errors": [],
        "warnings": [],
        "size": 0,
        "model_id": "",
        "cgrid": "",
        "nx": 0,
        "ny": 0,
        "nz": 0,
        "reclen": 0,
        "nrecord": 0,
        "stime": None,
        "etime": None,
        "hourly": 0,
        "ntime": 0,
    }

    errors: list[str] = info["errors"]
    warnings: list[str] = info["warnings"]

    try:
        if not path.is_file():
            errors.append("file does not exist")
            return info

        size = path.stat().st_size
        info["size"] = size
        if size == 0:
            errors.append("zero-length file")
            return info
        if size < 158:
            errors.append(f"file is too small ({size} bytes)")
            return info

        with path.open("rb") as f:
            first_label_raw = f.read(50)
            first_header_raw = f.read(108)

            try:
                first_label = _parse_label(first_label_raw)
            except Exception as exc:
                errors.append(f"cannot parse first ARL label: {exc}")
                return info

            try:
                first_header = _parse_index_header(first_header_raw, first_label["cgrid"])
            except Exception as exc:
                errors.append(f"cannot parse first ARL index header: {exc}")
                return info

            info["model_id"] = first_header["model_id"]
            info["cgrid"] = first_label["cgrid"]
            info["nx"] = first_header["nx"]
            info["ny"] = first_header["ny"]
            info["nz"] = first_header["nz"]

            nx = first_header["nx"]
            ny = first_header["ny"]
            nz = first_header["nz"]
            if nx <= 0 or ny <= 0 or nz <= 0:
                errors.append(f"invalid grid dimensions: {nx} x {ny} x {nz}")
                return info

            reclen = nx * ny + 50
            info["reclen"] = reclen
            if reclen < 158:
                errors.append(f"invalid ARL record length: {reclen}")
                return info
            if size < reclen:
                errors.append(f"file size ({size}) is smaller than one ARL record ({reclen})")
                return info

            nrecord, remainder = divmod(size, reclen)
            info["nrecord"] = nrecord
            if remainder != 0:
                errors.append(
                    f"truncated/misaligned file: size {size} is not a multiple "
                    f"of record length {reclen} (remainder {remainder})"
                )

            times: list[datetime] = []
            previous_time: datetime | None = None

            for i in range(nrecord):
                f.seek(i * reclen)
                raw = f.read(50)
                if len(raw) != 50:
                    errors.append(f"cannot read record label {i}")
                    break

                try:
                    label = _parse_label(raw)
                except Exception as exc:
                    errors.append(f"bad ARL label at record {i}: {exc}")
                    break

                t = label["time"]
                if previous_time is not None and t < previous_time:
                    errors.append(
                        f"time decreases at record {i}: "
                        f"{t:%Y%m%d%H} < {previous_time:%Y%m%d%H}"
                    )
                    break

                if previous_time is None or t != previous_time:
                    if label["kvar"].upper() != "INDX":
                        errors.append(
                            f"time block {t:%Y%m%d%H} starts with "
                            f"KVAR={label['kvar']!r}, expected 'INDX' (record {i})"
                        )
                        break

                    f.seek(i * reclen + 50)
                    raw_header = f.read(108)
                    try:
                        hdr = _parse_index_header(raw_header, label["cgrid"])
                    except Exception as exc:
                        errors.append(f"bad index header at record {i} ({t:%Y%m%d%H}): {exc}")
                        break

                    block_reclen = hdr["nx"] * hdr["ny"] + 50
                    if block_reclen != reclen:
                        errors.append(
                            f"grid/record length changes at {t:%Y%m%d%H}: "
                            f"{hdr['nx']}x{hdr['ny']} -> {block_reclen}, expected {reclen}"
                        )
                        break

                    times.append(t)

                previous_time = t

        if not times:
            errors.append("no valid ARL time blocks found")
            return info

        info["stime"] = times[0]
        info["etime"] = times[-1]
        info["ntime"] = len(times)

        if len(times) >= 2:
            dh = [int((b - a).total_seconds() / 3600) for a, b in zip(times, times[1:])]
            positive = [x for x in dh if x > 0]
            if not positive:
                errors.append("ARL time blocks do not advance")
            else:
                info["hourly"] = positive[0]
                if any(x != positive[0] for x in positive[1:]):
                    warnings.append(
                        "time interval changes within file: "
                        + ",".join(str(x) for x in sorted(set(positive)))
                        + " h"
                    )
        else:
            warnings.append("file contains only one meteorological time block")

        info["valid"] = len(errors) == 0
        return info

    except OSError as exc:
        errors.append(str(exc))
        return info


# -----------------------------------------------------------------------------
# Coverage and public interface
# -----------------------------------------------------------------------------


def _coverage_check(infos: list[dict[str, Any]], time: Any) -> tuple[bool, list[str]]:
    requested = [_parse_time(x) for x in _as_times(time)]
    if not requested:
        return True, []

    start = min(requested)
    end = max(requested)
    good = [x for x in infos if x.get("valid") and x.get("stime") and x.get("etime")]
    if not good:
        return False, ["no valid ARL files available for requested time"]

    good.sort(key=lambda x: x["stime"])
    intervals: list[tuple[datetime, datetime, int]] = []
    for x in good:
        intervals.append((x["stime"], x["etime"], int(x.get("hourly") or 0)))

    current_start, current_end, current_step = intervals[0]
    merged: list[tuple[datetime, datetime]] = []
    for s, e, step in intervals[1:]:
        tolerance_h = max(current_step, step, 1)
        if s <= current_end + timedelta(hours=tolerance_h):
            current_end = max(current_end, e)
            current_step = max(current_step, step)
        else:
            merged.append((current_start, current_end))
            current_start, current_end, current_step = s, e, step
    merged.append((current_start, current_end))

    for s, e in merged:
        if s <= start and e >= end:
            return True, []

    messages = [f"requested coverage {start:%Y%m%d%H}-{end:%Y%m%d%H} is not continuous"]
    messages.extend(f"available {s:%Y%m%d%H}-{e:%Y%m%d%H}" for s, e in merged)
    return False, messages


def _print_info(info: dict[str, Any]) -> None:
    status = "OK " if info["valid"] else "BAD"
    print(f"[{status}] {info['file']}")
    if info["valid"]:
        st = info["stime"].strftime("%Y%m%d%H") if info["stime"] else ""
        et = info["etime"].strftime("%Y%m%d%H") if info["etime"] else ""
        print(
            f"      {st} - {et}  dt={info['hourly']}h  ntime={info['ntime']}  "
            f"grid={info['nx']}x{info['ny']}x{info['nz']}  records={info['nrecord']}"
        )
        for msg in info["warnings"]:
            print(f"      WARNING: {msg}")
    else:
        for msg in info["errors"]:
            print(f"      {msg}")


def hysp_arl_chk(
    target: str | os.PathLike[str] | Sequence[str | os.PathLike[str]],
    *,
    time: Any | None = None,
    ini: str | Path = "hysp.ini",
    verbose: bool = True,
) -> bool:
    """
    Check ARL files by dataset name or filename.

    Examples
    --------
    hysp_arl_chk("gdas1", time=[2026072500, 2026072700])
    hysp_arl_chk("/data/arl/gfs0p25/2026/07/20260725_gfs0p25")

    A recognized dataset name requires ``time`` and resolves files under
    ARL_PATH using the current IDL directory conventions.  Any other argument
    is treated as a filename (or sequence of filenames).

    The checker never downloads, deletes, or rewrites files.
    """
    dataset_mode = False
    dataset_name = ""
    plan: dict[str, Any] | None = None

    if isinstance(target, (str, os.PathLike)):
        text = str(target)
        low = text.lower()
        # Existing paths always mean file mode, even if their basename happens
        # to match a dataset name.
        if low in ARL_NAMES and not Path(text).expanduser().exists():
            dataset_mode = True
            dataset_name = low

    if dataset_mode:
        if time is None:
            raise ValueError(f'"time" required for ARL dataset {dataset_name!r}')

        plan = _dataset_plan(dataset_name, time, ini)
        files = list(plan["files"])

        if verbose:
            print(f"ARL       : {dataset_name}")
            print(f"ARL_PATH  : {plan['root']}")
            print(f"TIME      : {plan['start']:%Y%m%d%H} - {plan['end']:%Y%m%d%H}")

        # GDAS1 can be satisfied by weekly archives, current7days, and then
        # GFS1 forecast files.  Add existing/planned forecast files only when
        # the archive/current candidates do not cover the requested end.
        if dataset_name == "gdas1":
            infos0 = [hysp_arl_info(p) for p in files]
            cov0, _ = _coverage_check(infos0, time)
            if not cov0:
                valid0 = [x for x in infos0 if x.get("valid") and x.get("etime")]
                if valid0:
                    coverage_end = max(x["etime"] for x in valid0)
                    fcst_start = max(plan["start"], coverage_end + timedelta(hours=1))
                else:
                    fcst_start = plan["start"]

                fcst = _gfs1_forecast_files(plan["root"], fcst_start)
                files.extend(fcst)
                files = _unique(files)

    else:
        files = _as_files(target)

    if not files:
        if verbose:
            print(f"[BAD] no ARL files matched/resolved: {target}")
        return False

    infos = [hysp_arl_info(p) for p in files]
    ok_files = all(x["valid"] for x in infos)

    if verbose:
        for info in infos:
            _print_info(info)

    cov_ok = True
    messages: list[str] = []
    if time is not None:
        cov_ok, messages = _coverage_check(infos, time)

    # For normal datasets, every expected file is required.  For gdas1,
    # missing weekly archive files are allowed when current7days/forecast gives
    # valid continuous coverage.  Existing corrupt files still fail the check.
    if dataset_mode and dataset_name == "gdas1" and plan is not None:
        existing_expected = [p for p in plan["expected"] if p.is_file()]
        existing_expected_set = {str(p) for p in existing_expected}
        corrupt_expected = [
            x for x in infos
            if x["file"] in existing_expected_set and not x["valid"]
        ]
        corrupt_other = [
            x for x in infos
            if x["file"] not in {str(p) for p in plan["missing"]}
            and x["file"] not in existing_expected_set
            and Path(x["file"]).is_file()
            and not x["valid"]
        ]
        ok_files = not corrupt_expected and not corrupt_other

        if verbose and plan["missing"]:
            tag = "substituted" if cov_ok else "not covered"
            for p in plan["missing"]:
                print(f"[MISS] {p}  ({tag})")

    ok = ok_files and cov_ok

    if time is not None and verbose:
        if cov_ok:
            start, end = _time_bounds(time)
            print(f"[COVERAGE OK] {start:%Y%m%d%H} - {end:%Y%m%d%H}")
        else:
            print("[COVERAGE BAD]")
            for msg in messages:
                print(f"      {msg}")

    return ok


# -----------------------------------------------------------------------------
# Command line
# -----------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Check HYSPLIT ARL files. TARGET can be an ARL dataset name "
            "(gdas1, gfs0p25, gfs0p25.f, ...) or one/more filenames."
        )
    )
    parser.add_argument(
        "target",
        nargs="+",
        help="ARL dataset name or ARL file(s)",
    )
    parser.add_argument(
        "--time",
        nargs="+",
        default=None,
        help="time array; required for dataset-name mode; min/max are checked",
    )
    parser.add_argument(
        "--ini",
        default="hysp.ini",
        help="shared IDL/Python hysp.ini (default: ./hysp.ini)",
    )
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args()

    if len(args.target) == 1:
        target: Any = args.target[0]
    else:
        # Multiple positional arguments are file mode.  A dataset name is one
        # positional argument plus --time.
        target = args.target

    try:
        ok = hysp_arl_chk(
            target,
            time=args.time,
            ini=args.ini,
            verbose=not args.quiet,
        )
    except (ValueError, KeyError, OSError) as exc:
        if not args.quiet:
            print(f"[BAD] {exc}")
        raise SystemExit(2)

    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
