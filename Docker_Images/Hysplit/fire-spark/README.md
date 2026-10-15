# SPARK — HYSPLIT fire-smoke workflow

Internal research-code handoff, 12 October 2026. The three `spark*.py` programs are independent command-line controllers that share the existing HYSP and fire libraries. HYSPLIT itself is installed separately; it is not included in this folder.

## Controllers

| Program | Purpose | Details |
| --- | --- | --- |
| `spark_daily.py` | Daily FINN emissions → HYSPLIT concentration run | [README_spark_daily.md](README_spark_daily.md) |
| `spark_spread.py` | Timestamped fire-spread GeoJSON → hourly sources → HYSPLIT | [README_spark_spread.md](README_spark_spread.md) |
| `spark_product.py` | Combine specified HYSPLIT runs into daily NetCDF products | [README_spark_product.md](README_spark_product.md) |

## Layout

```text
fire-spark/
  spark_daily.py             FINN controller and shared configuration helpers
  spark_spread.py            fire-spread controller
  spark_product.py           NetCDF product controller
  spark.ini                  SPARK settings (group, ARL preference, CPU, domain)
  hysp.ini                   HYSPLIT/ARL/MPI installation paths and settings
  hysp.lib/python/           bundled Python library (hysp/, fire/, base/, ...)
  hysp.in/GROUP/             HYSPLIT CONTROL, SETUP.CFG, ASCDATA.CFG templates
  hysp.data/                 meteorology, FINN inventory, GeoJSON, hourly spread
  hysp.run/                  generated group/experiment/date simulation directories
  hysp.out/                  generated group/experiment/date NetCDF products
```

`GROUP` selects the HYSPLIT template set in `hysp.in/GROUP/`. Existing `spark.ini` and `hysp.ini` are retained. This archive's `spark.ini` currently selects `SPARK-test`, archived `gdas1` meteorology, and emission domain `K09`; these are **example/current settings**, not hardcoded application defaults. Set `group` to `SPARK` to use `hysp.in/SPARK/`.

## Library resolution

All three controllers rely on the small bootstrap in `spark_daily.py`:

1. If `<directory containing spark_daily.py>/hysp.lib/python` exists, put it at the front of Python's import search path.
2. Otherwise use the active Python interpreter's existing search path. On the author's development machine, `~/lib/python` is already added by a site-packages `.pth` file.

There is no manual fallback to a particular person's home directory. A `.pth` entry only applies if it is installed in the **active Python environment**. Check which copy is used with:

```bash
python -c 'import spark_daily; from hysp import hysp_init; print(hysp_init.__file__)'
```

## Setup

1. Use a Python environment with the required scientific libraries (notably `numpy`, `pyproj`, and `netCDF4`; `rasterio` and `psutil` are used by some bundled HYSP utilities). Python 3.11 is a suitable reference environment.
2. Edit `hysp.ini` for the destination machine: `HYSPLIT_PATH`, `ARL_PATH`, `MPI_PATH`, `MPI_USE`, `MPI_CPU` and `ARL_DOWN`. The provided paths belong to the originating server.
3. Select the template group and ARL/emission options in `spark.ini`. Supply valid `CONTROL` and `SETUP.CFG` files in `hysp.in/GROUP/`.
4. Provide or download the appropriate ARL meteorology and source data. HYSPLIT executables and meteorological archives are not bundled.

Preview the commands and an example day:

```bash
python spark_daily.py --help
python spark_spread.py --help
python spark_product.py --help
python spark_daily.py 20250428 --dry-run
python spark_spread.py 20250428 --dry-run
python spark_product.py 20250428 --source gdas1-finn gdas1-spread --dry-run
```

Normal simulation sequence is `prepare → check → run`. The respective controllers call the shared `fire.nsfs_prep`, `fire.nsfs_chk`, and `fire.nsfs_run` routines.

**Scientific caveat:** `spark_product.py` currently adds selected concentration outputs without removing overlapping FINN/SPREAD fire emissions. Such combined results can double-count smoke sources. The legacy AOD field is an empirical concentration proxy, not a physically integrated AOD retrieval.
