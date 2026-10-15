"""Bootstrap a writable, job-specific SPARK root and exec one controller.

This is a CLI adapter, not an API job orchestrator or a completion validator.
Existing configuration files are preserved between prepare/check/run/product.
"""
import json
import os
from pathlib import Path
import shutil
import sys


def bootstrap(root: Path, app: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    templates = root / "hysp.in"
    if not templates.exists():
        shutil.copytree(app / "hysp.in", templates)
    for directory in ("hysp.data", "hysp.run", "hysp.out"):
        (root / directory).mkdir(exist_ok=True)

    shared = root / "hysp.ini"
    if not shared.exists():
        cpu = int(os.environ.get("MPI_NP", "6"))
        if cpu < 1:
            raise ValueError("MPI_NP must be positive")
        mode = os.environ.get("SPARK_CPU_MODE", "serial")
        if mode not in {"serial", "mpi", "auto"}:
            raise ValueError("SPARK_CPU_MODE must be serial, mpi or auto")
        shared.write_text(json.dumps({
            "HYSPLIT_PATH": "/opt/hysplit",
            "ARL_PATH": "/met",
            "ARL_DOWN": 0,
            "MPI_USE": int(mode == "mpi"),
            "MPI_PATH": shutil.which("mpirun") or "",
            "MPI_CPU": cpu,
        }, indent=2) + "\n")
    settings = root / "spark.ini"
    if not settings.exists():
        cfg = json.loads((app / "spark.ini").read_text())
        cfg["cpu_mode"] = os.environ.get("SPARK_CPU_MODE", "serial")
        cfg["cpu_n"] = int(os.environ.get("MPI_NP", "6"))
        settings.write_text(json.dumps(cfg, indent=2) + "\n")


def main() -> None:
    args = sys.argv[1:]
    modes = {"spread": "spark_spread.py", "daily": "spark_daily.py", "product": "spark_product.py"}
    if not args or args[0] not in modes:
        raise SystemExit("Usage: IMAGE {spread|daily|product} <controller arguments>")
    # Keep all state and config under one job root, including product config.
    if any(a == "--root" or a.startswith("--root=") for a in args[1:]):
        raise SystemExit("Set SPARK_WORK_ROOT instead of passing --root")
    app = Path(os.environ.get("SPARK_APP_ROOT", "/opt/fire-spark")).resolve()
    root = Path(os.environ.get("SPARK_WORK_ROOT", "/work")).resolve()
    bootstrap(root, app)
    command = [sys.executable, str(app / modes[args[0]]), *args[1:], "--root", str(root)]
    os.execv(sys.executable, command)


if __name__ == "__main__":
    main()
