#!/usr/bin/env python3
"""
hysp_cdump2nc.py

Designed by Hyun Cheol Kim (hyun.kim@noaa.gov).

Command-line converter for HYSPLIT cdump files using hysp_cdump.py.

Main output modes
-----------------
1. Compact HYSP NetCDF (default)
2. HYGV/Web-Mercator NetCDF (--hygv)
3. CF-1.10 NetCDF (--cf)
4. Arbitrary target EPSG (--epsg)

Examples
--------
Original lon/lat compact NetCDF:
    python hysp_cdump2nc.py cdump -o out.nc

HYGV/Web Mercator:
    python hysp_cdump2nc.py cdump --hygv -o out_wm.nc

Projected compact NetCDF in EPSG:5179:
    python hysp_cdump2nc.py cdump --epsg 5179 -o out_5179.nc

CF-compliant NetCDF in lon/lat:
    python hysp_cdump2nc.py cdump --cf -o out_cf.nc

CF-compliant NetCDF in EPSG:5179:
    python hysp_cdump2nc.py cdump --cf --epsg 5179 -o out_cf_5179.nc
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

try:
    from .hysp_cdump import (
        APP_VERSION,
        process_cdump,
        resolve_cdump_inputs,
        save_cf_netcdf,
        save_compact_netcdf,
    )
except ImportError:
    # Allow direct execution: python hysp_cdump2nc.py ...
    from hysp_cdump import (
        APP_VERSION,
        process_cdump,
        resolve_cdump_inputs,
        save_cf_netcdf,
        save_compact_netcdf,
    )

__author__ = "Hyun Cheol Kim <hyun.kim@noaa.gov>"
__designer__ = "Designed by Hyun Cheol Kim (hyun.kim@noaa.gov)"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Convert HYSPLIT cdump files to compact, HYGV, or CF NetCDF."
    )
    p.add_argument("files", nargs="*", help="actual cdump path(s) or wildcard(s)")
    p.add_argument(
        "--file-list", "--files-from", dest="file_list", action="append", default=None,
        help="text file containing cdump paths; one path or wildcard per line",
    )
    p.add_argument("-o", "--output", default="hysp_cdump.nc", help="output NetCDF file")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--hygv", action="store_true", help="HYGV compact output; target EPSG defaults to 3857")
    mode.add_argument("--cf", action="store_true", help="write CF-1.10-compliant NetCDF")

    p.add_argument("--epsg", type=int, default=None, help="target EPSG code. Default: 4326; --hygv defaults to 3857")
    p.add_argument("--var-name", default="CONC", help="output data variable name")
    p.add_argument("--units", default=None, help="data units attribute, e.g. ug m-3")
    p.add_argument("--long-name", default=None, help="data long_name attribute")

    # Source selection / processing
    p.add_argument("--xlevel", nargs="+", type=int, default=None, help="zero-based vertical level index/indices")
    p.add_argument("--level", nargs="+", type=int, default=None, help="vertical level value(s) in meters")
    p.add_argument("--xptype", nargs="+", type=int, default=None, help="zero-based pollutant index/indices")
    p.add_argument("--ptype", nargs="+", default=None, help="pollutant name(s), e.g. PM25")
    p.add_argument("--tflag", nargs="+", default=None, help="sample-start timestamps YYYYMMDD[HH[MM]]")
    p.add_argument("--date", nargs="+", default=None, help="one or more UTC dates YYYYMMDD")
    p.add_argument("--stime", "--start", dest="stime", default=None, help="inclusive start time YYYYMMDD[HH[MM]]")
    p.add_argument("--etime", "--end", dest="etime", default=None, help="inclusive end time YYYYMMDD[HH[MM]]")
    p.add_argument(
        "--factor", "--source-factor", dest="factor", nargs="+", type=float, default=None,
        help="source/file coefficient(s): output=sum(factor[i]*file[i]); one value applies to all files",
    )
    p.add_argument("--decay", type=float, default=None, help="radioactive half-life in days")
    p.add_argument("--decay-reference", choices=("idl", "exact", "first", "earliest"), default="idl")
    p.add_argument("--vmean", action="store_true", help="thickness-weighted vertical mean")
    p.add_argument("--zero-to-nan", "--nan", dest="zero_to_nan", action="store_true", help="replace exact output zeros with NaN")
    p.add_argument("--dtype", choices=("float32", "float64"), default="float32")
    p.add_argument("--no-strict", action="store_true", help="disable pollutant/level label validation")

    # Grid / projection
    p.add_argument("--bbox", nargs=4, type=float, default=None, metavar=("LAT_MIN", "LON_MIN", "LAT_MAX", "LON_MAX"), help="manual geographic bbox")
    p.add_argument("--bbox-round", type=int, default=2, help="automatic geographic bbox decimal places. Default: 2")
    p.add_argument("--res", type=float, default=None, help="target-grid spacing in target CRS units")
    p.add_argument("--dim", nargs=2, type=int, default=None, metavar=("NX", "NY"), help="target-grid dimension")
    p.add_argument("--max-dim", type=int, default=2000, help="cap automatic projected grid dimension; 0 disables cap")
    p.add_argument("--flip-y", action="store_true", help="write rows north-to-south instead of default south-to-north")

    # Backward-compatible Web Mercator aliases
    p.add_argument("--hygv-proj", choices=("wm", "ll"), default=None, help=argparse.SUPPRESS)
    p.add_argument("--wm-res-m", type=float, default=None, help=argparse.SUPPRESS)
    p.add_argument("--wm-res-km", type=float, default=None, help=argparse.SUPPRESS)
    p.add_argument("--wm-dim", nargs=2, type=int, default=None, help=argparse.SUPPRESS)
    p.add_argument("--wm-max-dim", type=int, default=None, help=argparse.SUPPRESS)
    p.add_argument("--wm-flip-y", action="store_true", help=argparse.SUPPRESS)

    p.add_argument("--no-gzip", action="store_true", help="disable NetCDF compression")
    p.add_argument("-c", "--compression-level", type=int, default=4, help="NetCDF deflate level 0-9. Default: 4")
    p.add_argument("--quiet", action="store_true", help="suppress progress messages")
    return p


def main() -> int:
    args = _parser().parse_args()

    try:
        input_files = resolve_cdump_inputs(args.files, file_lists=args.file_list)
    except Exception as exc:
        print(f"Input-file error: {exc}", file=sys.stderr)
        return 2

    target_epsg = args.epsg
    if args.hygv_proj is not None:
        target_epsg = 3857 if args.hygv_proj == "wm" else 4326
    if target_epsg is None:
        target_epsg = 3857 if args.hygv else 4326
    if args.hygv and target_epsg != 3857:
        print("--hygv is the HYGV/Web-Mercator mode and requires EPSG:3857", file=sys.stderr)
        return 2

    res = args.res
    dim = args.dim
    max_dim = args.max_dim
    flip_y = bool(args.flip_y)
    if args.wm_res_km is not None:
        res = float(args.wm_res_km) * 1000.0
    elif args.wm_res_m is not None:
        res = float(args.wm_res_m)
    if args.wm_dim is not None:
        dim = args.wm_dim
    if args.wm_max_dim is not None:
        max_dim = args.wm_max_dim
    if args.wm_flip_y:
        flip_y = True

    if not args.quiet:
        mode = "CF NetCDF" if args.cf else ("HYGV NetCDF" if args.hygv else "compact NetCDF")
        print(f"Starting hysp_cdump2nc.py {APP_VERSION} ...")
        print(f"Designed by Hyun Cheol Kim (hyun.kim@noaa.gov)")
        print(f"Files : {len(input_files)} expanded input file(s)")
        if args.file_list:
            print("File list(s): " + ", ".join(os.fspath(x) for x in args.file_list))
        print(f"Output: {args.output}")
        print(f"Mode  : {mode}")
        print(f"Target: EPSG:{target_epsg}")
        if res is not None:
            print(f"Resolution: {res:g} target-CRS units")
        elif dim is not None:
            print(f"Dimension : {dim[0]} x {dim[1]}")
        else:
            print("Resolution: automatic native-like spacing")
        print("Reading and accumulating cdump data. This may take a while...")

    data, info = process_cdump(
        input_files,
        xlevel=args.xlevel,
        level=args.level,
        xptype=args.xptype,
        ptype=args.ptype,
        tflag=args.tflag,
        date=args.date,
        stime=args.stime,
        etime=args.etime,
        factor=args.factor,
        decay=args.decay,
        vmean=args.vmean,
        nan=args.zero_to_nan,
        order="tyx",
        dtype=np.float32 if args.dtype == "float32" else np.float64,
        decay_reference=args.decay_reference,
        strict=not args.no_strict,
    )
    if data is None or info is None:
        print("No selected non-empty concentration records were found.", file=sys.stderr)
        return 2

    try:
        if args.cf:
            created = save_cf_netcdf(
                args.output, data, info,
                var_name=args.var_name,
                target_epsg=target_epsg,
                bbox=args.bbox,
                bbox_round=args.bbox_round,
                dim=dim,
                res=res,
                max_dim=max_dim,
                flip_y=flip_y,
                fill_value=float("nan"),
                gzip=not args.no_gzip,
                compression_level=args.compression_level,
                units=args.units,
                long_name=args.long_name,
            )
        else:
            created = save_compact_netcdf(
                args.output, data, info,
                var_name=args.var_name,
                target_epsg=target_epsg,
                hygv=args.hygv,
                bbox=args.bbox,
                bbox_round=args.bbox_round,
                dim=dim,
                res=res,
                max_dim=max_dim,
                flip_y=flip_y,
                fill_value=float("nan"),
                gzip=not args.no_gzip,
                compression_level=args.compression_level,
                units=args.units,
                long_name=args.long_name,
            )
    except Exception as exc:
        print(f"Output error: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(f"Wrote {created}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
