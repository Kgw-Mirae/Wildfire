# SPARK product generation — spark_product.py

Controller revision: `20261012-004` (12 October 2026).

## 1. Purpose

`spark_product.py` makes one 24-hour SPARK smoke product from **explicitly selected HYSPLIT experiment directories**. The experiments are the exact directory names underneath `hysp.run/<GROUP>/` such as `gdas1-finn`, `gdas1-spread`, `gfs0p25.f-finn`, or `hrrr-gdas1-finn`.

Specify **one or more experiments** with `--source`, in the order they should appear in the final product name. This replaces the earlier `--mode daily|spread|combined` and `--daily-experiment`/`--spread-experiment` interfaces. SPARK does not silently switch from an explicitly selected experiment to an alternative ARL experiment.

The controller merges all **available** CDUMPs for the target day and the preceding four start dates (by default), sums their compatible concentration fields, extracts the target day's 24 UTC hours, and writes EPSG:5179 and EPSG:3857 NetCDF files. It never modifies HYSPLIT run files.

## 2. Installation and dependencies

Place `spark_product.py` in your chosen project root, alongside `spark_daily.py`:

```bash
cd ~/work/model/fire-spark-test2
unzip -o spark_product_20261012-004.zip spark_product.py README_Spark_Product.md
```

Use the project-root `spark.ini` to supply the `group` (for example `SPARK-test`) and `cdump` filename. `hysp.ini` is not modified by the merger. **No SPARK_HOME environment variable is needed.**

Required libraries: existing `hysp.hysp_cdump`, `hysp.hygv_spark`, `numpy`, `pyproj`, and `netCDF4`.

**IMPORTANT FOR THIS REVISION: replace `hysp/hygv_spark.py` in your Python library too.**
Your earlier copy of that converter hard-coded a 1000×1000 grid. Replacing only
`spark_product.py` does **not** fix the old converter's fallback behavior.
No changes to `hysp_cdump.py`, `nsfs_prep.py`, `hysp.ini`, or `spark.ini` are needed.

```bash
cd ~/work/model/fire-spark-test2

# Replace the SPARK controller without changing either .ini file.
unzip -o spark_product_20261012-004.zip spark_product.py README_Spark_Product.md

# Install the corrected shared converter with a backup of the current version.
mkdir -p /tmp/spark-product-install
unzip -o spark_product_20261012-004.zip hysp/hygv_spark.py -d /tmp/spark-product-install
cp -p ~/lib/python/hysp/hygv_spark.py ~/lib/python/hysp/hygv_spark.py.bak.20261012 2>/dev/null || true
cp /tmp/spark-product-install/hysp/hygv_spark.py ~/lib/python/hysp/hygv_spark.py

# Verify the modified modules resolve from the intended locations.
python - <<'PY_CHECK'
import spark_product
from hysp import hygv_spark
print('SPARK PRODUCT:', spark_product.__version__, spark_product.__file__)
print('HYGV CONVERTER:', hygv_spark.__version__, hygv_spark.__file__)
PY_CHECK
```

In this release, the controller should report `20261012-004` and the converter
should report `20261012-001`. Source filenames in the ZIP remain unversioned.

## 3. Run commands

```bash
cd ~/work/model/fire-spark-test2

# One experiment, FINN only
python spark_product.py 20250428 --source gdas1-finn

# One experiment, SPREAD only
python spark_product.py 20250428 --source gdas1-spread

# FINN + SPREAD using the same meteorological archive
python spark_product.py 20250428 --source gdas1-finn gdas1-spread

# FINN + SPREAD with distinct meteorology
python spark_product.py 20250428 --source gfs0p25-finn gdas1-spread

# Any future experiment may also be selected by its exact directory name
python spark_product.py 20250428 --source gdas1-finn gdas1-spread hrrr-gdas1-rave3

# Preview selected CDUMPs and destinations; writes nothing
python spark_product.py 20250428 --source gdas1-finn gdas1-spread --dry-run

# Force regeneration after inputs arrive
python spark_product.py 20250428 --source gdas1-finn gdas1-spread --renew

# A date range; outputs each day independently
python spark_product.py 20250428 20250502 --source gdas1-finn
```

**Note:** The selected order is intentional: `--source gdas1-finn gdas1-spread` and `--source gdas1-spread gdas1-finn` produce differently named products. Duplicate entries are rejected because they would double-count the same CDUMPs.

## 4. Input and output directory conventions

For the user's example with `group="SPARK-test"` and two selected sources:

```text
hysp.run/
  SPARK-test/
    gdas1-finn/
      2025/20250424/cdump3
      2025/20250425/cdump3
      ...
      2025/20250428/cdump3
    gdas1-spread/
      2025/20250428/cdump3

hysp.out/
  SPARK-test/
    gdas1-finn-gdas1-spread/
      2025/
        20250428/
          spark.gdas1-finn-gdas1-spread.20250428.epsg5179.nc
          spark.gdas1-finn-gdas1-spread.20250428.epsg3857.nc
          product.json
          spark_product.status.json
```

The top-level `GROUP` is always taken from the project-root `spark.ini` unless `--group` overrides it. The names after `--source` are looked up exactly as written, within this one GROUP. Source names are not paths and must not contain `/` or `..` components.

The product name is derived by joining the **requested experiment names**, regardless of how many individual CDUMPs are actually available. The manifest lists exactly which contributions were used, so a partial product cannot silently look complete.

Old outputs made by `--mode combined` remain under their previous `hysp.out/combined/...` location. The updated controller does not move or overwrite them; new products use the group/experiment layout.

## 5. Missing inputs and incomplete products

For a target date of April 28 and default `--lookback 4`, the script checks April 24–28 inclusive for **each requested experiment**.

- Missing `*-finn` CDUMP: **nonfatal error**, `MISSING_FINN_RUN`, one for every missing date; the error remains in monitoring records. If any usable CDUMPs exist, write NetCDF anyway with `status="partial"`.
- Missing `*-spread` on some dates: **informational**, because GeoJSON may have been supplied only for selected dates. If at least one SPREAD CDUMP exists and there are no other errors, SPREAD coverage alone need not mark a product partial.
- If any *requested* experiment has zero CDUMPs in the entire window: mark the product **partial** when at least one other source has data, and report `NO_SOURCE_CONTRIBUTION`.
- Missing dates of other source types: tracked as nonfatal source errors until we add source-specific optionality rules.
- No usable CDUMPs of any requested experiment: write only `spark_product.status.json` with `status="missing"` and return a nonzero exit code. No empty NetCDF is fabricated.

For the actual April 28 scenario, where only April 27 FINN is missing:

```text
ERROR (nonfatal) MISSING_FINN_RUN: FINN CDUMP missing: gdas1-finn on 20250427; using available contributions
STATUS PARTIAL .../hysp.out/SPARK-test/gdas1-finn-gdas1-spread/2025/20250428/spark_product.status.json
```

Both `product.json` and `spark_product.status.json` contain `source_experiments`, `coverage` **by experiment**, `used`, `missing`, `issues`, `errors`, `missing_finn_dates`, `missing_spread_dates`, and `status`. A usable partial product returns status code **0 during generation**, permitting scheduled products to continue. A later monitoring check returns nonzero until missing-FINN errors are resolved and the product regenerated.

If a requested experiment uses a nonstandard name that does not end in `-finn` or `-spread`, the controller still selects it; its missing dates are treated as errors by default.

## 6. Read-only monitoring

Use the exact same experiment list used to create the product:

```bash
python spark_product.py 20250428 --source gdas1-finn gdas1-spread --status
python spark_product.py 20250428 --source gdas1-finn gdas1-spread --status --json
python spark_product.py 20250428 20250502 --source gdas1-finn --status --json
```

`--status` reads the saved product-specific status, does not run HYSPLIT, and does not regenerate NetCDF. It returns 0 only for `complete`, 1 for `partial`, `missing`, `failed`, or unavailable. `--status --json` emits one machine-readable JSON object per date (JSON Lines for ranges).

If missing inputs become available later, explicitly regenerate that product using `--renew`. Without `--renew`, the existing product is preserved; a partial product's monitoring status remains visible.

## 7. Fields, projection, and calculation limitations

The output uses the existing `hysp.hygv_spark._write_day` /
`hysp_cdump.process_cdump` routines. The default output bbox remains Korea
`[32.5, 122, 42.55, 132.05]`, but **the default projected dimensions are now
exactly the original HYSPLIT CDUMP NX × NY**. This matches the effective
2026-10-07 IDL `myidl/regrd_grd2wm.pro` code:

```idl
; latest IDL implementation (rather than the old 1000×1000 comment)
dm2 = var_set(_dm,ina=[minfo.nx,minfo.ny])
```

For example, an original 201×201 HYSPLIT grid now produces 201×201 NetCDF
arrays in **both EPSG:5179 and EPSG:3857** unless you supply an explicit override.
The default output sampling does not create artificial 1000×1000 detail.

```bash
# Native dimensions from CDUMP (e.g., 201×201)
python spark_product.py 20250428 --source gdas1-spread --renew

# Explicitly request a different output grid
python spark_product.py 20250428 --source gdas1-spread --dim 1000 1000 --renew

# Or use desired projected resolution instead of an explicit dimension
python spark_product.py 20250428 --source gdas1-spread --res 1000 --renew
```

`--bbox S W N E` controls the geographic bounds (not the `spark.ini.emission_domain`
input-emission selection). Output grid dimensions are still the source-grid
numbers even when the requested EPSG is 5179; the physical pixel dimensions
may differ between EPSGs. The first NetCDF contains attributes
`SPARK_NATIVE_GRID_NX`, `SPARK_NATIVE_GRID_NY`, and
`SPARK_OUTPUT_DIMENSION_SOURCE` for traceability.

**Grid registration note:** The corrected default matches IDL **array dimensions**,
but does not claim bitwise equivalence to legacy `spark8` pixels. The latest
IDL `regrd_grd2wm.pro` samples projected nodes including the bbox endpoints;
the existing Python `hysp_cdump.reproject_tyx` samples pixel centers within
the bbox (an outer-edge raster convention). Align and inspect the grid
registration if exact cell-for-cell comparison is needed. This revision does
not change the shared `hysp_cdump` mapping algorithm.

Variables follow the legacy conventions:

- `PM2P5`: thickness-weighted mean at zero-based level `[1]` multiplied by `1e6`.
- `PM2P5_2`: mean over levels `[1,2]` multiplied by `1e6`.
- `AOD`: mean over `[1,2,3,4]` multiplied by `1e6 * 0.04`; this is an **empirical proxy**, not physically integrated aerosol optical depth.

All CDUMPs must use mutually compatible grids, pollutant definitions, and vertical levels. Incompatible CDUMPs fail with a saved `failed` status and do not silently regrid. Sources from different meteorological models can be combined only when their original CDUMP grids and definitions are compatible.

**Duplicate fire emissions are not removed.** Selecting FINN and SPREAD together sums their concentrations directly; this may double-count fires. The manifest records `combination_method="uncorrected_additive_sum"` and `emission_overlap_removed=false` for multiple contributing experiments. We will handle overlap correction in a future revision.

## 8. CLI summary

```text
--source EXPERIMENT [EXPERIMENT ...]   REQUIRED: exact hysp.run/GROUP directory names
--group GROUP                         override spark.ini group
--lookback N                          preceding run dates (default 4)
--cdump FILE                          override spark.ini cdump name
--bbox S W N E                        output geographic extent
--dim NX NY | --res RES               output grid dimensions or resolution (default: source CDUMP NX NY)
--cf                                  CF-compliant NetCDF instead of HYGV compact
--name NAME                           NetCDF filename prefix (default spark)
--renew                               replace existing products
--dry-run                             print planned source/output paths only
--status [--json]                     read saved product monitoring state
--root ROOT                           explicit SPARK project root
```

This revision is designed to work with your existing SPARK working directory. It does not modify `spark.ini`, `hysp.ini`, `spark_daily.py`, `spark_spread.py`, NSFS routines, or the HYSP CDUMP reader.

## 9. Regenerating existing 1000×1000 products

**Important:** SPARK intentionally preserves previously generated NetCDF products.
After installing both updated files, use `--renew` to regenerate any existing
products that were produced at 1000×1000. Older outputs are not automatically
moved or resampled in place.

```bash
cd ~/work/model/fire-spark-test2
python spark_product.py 20250428 20250501 --source gdas1-spread --renew
# Combined products, if needed later:
# python spark_product.py 20250428 20250501 --source gdas1-finn gdas1-spread --renew
```

Verify the output size with your installed `netCDF4` package:

```bash
python - <<'PY_VERIFY'
from pathlib import Path
from netCDF4 import Dataset
p = Path('hysp.out/SPARK-test/gdas1-spread/2025/20250428/spark.gdas1-spread.20250428.epsg3857.nc')
with Dataset(p) as nc:
    print('PM2P5', nc.variables['PM2P5'].shape)  # e.g. (24, 201, 201)
    print('native dimensions', nc.getncattr('SPARK_NATIVE_GRID_NX'), nc.getncattr('SPARK_NATIVE_GRID_NY'))
    print('selection', nc.getncattr('SPARK_OUTPUT_DIMENSION_SOURCE'))
PY_VERIFY
```

If your actual HYSPLIT grid is not 201×201, the saved dimensions will reflect
its actual `NX` and `NY` instead.
