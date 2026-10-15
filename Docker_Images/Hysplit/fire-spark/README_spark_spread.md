# spark_spread.py — fire-spread/HYSPLIT controller

Source version: `20261012-002` (12 October 2026).

## Purpose

Convert timestamped fire-front GeoJSON snapshots to an hourly **1-km default** activity grid and daily HYSPLIT `EMITIMES` sources, then prepare/check/run HYSPLIT through the existing NSFS routines. The workflow is:

```text
GeoJSON or ZIP → hourly UTC spread cells → EMITIMES → HYSPLIT cdump
```

This controller reuses `spark_daily.py` for configuration, meteorological selection, and run management; it uses the existing `fire.fire_spread` and `fire.fire_spread_emitimes` modules for emission preparation.

## Examples

```bash
# Preview one UTC day without converting or writing anything
python spark_spread.py 20250428 --dry-run

# Three-stage run
python spark_spread.py 20250428 --prepare-only
python spark_spread.py 20250428 --check-only
python spark_spread.py 20250428

# Explicit GeoJSON input, for example when a case spans multiple days
python spark_spread.py 20250428 --input /path/to/fire-geojson/ --input-timezone Asia/Seoul

# Run a date range or change source grid and emissions
python spark_spread.py 20250428 20250430 --grid-m 1000 --rate-gph 3000000

# Inspect or rebuild
python spark_spread.py 20250428 --status
python spark_spread.py 20250428 --renew
```

Date arguments are UTC `YYYYMMDD` or `YYYYMMDDHH`; omitting the hour means 00 UTC. The optional end date is inclusive.

## GeoJSON requirements

Without `--input`, source files are searched under:

```text
hysp.data/fire-spread/geojson/YYYY/YYYYMMDD/
```

`--input` accepts one or more `.geojson` files, `.zip` files, or directories. Filename timestamps follow `YYYYMMDDHHMM_YYYYMMDDHHMM_P.geojson`: the first is the case start and the second the snapshot time. The GeoJSON must identify `EPSG:5179` and contain the fire-line activity information expected by `fire.fire_spread`. By default filename timestamps are interpreted as `Asia/Seoul`, then converted to UTC; change with `--input-timezone` when necessary.

The automatic directory search uses the requested day's directory only. It **does not** add adjacent days' files; use `--input` with the full set of snapshots when a single fire case crosses day boundaries.

## Source parameters

| CLI option | Default | Meaning |
| --- | --- | --- |
| `--grid-m` | `1000` | Horizontal cell size in meters |
| `--origin-x`, `--origin-y` | `0`, `0` | Grid origin in projected coordinates |
| `--input-timezone` | `Asia/Seoul` | Time zone used in GeoJSON filenames |
| `--rate-gph` | `3e6` | HYSPLIT emission rate in g/h **per active cell-hour** |
| `--area-m2` | `1e6` | Source area per emission record |
| `--heat-w` | `5e6` | Source heat |
| `--height-m` | `1` | Release height above ground |

The fire-line intensity is currently used to determine **active** cells (positive intensity). It is not scaled into the default `RATE` or `HEAT` parameters. These values are placeholders/assumptions requiring scientific assessment for a given fire case.

## Configuration and outputs

Meteorology, HYSPLIT executable paths, CPU mode, and group templates follow the same `spark.ini`, `hysp.ini`, and `hysp.in/<group>/` conventions as `spark_daily.py`. Relevant overrides include `--group`, `--arl`, `--met-file`, `--forecast-cycle`, `--emission-domain`, `--duration`, `--cpu-mode`, and `--cpu-n`.

```text
hysp.data/fire-spread/hourly/YYYY/YYYYMMDD/
    spread_hourly.txt
    spread_hourly.source.json

hysp.run/<group>/<meteorology>-spread/YYYY/YYYYMMDD/
    CONTROL   SETUP.CFG   ASCDATA.CFG   EMITIMES
    cdump3    MESSAGE     log            spark_spread.status.json
```

The hourly source manifest records file signatures and grid/time-zone settings. Existing prepared files are preserved unless `--renew` is requested. Changing GeoJSON or the associated spread settings requires `--renew` before regenerating the run.

A day with no GeoJSON may legitimately return `no_input`; a day with no active UTC cells returns `no_emission`. Neither should be confused with a failed HYSPLIT simulation.

The local `hysp.lib/python` library is preferred through `spark_daily.py`; if it does not exist, the normal Python paths, including any `.pth` registration, apply.
