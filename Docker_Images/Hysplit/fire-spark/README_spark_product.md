# spark_product.py — daily SPARK NetCDF products

Source version: `20261012-004` (12 October 2026).

## Purpose

Read existing HYSPLIT concentration files (`cdump3`, or the `spark.ini` alternative), select only the **explicitly named experiment directories**, and generate a 24-hour daily NetCDF product in **EPSG:5179** and **EPSG:3857**. HYSPLIT is **not** run by this controller.

For target date `D`, the default `--lookback 4` collects nonempty CDUMPs from HYSPLIT runs started on `D-4` through `D` (five possible start days per experiment). The combined fields are processed using `hysp.hygv_spark` and its direct binary reader, `hysp.hysp_cdump`.

## Examples

```bash
# One FINN experiment
python spark_product.py 20250428 --source gdas1-finn

# One SPREAD experiment
python spark_product.py 20250428 --source gdas1-spread

# Add FINN and SPREAD simulation outputs (see overlap warning below)
python spark_product.py 20250428 --source gdas1-finn gdas1-spread

# Inspect selection and output paths, without writing anything
python spark_product.py 20250428 --source gdas1-finn gdas1-spread --dry-run

# Daily products over an inclusive date range
python spark_product.py 20250428 20250430 --source gdas1-finn

# Check saved completeness or regenerate
python spark_product.py 20250428 --source gdas1-finn gdas1-spread --status
python spark_product.py 20250428 --source gdas1-finn gdas1-spread --renew
```

`--source` entries must be **exact** experiment-directory names under `hysp.run/<group>/`. For example, `gdas1-finn` and `gfs0p25.f-finn` are distinct and are never substituted automatically. The order of `--source` entries determines the output product name. Repeated experiment names are rejected.

## Input/output structure

```text
INPUTS
hysp.run/<group>/<experiment>/YYYY/YYYYMMDD/cdump3

OUTPUTS (example: gdas1-finn and gdas1-spread)
hysp.out/<group>/gdas1-finn-gdas1-spread/YYYY/YYYYMMDD/
    spark.gdas1-finn-gdas1-spread.YYYYMMDD.epsg5179.nc
    spark.gdas1-finn-gdas1-spread.YYYYMMDD.epsg3857.nc
    product.json
    spark_product.status.json
```

Output bounds default to `[32.5, 122, 42.55, 132.05]` in **south, west, north, east** order. Unless `--dim NX NY` or `--res` is specified, the output grid uses the native CDUMP dimensions. `--cf` requests CF-1.10-style NetCDF instead of the default compact HYGV convention. Other controls include `--bbox`, `--xptype`, `--lookback`, `--max-dim`, `--compression-level`, `--name`, `--group`, and `--cdump`.

## Missing data and monitoring

- If **no** usable CDUMP is found, no NetCDF is written; `spark_product.status.json` records `missing`.
- If some inputs are available, available contributions are used. Missing FINN dates are recorded as **nonfatal errors** and the result may be classified `partial`.
- Missing SPREAD dates can be normal when no GeoJSON source exists; they are retained in the input list/status but are informational.
- Missing contributions from a requested experiment are recorded in `product.json` and the status metadata. `--status --json` prints saved status as JSON Lines.
- Existing complete output files are not regenerated unless `--renew` is supplied.

The files `product.json` and `spark_product.status.json` contain the source experiments, selected and missing dates, output locations, and completeness/issue summaries. NetCDF files also contain SPARK provenance attributes.

## Important scientific limitations

**Emission-source overlap is not removed.** This implementation makes an **uncorrected additive sum** of compatible HYSPLIT CDUMP concentrations. Combining `*-finn` with `*-spread` can double-count smoke from the same fires. Treat combined products as provisional until source reconciliation is implemented.

The legacy `AOD` output uses an empirical concentration scaling (`× 0.04` after concentration conversion); it is **not** a physically calculated column aerosol optical depth. Source-grid compatibility and pollutant/vertical-layer definitions should be verified before comparing products.

This program needs `hysp.hygv_spark`, `hysp.hysp_cdump`, `numpy`, `pyproj`, and `netCDF4`. It imports `spark_daily.py`, so the same local `hysp.lib/python` versus development `.pth` path selection applies.
