#!/usr/bin/env python3
"""
hysp_cdump2tif.py

Designed by Hyun Cheol Kim (hyun.kim@noaa.gov).

Convert HYSPLIT cdump files to GeoTIFF using hysp_cdump.py.

The target CRS can be any EPSG understood by pyproj/rasterio.  The default is
EPSG:4326.  Internal HYSP arrays are south-to-north; GeoTIFF output is written
in the standard north-up raster orientation.

Examples
--------
Original lon/lat GeoTIFF:
    python hysp_cdump2tif.py cdump -o out.tif

Korea Unified CS / EPSG:5179:
    python hysp_cdump2tif.py cdump --epsg 5179 --res 1000 -o out_5179.tif

One file per timestep:
    python hysp_cdump2tif.py cdump --epsg 3857 --split-time -o smoke.tif
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

try:
    from .hysp_cdump import (
        APP_VERSION,
        process_cdump,
        resolve_cdump_inputs,
        save_geotiff,
    )
except ImportError:
    # Allow direct execution: python hysp_cdump2tif.py ...
    from hysp_cdump import (
        APP_VERSION,
        process_cdump,
        resolve_cdump_inputs,
        save_geotiff,
    )

__author__ = "Hyun Cheol Kim <hyun.kim@noaa.gov>"
__designer__ = "Designed by Hyun Cheol Kim (hyun.kim@noaa.gov)"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Convert HYSPLIT cdump files to GeoTIFF.")
    p.add_argument("files", nargs="*", help="actual cdump path(s) or wildcard(s)")
    p.add_argument("--file-list", "--files-from", dest="file_list", action="append", default=None, help="text file containing cdump paths")
    p.add_argument("-o", "--output", default="hysp_cdump.tif", help="output GeoTIFF path")
    p.add_argument("--epsg", type=int, default=4326, help="target EPSG code. Default: 4326")
    p.add_argument("--var-name", default="CONC", help="variable name stored in TIFF metadata")

    p.add_argument("--xlevel", nargs="+", type=int, default=None, help="zero-based vertical level index/indices")
    p.add_argument("--level", nargs="+", type=int, default=None, help="vertical level value(s) in meters")
    p.add_argument("--xptype", nargs="+", type=int, default=None, help="zero-based pollutant index/indices")
    p.add_argument("--ptype", nargs="+", default=None, help="pollutant name(s)")
    p.add_argument("--tflag", nargs="+", default=None, help="sample-start timestamps YYYYMMDD[HH[MM]]")
    p.add_argument("--date", nargs="+", default=None, help="one or more UTC dates YYYYMMDD")
    p.add_argument("--stime", "--start", dest="stime", default=None, help="inclusive start time YYYYMMDD[HH[MM]]")
    p.add_argument("--etime", "--end", dest="etime", default=None, help="inclusive end time YYYYMMDD[HH[MM]]")
    p.add_argument("--factor", "--source-factor", dest="factor", nargs="+", type=float, default=None, help="source/file coefficient(s)")
    p.add_argument("--decay", type=float, default=None, help="radioactive half-life in days")
    p.add_argument("--decay-reference", choices=("idl", "exact", "first", "earliest"), default="idl")
    p.add_argument("--vmean", action="store_true", help="thickness-weighted vertical mean")
    p.add_argument("--zero-to-nan", "--nan", dest="zero_to_nan", action="store_true", help="replace exact output zeros with NaN")
    p.add_argument("--dtype", choices=("float32", "float64"), default="float32")
    p.add_argument("--no-strict", action="store_true")

    p.add_argument("--bbox", nargs=4, type=float, default=None, metavar=("LAT_MIN", "LON_MIN", "LAT_MAX", "LON_MAX"), help="manual geographic bbox")
    p.add_argument("--bbox-round", type=int, default=2, help="automatic bbox decimal places. Default: 2")
    p.add_argument("--res", type=float, default=None, help="target-grid spacing in target CRS units")
    p.add_argument("--dim", nargs=2, type=int, default=None, metavar=("NX", "NY"), help="target-grid dimension")
    p.add_argument("--max-dim", type=int, default=2000, help="cap automatic grid dimension; 0 disables cap")
    p.add_argument("--split-time", action="store_true", help="write one GeoTIFF per timestep instead of a multiband file")
    p.add_argument("--no-compress", action="store_true", help="disable GeoTIFF DEFLATE compression")
    p.add_argument("--quiet", action="store_true")
    return p


def main() -> int:
    args = _parser().parse_args()
    try:
        input_files = resolve_cdump_inputs(args.files, file_lists=args.file_list)
    except Exception as exc:
        print(f"Input-file error: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(f"Starting hysp_cdump2tif.py {APP_VERSION} ...")
        print("Designed by Hyun Cheol Kim (hyun.kim@noaa.gov)")
        print(f"Files : {len(input_files)} expanded input file(s)")
        if args.file_list:
            print("File list(s): " + ", ".join(os.fspath(x) for x in args.file_list))
        print(f"Output: {args.output}")
        print(f"Target: EPSG:{args.epsg}")
        if args.res is not None:
            print(f"Resolution: {args.res:g} target-CRS units")
        elif args.dim is not None:
            print(f"Dimension : {args.dim[0]} x {args.dim[1]}")
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
        created = save_geotiff(
            args.output, data, info,
            var_name=args.var_name,
            target_epsg=args.epsg,
            bbox=args.bbox,
            bbox_round=args.bbox_round,
            dim=args.dim,
            res=args.res,
            max_dim=args.max_dim,
            fill_value=float("nan"),
            compress=not args.no_compress,
            split_time=args.split_time,
        )
    except Exception as exc:
        print(f"Output error: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        for path in created:
            print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
