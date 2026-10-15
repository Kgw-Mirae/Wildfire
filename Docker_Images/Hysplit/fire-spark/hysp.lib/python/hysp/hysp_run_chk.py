#!/usr/bin/env python3
"""
NAME
    hysp_run_chk.py

PURPOSE
    Inspect a HYSPLIT trajectory or dispersion simulation while it runs,
    without modifying HYSPLIT files. Supports serial MESSAGE and MPI
    MESSAGE.001, MESSAGE.002, ... files. Read computational-hour progress and
    diagnostics for each rank, planned duration from CONTROL, and whether the
    model process is active in the corresponding run directory.

USAGE
    python hysp_run_chk.py /path/to/hysplit/run
    python hysp_run_chk.py /path/to/run/MESSAGE --watch 10
    python hysp_run_chk.py /path/to/mpi/run --watch 10
    python hysp_run_chk.py /path/to/mpi/run/MESSAGE.006
    python hysp_run_chk.py /path/to/run --json

    from hysp.hysp_run_chk import hysp_run_chk
    report = hysp_run_chk('/path/to/run')

VERSION
    20261012-001

AUTHOR
    2026-10-12 Hyun Cheol Kim (hyun.kim@noaa.gov)

DEPENDENCIES
    Python 3.9 or newer, standard library only. Local process identification
    uses /proc on Linux or psutil when installed on another platform.

NOTES
    * NOTICE main: HOUR ... is a computational-hour indicator, not a verified
      completion count. Percentages are APPROXIMATE.
    * For MPI, rank progress may differ. Report the slowest rank with a known
      computational hour and the complete range; unreported ranks stay unknown.
      Rank MESSAGE files are independent and their timestamps can differ.
    * An unnumbered MESSAGE is not used as MPI progress if numbered files exist.
      A single rank reaching the final hour does NOT imply MPI completion.
    * cdump output can exist while the model is still running.
    * A process must match both the HYSPLIT executable name and run directory.
      Process state is UNKNOWN if the local process table is inaccessible.
    * MESSAGE alone cannot prove a successful process exit. Without an explicit
      success marker, a completed controller record, or a known return code,
      a full-duration inactive run is FINISHED_UNVERIFIED.
    * No files are written or changed.
"""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

VERSION = "20261012-001"

_MAIN_RE = re.compile(r"^\s*NOTICE\s+main\s*:\s*(?:HOUR\s*[:=]?\s*)?([+-]?\d+)(?=\s|$)", re.I)
_ISSUE_RE = re.compile(r"^\s*(FATAL|ERROR|WARNING|SEVERE)\b\s*[:\s]", re.I)
_FINISH_RE = re.compile(
    r"^\s*(?:Complete\s+Hysplit|(?:HYSPLIT\s+)?(?:simulation|calculation|model)\s+"
    r"(?:completed\s+successfully|complete|finished))\b", re.I
)
_MODEL_RE = re.compile(r"^hy(?:cs|cm|ts|tm)[\w.-]*$", re.I)
_LAUNCHER_RE = re.compile(r"^(?:mpirun|mpiexec|srun|prterun|orterun)$", re.I)
_STATUS_FILENAME = "spark_daily.status.json"


def _utc_iso(t: float | None) -> str | None:
    if t is None:
        return None
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def _elapsed(t: float | None) -> str:
    if t is None:
        return "unknown"
    seconds = max(0, int(time.time() - t))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


def _lines(path: Path) -> list[str]:
    """Keep nonempty CONTROL records, honoring HYSPLIT-style comments."""
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return [clean for raw in f if (clean := raw.split("#", 1)[0].strip())]


def read_control(path: Path) -> dict[str, Any]:
    """Parse only start, source count, and duration; works for conc/traj CONTROL."""
    if not path.is_file():
        return {"start_utc": None, "duration_hours": None, "error": "CONTROL missing"}
    try:
        records = _lines(path)
        first = [int(x) for x in records[0].split()[:5]]
        if len(first) < 4:
            raise ValueError("CONTROL start has fewer than 4 fields")
        year, month, day, hour = first[:4]
        if year < 100:
            year += 1900 if year > 40 else 2000
        start = datetime(year, month, day, hour,
                         first[4] if len(first) >= 5 else 0, tzinfo=timezone.utc)
        count = int(records[1].split()[0])
        if not 0 <= count <= 1_000_000:
            raise ValueError(f"invalid start-location count {count}")
        duration = int(float(records[2 + count].split()[0]))
        if duration == 0:
            raise ValueError("CONTROL duration is zero")
        return {"start_utc": start.isoformat(timespec="minutes"),
                "duration_hours": duration, "error": None}
    except (OSError, ValueError, IndexError) as exc:
        return {"start_utc": None, "duration_hours": None,
                "error": f"Cannot parse CONTROL: {exc}"}


class MessageMonitor:
    """Incrementally scan a growing MESSAGE without rereading earlier contents."""

    def __init__(self, path: Path, *, retain: int = 8) -> None:
        self.path = path
        self.retain = max(1, int(retain))
        self.reset()

    def reset(self) -> None:
        self.identity: tuple[int, int] | None = None
        self.offset = 0
        self.pending = b""
        self.computational_hour: int | None = None
        self.warning_count = 0
        self.error_count = 0
        self.warnings: deque[str] = deque(maxlen=self.retain)
        self.errors: deque[str] = deque(maxlen=self.retain)
        self.latest_lines: deque[str] = deque(maxlen=self.retain)
        self.last_progress_line: str | None = None
        self.complete_marker = False
        self.lines_scanned = 0

    def _scan_line(self, raw: bytes) -> None:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line.strip():
            return
        self.lines_scanned += 1
        self.latest_lines.append(line.strip())
        main = _MAIN_RE.match(line)
        if main:
            value = int(main.group(1))
            self.computational_hour = value
            self.last_progress_line = line.strip()
        issue = _ISSUE_RE.match(line)
        if issue:
            if issue.group(1).upper() == "WARNING":
                self.warning_count += 1
                self.warnings.append(line.strip())
            else:
                self.error_count += 1
                self.errors.append(line.strip())
        if _FINISH_RE.match(line):
            self.complete_marker = True

    def update(self) -> dict[str, Any]:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            self.reset()
            return {"exists": False, "size": 0, "mtime_utc": None,
                    "modified_seconds_ago": None}
        new_id = (st.st_dev, st.st_ino)
        if self.identity != new_id or st.st_size < self.offset:
            self.reset()
            self.identity = new_id
        # Read binary chunks; MESSAGE may be appended to while we are reading.
        with self.path.open("rb") as src:
            src.seek(self.offset)
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                self.offset += len(chunk)
                data = self.pending + chunk
                *full, self.pending = data.split(b"\n")
                for line in full:
                    self._scan_line(line)
        return {"exists": True, "size": st.st_size,
                "mtime_utc": _utc_iso(st.st_mtime),
                "modified_seconds_ago": round(max(0.0, time.time() - st.st_mtime), 1)}


class MessageCollectionMonitor:
    """Track all rank MESSAGE files, retaining scan offsets between checks.

    For a run directory, MESSAGE.NNN files are discovered automatically. An
    explicitly supplied MESSAGE.NNN path instead inspects only that rank.
    Each rank has its own incremental MessageMonitor, so --watch does not
    repeatedly scan multi-megabyte MPI messages.
    """

    def __init__(
        self,
        run_dir: Path,
        message: str = "MESSAGE",
        *,
        explicit_file: bool = False,
        retain: int = 8,
        initial_monitor: MessageMonitor | None = None,
    ) -> None:
        self.run_dir = Path(run_dir).expanduser().resolve()
        self.message = message
        self.explicit_file = explicit_file or bool(re.search(r"\.\d+$", message))
        self.retain = max(1, int(retain))
        self.monitors: dict[str, MessageMonitor] = {}
        if initial_monitor is not None:
            if initial_monitor.path.resolve() != (self.run_dir / message).resolve():
                raise ValueError("Monitor MESSAGE path does not match target")
            self.monitors[message] = initial_monitor

    def _discover(self) -> tuple[str, list[Path], list[Path]]:
        base = self.run_dir / self.message
        if self.explicit_file:
            mode = "mpi_rank" if re.search(r"\.\d+$", self.message) else "serial"
            return mode, [base], [base] if mode == "mpi_rank" else []

        matcher = re.compile(rf"{re.escape(self.message)}\.(\d+)$")
        numbered: list[tuple[int, Path]] = []
        for file in self.run_dir.iterdir():
            match = matcher.fullmatch(file.name)
            if match and file.is_file():
                numbered.append((int(match.group(1)), file))
        numbered.sort(key=lambda item: (item[0], item[1].name))
        ranks = [path for _, path in numbered]
        if ranks:
            # Also inspect an unnumbered MESSAGE for diagnostics, if present.
            files = ([base] if base.is_file() else []) + ranks
            return "mpi", files, ranks
        return "serial", [base], []

    def update(self) -> dict[str, Any]:
        mode, paths, rank_paths = self._discover()
        active_names = {path.name for path in paths}
        for name in list(self.monitors):
            if name not in active_names:
                del self.monitors[name]

        entries: list[dict[str, Any]] = []
        warnings: list[tuple[float, str]] = []
        errors: list[tuple[float, str]] = []
        for path in paths:
            mon = self.monitors.setdefault(path.name, MessageMonitor(path, retain=self.retain))
            info = mon.update()
            rank_match = re.search(r"\.(\d+)$", path.name)
            rank = int(rank_match.group(1)) if rank_match else None
            row = {
                "path": str(path), "name": path.name, "rank": rank,
                **info,
                "computational_hour": mon.computational_hour,
                "last_notice": mon.last_progress_line,
                "warnings": mon.warning_count,
                "errors": mon.error_count,
                "complete_marker": mon.complete_marker,
                "lines_scanned": mon.lines_scanned,
            }
            entries.append(row)
            # Cross-rank ordering is only approximate (file mtime). Retain
            # filenames so that each diagnostic can be found by an operator.
            age = info["modified_seconds_ago"]
            sort_key = -float(age) if age is not None else float("-inf")
            prefix = f"{path.name}: " if mode != "serial" else ""
            warnings.extend((sort_key, prefix + line) for line in mon.warnings)
            errors.extend((sort_key, prefix + line) for line in mon.errors)

        existing = [row for row in entries if row["exists"]]
        newest = min(existing, key=lambda r: r["modified_seconds_ago"], default=None)
        progress_rows = ([row for row in entries if row["rank"] is not None]
                         if mode != "serial" else entries)
        known_progress = [row for row in progress_rows if row["computational_hour"] is not None]
        # Do not overstate a parallel run's progress by selecting the fastest
        # MPI rank. Rank files without an HOUR entry stay explicitly unknown.
        slowest = min(known_progress, key=lambda r: abs(r["computational_hour"]), default=None)
        fastest = max(known_progress, key=lambda r: abs(r["computational_hour"]), default=None)

        message = {
            "path": str((self.run_dir / self.message) if mode == "serial"
                        else (entries[0]["path"] if entries else self.run_dir / self.message)),
            "exists": bool(existing),
            "size": sum(row["size"] for row in existing),
            "mtime_utc": newest["mtime_utc"] if newest else None,
            "modified_seconds_ago": newest["modified_seconds_ago"] if newest else None,
            "mode": mode,
            "file_count": len(existing),
            "rank_file_count": len(rank_paths),
            "files": entries,
        }
        return {
            "message": message,
            "computational_hour": slowest["computational_hour"] if slowest else None,
            "last_progress_line": slowest["last_notice"] if slowest else None,
            "progress_min_hour": slowest["computational_hour"] if slowest else None,
            "progress_max_hour": fastest["computational_hour"] if fastest else None,
            "slowest_rank": slowest["name"] if slowest else None,
            "fastest_rank": fastest["name"] if fastest else None,
            "ranks_reporting": len(known_progress),
            "ranks_total": len(progress_rows) if mode != "serial" else 0,
            "rank_hours": {row["name"]: row["computational_hour"]
                           for row in progress_rows} if mode != "serial" else {},
            "warnings": sum(row["warnings"] for row in entries),
            "errors": sum(row["errors"] for row in entries),
            "recent_warnings": [item[1] for item in sorted(warnings)],
            "recent_errors": [item[1] for item in sorted(errors)],
            "complete_marker": bool(existing) and all(row["complete_marker"] for row in existing),
        }


def _process_name(comm: str) -> bool:
    return bool(_MODEL_RE.fullmatch(comm) or _LAUNCHER_RE.fullmatch(comm))


def _linux_processes(run_dir: Path) -> tuple[bool, list[dict[str, Any]]]:
    proc = Path("/proc")
    if not proc.is_dir():
        return False, []
    matches: list[dict[str, Any]] = []
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            cwd = (entry / "cwd").resolve(strict=True)
            if cwd != run_dir:
                continue
            comm = (entry / "comm").read_text(encoding="utf-8").strip()
            if not _process_name(comm):
                continue
            # Zombie processes are no longer executing the model.
            state = (entry / "stat").read_text(encoding="utf-8").split(") ", 1)[1].split()[0]
            if state == "Z":
                continue
            matches.append({"pid": int(entry.name), "name": comm})
        except (OSError, IndexError, UnicodeError, ValueError):
            continue  # A process exited, or is not visible to this user.
    return True, sorted(matches, key=lambda x: x["pid"])


def _psutil_processes(run_dir: Path) -> tuple[bool, list[dict[str, Any]]]:
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return False, []
    found: list[dict[str, Any]] = []
    for process in psutil.process_iter(attrs=["name"]):
        try:
            name = process.info.get("name") or ""
            if _process_name(name) and Path(process.cwd()).resolve() == run_dir:
                if process.status() != psutil.STATUS_ZOMBIE:
                    found.append({"pid": int(process.pid), "name": name})
        except (psutil.Error, OSError):
            continue
    return True, sorted(found, key=lambda x: x["pid"])


def find_processes(run_dir: Path) -> tuple[bool, list[dict[str, Any]]]:
    """Find model/MPI processes whose current directory is THIS run directory."""
    supported, found = _linux_processes(run_dir)
    if supported:
        return supported, found
    return _psutil_processes(run_dir)


def _load_spark_status(run_dir: Path) -> dict[str, Any]:
    """Optional supplementary evidence; never required for a generic HYSPLIT run."""
    path = run_dir / _STATUS_FILENAME
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    except (OSError, ValueError):
        pass
    return {}


def _file_info(path: Path) -> dict[str, Any]:
    try:
        st = path.stat()
    except FileNotFoundError:
        return {"path": str(path), "exists": False, "bytes": 0, "mtime_utc": None}
    return {"path": str(path), "exists": True, "bytes": st.st_size,
            "mtime_utc": _utc_iso(st.st_mtime)}


def _output_files(run_dir: Path, explicit: str | None) -> list[Path]:
    """Discover existing concentration/trajectory dumps without interpreting them."""
    if explicit is not None:
        return [run_dir / explicit]
    outputs = []
    for path in run_dir.iterdir():
        name = path.name.lower()
        if (name.startswith("cdump") or name.startswith("tdump")) and path.is_file():
            if ".previous." not in name and not name.endswith((".bak", ".old", ".tmp")):
                outputs.append(path)
    return sorted(outputs, key=lambda p: p.name)


def _resolve_target(target: str | os.PathLike[str], message_name: str) -> tuple[Path, Path]:
    path = Path(target).expanduser().resolve()
    if path.is_dir():
        return path, path / message_name
    if path.name.upper().startswith("MESSAGE") or path.name == message_name:
        return path.parent, path
    # A specific custom-named MESSAGE file can also be supplied directly.
    if path.is_file() and path.name not in {"CONTROL", "SETUP.CFG", "ASCDATA.CFG"}:
        return path.parent, path
    raise FileNotFoundError(f"Expected a HYSPLIT run directory or MESSAGE file: {path}")


def hysp_run_chk(
    target: str | os.PathLike[str] = ".",
    *,
    message: str = "MESSAGE",
    control: str = "CONTROL",
    cdump: str | None = None,
    process_check: bool = True,
    stale_minutes: float = 30.0,
    monitor: MessageMonitor | MessageCollectionMonitor | None = None,
    max_diagnostics: int = 5,
) -> dict[str, Any]:
    """Return a read-only, JSON-compatible HYSPLIT runtime-status report.

    ``target`` may be a run directory or a MESSAGE file.  No HYSP, NSFS,
    SPARK, or HYSPLIT Python libraries are required.
    """
    run_dir, message_file = _resolve_target(target, message)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    explicit_file = not Path(target).expanduser().resolve().is_dir()
    if isinstance(monitor, MessageCollectionMonitor):
        if (monitor.run_dir != run_dir or monitor.message != message_file.name
                or monitor.explicit_file != (explicit_file or bool(re.search(r"\.\d+$", message_file.name)))):
            raise ValueError("MESSAGE collection monitor does not match target")
        collection = monitor
    else:
        collection = MessageCollectionMonitor(
            run_dir, message_file.name, explicit_file=explicit_file,
            retain=max(8, max_diagnostics), initial_monitor=monitor,
        )
    snapshot = collection.update()
    msg_info = snapshot["message"]
    ctrl = read_control(run_dir / control)

    process_known, processes = find_processes(run_dir) if process_check else (False, [])
    running = bool(processes) if process_known else None
    controller = _load_spark_status(run_dir)
    ctl_status = str(controller.get("status", "")).lower()
    hour = snapshot["computational_hour"]
    total = ctrl["duration_hours"]
    percentage = None
    if total and hour is not None:
        percentage = round(min(100.0, 100.0 * abs(hour) / abs(total)), 1)
    if (msg_info["mode"] == "mpi" and
            snapshot["ranks_reporting"] < snapshot["ranks_total"]):
        # Unknown ranks may be behind the slowest rank we can see. Report
        # that hour but withhold a global percentage until all ranks report.
        percentage = None
    all_at_end = bool(
        total and snapshot["ranks_total"] and
        snapshot["ranks_reporting"] == snapshot["ranks_total"] and
        all(value is not None and abs(value) >= abs(total)
            for value in snapshot["rank_hours"].values())
    )
    # A single explicitly selected MPI rank cannot establish global completion.
    full_progress = (all_at_end if msg_info["mode"] == "mpi"
                     else (bool(hour is not None and total and abs(hour) >= abs(total))
                           if msg_info["mode"] == "serial" else False))

    # Priority: active model, explicit failure, verified completion, diagnostic
    # evidence.  An incomplete message with no local process is NOT completed.
    if snapshot["errors"] and not running and process_known:
        status = "ERROR_REPORTED"
    elif running:
        status = "RUNNING_WITH_ERRORS" if snapshot["errors"] else "RUNNING"
    elif ctl_status == "failed":
        status = "FAILED"
    elif ctl_status == "completed" and not running:
        status = "COMPLETED"
    elif snapshot["complete_marker"] and process_known and not running and msg_info["mode"] != "mpi_rank":
        status = "COMPLETED"
    elif process_known and snapshot["errors"]:
        status = "ERROR_REPORTED"
    elif process_known and full_progress:
        status = "FINISHED_UNVERIFIED"
    elif process_known and any(row["lines_scanned"] for row in msg_info["files"]):
        status = "INACTIVE"
    elif process_known:
        status = "PREPARED" if (run_dir / control).is_file() else "NOT_STARTED"
    else:
        status = "UNKNOWN"

    if running and not msg_info["exists"]:
        status = "STARTING"

    stale = bool(
        running and msg_info["modified_seconds_ago"] is not None
        and msg_info["modified_seconds_ago"] >= 60.0 * stale_minutes
    )
    stale_rank_messages = [
        row["name"] for row in msg_info["files"]
        if row["rank"] is not None and row["exists"]
        and row["modified_seconds_ago"] is not None
        and row["modified_seconds_ago"] >= 60.0 * stale_minutes
    ] if running else []
    outputs = [_file_info(p) for p in _output_files(run_dir, cdump)]
    output = max(outputs, key=lambda x: x["bytes"], default=None)
    report: dict[str, Any] = {
        "run_directory": str(run_dir),
        "status": status,
        "process_check_available": process_known,
        "process_active": running,
        "processes": processes,
        "control": {"path": str(run_dir / control), **ctrl},
        "message": {"path": str(message_file), **msg_info},
        "progress": {
            "computational_hour": hour, "duration_hours": total,
            "percent_approx": percentage,
            "last_notice": snapshot["last_progress_line"],
            "min_hour": snapshot["progress_min_hour"],
            "max_hour": snapshot["progress_max_hour"],
            "slowest_rank": snapshot["slowest_rank"],
            "fastest_rank": snapshot["fastest_rank"],
            "ranks_reporting": snapshot["ranks_reporting"],
            "ranks_total": snapshot["ranks_total"],
            "rank_hours": snapshot["rank_hours"],
            "all_ranks_at_end": all_at_end,
        },
        "diagnostics": {
            "warnings": snapshot["warnings"], "errors": snapshot["errors"],
            "recent_warnings": snapshot["recent_warnings"][-max_diagnostics:] if max_diagnostics else [],
            "recent_errors": snapshot["recent_errors"][-max_diagnostics:] if max_diagnostics else [],
            "per_file": [
                {"name": row["name"], "rank": row["rank"],
                 "warnings": row["warnings"], "errors": row["errors"]}
                for row in msg_info["files"]
            ],
        },
        "output": output,
        "outputs": outputs,
        "controller_status": ctl_status or None,
        "stale_message": stale,
        "stale_rank_messages": stale_rank_messages,
        "checked_utc": _utc_iso(time.time()),
    }
    return report


def _short_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024.0 or unit == "TiB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TiB"


def format_report(report: dict[str, Any], *, max_diagnostics: int = 5) -> str:
    """Plain-text readable summary."""
    ctrl = report["control"]
    p = report["progress"]
    msg = report["message"]
    d = report["diagnostics"]
    parts = [f"HYSPLIT RUN : {report['run_directory']}",
             f"STATUS      : {report['status']}"]
    if report["process_check_available"]:
        processes = report["processes"]
        if len(processes) > 8:
            by_name: dict[str, int] = {}
            for item in processes:
                by_name[item["name"]] = by_name.get(item["name"], 0) + 1
            names = ", ".join(f"{name} x{count}" for name, count in sorted(by_name.items()))
            names += f" ({len(processes)} processes)"
        else:
            names = ", ".join(f"{x['name']}({x['pid']})" for x in processes)
        parts.append(f"PROCESS     : {names or 'none active in this directory'}")
    else:
        parts.append("PROCESS     : unknown (process inspection unavailable)")
    if ctrl["duration_hours"] is not None:
        parts.append(f"SIMULATION  : {ctrl['start_utc']} / {ctrl['duration_hours']:+d} h")
    else:
        parts.append(f"CONTROL     : {ctrl['error']}")
    hour = p["computational_hour"]
    if hour is not None:
        if p["percent_approx"] is None:
            if msg["mode"] == "mpi" and p["ranks_reporting"] < p["ranks_total"]:
                parts.append(f"PROGRESS    : slowest reported hour {hour} / {p['duration_hours']} "
                             "(partial rank data; whole-run % unavailable)")
            else:
                parts.append(f"PROGRESS    : computational hour {hour} (no duration available)")
        else:
            parts.append(f"PROGRESS    : hour {hour} / {p['duration_hours']} "
                         f"(approx. {p['percent_approx']:.1f}%)")
    else:
        parts.append("PROGRESS    : no NOTICE main: hour entry yet")
    if msg["mode"] != "serial":
        parts.append(f"MPI LOGS    : {msg['rank_file_count']} numbered MESSAGE files"
                     + (" (single rank selected)" if msg["mode"] == "mpi_rank" else ""))
        n = p["ranks_reporting"]
        total = p["ranks_total"]
        if hour is not None:
            parts.append(f"MPI HOURS   : slowest reported {p['min_hour']}, "
                         f"fastest {p['max_hour']}; {n}/{total} ranks reporting")
            parts.append(f"MPI SLOWEST : {p['slowest_rank']}")
        else:
            parts.append(f"MPI HOURS   : 0/{total} ranks reporting computational hours")
        # A compact list makes individual lagging MPI ranks easy to identify.
        hours = [f"{name.rsplit('.', 1)[-1]}={value if value is not None else '?'}"
                 for name, value in p["rank_hours"].items()]
        for idx in range(0, len(hours), 8):
            label = "MPI RANKS   : " if idx == 0 else "              "
            parts.append(label + " ".join(hours[idx:idx + 8]))
        if n < total:
            missing = [name for name, value in p["rank_hours"].items() if value is None]
            parts.append("MPI UNKNOWN : " + ", ".join(missing))
        parts.append("MPI NOTE    : progress is approximate; one rank reaching the final hour is not completion")
    if msg["exists"]:
        modified = msg["modified_seconds_ago"]
        age = f"{modified:.0f}s ago" if modified is not None else "unknown"
        if msg["mode"] != "serial":
            parts.append(f"MESSAGE     : {msg['file_count']} files, total {_short_bytes(msg['size'])}, "
                         f"newest updated {age}")
        else:
            parts.append(f"MESSAGE     : {_short_bytes(msg['size'])}, updated {age}")
    else:
        parts.append("MESSAGE     : missing")
    if report["stale_message"]:
        parts.append("ATTENTION   : model process active, but MESSAGE has not changed recently")
    if msg["mode"] != "serial" and report.get("stale_rank_messages"):
        count = len(report["stale_rank_messages"])
        parts.append(f"RANK AGES   : {count}/{msg['rank_file_count']} MESSAGE ranks unchanged "
                     "beyond stale threshold (may be idle)")
    for out in report["outputs"]:
        parts.append(f"OUTPUT      : {Path(out['path']).name} "
                     f"({_short_bytes(out['bytes']) if out['exists'] else 'not present'})")
    parts.append(f"DIAGNOSTICS : {d['warnings']} warning(s), {d['errors']} error(s)")
    for line in d["recent_errors"][-max_diagnostics:]:
        parts.append(f"  ERROR     : {line}")
    for line in d["recent_warnings"][-max_diagnostics:]:
        parts.append(f"  WARNING   : {line}")
    if report["status"] in {"INACTIVE", "FINISHED_UNVERIFIED", "UNKNOWN"}:
        parts.append("NOTE        : MESSAGE alone cannot confirm a successful model exit")
    return "\n".join(parts)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Read-only HYSPLIT progress and health check from MESSAGE/CONTROL")
    p.add_argument("run", nargs="?", default=".",
                   help="HYSPLIT run directory or MESSAGE filename; default: .")
    p.add_argument("--watch", nargs="?", type=float, const=10.0, metavar="SECONDS",
                   help="repeat check until Ctrl+C; default repeat interval 10 seconds")
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p.add_argument("--message", default="MESSAGE", help="MESSAGE filename in run directory")
    p.add_argument("--control", default="CONTROL", help="CONTROL filename in run directory")
    p.add_argument("--cdump", default=None,
                   help="specific output name; default automatically discovers cdump*/tdump*")
    p.add_argument("--no-process-check", action="store_true",
                   help="skip OS process inspection (e.g., inspecting another host's files)")
    p.add_argument("--stale-minutes", type=float, default=30.0,
                   help="flag slow MESSAGE updates while a process is active")
    p.add_argument("--last", type=int, default=5, help="number of recent warnings/errors shown")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.watch is not None and args.watch <= 0:
        print("ERROR: --watch interval must be positive", file=sys.stderr)
        return 2
    if args.stale_minutes < 0 or args.last < 0:
        print("ERROR: --stale-minutes and --last must be nonnegative", file=sys.stderr)
        return 2
    try:
        rd, message_file = _resolve_target(args.run, args.message)
        explicit_file = not Path(args.run).expanduser().resolve().is_dir()
        monitor = MessageCollectionMonitor(
            rd, message_file.name, explicit_file=explicit_file,
            retain=max(8, args.last),
        )
        while True:
            result = hysp_run_chk(args.run, message=message_file.name,
                                  control=args.control, cdump=args.cdump,
                                  process_check=not args.no_process_check,
                                  stale_minutes=args.stale_minutes,
                                  monitor=monitor, max_diagnostics=args.last)
            if args.json:
                print(json.dumps(result, indent=2, sort_keys=True), flush=True)
            else:
                if args.watch is not None:
                    print(f"\n===== {_utc_iso(time.time())} =====")
                print(format_report(result, max_diagnostics=args.last), flush=True)
            if args.watch is None:
                return 0
            time.sleep(args.watch)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
