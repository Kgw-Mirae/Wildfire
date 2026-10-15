#!/usr/bin/env python3
"""
nsfs_run.py

Execute a prepared NSFS/HYSPLIT run directory.

This module never prepares CONTROL, EMITIMES, meteorology, or links.  It first
runs nsfs_chk on the already-prepared directory and refuses to start HYSPLIT
unless the selected execution mode is READY.

Typical workflow
----------------
    python -m fire.nsfs_prep 20261005 --name NSFS --arl gfs0p25 \
        --emis rave3 --domain nca12

    python -m fire.nsfs_chk \
        hysp.run/NSFS/gfs0p25-rave3/2026/20261005

    python -m fire.nsfs_run \
        hysp.run/NSFS/gfs0p25-rave3/2026/20261005
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence

from hysp.hysp_init import hysp_init
from .nsfs_chk import nsfs_chk1


def _is_executable(path: Path) -> bool:
    return path.exists() and path.is_file() and os.access(path, os.X_OK)


def _mpi_program(opt: dict[str, Any]) -> str | None:
    p = str(opt.get('MPI_PATH', '')).strip()
    if p and Path(p).is_file():
        return p
    return shutil.which('mpirun')


def _choose_mode(run_dir: Path, requested: str, opt: dict[str, Any]) -> str:
    requested = requested.lower()
    if requested in {'serial', 'mpi'}:
        return requested
    if requested != 'auto':
        raise ValueError("mode must be 'auto', 'serial', or 'mpi'")

    mpi_ok = _is_executable(run_dir / 'hycm_std') and bool(_mpi_program(opt))
    serial_ok = _is_executable(run_dir / 'hycs_std')

    if int(opt.get('MPI_USE', 0)) and mpi_ok:
        return 'mpi'
    if serial_ok:
        return 'serial'
    if mpi_ok:
        return 'mpi'
    raise FileNotFoundError('Neither a runnable hycs_std nor hycm_std is available')


def nsfs_run1(
    rdir: str | os.PathLike[str],
    *,
    mode: str = 'auto',
    cpu: int | None = None,
    ini: str | os.PathLike[str] = 'hysp.ini',
    logfile: str = 'log',
    renew: bool = False,
    dry_run: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    """Validate and execute one prepared HYSPLIT run directory."""
    run_dir = Path(rdir).expanduser().resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f'Run directory does not exist: {run_dir}')

    opt = hysp_init(ini)
    selected = _choose_mode(run_dir, mode, opt)

    # Final check immediately before execution.  This is deliberate even when
    # the user already called nsfs_chk manually.
    report = nsfs_chk1(run_dir, mode=selected, ini=ini, verbose=verbose)
    if not report['ok']:
        raise RuntimeError(f'NSFS run is NOT READY: {run_dir}')

    if selected == 'serial':
        cmd = [str(run_dir / 'hycs_std')]
    else:
        mpirun = _mpi_program(opt)
        if not mpirun:
            raise FileNotFoundError('mpirun not found')
        ncpu = int(cpu if cpu is not None else opt.get('MPI_CPU', 16))
        if ncpu < 1:
            raise ValueError('MPI cpu count must be >= 1')
        cmd = [mpirun, '-np', str(ncpu), str(run_dir / 'hycm_std')]

    log = run_dir / logfile
    if log.exists() and not renew and not dry_run:
        raise FileExistsError(
            f'Log already exists: {log}. Use --renew only when you intend to rerun.'
        )

    if verbose:
        print(f"MODE    : {selected}")
        print('COMMAND :', ' '.join(shlex.quote(x) for x in cmd))
        print(f"RDIR    : {run_dir}")
        print(f"LOG     : {log}")

    result: dict[str, Any] = {
        'rdir': str(run_dir),
        'mode': selected,
        'command': cmd,
        'log': str(log),
        'returncode': None,
        'dry_run': bool(dry_run),
    }

    if dry_run:
        if verbose:
            print('DRY RUN : HYSPLIT was not started')
        return result

    with log.open('w', encoding='utf-8') as f:
        proc = subprocess.run(
            cmd,
            cwd=run_dir,
            stdout=f,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
        )

    result['returncode'] = int(proc.returncode)
    if verbose:
        print(f"RETURN  : {proc.returncode}")
        print('STATUS  :', 'DONE' if proc.returncode == 0 else 'FAILED')

    if proc.returncode != 0:
        raise RuntimeError(f'HYSPLIT failed with return code {proc.returncode}; see {log}')

    return result


def nsfs_run(
    rdir: str | os.PathLike[str] | Sequence[str | os.PathLike[str]],
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Execute one or more prepared run directories sequentially."""
    dirs = [rdir] if isinstance(rdir, (str, os.PathLike)) else list(rdir)
    return [nsfs_run1(x, **kwargs) for x in dirs]


def main() -> None:
    p = argparse.ArgumentParser(description='Validate then execute prepared NSFS/HYSPLIT runs.')
    p.add_argument('rdir', nargs='+', help='prepared run directory/directories')
    p.add_argument('--mode', choices=('auto', 'serial', 'mpi'), default='auto')
    p.add_argument('--cpu', type=int, default=None, help='MPI process count; default MPI_CPU in hysp.ini')
    p.add_argument('--ini', default='hysp.ini')
    p.add_argument('--log', default='log')
    p.add_argument('--renew', action='store_true', help='allow overwrite of an existing log')
    p.add_argument('--dry-run', action='store_true', help='check and show command but do not start HYSPLIT')
    p.add_argument('-q', '--quiet', action='store_true')
    args = p.parse_args()

    try:
        nsfs_run(
            args.rdir,
            mode=args.mode,
            cpu=args.cpu,
            ini=args.ini,
            logfile=args.log,
            renew=args.renew,
            dry_run=args.dry_run,
            verbose=not args.quiet,
        )
    except Exception as exc:
        if not args.quiet:
            print(f'ERROR: {exc}')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
