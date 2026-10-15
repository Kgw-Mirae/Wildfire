#!/usr/bin/env python3
"""
hysp_init.py

Shared IDL/Python HYSP initialization.

The same hysp.ini JSON file can be used by both IDL and Python.

If hysp.ini does not exist:
  HYSPLIT_PATH : use $hysplit, otherwise $HYSPLIT_PATH, otherwise ""
  ARL_PATH     : ~/data/arl
  ARL_DOWN     : 1
  MPI_PATH     : full path to mpirun if found in PATH, otherwise ""
  MPI_USE      : 1 if mpirun is found, otherwise 0
  MPI_CPU      : 16

If hysp.ini already exists, it is read as-is.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any


def _default_options() -> dict[str, Any]:
    hysplit_path = os.environ.get("hysplit", "").strip()
    if not hysplit_path:
        hysplit_path = os.environ.get("HYSPLIT_PATH", "").strip()

    if hysplit_path:
        hysplit_path = str(Path(hysplit_path).expanduser())

    mpi_path = shutil.which("mpirun") or ""

    return {
        "HYSPLIT_PATH": hysplit_path,
        "ARL_PATH": str(Path("~/data/arl").expanduser()),
        "ARL_DOWN": 1,
        "MPI_USE": 1 if mpi_path else 0,
        "MPI_PATH": mpi_path,
        "MPI_CPU": 16,
    }


def hysp_init(
    filename: str | Path = "hysp.ini",
    *,
    renew: bool = False,
) -> dict[str, Any]:
    """
    Read or create the shared HYSP configuration file.

    Parameters
    ----------
    filename : str or Path
        Configuration filename. Default: ./hysp.ini
    renew : bool
        Recreate hysp.ini from machine-derived defaults.

    Returns
    -------
    dict
        HYSP options.
    """
    path = Path(filename)

    if renew or not path.is_file():
        opt = _default_options()
        with path.open("w", encoding="utf-8") as f:
            json.dump(opt, f, indent=4)
            f.write("\n")

    with path.open("r", encoding="utf-8") as f:
        opt = json.load(f)

    required = (
        "HYSPLIT_PATH",
        "ARL_PATH",
        "ARL_DOWN",
        "MPI_USE",
        "MPI_PATH",
        "MPI_CPU",
    )

    missing = [key for key in required if key not in opt]
    if missing:
        raise KeyError(
            f"Missing option(s) in {path}: " + ", ".join(missing)
        )

    opt["HYSPLIT_PATH"] = str(opt["HYSPLIT_PATH"])
    opt["ARL_PATH"] = str(opt["ARL_PATH"])
    opt["ARL_DOWN"] = int(opt["ARL_DOWN"])
    opt["MPI_USE"] = int(opt["MPI_USE"])
    opt["MPI_PATH"] = str(opt["MPI_PATH"])
    opt["MPI_CPU"] = int(opt["MPI_CPU"])

    return {key: opt[key] for key in required}


if __name__ == "__main__":
    print(json.dumps(hysp_init(), indent=4))
