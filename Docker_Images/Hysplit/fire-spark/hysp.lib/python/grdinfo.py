#!/usr/bin/env python3
"""
grdinfo.py

Python counterpart of the user's current IDL grid interface:

    grdinfo.pro
    grdinfo_proj.pro
    grdinfo_bbox.pro
    aqm_gi.pro / aqm_fgi.pro

Named-grid definitions are retained from aqm_grid_minfo.pro because the
current grdinfo.pro still delegates named-domain lookup to that routine.

For FINN, the important public functions are:

    grdinfo(domain="nca12")
    grdinfo_bbox(domain="nca12")
    grdinfo_mask(lon, lat, domain="nca12")

The registered-grid convention is also supported:

    ~/data/grdinfo/<DOMAIN>.minfo

where the .minfo file contains JSON.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

DOMAINS = {'3x': {'dx': 12000,
        'dy': 12000,
        'lat0': 40,
        'lat1': 33,
        'lat2': 45,
        'lon0': -97,
        'nx': 268,
        'ny': 259,
        'proj': 'lcc',
        'r': 6370000,
        'x0': -420000,
        'y0': -1716000},
 '5x': {'dx': 12000,
        'dy': 12000,
        'lat0': 40,
        'lat1': 33,
        'lat2': 45,
        'lon0': -97,
        'nx': 442,
        'ny': 265,
        'proj': 'lcc',
        'r': 6370000,
        'x0': -2508000,
        'y0': -1716000},
 '5x108': {'dx': 108000,
           'dy': 108000,
           'lat0': 40,
           'lat1': 33,
           'lat2': 45,
           'lon0': -97,
           'nx': 50,
           'ny': 30,
           'proj': 'lcc',
           'r': 6370000,
           'x0': -2508000,
           'y0': -1716000},
 '5x36': {'dx': 36000,
          'dy': 36000,
          'lat0': 40,
          'lat1': 33,
          'lat2': 45,
          'lon0': -97,
          'nx': 147,
          'ny': 89,
          'proj': 'lcc',
          'r': 6370000,
          'x0': -2508000,
          'y0': -1716000},
 '7x': {'dx': 4000,
        'dy': 4000,
        'lat0': 40,
        'lat1': 33,
        'lat2': 45,
        'lon0': -97,
        'nx': 1199,
        'ny': 799,
        'proj': 'lcc',
        'r': 6370000,
        'x0': -2398000,
        'y0': -1598000},
 '9x': {'dx': 1000,
        'dy': 1000,
        'lat0': 40,
        'lat1': 33,
        'lat2': 45,
        'lon0': -97,
        'nx': 5200,
        'ny': 3200,
        'proj': 'lcc',
        'r': 6370000,
        'x0': -2508000,
        'y0': -1716000},
 'a81': {'dx': 81000,
         'dy': 81000,
         'lat0': 38,
         'lat1': 30,
         'lat2': 60,
         'lon0': 126,
         'nx': 85,
         'ny': 70,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -4131000,
         'y0': -2133000},
 'afr': {'dx': 1, 'dy': 1, 'nx': 101, 'ny': 41, 'proj': 'll', 'x0': -100, 'y0': 0},
 'ak12': {'dx': 12000,
          'dy': 12000,
          'lat0': 63.2,
          'lat1': 57,
          'lat2': 63,
          'lon0': -148.6,
          'nx': 199,
          'ny': 163,
          'proj': 'lcc',
          'r': 6370000,
          'x0': -1194000,
          'y0': -978000},
 'aqum': {'dx': 0.11,
          'dy': 0.11,
          'lat0': 52.43,
          'lon0': 306.97,
          'nx': 540,
          'ny': 432,
          'proj': 'ell',
          'r': 6371229,
          'x0': -29.7,
          'y0': -23.76},
 'b04': {'dx': 0.042,
         'dy': 0.036,
         'lat0': 54,
         'lon0': -106,
         'nx': 1114,
         'ny': 880,
         'proj': 'rll',
         'x0': -16.695046,
         'y0': -29.375995},
 'b3x': {'dx': 0.126,
         'dy': 0.108,
         'lat0': 54,
         'lon0': -106,
         'nx': 180,
         'ny': 144,
         'proj': 'rll',
         'x0': 8.048,
         'y0': -20.955},
 'ca4b': {'dx': 0.042,
          'dy': 0.036,
          'lat0': 54,
          'lon0': -106,
          'nx': 241,
          'ny': 346,
          'proj': 'rll',
          'x0': -15.708,
          'y0': -21.726},
 'cesm': {'dx': 2.5, 'dy': 1.8947368, 'nx': 144, 'ny': 94, 'proj': 'll', 'x0': -1.25, 'y0': -89.052632},
 'co4': {'dx': 4000,
         'dy': 4000,
         'lat0': 40,
         'lat1': 33,
         'lat2': 45,
         'lon0': -97,
         'nx': 149,
         'ny': 131,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -1004000,
         'y0': -260000},
 'd04': {'dx': 4000,
         'dy': 4000,
         'lat0': 40,
         'lat1': 30,
         'lat2': 60,
         'lon0': -100,
         'nx': 83,
         'ny': 65,
         'proj': 'lcc',
         'r': 6370000,
         'x0': 356000,
         'y0': -1228000},
 'd04d': {'dx': 4000,
          'dy': 4000,
          'lat0': 40,
          'lat1': 30,
          'lat2': 60,
          'lon0': -100,
          'nx': 74,
          'ny': 65,
          'proj': 'lcc',
          'r': 6370000,
          'x0': 140000,
          'y0': -940000},
 'd12': {'dx': 12000,
         'dy': 12000,
         'lat0': 40,
         'lat1': 30,
         'lat2': 60,
         'lon0': -100,
         'nx': 89,
         'ny': 89,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -12000,
         'y0': -1488000},
 'd36': {'dx': 36000,
         'dy': 36000,
         'lat0': 40,
         'lat1': 30,
         'lat2': 60,
         'lon0': -100,
         'nx': 133,
         'ny': 91,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -2160000,
         'y0': -1836000},
 'e04': {'dx': 4000,
         'dy': 4000,
         'lat0': 40,
         'lat1': 30,
         'lat2': 60,
         'lon0': -100,
         'nx': 137,
         'ny': 137,
         'proj': 'lcc',
         'r': 6370000,
         'x0': 140000,
         'y0': -1228000},
 'e12': {'dx': 12000,
         'dy': 12000,
         'lat0': 40,
         'lat1': 30,
         'lat2': 60,
         'lon0': -100,
         'nx': 167,
         'ny': 128,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -660000,
         'y0': -1704000},
 'etx4': {'dx': 4000,
          'dy': 4000,
          'lat0': 40,
          'lat1': 33,
          'lat2': 45,
          'lon0': -97,
          'nx': 196,
          'ny': 268,
          'proj': 'lcc',
          'r': 6370000,
          'x0': -368000,
          'y0': -1592000},
 'g005': {'dx': 0.05, 'dy': 0.05, 'nx': 7200, 'ny': 3600, 'proj': 'll', 'x0': -180, 'y0': -90},
 'g01': {'dx': 0.1, 'dy': 0.1, 'nx': 3600, 'ny': 1800, 'proj': 'll', 'x0': -180, 'y0': -90},
 'g05': {'dx': 0.5, 'dy': 0.5, 'nx': 720, 'ny': 360, 'proj': 'll', 'x0': -180, 'y0': -90},
 'g1': {'dx': 1, 'dy': 1, 'nx': 360, 'ny': 180, 'proj': 'll', 'x0': -180, 'y0': -90},
 'global': {'dx': 1, 'dy': 1, 'nx': 360, 'ny': 180, 'proj': 'll', 'x0': -180, 'y0': -90},
 'hi12': {'dx': 12000,
          'dy': 12000,
          'lat0': 20.53,
          'lat1': 19,
          'lat2': 21,
          'lon0': -157.5,
          'nx': 80,
          'ny': 52,
          'proj': 'lcc',
          'r': 6370000,
          'x0': -480000,
          'y0': -312000},
 'hou4': {'dx': 4000,
          'dy': 4000,
          'lat0': 40,
          'lat1': 33,
          'lat2': 45,
          'lon0': -97,
          'nx': 160,
          'ny': 180,
          'proj': 'lcc',
          'r': 6370000,
          'x0': -222000,
          'y0': -1302000},
 'k01k': {'dx': 1000,
          'dy': 1000,
          'lat0': 38,
          'lat1': 30,
          'lat2': 60,
          'lon0': 126,
          'nx': 357,
          'ny': 519,
          'proj': 'lcc',
          'r': 6370000,
          'x0': -30000,
          'y0': -435000},
 'k03': {'dx': 3000,
         'dy': 3000,
         'lat0': 38,
         'lat1': 30,
         'lat2': 60,
         'lon0': 126,
         'nx': 58,
         'ny': 61,
         'proj': 'lcc',
         'r': 6370000,
         'x0': 0,
         'y0': -135000},
 'k03_05': {'dx': 3000,
            'dy': 3000,
            'lat0': 38,
            'lat1': 30,
            'lat2': 60,
            'lon0': 126,
            'nx': 119,
            'ny': 173,
            'proj': 'lcc',
            'r': 6370000,
            'x0': -30000,
            'y0': -435000},
 'k03k': {'dx': 3000,
          'dy': 3000,
          'lat0': 38,
          'lat1': 30,
          'lat2': 60,
          'lon0': 126,
          'nx': 201,
          'ny': 246,
          'proj': 'lcc',
          'r': 6370000,
          'x0': -180000,
          'y0': -585000},
 'k09': {'dx': 9000,
         'dy': 9000,
         'lat0': 38,
         'lat1': 30,
         'lat2': 60,
         'lon0': 126,
         'nx': 67,
         'ny': 82,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -180000,
         'y0': -585000},
 'k09dh': {'dx': 9000,
           'dy': 9000,
           'lat0': 38,
           'lat1': 30,
           'lat2': 60,
           'lon0': 126,
           'nx': 5,
           'ny': 5,
           'proj': 'lcc',
           'r': 6370000,
           'x0': 243000,
           'y0': -72000},
 'k09n': {'dx': 9000,
          'dy': 9000,
          'lat0': 38,
          'lat1': 30,
          'lat2': 60,
          'lon0': 126,
          'nx': 78,
          'ny': 132,
          'proj': 'lcc',
          'r': 6370000,
          'x0': -270000,
          'y0': -567000},
 'k09n2': {'dx': 9000,
           'dy': 9000,
           'lat0': 38,
           'lat1': 30,
           'lat2': 60,
           'lon0': 126,
           'nx': 75,
           'ny': 132,
           'proj': 'lcc',
           'r': 6370000,
           'x0': -243000,
           'y0': -594000},
 'k09yw': {'dx': 9000,
           'dy': 9000,
           'lat0': 38,
           'lat1': 30,
           'lat2': 60,
           'lon0': 126,
           'nx': 5,
           'ny': 5,
           'proj': 'lcc',
           'r': 6370000,
           'x0': 180000,
           'y0': -117000},
 'k12': {'dx': 12000,
         'dy': 12000,
         'lat0': 40,
         'lat1': 33,
         'lat2': 45,
         'lon0': 120,
         'nx': 718,
         'ny': 776,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -4308000,
         'y0': -4656000},
 'k27': {'dx': 27000,
         'dy': 27000,
         'lat0': 38,
         'lat1': 30,
         'lat2': 60,
         'lon0': 126,
         'nx': 174,
         'ny': 128,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -2349000,
         'y0': -1728000},
 'kaq27': {'dx': 27000,
           'dy': 27000,
           'lat0': 38,
           'lat1': 30,
           'lat2': 60,
           'lon0': 126,
           'nx': 52,
           'ny': 46,
           'proj': 'lcc',
           'r': 6370000,
           'x0': -918000,
           'y0': -756000},
 'namb': {'dx': 0.126,
          'dy': 0.108,
          'lat0': 54,
          'lon0': -106,
          'nx': 954,
          'ny': 835,
          'proj': 'rll',
          'x0': -60.102,
          'y0': -45.09},
 'nca108': {'dx': 108000,
            'dy': 108000,
            'lat0': 40,
            'lat1': 33,
            'lat2': 45,
            'lon0': -97,
            'nx': 80,
            'ny': 85,
            'proj': 'lcc',
            'r': 6370000,
            'x0': -4308000,
            'y0': -4656000},
 'nca12': {'dx': 12000,
           'dy': 12000,
           'lat0': 40,
           'lat1': 33,
           'lat2': 45,
           'lon0': -97,
           'nx': 718,
           'ny': 776,
           'proj': 'lcc',
           'r': 6370000,
           'x0': -4308000,
           'y0': -4656000},
 'nca36': {'dx': 36000,
           'dy': 36000,
           'lat0': 40,
           'lat1': 33,
           'lat2': 45,
           'lon0': -97,
           'nx': 240,
           'ny': 260,
           'proj': 'lcc',
           'r': 6370000,
           'x0': -4308000,
           'y0': -4656000},
 'nish01': {'dx': 0.1, 'dy': 0.1, 'nx': 501, 'ny': 501, 'proj': 'll', 'x0': 115.882, 'y0': 2.2740002},
 'q01': {'dx': 1000,
         'dy': 1000,
         'lat0': 40,
         'lat1': 33,
         'lat2': 45,
         'lon0': -97,
         'nx': 4860,
         'ny': 3240,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -2508000,
         'y0': -1716000},
 'q04': {'dx': 4000,
         'dy': 4000,
         'lat0': 40,
         'lat1': 33,
         'lat2': 45,
         'lon0': -97,
         'nx': 1215,
         'ny': 810,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -2508000,
         'y0': -1716000},
 'q108': {'dx': 108000,
          'dy': 108000,
          'lat0': 40,
          'lat1': 33,
          'lat2': 45,
          'lon0': -97,
          'nx': 45,
          'ny': 30,
          'proj': 'lcc',
          'r': 6370000,
          'x0': -2508000,
          'y0': -1716000},
 'q12': {'dx': 12000,
         'dy': 12000,
         'lat0': 40,
         'lat1': 33,
         'lat2': 45,
         'lon0': -97,
         'nx': 405,
         'ny': 270,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -2508000,
         'y0': -1716000},
 'q36': {'dx': 36000,
         'dy': 36000,
         'lat0': 40,
         'lat1': 33,
         'lat2': 45,
         'lon0': -97,
         'nx': 135,
         'ny': 90,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -2508000,
         'y0': -1716000},
 'r12': {'dx': 12000,
         'dy': 12000,
         'lat0': 40,
         'lat1': 33,
         'lat2': 45,
         'lon0': -97,
         'nx': 444,
         'ny': 336,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -2736000,
         'y0': -2088000},
 'r36': {'dx': 36000,
         'dy': 36000,
         'lat0': 40,
         'lat1': 33,
         'lat2': 45,
         'lon0': -97,
         'nx': 148,
         'ny': 112,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -2736000,
         'y0': -2088000},
 'sc4': {'dx': 4000,
         'dy': 4000,
         'lat0': 37,
         'lat1': 30,
         'lat2': 60,
         'lon0': -120.5,
         'nx': 156,
         'ny': 102,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -84000,
         'y0': -552000},
 'sjv4': {'dx': 4000,
          'dy': 4000,
          'lat0': 40,
          'lat1': 33,
          'lat2': 45,
          'lon0': -97,
          'nx': 110,
          'ny': 160,
          'proj': 'lcc',
          'r': 6370000,
          'x0': -2242000,
          'y0': -522000},
 'sn4': {'dx': 4000,
         'dy': 4000,
         'lat0': 40,
         'lat1': 33,
         'lat2': 45,
         'lon0': -97,
         'nx': 308,
         'ny': 244,
         'proj': 'lcc',
         'r': 6370000,
         'x0': 658000,
         'y0': -1134000},
 't36': {'dx': 36000,
         'dy': 36000,
         'lat0': 40,
         'lat1': 33,
         'lat2': 45,
         'lon0': -97,
         'nx': 148,
         'ny': 112,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -2736000,
         'y0': -2088000},
 'tcna36': {'dx': 36000,
            'dy': 36000,
            'lat0': 40,
            'lat1': 30,
            'lat2': 45,
            'lon0': -97,
            'nx': 162,
            'ny': 128,
            'proj': 'lcc',
            'r': 6370000,
            'x0': -2916000,
            'y0': -2304000},
 'tcsus12': {'dx': 12000,
             'dy': 12000,
             'lat0': 40,
             'lat1': 30,
             'lat2': 45,
             'lon0': -97,
             'nx': 174,
             'ny': 138,
             'proj': 'lcc',
             'r': 6370000,
             'x0': -1188000,
             'y0': -1800000},
 'tctx04': {'dx': 4000,
            'dy': 4000,
            'lat0': 40,
            'lat1': 30,
            'lat2': 45,
            'lon0': -97,
            'nx': 216,
            'ny': 288,
            'proj': 'lcc',
            'r': 6370000,
            'x0': -408000,
            'y0': -1632000},
 'u04a': {'dx': 4000,
          'dy': 4000,
          'lat0': 40,
          'lat1': 30,
          'lat2': 60,
          'lon0': -95,
          'nx': 139,
          'ny': 97,
          'proj': 'lcc',
          'r': 6370000,
          'x0': 804000,
          'y0': -306000},
 'u04b': {'dx': 4000,
          'dy': 4000,
          'lat0': 40,
          'lat1': 30,
          'lat2': 60,
          'lon0': -95,
          'nx': 283,
          'ny': 199,
          'proj': 'lcc',
          'r': 6370000,
          'x0': -60000,
          'y0': 198000},
 'u04c': {'dx': 4000,
          'dy': 4000,
          'lat0': 40,
          'lat1': 30,
          'lat2': 60,
          'lon0': -95,
          'nx': 238,
          'ny': 238,
          'proj': 'lcc',
          'r': 6370000,
          'x0': 1116000,
          'y0': -30000},
 'u12': {'dx': 12000,
         'dy': 12000,
         'lat0': 40,
         'lat1': 30,
         'lat2': 60,
         'lon0': -95,
         'nx': 211,
         'ny': 142,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -396000,
         'y0': -486000},
 'u36': {'dx': 36000,
         'dy': 36000,
         'lat0': 40,
         'lat1': 30,
         'lat2': 60,
         'lon0': -95,
         'nx': 123,
         'ny': 88,
         'proj': 'lcc',
         'r': 6370000,
         'x0': -2196000,
         'y0': -1566000},
 'world': {'dx': 1, 'dy': 1, 'nx': 360, 'ny': 160, 'proj': 'll', 'x0': -179.5, 'y0': -80}}


def _norm_domain(name: str) -> str:
    return str(name).strip().lower()


def _data_root(data_root: str | os.PathLike[str] | None = None) -> Path:
    if data_root is not None:
        return Path(data_root).expanduser()
    env = os.environ.get("DATA_PATH") or os.environ.get("BLUTOUCH_DATA")
    return Path(env).expanduser() if env else Path("~/data").expanduser()


def _load_registered_minfo(
    domain: str,
    *,
    data_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Read ~/data/grdinfo/<DOMAIN>.minfo if present."""
    file = _data_root(data_root) / "grdinfo" / f"{str(domain).upper()}.minfo"
    if not file.is_file():
        return None
    try:
        obj = json.loads(file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Cannot read minfo file: {file}") from exc
    if not isinstance(obj, Mapping):
        raise ValueError(f"Invalid minfo file: {file}")
    return {str(k).lower(): v for k, v in obj.items()}


def get_minfo(
    domain: str | Mapping[str, Any] | None = None,
    *,
    minfo: Mapping[str, Any] | None = None,
    data_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    if minfo is not None:
        return {str(k).lower(): v for k, v in minfo.items()}

    if isinstance(domain, Mapping):
        return {str(k).lower(): v for k, v in domain.items()}

    if domain is None:
        return None

    key = _norm_domain(domain)

    # Allow a literal "south,west,north,east" string; handled by grdinfo_bbox.
    if "," in key:
        return None

    # Match the IDL library's registered-grid behavior when such a file exists.
    reg = _load_registered_minfo(str(domain), data_root=data_root)
    if reg is not None:
        return reg

    if key in DOMAINS:
        return dict(DOMAINS[key])

    raise KeyError(f"Unknown domain: {domain}")



def grdinfo(
    input=None,
    *,
    domain=None,
    minfo=None,
    radius=None,
    proj=None,
    zoom=None,
    dot=False,
    boundary=False,
    nthick=1,
    dxy=None,
    data_root=None,
):
    """
    Return grid information, following the role of IDL grdinfo.pro.

    Parameters
    ----------
    input, domain, minfo
        A domain name or an existing minfo mapping.
    radius
        Override Earth radius ``r``.
    proj
        Override projection name.
    zoom
        Grid-index subset [x0, y0, x1, y1], inclusive, matching the IDL logic.
    dot
        Convert CRO-style cell grid to DOT grid.
    boundary
        Add ``nthick`` boundary cells.
    dxy
        Resample the grid spacing using the same integer-count logic as IDL.

    Returns
    -------
    dict
        Normalized minfo mapping.
    """
    if input is not None:
        if isinstance(input, Mapping):
            minfo = input
        elif domain is None:
            domain = input

    m = get_minfo(domain, minfo=minfo, data_root=data_root)
    if m is None:
        raise ValueError("domain or minfo is required")
    m = dict(m)

    m.setdefault("r", 6370000.0)
    if radius is not None:
        m["r"] = float(radius)
    if proj is not None:
        m["proj"] = str(proj).lower()

    if zoom is not None:
        z = [int(v) for v in zoom]
        if len(z) != 4:
            raise ValueError("zoom must be [x0, y0, x1, y1]")
        m["nx"] = int(z[2] - z[0] + 1)
        m["ny"] = int(z[3] - z[1] + 1)
        m["x0"] = float(m["x0"]) + float(m["dx"]) * z[0]
        m["y0"] = float(m["y0"]) + float(m["dy"]) * z[1]

    if dxy is not None:
        dxy = float(dxy)
        m["nx"] = int(float(m["dx"]) / dxy) * int(m["nx"]) + 1
        m["ny"] = int(float(m["dy"]) / dxy) * int(m["ny"]) + 1
        m["dx"] = dxy
        m["dy"] = dxy

    if dot:
        m["x0"] = float(m["x0"]) - float(m["dx"]) / 2.0
        m["y0"] = float(m["y0"]) - float(m["dy"]) / 2.0
        m["nx"] = int(m["nx"]) + 1
        m["ny"] = int(m["ny"]) + 1

    if boundary:
        n = int(nthick)
        m["x0"] = float(m["x0"]) - float(m["dx"]) * n
        m["y0"] = float(m["y0"]) - float(m["dy"]) * n
        m["nx"] = int(m["nx"]) + 2 * n
        m["ny"] = int(m["ny"]) + 2 * n

    return m

def _perimeter_xy(m: Mapping[str, Any], n: int = 101) -> tuple[np.ndarray, np.ndarray]:
    x0 = float(m["x0"])
    y0 = float(m["y0"])
    x1 = x0 + float(m["dx"]) * int(m["nx"])
    y1 = y0 + float(m["dy"]) * int(m["ny"])

    xb = np.linspace(x0, x1, n)
    yb = np.full(n, y0)
    xr = np.full(n, x1)
    yr = np.linspace(y0, y1, n)
    xt = np.linspace(x1, x0, n)
    yt = np.full(n, y1)
    xl = np.full(n, x0)
    yl = np.linspace(y1, y0, n)
    return np.concatenate([xb, xr, xt, xl]), np.concatenate([yb, yr, yt, yl])


def minfo_bbox(minfo: Mapping[str, Any]) -> tuple[float, float, float, float]:
    """
    Return [south, west, north, east] for a minfo structure.

    For LCC grids, the complete projected perimeter is sampled before taking
    lon/lat extrema.  This is closer to the IDL grdinfo_bbox behavior than
    transforming only four corners.
    """
    m = {str(k).lower(): v for k, v in minfo.items()}
    proj = str(m.get("proj", "ll")).strip().lower()

    if proj in ("ll", "latlon", "lat/lon", "noproj"):
        west = float(m["x0"])
        south = float(m["y0"])
        east = west + float(m["dx"]) * int(m["nx"])
        north = south + float(m["dy"]) * int(m["ny"])
        return (south, west, north, east)

    if proj == "lcc":
        try:
            from pyproj import CRS, Transformer
        except ImportError as exc:
            raise RuntimeError(
                "pyproj is required to determine the bbox of an LCC domain"
            ) from exc

        r = float(m.get("r", 6370000.0))
        crs = CRS.from_proj4(
            f"+proj=lcc +lat_1={float(m['lat1'])} +lat_2={float(m['lat2'])} "
            f"+lat_0={float(m['lat0'])} +lon_0={float(m['lon0'])} "
            f"+R={r} +units=m +no_defs"
        )
        to_ll = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        x, y = _perimeter_xy(m)
        lon, lat = to_ll.transform(x, y)
        lon = np.asarray(lon, dtype=float)
        lat = np.asarray(lat, dtype=float)
        return (float(np.nanmin(lat)), float(np.nanmin(lon)),
                float(np.nanmax(lat)), float(np.nanmax(lon)))

    raise NotImplementedError(
        f"Domain projection {proj!r} is not yet implemented for FINN filtering. "
        "Supply bbox=[south, west, north, east] explicitly."
    )


def grdinfo_bbox(
    bbox: Sequence[float] | str | None = None,
    *,
    domain: str | Mapping[str, Any] | None = None,
    minfo: Mapping[str, Any] | None = None,
    margin: float = 0.0,
    data_root: str | os.PathLike[str] | None = None,
) -> tuple[float, float, float, float] | None:
    if bbox is not None:
        if isinstance(bbox, str):
            vals = [float(x.strip()) for x in bbox.split(",")]
        else:
            vals = [float(x) for x in bbox]
        if len(vals) != 4:
            raise ValueError("bbox must be [south, west, north, east]")
        out = vals
    elif isinstance(domain, str) and "," in domain:
        vals = [float(x.strip()) for x in domain.split(",")]
        if len(vals) != 4:
            raise ValueError("domain bbox string must have four values")
        out = vals
    else:
        m = grdinfo(domain=domain, minfo=minfo, data_root=data_root)
        out = list(minfo_bbox(m))

    south, west, north, east = out
    margin = float(margin)
    return (south - margin, west - margin, north + margin, east + margin)




def domain_mask(
    lon: np.ndarray,
    lat: np.ndarray,
    *,
    domain: str | Mapping[str, Any] | None = None,
    minfo: Mapping[str, Any] | None = None,
    data_root: str | os.PathLike[str] | None = None,
) -> np.ndarray:
    """
    Return the point-in-grid mask corresponding to IDL aqm_gi(...).ixy ne -1.

    For projected grids, lon/lat are transformed to the grid projection and
    converted to nearest cell-center indices using the same basic formula as
    aqm_gi.pro.
    """
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    good = np.isfinite(lon) & np.isfinite(lat)

    m = grdinfo(domain=domain, minfo=minfo, data_root=data_root)

    proj = str(m.get("proj", "ll")).strip().lower()
    llon = lon.copy()

    # Same longitude convention check used by aqm_gi.pro.
    if float(m["x0"]) + float(m["dx"]) * int(m["nx"]) > 180.0:
        llon = np.mod(llon, 360.0)

    if proj in ("ll", "latlon", "lat/lon", "noproj"):
        x = llon
        y = lat

    elif proj == "lcc":
        try:
            from pyproj import CRS, Transformer
        except ImportError as exc:
            raise RuntimeError("pyproj is required for LCC domain filtering") from exc
        r = float(m.get("r", 6370000.0))
        crs = CRS.from_proj4(
            f"+proj=lcc +lat_1={float(m['lat1'])} +lat_2={float(m['lat2'])} "
            f"+lat_0={float(m['lat0'])} +lon_0={float(m['lon0'])} "
            f"+R={r} +units=m +no_defs"
        )
        tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        x, y = tr.transform(llon, lat)
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)

    elif proj == "polar":
        try:
            from pyproj import CRS, Transformer
        except ImportError as exc:
            raise RuntimeError("pyproj is required for polar domain filtering") from exc
        r = float(m.get("r", 6370000.0))
        lat_ts = float(m.get("lat2", 60.0))
        lat0 = 90.0 if lat_ts >= 0 else -90.0
        crs = CRS.from_proj4(
            f"+proj=stere +lat_0={lat0} +lat_ts={lat_ts} "
            f"+lon_0={float(m['lon0'])} +R={r} +units=m +no_defs"
        )
        tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        x, y = tr.transform(llon, lat)
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)

    elif proj == "rll":
        # Direct port of aqm_gi.pro rotated-lat/lon equations.
        dtor = np.pi / 180.0
        lon0 = float(m["lon0"]) * dtor
        lat0 = float(m["lat0"]) * dtor
        lnr = llon * dtor
        ltr = lat * dtor
        dlon = lnr - lon0
        x = np.arctan2(
            np.cos(ltr) * np.sin(dlon),
            np.cos(lat0) * np.cos(ltr) * np.cos(dlon)
            + np.sin(lat0) * np.sin(ltr),
        ) / dtor
        y = np.arcsin(
            np.cos(lat0) * np.sin(ltr)
            - np.sin(lat0) * np.cos(ltr) * np.cos(dlon)
        ) / dtor

    else:
        raise NotImplementedError(
            f"Domain projection {proj!r} is not implemented for exact FINN filtering. "
            "Supply bbox= explicitly or add the projection."
        )

    x0 = float(m["x0"])
    y0 = float(m["y0"])
    dx = float(m["dx"])
    dy = float(m["dy"])
    nx = int(m["nx"])
    ny = int(m["ny"])

    ix = np.rint((x - x0 - dx / 2.0) / dx)
    iy = np.rint((y - y0 - dy / 2.0) / dy)
    good &= np.isfinite(x) & np.isfinite(y)
    good &= (ix >= 0) & (ix <= nx - 1) & (iy >= 0) & (iy <= ny - 1)
    return good


def bbox_mask(
    lon: np.ndarray,
    lat: np.ndarray,
    bbox: Sequence[float] | None,
) -> np.ndarray:
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    if bbox is None:
        return np.isfinite(lon) & np.isfinite(lat)

    south, west, north, east = [float(x) for x in bbox]
    good = np.isfinite(lon) & np.isfinite(lat)
    good &= (lat >= south) & (lat <= north)

    # Normalize to [-180, 180).  If west > east, the bbox crosses the dateline.
    ll = ((lon + 180.0) % 360.0) - 180.0
    w = ((west + 180.0) % 360.0) - 180.0
    e = ((east + 180.0) % 360.0) - 180.0
    if w <= e:
        good &= (ll >= w) & (ll <= e)
    else:
        good &= (ll >= w) | (ll <= e)
    return good


# Public names matching the current grdinfo-based design.
grdinfo_mask = domain_mask
grdinfo_minfo = get_minfo
