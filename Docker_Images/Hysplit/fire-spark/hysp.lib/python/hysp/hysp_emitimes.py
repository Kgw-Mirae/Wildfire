#!/usr/bin/env python3
"""
hysp_emitimes.py

Minimal Python reader/writer for HYSPLIT EMITIMES files, matching the formatting
used by the user's hysp_emitimes_write.pro / hysp_emitimes_read.pro routines.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence, Any


@dataclass
class EmitimesRecord:
    time: datetime
    duration: str
    lat: float
    lon: float
    hgt: float
    rate: float
    area: float
    heat: float


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 12:
        return datetime.strptime(digits[:12], "%Y%m%d%H%M")
    if len(digits) >= 10:
        return datetime.strptime(digits[:10], "%Y%m%d%H")
    if len(digits) >= 8:
        return datetime.strptime(digits[:8], "%Y%m%d")
    return datetime.fromisoformat(text)


def _duration_hours(duration: str) -> float:
    text = str(duration).strip().zfill(4)
    hh = int(text[:2])
    mm = int(text[2:4])
    return hh + mm / 60.0


def hysp_emitimes_write(
    records: Sequence[EmitimesRecord] | Iterable[EmitimesRecord],
    *,
    filename: str | Path = "EMITIMES",
    group: Sequence[Any] | None = None,
    record: str | None = None,
    overwrite: bool = True,
    verbose: bool = True,
) -> Path:
    rr = list(records)
    if not rr:
        raise ValueError("No EMITIMES records")

    out = Path(filename)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not overwrite:
        raise FileExistsError(out)

    header1 = "YYYY MM DD HH DURATION(hhhh) RECORDS"
    header2 = "YYYY MM DD HH MM DURATION(hhmm) LAT LON HGT(m) RATE(/h) AREA(m2) HEAT(W)"

    start = min(x.time for x in rr)
    end = max(x.time + timedelta(hours=_duration_hours(x.duration)) for x in rr)
    dhour = int((end - start).total_seconds() / 3600.0 + 0.999999)

    if group is not None:
        g = list(group)
        if len(g) >= 1:
            start = _parse_time(g[0])
        if len(g) >= 2:
            dhour = int(g[1])

    if record:
        base = header2.split()
        names = str(record).split()
        header2 = " ".join(base[: len(base) - len(names)] + names)

    header3 = f"{start:%Y %m %d %H} {dhour:04d} {len(rr)}"

    if verbose:
        print(f"SAVE {out} {len(rr)} lines")

    with out.open("w", encoding="utf-8") as f:
        f.write(header1 + "\n")
        f.write(header2 + "\n")
        f.write(header3 + "\n")
        for x in rr:
            f.write(
                f"{x.time:%Y %m %d %H %M}"
                f"{str(x.duration):>5}"
                f"{float(x.lat):8.2f}"
                f"{float(x.lon):8.2f}"
                f"{float(x.hgt):8.2f}"
                f"{float(x.rate):12.4E}"
                f"{float(x.area):12.4E}"
                f"{float(x.heat):12.4E}\n"
            )
    return out


def hysp_emitimes_read(file: str | Path) -> list[EmitimesRecord]:
    path = Path(file)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 3:
        raise ValueError(f"Invalid EMITIMES: {path}")

    out: list[EmitimesRecord] = []
    for line in lines[3:]:
        p = line.split()
        if len(p) < 12:
            continue
        dt = datetime.strptime("".join(p[:5]), "%Y%m%d%H%M")
        out.append(
            EmitimesRecord(
                time=dt,
                duration=p[5],
                lat=float(p[6]),
                lon=float(p[7]),
                hgt=float(p[8]),
                rate=float(p[9]),
                area=float(p[10]),
                heat=float(p[11]),
            )
        )
    return out


def hysp_emitimes_locations(file: str | Path) -> list[str]:
    return [f"{x.lat:g} {x.lon:g} {x.hgt:g}" for x in hysp_emitimes_read(file)]
