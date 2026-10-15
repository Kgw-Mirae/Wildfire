# HYSPLIT fire-spread emission modules

These are the previously developed fire-spread modules for the existing `fire` Python package. This distribution preserves their source without modification.

## Install on halo2

Unzip the two Python files into the `fire` module directory (the directory containing `nsfs_prep.py`):

```bash
unzip -o fire_spread_20261012-001.zip fire_spread.py fire_spread_emitimes.py \
    -d /data/blutouch/blutouch/lib/python/fire/
```

An existing `__init__.py` should remain unchanged. The ZIP has unversioned Python filenames.

## Check imports

```bash
python -c "from fire.fire_spread import fire_spread; from fire.fire_spread_emitimes import fire_spread_emitimes; print('SPREAD modules OK')"
```

## Retry SPARK preparation

```bash
cd ~/work/model/fire-spark-test2
python spark_spread.py 20250428 --prepare-only
python spark_spread.py 20250428 --check-only
```

## Routines

- `fire_spread.py`: parses timestamped EPSG:5179 GeoJSON snapshot lines or ZIPs and converts to an hourly UTC 1-km grid.
- `fire_spread_emitimes.py`: reads the hourly activity records and writes a daily HYSPLIT EMITIMES file using `hysp.hysp_emitimes`.

## Dependencies

- `pyproj`, used by `fire_spread.py`.
- Existing `hysp.hysp_emitimes` in the user's HYSP library, used by `fire_spread_emitimes.py`.
- `grdinfo.py` / `grdinfo_mask` only when a named domain or `minfo` spatial filter is requested. A numeric bbox does not require this module.

## GeoJSON input assumptions

- Snapshot file names follow `YYYYMMDDHHMM_YYYYMMDDHHMM_P.geojson`.
- GeoJSON declares CRS EPSG:5179 explicitly.
- The filename times default to `Asia/Seoul` and are converted to UTC (configure `input_timezone` if your inputs use a different time zone).
- GeoJSON features contain an `Intensity` property; positive activity yields emission records.

The existing emission-rate defaults are illustrative, not physically calibrated to a particular fire event.
