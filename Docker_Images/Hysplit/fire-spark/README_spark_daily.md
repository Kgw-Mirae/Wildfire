# spark_daily.py — daily FINN/HYSPLIT controller

Source version: `20261012-002` (12 October 2026).

## Purpose

Run an independent HYSPLIT simulation for each requested UTC start date using that day's **24-hour FINN emissions**. HYSPLIT transport duration comes from `hysp.in/<group>/CONTROL` unless explicitly overridden with `--duration`. The program reuses `fire.nsfs_prep.nsfs_prep1`, `fire.nsfs_chk.nsfs_chk1`, and `fire.nsfs_run.nsfs_run1` in the order **prepare → check → run**.

The program prefers the archived meteorology selected by `analysis_arl` (currently `gdas1` in the included `spark.ini`). When the requested run is sufficiently recent and archive meteorology is unavailable, it can try forecast `gfs0p25.f`. Explicit `--met-file` inputs bypass automatic selection. An ARL-only validation failure can trigger the forecast fallback; executable or other failures cannot.

## Examples

Run from the SPARK root, or supply `--root <path>`:

```bash
# Non-writing preview
python spark_daily.py 20250428 --dry-run

# Stage HYSPLIT inputs, then validate, then execute
python spark_daily.py 20250428 --prepare-only
python spark_daily.py 20250428 --check-only
python spark_daily.py 20250428

# Run once per day in an inclusive date range
python spark_daily.py 20250428 20250430

# Explicit start hour and duration
python spark_daily.py 2025042812 --duration 48

# Override archive dataset or the selected template set
python spark_daily.py 20250428 --arl gfs0p25 --group SPARK

# Inspect saved status; intentionally rebuild existing inputs and output
python spark_daily.py 20250428 --status
python spark_daily.py 20250428 --renew

# First-time configuration creation (only if needed)
python spark_daily.py --init --group SPARK --hysplit /path/to/hysplit
```

With no date argument, the default is the **previous UTC day at 00 UTC**. Dates may be `YYYYMMDD` or `YYYYMMDDHH`; the optional second date is inclusive, with one run per calendar day.

## Inputs and configuration

- `spark.ini`: `group`, `analysis_arl`, `forecast_arl`, `forecast_cycle`, `emission_domain`, `cpu_mode`, `cpu_n`, `cdump`, `logfile`. CLI arguments override relevant settings for that invocation.
- `hysp.ini`: `HYSPLIT_PATH`, `ARL_PATH`, `ARL_DOWN`, `MPI_USE`, `MPI_PATH`, `MPI_CPU`.
- `hysp.in/<group>/CONTROL` and `SETUP.CFG`: existing HYSPLIT templates. `ASCDATA.CFG` may also be supplied.
- FINN inventory: `hysp.data/fire-finn/nrt/dayfile/YYYY/fire-finn-nrt.YYYYMMDD.npz` (prepared or downloaded by the existing fire library as configured).
- ARL meteorology in the location selected by `hysp.ini`, or explicit paths supplied with `--met-file`.

`emission_domain` may be a named region (for example `K09`) or a `south,west,north,east` comma-delimited bounding box. Template selection is controlled by `group`; it is not simply an arbitrary run-directory label.

## Outputs

```text
hysp.run/<group>/<meteorology>-finn/YYYY/YYYYMMDD/
    CONTROL   SETUP.CFG   ASCDATA.CFG   EMITIMES
    cdump3    MESSAGE     log            spark_daily.status.json
```

The experiment name reflects selected meteorology, for example `gdas1-finn`, `gfs0p25-finn`, or `gfs0p25.f-finn`. `cdump3` and `log` names are configurable. When FINN cannot be downloaded or its dayfile is absent, the run is skipped with `spark_daily.status.json` status `missing_finn`; a date range continues to the next day. When a valid FINN dayfile contains no sources in the selected domain, the status is `no_emission`. Missing input is **not** treated as zero emissions.

## Operational notes

- Without `--renew`, existing prepared HYSPLIT inputs and existing completed `cdump` are preserved. Modified or partially prepared runs require operator attention or `--renew`.
- `--prepare-only` stages a run without requiring working model executables; `--check-only` verifies an existing prepared run and reports readiness.
- `--renew-raw` (refresh FINN source files) is only valid together with `--renew`.
- `--hour`, `--duration`, `--forecast-cycle {00z,latest}`, `--cpu-mode {auto,serial,mpi}`, `--cpu-n`, `--quiet`, and `--debug` provide operational overrides; inspect `--help` for the complete CLI.
- If `hysp.lib/python` exists beside `spark_daily.py`, that library is preferred. Otherwise the normal Python environment is used, including any preconfigured `.pth` entry for `~/lib/python`.

HYSPLIT itself, ARL data, and third-party Python dependencies must be available separately. There is no `SPARK_HOME` requirement.
