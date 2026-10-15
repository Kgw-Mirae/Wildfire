#!/usr/bin/env python3
"""
nsfs_chk.py

Validate a prepared NSFS/HYSPLIT run directory.  Nothing is downloaded,
rewritten, or executed.

The checker is intentionally strict about meteorology because the purpose of
splitting NSFS into prep/chk/run is to catch missing or corrupt ARL input before
HYSPLIT is started.

Checks
------
* CONTROL exists and parses
* SETUP.CFG exists and points EFILE to an existing EMITIMES file
* ASCDATA.CFG exists and its boundary-data path exists
* EMITIMES exists, parses, contains records, and overlaps the simulation time
* CONTROL source count matches EMITIMES record count
* every ARL file listed in CONTROL exists and is structurally valid
* ARL time coverage is continuous for the complete simulation period
* the requested HYSPLIT executable is available

Typical use
-----------
    python -m fire.nsfs_chk \
        hysp.run/NSFS/gfs0p25-rave3/2026/20261005

    python -m fire.nsfs_chk RUN_DIR --mode mpi --ini hysp.ini
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from hysp.hysp_arl_chk import hysp_arl_chk, hysp_arl_info
from hysp.hysp_control import hysp_control_read
from hysp.hysp_emitimes import hysp_emitimes_read
from hysp.hysp_init import hysp_init


def _control_start(text: str) -> datetime:
    p = str(text).split()
    if len(p) < 4:
        raise ValueError(f"Invalid CONTROL starting_time: {text!r}")
    yy, mm, dd, hh = (int(x) for x in p[:4])
    year = 1900 + yy if yy > 40 else 2000 + yy
    return datetime(year, mm, dd, hh)


def _simulation_window(control: Mapping[str, Any]) -> tuple[datetime, datetime]:
    start = _control_start(str(control['starting_time']))
    nhour = int(float(str(control['run_time']).strip()))
    end = start + timedelta(hours=nhour)
    return (start, end) if start <= end else (end, start)


def _duration_hours(value: Any) -> float:
    s = str(value).strip().zfill(4)
    if len(s) < 4 or not s[-4:].isdigit():
        return 0.0
    s = s[-4:]
    return int(s[:2]) + int(s[2:4]) / 60.0


def _efile_from_setup(path: Path) -> str | None:
    text = path.read_text(encoding='utf-8', errors='replace')
    m = re.search(r"(?im)^\s*efile\s*=\s*['\"]?([^,'\"\s/&]+)", text)
    return m.group(1).strip() if m else None


def _ascdata_path(path: Path) -> Path | None:
    text = path.read_text(encoding='utf-8', errors='replace')
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", text)
    if not quoted:
        return None
    return Path(quoted[-1]).expanduser()


def _is_executable(path: Path) -> bool:
    return path.exists() and path.is_file() and os.access(path, os.X_OK)


def _print_item(ok: bool, name: str, detail: str = '', *, verbose: bool = True) -> None:
    if not verbose:
        return
    tag = 'OK ' if ok else 'BAD'
    if detail:
        print(f"[{tag}] {name:<18} {detail}")
    else:
        print(f"[{tag}] {name}")


def nsfs_chk1(
    rdir: str | os.PathLike[str],
    *,
    mode: str = 'any',
    ini: str | os.PathLike[str] = 'hysp.ini',
    verbose: bool = True,
) -> dict[str, Any]:
    """Check one prepared run directory and return a structured report."""
    run_dir = Path(rdir).expanduser().resolve()
    mode = str(mode).lower()
    if mode not in {'any', 'serial', 'mpi'}:
        raise ValueError("mode must be 'any', 'serial', or 'mpi'")

    report: dict[str, Any] = {
        'rdir': str(run_dir),
        'ok': True,
        'checks': [],
        'control': None,
        'met_files': [],
        'emitimes_records': 0,
        'mode': mode,
    }

    def add(name: str, ok: bool, detail: str = '') -> None:
        report['checks'].append({'name': name, 'ok': bool(ok), 'detail': detail})
        if not ok:
            report['ok'] = False
        _print_item(ok, name, detail, verbose=verbose)

    if verbose:
        print(f"RUN DIRECTORY: {run_dir}")

    if not run_dir.is_dir():
        add('run directory', False, 'does not exist')
        if verbose:
            print('STATUS: NOT READY')
        return report

    # Required files first.
    required = ['CONTROL', 'SETUP.CFG', 'ASCDATA.CFG', 'EMITIMES']
    for name in required:
        p = run_dir / name
        ok = p.is_file() and p.stat().st_size > 0
        add(name, ok, f"{p.stat().st_size} bytes" if ok else 'missing/empty')

    control_path = run_dir / 'CONTROL'
    cc: dict[str, Any] | None = None
    sim_start: datetime | None = None
    sim_end: datetime | None = None

    if control_path.is_file():
        try:
            cc = hysp_control_read(control_path)
            report['control'] = cc
            sim_start, sim_end = _simulation_window(cc)
            add(
                'CONTROL parse',
                True,
                f"{sim_start:%Y%m%d%H} - {sim_end:%Y%m%d%H}  run={cc['run_time']} h",
            )
        except Exception as exc:
            add('CONTROL parse', False, str(exc))

    # SETUP.CFG / EFILE.
    setup = run_dir / 'SETUP.CFG'
    if setup.is_file():
        try:
            efile = _efile_from_setup(setup)
            if not efile:
                add('SETUP EFILE', False, 'EFILE is not defined')
            else:
                ep = Path(efile).expanduser()
                if not ep.is_absolute():
                    ep = run_dir / ep
                add('SETUP EFILE', ep.is_file(), f"{efile} -> {ep}")
        except Exception as exc:
            add('SETUP EFILE', False, str(exc))

    # ASCDATA.CFG boundary data path.
    asc = run_dir / 'ASCDATA.CFG'
    if asc.is_file():
        try:
            bdy = _ascdata_path(asc)
            if bdy is None:
                add('ASCDATA path', False, 'boundary-data path not found')
            else:
                add('ASCDATA path', bdy.exists(), str(bdy))
        except Exception as exc:
            add('ASCDATA path', False, str(exc))

    # EMITIMES and CONTROL sources.
    emit = run_dir / 'EMITIMES'
    records = []
    if emit.is_file():
        try:
            records = hysp_emitimes_read(emit)
            report['emitimes_records'] = len(records)
            add('EMITIMES parse', len(records) > 0, f"{len(records)} records")

            if records and sim_start is not None and sim_end is not None:
                overlap = False
                for x in records:
                    t1 = x.time
                    t2 = x.time + timedelta(hours=_duration_hours(x.duration))
                    if t2 >= sim_start and t1 <= sim_end:
                        overlap = True
                        break
                add('EMITIMES time', overlap, f"simulation {sim_start:%Y%m%d%H}-{sim_end:%Y%m%d%H}")
        except Exception as exc:
            add('EMITIMES parse', False, str(exc))

    if cc is not None:
        loc = list(cc.get('starting_locations', []))
        if records:
            add(
                'source count',
                len(loc) == len(records),
                f"CONTROL={len(loc)} EMITIMES={len(records)}",
            )
        else:
            add('source count', len(loc) > 0, f"CONTROL={len(loc)}")

        # Meteorology: validate the exact files listed in CONTROL.
        met = [str(Path(x).expanduser()) for x in cc.get('meteorological_data', [])]
        report['met_files'] = met
        add('ARL file count', len(met) > 0, str(len(met)))

        all_valid = bool(met)
        if met:
            if verbose:
                print('\nARL FILES:')
            for filename in met:
                info = hysp_arl_info(filename)
                ok = bool(info.get('valid'))
                all_valid &= ok
                st = info.get('stime')
                et = info.get('etime')
                if ok and st and et:
                    detail = (
                        f"{st:%Y%m%d%H}-{et:%Y%m%d%H} "
                        f"dt={info.get('hourly', 0)}h "
                        f"grid={info.get('nx')}x{info.get('ny')}x{info.get('nz')}"
                    )
                else:
                    errs = '; '.join(info.get('errors', [])) or 'invalid ARL file'
                    detail = errs
                _print_item(ok, 'ARL', f"{filename}  {detail}", verbose=verbose)

            add('ARL integrity', all_valid, f"{len(met)} files checked")

            if sim_start is not None and sim_end is not None:
                try:
                    cov = hysp_arl_chk(
                        met,
                        time=[sim_start, sim_end],
                        ini=ini,
                        verbose=False,
                    )
                except Exception as exc:
                    cov = False
                    add('ARL coverage', False, str(exc))
                else:
                    add(
                        'ARL coverage',
                        bool(cov),
                        f"{sim_start:%Y%m%d%H} - {sim_end:%Y%m%d%H}",
                    )

    # Executables.  Manual checker defaults to mode=any; nsfs_run passes the
    # exact mode it intends to execute.
    serial = run_dir / 'hycs_std'
    mpi = run_dir / 'hycm_std'
    serial_ok = _is_executable(serial)
    mpi_ok = _is_executable(mpi)
    _print_item(serial_ok, 'hycs_std', str(serial), verbose=verbose)
    _print_item(mpi_ok, 'hycm_std', str(mpi), verbose=verbose)

    if mode == 'serial':
        add('executable', serial_ok, 'serial')
    elif mode == 'mpi':
        add('executable', mpi_ok, 'MPI')
        try:
            opt = hysp_init(ini)
            mpi_path = str(opt.get('MPI_PATH', '')).strip()
            found = Path(mpi_path).is_file() if mpi_path else bool(shutil.which('mpirun'))
            add('mpirun', found, mpi_path or str(shutil.which('mpirun') or 'not found'))
        except Exception as exc:
            add('mpirun', False, str(exc))
    else:
        add('executable', serial_ok or mpi_ok, 'at least one of hycs_std/hycm_std')

    if verbose:
        print('\nSTATUS:', 'READY' if report['ok'] else 'NOT READY')

    return report


def nsfs_chk(
    rdir: str | os.PathLike[str] | Sequence[str | os.PathLike[str]],
    *,
    mode: str = 'any',
    ini: str | os.PathLike[str] = 'hysp.ini',
    verbose: bool = True,
) -> bool:
    """Return True only when every supplied run directory is ready."""
    if isinstance(rdir, (str, os.PathLike)):
        dirs = [rdir]
    else:
        dirs = list(rdir)

    ok = True
    for i, item in enumerate(dirs):
        if i and verbose:
            print()
        report = nsfs_chk1(item, mode=mode, ini=ini, verbose=verbose)
        ok = bool(report['ok']) and ok
    return ok


def main() -> None:
    p = argparse.ArgumentParser(description='Validate prepared NSFS/HYSPLIT run directories.')
    p.add_argument('rdir', nargs='+', help='prepared run directory/directories')
    p.add_argument('--mode', choices=('any', 'serial', 'mpi'), default='any')
    p.add_argument('--ini', default='hysp.ini')
    p.add_argument('-q', '--quiet', action='store_true')
    args = p.parse_args()

    try:
        ok = nsfs_chk(args.rdir, mode=args.mode, ini=args.ini, verbose=not args.quiet)
    except Exception as exc:
        if not args.quiet:
            print(f'[BAD] {exc}')
        raise SystemExit(2)

    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    main()
