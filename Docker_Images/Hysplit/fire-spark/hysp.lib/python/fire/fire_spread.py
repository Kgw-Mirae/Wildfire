#!/usr/bin/env python3
"""
fire_spread.py

Fire-spread GeoJSON -> hourly 1-km source-grid converter.

This is the "spread" emission-data counterpart to fire_finn_nrt.py and
fire_rave.py.

It preserves the earlier fire-line workflow:

    timestamped EPSG:5179 GeoJSON snapshots
        -> square projected grid (default 1000 m)
        -> hourly UTC source cells
        -> ASCII:
             YYYYMMDDHH LAT LON intensity

Filename convention
-------------------
    YYYYMMDDHHMM_YYYYMMDDHHMM_P.geojson

The FIRST timestamp identifies the beginning of an independent spread case.
The SECOND timestamp is the snapshot time.  Within a case, each snapshot
represents the interval immediately preceding that snapshot:

    first interval : case_start -> first snapshot
    later intervals: previous snapshot -> current snapshot

Cases are distinguished by parent directory + first filename timestamp.

The GeoJSON must explicitly identify EPSG:5179.  Line pieces are clipped at
grid-cell boundaries.  Hourly cell intensity is weighted by clipped line
length times the amount of snapshot interval overlapping that UTC hour.

The intensity field is an activity indicator/diagnostic; this module does not
interpret it as PM2.5 emission rate or FRP.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, Sequence
from zoneinfo import ZoneInfo


_FILENAME_RE = re.compile(
    r"(?P<case>\d{12})_(?P<snap>\d{12})(?:_[^/]*)?\.geojson$",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class SpreadRecord:
    time: datetime       # UTC hour, naive datetime
    lat: float
    lon: float
    intensity: float


@dataclass(frozen=True)
class _Snapshot:
    source: str
    parent_key: str
    case_start: datetime
    snap_time: datetime
    data: dict[str, Any]


def _require_pyproj():
    try:
        from pyproj import Transformer
    except ImportError as exc:
        raise ImportError(
            "fire_spread.py requires pyproj. Install it in the active environment."
        ) from exc
    return Transformer


def _parse_filename(name: str) -> tuple[datetime, datetime]:
    m = _FILENAME_RE.search(Path(name).name)
    if not m:
        raise ValueError(
            "Spread GeoJSON filename must look like "
            "YYYYMMDDHHMM_YYYYMMDDHHMM_P.geojson: "
            f"{name}"
        )
    return (
        datetime.strptime(m.group("case"), "%Y%m%d%H%M"),
        datetime.strptime(m.group("snap"), "%Y%m%d%H%M"),
    )


def _crs_is_5179(data: dict[str, Any]) -> bool:
    crs = data.get("crs")
    if not crs:
        return False

    text = json.dumps(crs, sort_keys=True).upper()
    return (
        "5179" in text
        and ("EPSG" in text or "URN:OGC:DEF:CRS" in text or "NAME" in text)
    )


def _feature_intensity(feature: dict[str, Any]) -> float:
    prop = feature.get("properties") or {}
    for key, value in prop.items():
        if str(key).lower() == "intensity":
            try:
                return float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid Intensity={value!r}") from exc
    raise KeyError("GeoJSON feature has no 'Intensity' property")


def _iter_lines_geometry(geom: dict[str, Any] | None) -> Iterator[list[list[float]]]:
    if not geom:
        return
    gtype = str(geom.get("type", ""))
    coords = geom.get("coordinates")

    if gtype == "LineString":
        if coords:
            yield coords
    elif gtype == "MultiLineString":
        for line in coords or []:
            if line:
                yield line
    elif gtype == "Polygon":
        # Be permissive: use rings as fire-line pieces.
        for ring in coords or []:
            if ring:
                yield ring
    elif gtype == "MultiPolygon":
        for poly in coords or []:
            for ring in poly or []:
                if ring:
                    yield ring
    elif gtype == "GeometryCollection":
        for part in geom.get("geometries") or []:
            yield from _iter_lines_geometry(part)
    else:
        raise ValueError(f"Unsupported GeoJSON geometry type: {gtype!r}")


def _expand_inputs(inputs: Sequence[str | os.PathLike[str]]) -> list[_Snapshot]:
    out: list[_Snapshot] = []
    seen: set[str] = set()

    def add_json(data: dict[str, Any], source: str, parent_key: str, base_name: str) -> None:
        case_start, snap_time = _parse_filename(base_name)
        key = f"{source}"
        if key in seen:
            return
        seen.add(key)

        if not _crs_is_5179(data):
            raise ValueError(f"Expected EPSG:5179 in GeoJSON CRS: {source}")

        out.append(
            _Snapshot(
                source=source,
                parent_key=parent_key,
                case_start=case_start,
                snap_time=snap_time,
                data=data,
            )
        )

    for item0 in inputs:
        item = Path(item0).expanduser()

        if item.is_dir():
            for p in sorted(item.rglob("*.geojson")):
                data = json.loads(p.read_text(encoding="utf-8"))
                add_json(data, str(p), str(p.parent.resolve()), p.name)
            for p in sorted(item.rglob("*.zip")):
                with zipfile.ZipFile(p) as z:
                    for member in sorted(z.namelist()):
                        if not member.lower().endswith(".geojson"):
                            continue
                        data = json.loads(z.read(member).decode("utf-8"))
                        parent = f"{p.resolve()}::{PurePosixPath(member).parent}"
                        add_json(data, f"{p}::{member}", parent, PurePosixPath(member).name)
            continue

        if item.is_file() and item.suffix.lower() == ".zip":
            with zipfile.ZipFile(item) as z:
                for member in sorted(z.namelist()):
                    if not member.lower().endswith(".geojson"):
                        continue
                    data = json.loads(z.read(member).decode("utf-8"))
                    parent = f"{item.resolve()}::{PurePosixPath(member).parent}"
                    add_json(data, f"{item}::{member}", parent, PurePosixPath(member).name)
            continue

        if item.is_file() and item.suffix.lower() == ".geojson":
            data = json.loads(item.read_text(encoding="utf-8"))
            add_json(data, str(item), str(item.parent.resolve()), item.name)
            continue

        # Support a shell pattern passed literally.
        matches = sorted(Path().glob(str(item0)))
        if matches:
            for p in matches:
                if p.is_file() and p.suffix.lower() == ".geojson":
                    data = json.loads(p.read_text(encoding="utf-8"))
                    add_json(data, str(p), str(p.parent.resolve()), p.name)
            continue

        raise FileNotFoundError(item)

    if not out:
        raise FileNotFoundError("No spread GeoJSON files found")

    return out


def _local_to_utc(dt: datetime, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    return dt.replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)


def _hour_overlaps(start: datetime, end: datetime) -> Iterator[tuple[datetime, float]]:
    """Yield (UTC hour start, overlap seconds) for [start,end)."""
    if end <= start:
        return
    h = start.replace(minute=0, second=0, microsecond=0)
    while h < end:
        h2 = h + timedelta(hours=1)
        a = max(start, h)
        b = min(end, h2)
        sec = (b - a).total_seconds()
        if sec > 0:
            yield h, sec
        h = h2


def _segment_grid_pieces(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    grid_m: float,
    origin_x: float,
    origin_y: float,
) -> Iterator[tuple[int, int, float]]:
    """
    Split one segment at all square-grid boundaries and return
    (ix, iy, clipped_length_m).
    """
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    if not math.isfinite(length) or length <= 0:
        return

    tt = [0.0, 1.0]

    if dx != 0:
        lo, hi = sorted((x0, x1))
        k0 = math.floor((lo - origin_x) / grid_m) + 1
        k1 = math.floor((hi - origin_x) / grid_m)
        for k in range(k0, k1 + 1):
            xb = origin_x + k * grid_m
            t = (xb - x0) / dx
            if 0.0 < t < 1.0:
                tt.append(t)

    if dy != 0:
        lo, hi = sorted((y0, y1))
        k0 = math.floor((lo - origin_y) / grid_m) + 1
        k1 = math.floor((hi - origin_y) / grid_m)
        for k in range(k0, k1 + 1):
            yb = origin_y + k * grid_m
            t = (yb - y0) / dy
            if 0.0 < t < 1.0:
                tt.append(t)

    tt = sorted(set(round(t, 14) for t in tt))

    for a, b in zip(tt[:-1], tt[1:]):
        if b <= a:
            continue
        tm = 0.5 * (a + b)
        xm = x0 + tm * dx
        ym = y0 + tm * dy
        ix = math.floor((xm - origin_x) / grid_m)
        iy = math.floor((ym - origin_y) / grid_m)
        yield ix, iy, length * (b - a)


def _case_groups(snapshots: Sequence[_Snapshot]) -> dict[tuple[str, datetime], list[_Snapshot]]:
    groups: dict[tuple[str, datetime], list[_Snapshot]] = defaultdict(list)
    for x in snapshots:
        groups[(x.parent_key, x.case_start)].append(x)
    return groups


def _validate_case_times(case: Sequence[_Snapshot], *, tz_name: str) -> None:
    if not case:
        return
    ss = sorted(case, key=lambda x: x.snap_time)
    case_start = ss[0].case_start

    intervals_min: list[float] = []
    prev = case_start
    for x in ss:
        dt = (x.snap_time - prev).total_seconds() / 60.0
        if dt <= 0:
            raise ValueError(f"Non-increasing spread snapshot time: {x.source}")
        intervals_min.append(dt)
        prev = x.snap_time

    # The original workflow expected regular snapshots.  Infer the nominal
    # interval from the shortest positive interval; any integer multiple >1
    # indicates one or more missing snapshots.
    nominal = min(intervals_min)
    tol = 1e-6
    for x, dt in zip(ss, intervals_min):
        ratio = dt / nominal
        if abs(ratio - 1.0) > tol:
            raise ValueError(
                "Missing or irregular snapshots in spread case "
                f"{ss[0].parent_key} start={case_start:%Y%m%d%H%M}: "
                f"interval {dt:g} min before {x.snap_time:%Y%m%d%H%M}; "
                f"expected {nominal:g} min"
            )


def fire_spread(
    inputs: Sequence[str | os.PathLike[str]] | str | os.PathLike[str],
    *,
    grid_m: float = 1000.0,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
    input_timezone: str = "Asia/Seoul",
    output: str | os.PathLike[str] | None = None,
    verbose: bool = True,
) -> list[SpreadRecord]:
    """
    Convert spread GeoJSON snapshots to hourly UTC 1-km source records.
    """
    if isinstance(inputs, (str, os.PathLike)):
        input_list = [inputs]
    else:
        input_list = list(inputs)

    if grid_m <= 0:
        raise ValueError("grid_m must be > 0")

    snapshots = _expand_inputs(input_list)
    groups = _case_groups(snapshots)

    Transformer = _require_pyproj()
    to_wgs84 = Transformer.from_crs(5179, 4326, always_xy=True)

    # key=(UTC-hour, ix, iy), values=[sum(I*L*dt), sum(L*dt)]
    accum: dict[tuple[datetime, int, int], list[float]] = defaultdict(lambda: [0.0, 0.0])

    for (_parent, _case_start), case0 in sorted(
        groups.items(), key=lambda x: (str(x[0][0]), x[0][1])
    ):
        case = sorted(case0, key=lambda x: x.snap_time)
        _validate_case_times(case, tz_name=input_timezone)

        prev_local = case[0].case_start
        for snap in case:
            start_utc = _local_to_utc(prev_local, input_timezone)
            end_utc = _local_to_utc(snap.snap_time, input_timezone)
            prev_local = snap.snap_time

            overlaps = list(_hour_overlaps(start_utc, end_utc))
            if not overlaps:
                continue

            features = snap.data.get("features") or []
            for feat in features:
                intensity = _feature_intensity(feat)
                if not math.isfinite(intensity):
                    continue

                for line in _iter_lines_geometry(feat.get("geometry")):
                    for p0, p1 in zip(line[:-1], line[1:]):
                        if len(p0) < 2 or len(p1) < 2:
                            continue
                        x0, y0 = float(p0[0]), float(p0[1])
                        x1, y1 = float(p1[0]), float(p1[1])

                        pieces = list(
                            _segment_grid_pieces(
                                x0, y0, x1, y1,
                                grid_m=grid_m,
                                origin_x=origin_x,
                                origin_y=origin_y,
                            )
                        )
                        for hour, sec in overlaps:
                            for ix, iy, length_m in pieces:
                                w = length_m * sec
                                a = accum[(hour, ix, iy)]
                                a[0] += intensity * w
                                a[1] += w

    records: list[SpreadRecord] = []
    for (hour, ix, iy), (num, den) in sorted(accum.items()):
        if den <= 0:
            continue
        xc = origin_x + (ix + 0.5) * grid_m
        yc = origin_y + (iy + 0.5) * grid_m
        lon, lat = to_wgs84.transform(xc, yc)
        records.append(
            SpreadRecord(
                time=hour,
                lat=float(lat),
                lon=float(lon),
                intensity=float(num / den),
            )
        )

    if output is not None:
        fire_spread_write(records, output, verbose=verbose)

    if verbose:
        print(
            f"SPREAD: {len(snapshots)} GeoJSON snapshots, "
            f"{len(groups)} cases, {len(records)} hourly cell records"
        )

    return records


def fire_spread_write(
    records: Sequence[SpreadRecord] | Iterable[SpreadRecord],
    file: str | os.PathLike[str],
    *,
    verbose: bool = True,
) -> Path:
    rr = sorted(list(records), key=lambda x: (x.time, x.lat, x.lon))
    path = Path(file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        f.write("YYYYMMDDHH LAT LON intensity\n")
        for x in rr:
            f.write(
                f"{x.time:%Y%m%d%H} "
                f"{x.lat:.9f} {x.lon:.9f} {x.intensity:.12g}\n"
            )

    if verbose:
        print(f"SAVE {path} {len(rr)} lines")
    return path


def fire_spread_read(file: str | os.PathLike[str]) -> list[SpreadRecord]:
    path = Path(file).expanduser()
    out: list[SpreadRecord] = []

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.upper().startswith("YYYY"):
            continue
        p = s.split()
        if len(p) < 4:
            continue
        out.append(
            SpreadRecord(
                time=datetime.strptime(p[0], "%Y%m%d%H"),
                lat=float(p[1]),
                lon=float(p[2]),
                intensity=float(p[3]),
            )
        )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Convert fire-spread GeoJSON snapshots to hourly UTC source cells."
    )
    p.add_argument("inputs", nargs="+", help="GeoJSON file(s), directories, or ZIP archives")
    p.add_argument("-o", "--output", required=True, help="hourly ASCII output")
    p.add_argument("--grid-m", type=float, default=1000.0)
    p.add_argument("--origin-x", type=float, default=0.0)
    p.add_argument("--origin-y", type=float, default=0.0)
    p.add_argument("--input-timezone", default="Asia/Seoul")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    try:
        fire_spread(
            args.inputs,
            grid_m=args.grid_m,
            origin_x=args.origin_x,
            origin_y=args.origin_y,
            input_timezone=args.input_timezone,
            output=args.output,
            verbose=not args.quiet,
        )
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
