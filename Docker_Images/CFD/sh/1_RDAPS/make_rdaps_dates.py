#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from data.Domain.domain_utils import load_domain_config
from fireline_schedule import build_fireline_schedule


SCRIPT_DIR = Path(__file__).resolve().parent
GEOJSON_DIRS = [
    PROJECT_DIR / "data" / "Geojson",
    PROJECT_DIR / "data" / "geojson",
]
OUT_FILE = SCRIPT_DIR / "rdaps_dates.txt"


def round_weather_hour(value: datetime) -> datetime:
    base = value.replace(minute=0, second=0, microsecond=0)
    if value.minute <= 30:
        return base
    return base + timedelta(hours=1)


def hourly_range(start: datetime, end: datetime) -> list[datetime]:
    dates: list[datetime] = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(hours=1)
    return dates


def main() -> None:
    geojson_dir = next((path for path in GEOJSON_DIRS if path.exists()), GEOJSON_DIRS[0])
    cfg = load_domain_config(PROJECT_DIR)
    schedule = build_fireline_schedule(geojson_dir, cfg)
    rdaps_start = round_weather_hour(schedule.first_fireline_time)
    rdaps_end = round_weather_hour(schedule.forecast_end_time)
    rdaps_dates = hourly_range(rdaps_start, rdaps_end)

    OUT_FILE.write_text(
        "\n".join(date.strftime("%Y.%m.%d.%H") for date in rdaps_dates) + "\n",
        encoding="utf-8",
    )

    print(
        "[OK] RDAPS dates: "
        f"fireline={schedule.first_fireline_time:%Y-%m-%d %H:%M}~"
        f"{schedule.last_used_fireline_time:%Y-%m-%d %H:%M}, "
        f"interval={int(schedule.interval.total_seconds())}s, "
        f"model_end={schedule.forecast_end_time:%Y-%m-%d %H:%M}, "
        f"rdaps={rdaps_dates[0]:%Y-%m-%d %H}:00~"
        f"{rdaps_dates[-1]:%Y-%m-%d %H}:00 "
        f"({len(rdaps_dates)} times)"
    )


if __name__ == "__main__":
    main()
