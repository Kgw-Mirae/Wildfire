from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from data.Domain.domain_utils import DomainConfig


@dataclass(frozen=True)
class FirelineEntry:
    path: Path
    forecast_base_time: datetime
    fireline_time: datetime


@dataclass(frozen=True)
class FirelineSchedule:
    forecast_base_time: datetime
    forecast_end_time: datetime
    entries: list[FirelineEntry]
    interval: timedelta

    @property
    def first_fireline_time(self) -> datetime:
        return self.entries[0].fireline_time

    @property
    def last_used_fireline_time(self) -> datetime:
        return self.entries[-1].fireline_time

    @property
    def model_duration_seconds(self) -> int:
        return int(round((self.forecast_end_time - self.first_fireline_time).total_seconds()))


def parse_fireline_times(path: Path) -> tuple[datetime, datetime] | None:
    match = re.search(r"(\d{12})_(\d{12})", path.stem)
    if not match:
        return None
    return (
        datetime.strptime(match.group(1), "%Y%m%d%H%M"),
        datetime.strptime(match.group(2), "%Y%m%d%H%M"),
    )


def infer_interval(times: list[datetime]) -> timedelta:
    if len(times) < 2:
        raise ValueError("At least two usable fireline times are required.")
    deltas = [
        int((b - a).total_seconds())
        for a, b in zip(times, times[1:])
        if b > a
    ]
    if not deltas:
        raise ValueError("Cannot infer positive fireline time interval.")
    return timedelta(seconds=min(deltas, key=lambda value: (-deltas.count(value), value)))


def build_fireline_schedule(geojson_dir: Path, cfg: DomainConfig) -> FirelineSchedule:
    entries: list[FirelineEntry] = []
    for path in sorted(geojson_dir.glob("*.geojson")):
        parsed = parse_fireline_times(path)
        if parsed is None:
            continue
        base_time, fireline_time = parsed
        entries.append(FirelineEntry(path, base_time, fireline_time))

    if not entries:
        raise RuntimeError(f"No valid fireline GeoJSON times found in {geojson_dir}")

    base_times = sorted({entry.forecast_base_time for entry in entries})
    forecast_base_time = base_times[0]
    if len(base_times) > 1:
        print(
            "[WARN] Multiple forecast base times found; "
            f"using earliest base time {forecast_base_time:%Y-%m-%d %H:%M}."
        )

    if cfg.forecast_duration_s <= 0:
        raise ValueError(
            "forecast_duration_h/forecast_duration_m must define a positive forecast duration."
        )

    forecast_end_time = forecast_base_time + timedelta(seconds=cfg.forecast_duration_s)
    selected = [
        entry
        for entry in entries
        if entry.forecast_base_time == forecast_base_time
        and entry.fireline_time < forecast_end_time
    ]
    if not selected:
        raise RuntimeError(
            "No fireline GeoJSON files are earlier than the configured forecast end time "
            f"({forecast_end_time:%Y-%m-%d %H:%M})."
        )
    selected.sort(key=lambda entry: entry.fireline_time)
    interval = infer_interval([entry.fireline_time for entry in selected])
    return FirelineSchedule(forecast_base_time, forecast_end_time, selected, interval)
