from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import numpy as np
import xarray as xr


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent

PRS_PATTERNS = (
    "1010_v040_easia_prs.2byte.ft{fhr:03d}.{init}.nc",
    "1010_v040_*_prs.2byte.ft{fhr:03d}.{init}.nc",
    "r030_v040_easia_prs.2byte.ft{fhr:03d}.{init}.nc",
    "r030_v040_*_prs.2byte.ft{fhr:03d}.{init}.nc",
    "l010_v040_korea_prs.2byte.ft{fhr:03d}.{init}.nc",
    "*prs*.ft{fhr:03d}.{init}.nc",
)

ETC_PATTERNS = (
    "1010_v040_easia_etc.2byte.ft{fhr:03d}.{init}.nc",
    "1010_v040_*_etc.2byte.ft{fhr:03d}.{init}.nc",
    "r030_v040_easia_etc.2byte.ft{fhr:03d}.{init}.nc",
    "r030_v040_*_etc.2byte.ft{fhr:03d}.{init}.nc",
    "l010_v040_korea_etc.2byte.ft{fhr:03d}.{init}.nc",
    "*etc*.ft{fhr:03d}.{init}.nc",
)

TARGET_VARS = {
    "u": ("U", "UGRD", "UU"),
    "v": ("V", "VGRD", "VV"),
    "t": ("T", "TMP", "TT"),
    "tmp": ("T", "TMP", "TT"),
    "hgt": ("GPH", "HGT", "GH", "Z"),
}

VERTICAL_DIMS = ("bottom_top", "level", "lev", "isobaric", "isobaricInhPa", "pressure", "plev")
Y_DIMS = ("south_north", "y", "lat", "latitude")
X_DIMS = ("west_east", "x", "lon", "longitude")
TIME_DIMS = ("Time", "time")

GRAVITY = 9.80665
PLAN_FILE = SCRIPT_DIR / "rdaps_nc_file_plan.txt"


@dataclass(frozen=True)
class NcFileSelection:
    valid_kst: datetime
    valid_utc: datetime
    cycle_utc: datetime
    fhr: int
    path: Path


def candidate_data_roots() -> list[Path]:
    roots: list[Path] = []
    env_root = os.environ.get("RDAPS_NC_DIR") or os.environ.get("RDAPS_DATA_ROOT")
    if env_root:
        roots.append(Path(env_root))
    roots.extend(
        [
            PROJECT_DIR / "data" / "RDAPS-KIM",
            PROJECT_DIR.parent / "data" / "RDAPS-KIM",
            PROJECT_DIR.parent,
        ]
    )
    unique: list[Path] = []
    for root in roots:
        resolved = root.expanduser()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def kst_to_utc(value: datetime) -> datetime:
    return value - timedelta(hours=9)


def cycle_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%d%H")


def is_probably_netcdf(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            header = f.read(8)
    except OSError:
        return False
    return header.startswith(b"CDF") or header.startswith(b"\x89HDF\r\n\x1a\n")


def scan_nc_files(prefer: str = "prs") -> dict[str, dict[int, Path]]:
    kind = "prs" if prefer == "prs" else "etc"
    files: dict[str, dict[int, Path]] = {}
    for root in candidate_data_roots():
        if not root.exists():
            continue
        for path in sorted(root.glob(f"*{kind}*.nc")):
            if not is_probably_netcdf(path):
                print(f"[WARN] Skipping non-NetCDF file with .nc extension: {path}")
                continue
            parsed = parse_nc_timestamp_from_name(path)
            if parsed is None:
                continue
            init, fhr = parsed
            files.setdefault(init, {}).setdefault(fhr, path)
    return files


def select_nc_cycle_for_dates(valid_kst_dates: list[datetime], prefer: str = "prs") -> list[NcFileSelection]:
    if not valid_kst_dates:
        raise ValueError("No valid times were provided for RDAPS NetCDF selection")

    valid_utc_dates = [kst_to_utc(value) for value in valid_kst_dates]
    available = scan_nc_files(prefer)
    available_cycles = sorted(
        (
            datetime.strptime(init, "%Y%m%d%H")
            for init in available
            if datetime.strptime(init, "%Y%m%d%H").hour in (0, 6, 12, 18)
        ),
        reverse=True,
    )

    selections: list[NcFileSelection] = []
    missing: list[str] = []
    for valid_kst, valid_utc in zip(valid_kst_dates, valid_utc_dates):
        selected: NcFileSelection | None = None
        for cycle_utc in available_cycles:
            if cycle_utc > valid_utc:
                continue
            fhr_float = (valid_utc - cycle_utc).total_seconds() / 3600.0
            if abs(fhr_float - round(fhr_float)) > 1.0e-6:
                continue
            fhr = int(round(fhr_float))
            path = available.get(cycle_stamp(cycle_utc), {}).get(fhr)
            if path is None:
                continue
            selected = NcFileSelection(
                valid_kst=valid_kst,
                valid_utc=valid_utc,
                cycle_utc=cycle_utc,
                fhr=fhr,
                path=path,
            )
            break
        if selected is None:
            missing.append(f"valid_utc={valid_utc:%Y%m%d%H}")
        else:
            selections.append(selected)

    if len(selections) == len(valid_kst_dates):
        return selections

    searched = ", ".join(str(root) for root in candidate_data_roots())
    if missing:
        preview = "; ".join(missing[:12])
        suffix = "" if len(missing) <= 12 else f"; ... ({len(missing)} missing)"
        print(f"[WARN] Missing RDAPS NetCDF files for {preview}{suffix}")
    raise FileNotFoundError(
        "No RDAPS NetCDF files contain all required valid times. "
        f"searched: {searched}"
    )


def write_nc_file_plan(selections: list[NcFileSelection], path: Path = PLAN_FILE) -> None:
    if not selections:
        raise ValueError("Cannot write empty RDAPS NetCDF file plan")
    lines = [
        "# Auto-generated RDAPS NetCDF file plan",
        f"# FIRST_CYCLE_UTC {cycle_stamp(selections[0].cycle_utc)}",
        "# VALID_KST VALID_UTC CYCLE_UTC FHR FILE",
    ]
    for item in selections:
        lines.append(
            f"{item.valid_kst:%Y%m%d%H} {item.valid_utc:%Y%m%d%H} "
            f"{item.cycle_utc:%Y%m%d%H} {item.fhr:03d} {item.path}"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def read_nc_file_plan(path: Path = PLAN_FILE) -> dict[str, NcFileSelection]:
    selections: dict[str, NcFileSelection] = {}
    if not path.exists():
        return selections
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            parts = text.split(maxsplit=4)
            if len(parts) != 5:
                continue
            valid_kst = datetime.strptime(parts[0], "%Y%m%d%H")
            valid_utc = datetime.strptime(parts[1], "%Y%m%d%H")
            cycle_utc = datetime.strptime(parts[2], "%Y%m%d%H")
            fhr = int(parts[3])
            selections[parts[0]] = NcFileSelection(valid_kst, valid_utc, cycle_utc, fhr, Path(parts[4]))
    return selections


def find_nc_file_for_valid_time(valid_kst: datetime, prefer: str = "prs") -> tuple[Path, str, int]:
    valid_tag = valid_kst.strftime("%Y%m%d%H")
    planned = read_nc_file_plan().get(valid_tag)
    if planned is not None:
        if not planned.path.exists():
            raise FileNotFoundError(f"Planned RDAPS NetCDF file is missing: {planned.path}")
        return planned.path, cycle_stamp(planned.cycle_utc), planned.fhr

    selection = select_nc_cycle_for_dates([valid_kst], prefer=prefer)[0]
    print(
        "[INFO] RDAPS NetCDF fallback selection: "
        f"valid_kst={selection.valid_kst:%Y%m%d%H} "
        f"valid_utc={selection.valid_utc:%Y%m%d%H} "
        f"cycle={selection.cycle_utc:%Y%m%d%H} ft{selection.fhr:03d} "
        f"file={selection.path.name}"
    )
    return selection.path, cycle_stamp(selection.cycle_utc), selection.fhr


def find_first_nc_file(prefer: str = "prs") -> Path:
    patterns = PRS_PATTERNS if prefer == "prs" else ETC_PATTERNS
    wildcard_patterns = [p.format(fhr=0, init="*").replace("ft000.", "ft*.") for p in patterns]
    wildcard_patterns.extend(["*prs*.nc"] if prefer == "prs" else ["*etc*.nc"])

    for root in candidate_data_roots():
        if not root.exists():
            continue
        for pattern in wildcard_patterns:
            matches = [path for path in sorted(root.glob(pattern)) if is_probably_netcdf(path)]
            if matches:
                return matches[0]
    raise FileNotFoundError("No RDAPS NetCDF file found")


def open_nc(path: Path) -> xr.Dataset:
    return xr.open_dataset(path, mask_and_scale=True)


def find_existing_variable(ds: xr.Dataset, candidates: Iterable[str]) -> str | None:
    lower_map = {name.lower(): name for name in ds.variables}
    for candidate in candidates:
        if candidate in ds.variables:
            return candidate
        found = lower_map.get(candidate.lower())
        if found is not None:
            return found
    return None


def find_vertical_dim(var: xr.DataArray) -> str | None:
    for dim in VERTICAL_DIMS:
        if dim in var.dims:
            return dim
    for dim in var.dims:
        low = dim.lower()
        if "lev" in low or "isobaric" in low or "press" in low:
            return dim
    return None


def find_dim(var: xr.DataArray, candidates: Iterable[str]) -> str | None:
    for dim in candidates:
        if dim in var.dims:
            return dim
    return None


def coord_2d(ds: xr.Dataset) -> tuple[np.ndarray, np.ndarray]:
    lat_name = find_existing_variable(ds, ("XLAT", "lat", "latitude", "LAT"))
    lon_name = find_existing_variable(ds, ("XLONG", "XLON", "lon", "longitude", "LON"))
    if lat_name is None or lon_name is None:
        raise KeyError("Cannot find XLAT/XLONG or lat/lon coordinate variables in NetCDF")

    lat = ds[lat_name]
    lon = ds[lon_name]
    for dim in TIME_DIMS:
        if dim in lat.dims:
            lat = lat.isel({dim: 0})
        if dim in lon.dims:
            lon = lon.isel({dim: 0})
    lat_vals = np.asarray(lat.values)
    lon_vals = np.asarray(lon.values)
    if lat_vals.ndim == 1 and lon_vals.ndim == 1:
        lon_vals, lat_vals = np.meshgrid(lon_vals, lat_vals)
    return lat_vals, lon_vals


def nearest_grid(ds: xr.Dataset, target_lon: float, target_lat: float) -> tuple[int, int, float, float]:
    lats, lons = coord_2d(ds)
    dist2 = (lons - target_lon) ** 2 + (lats - target_lat) ** 2
    iy, ix = np.unravel_index(np.nanargmin(dist2), dist2.shape)
    return int(ix), int(iy), float(lons[iy, ix]), float(lats[iy, ix])


def point_indexer(var: xr.DataArray, ix0: int, iy0: int) -> dict[str, int]:
    indexer: dict[str, int] = {}
    for dim in TIME_DIMS:
        if dim in var.dims:
            indexer[dim] = 0
    ydim = find_dim(var, Y_DIMS)
    xdim = find_dim(var, X_DIMS)
    if ydim is not None:
        indexer[ydim] = iy0
    if xdim is not None:
        indexer[xdim] = ix0
    return indexer


def normalize_height_m(values: xr.DataArray) -> xr.DataArray:
    units = str(values.attrs.get("units", "")).lower()
    if "m2" in units or "m**2" in units or "geopotential" in units:
        return values / GRAVITY
    return values


def extract_profile(ds: xr.Dataset, out_var: str, ix0: int, iy0: int) -> tuple[np.ndarray, np.ndarray]:
    hgt_name = find_existing_variable(ds, TARGET_VARS["hgt"])
    if hgt_name is None:
        raise KeyError(f"No height variable found. Candidates: {TARGET_VARS['hgt']}")

    hgt = normalize_height_m(ds[hgt_name].isel(**point_indexer(ds[hgt_name], ix0, iy0)))
    vdim = find_vertical_dim(hgt)
    if vdim is None:
        raise ValueError(f"Height variable {hgt_name} has no vertical dimension: {hgt.dims}")

    hgt_vals = np.asarray(hgt.values, dtype=float)
    order = np.argsort(hgt_vals)
    hgt_sorted = hgt_vals[order]

    if out_var == "hgt":
        return hgt_sorted, hgt_sorted

    if out_var == "tmp":
        t_name = find_existing_variable(ds, TARGET_VARS["t"])
        if t_name is None:
            raise KeyError(f"No temperature variable found. Candidates: {TARGET_VARS['t']}")
        vals = ds[t_name].isel(**point_indexer(ds[t_name], ix0, iy0))
        var_vdim = find_vertical_dim(vals)
        if var_vdim is None:
            raise ValueError(f"Temperature variable {t_name} has no vertical dimension")
        return hgt_sorted, np.asarray(vals.values, dtype=float)[order]

    var_name = find_existing_variable(ds, TARGET_VARS[out_var])
    if var_name is None:
        raise KeyError(f"No variable found for {out_var}. Candidates: {TARGET_VARS[out_var]}")
    vals = ds[var_name].isel(**point_indexer(ds[var_name], ix0, iy0))
    var_vdim = find_vertical_dim(vals)
    if var_vdim is None:
        raise ValueError(f"Variable {var_name} has no vertical dimension")
    return hgt_sorted, np.asarray(vals.values, dtype=float)[order]


def parse_rdaps_date(text: str) -> datetime:
    return datetime.strptime(text.strip(), "%Y.%m.%d.%H")


def date_valid_tag(valid_kst: datetime) -> str:
    return valid_kst.strftime("%Y%m%d%H")


def parse_point_line(line: str) -> tuple[int, int, float, float, str] | None:
    parts = line.split()
    if len(parts) < 4 or parts[0].startswith("#"):
        return None
    role = parts[4] if len(parts) >= 5 else "interior"
    return int(parts[0]), int(parts[1]), float(parts[2]), float(parts[3]), role


def read_points(path: Path) -> list[tuple[int, int, float, float, str]]:
    points: list[tuple[int, int, float, float, str]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            parsed = parse_point_line(line)
            if parsed is not None:
                points.append(parsed)
    if not points:
        raise ValueError(f"No usable points in {path}")
    return points


def read_dates(path: Path) -> list[datetime]:
    dates: list[datetime] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            text = line.strip()
            if text and not text.startswith("#"):
                dates.append(parse_rdaps_date(text))
    if not dates:
        raise ValueError(f"No usable dates in {path}")
    return dates


def parse_nc_timestamp_from_name(path: Path) -> tuple[str, int] | None:
    match = re.search(r"\.ft(\d{3})\.(\d{10})\.nc$", path.name)
    if match is None:
        return None
    return match.group(2), int(match.group(1))
