from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
PLAN_ENV = SCRIPT_DIR / "rdaps_source_plan.env"
PLAN_TXT = SCRIPT_DIR / "rdaps_source_plan.txt"
CYCLE_HOURS = (0, 6, 12, 18)


@dataclass(frozen=True)
class SourceSelection:
    source_type: str
    product: str
    valid_kst: datetime
    valid_utc: datetime
    cycle_utc: datetime
    fhr: int
    path: Path


def candidate_data_roots() -> list[Path]:
    roots: list[Path] = []
    env_root = os.environ.get("RDAPS_DATA_ROOT")
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
        root = root.expanduser()
        if root not in unique:
            unique.append(root)
    return unique


def kst_to_utc(value: datetime) -> datetime:
    return value - timedelta(hours=9)


def stamp(value: datetime) -> str:
    return value.strftime("%Y%m%d%H")


def is_netcdf(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            header = f.read(8)
    except OSError:
        return False
    return header.startswith(b"CDF") or header.startswith(b"\x89HDF\r\n\x1a\n")


def scan_nc_pres() -> dict[str, dict[int, Path]]:
    files: dict[str, dict[int, Path]] = {}
    patterns = [
        re.compile(r"\.ft(\d{3})\.(\d{10})\.nc$"),
        re.compile(r"_h(\d{3})\.(\d{10})\.nc$"),
    ]
    for root in candidate_data_roots():
        if not root.exists():
            continue
        for path in sorted(root.rglob("*prs*.nc")) + sorted(root.glob("*pres*.nc")):
            if not is_netcdf(path):
                continue
            parsed = None
            for pattern in patterns:
                match = pattern.search(path.name)
                if match:
                    parsed = (match.group(2), int(match.group(1)))
                    break
            if parsed is None:
                continue
            cycle, fhr = parsed
            files.setdefault(cycle, {}).setdefault(fhr, path)
    return files


def scan_grib(product: str) -> dict[str, dict[int, Path]]:
    files: dict[str, dict[int, Path]] = {}
    pattern = re.compile(rf"r030_v040_ne36_{re.escape(product)}_h(\d{{3}})\.(\d{{10}})\.gb2$")
    for root in candidate_data_roots():
        if not root.exists():
            continue
        for path in sorted(root.rglob(f"*_{product}_h*.gb2")):
            match = pattern.search(path.name)
            if not match:
                continue
            fhr = int(match.group(1))
            cycle = match.group(2)
            files.setdefault(cycle, {}).setdefault(fhr, path)
    return files


def choose_from_inventory(
    valid_kst_dates: list[datetime],
    inventory: dict[str, dict[int, Path]],
    source_type: str,
    product: str,
) -> list[SourceSelection] | None:
    if not valid_kst_dates:
        raise ValueError("No valid times were provided")

    valid_utc_dates = [kst_to_utc(value) for value in valid_kst_dates]
    available_cycles = sorted(
        (
            datetime.strptime(cycle, "%Y%m%d%H")
            for cycle in inventory
            if datetime.strptime(cycle, "%Y%m%d%H").hour in CYCLE_HOURS
        ),
        reverse=True,
    )

    selections: list[SourceSelection] = []
    for valid_kst, valid_utc in zip(valid_kst_dates, valid_utc_dates):
        selected: SourceSelection | None = None
        for cycle_utc in available_cycles:
            if cycle_utc > valid_utc:
                continue
            fhr_float = (valid_utc - cycle_utc).total_seconds() / 3600.0
            if abs(fhr_float - round(fhr_float)) > 1.0e-6:
                continue
            fhr = int(round(fhr_float))
            path = inventory.get(stamp(cycle_utc), {}).get(fhr)
            if path is None:
                continue
            selected = SourceSelection(source_type, product, valid_kst, valid_utc, cycle_utc, fhr, path)
            break
        if selected is None:
            return None
        selections.append(selected)
    return selections


def select_source(valid_kst_dates: list[datetime]) -> list[SourceSelection]:
    priorities = [
        ("nc_pres", "pres", scan_nc_pres()),
        ("grib_etas", "etas", scan_grib("etas")),
        ("grib_pres", "pres", scan_grib("pres")),
    ]
    for source_type, product, inventory in priorities:
        selections = choose_from_inventory(valid_kst_dates, inventory, source_type, product)
        if selections is not None:
            return selections
    searched = ", ".join(str(root) for root in candidate_data_roots())
    raise FileNotFoundError(
        "No weather input data found: required RDAPS weather input files were not found "
        "for all valid times (tried nc_pres, grib_etas, grib_pres; "
        "cycles 00/06/12/18). "
        f"searched: {searched}"
    )


def write_source_plan(selections: list[SourceSelection]) -> None:
    if not selections:
        raise ValueError("Cannot write empty RDAPS source plan")
    first = selections[0]
    PLAN_ENV.write_text(
        "\n".join(
            [
                "# Auto-generated by rdaps_source_utils.py",
                f'RDAPS_SOURCE_TYPE="{first.source_type}"',
                f'RDAPS_GRIB_PRODUCT="{first.product}"',
                f'RDAPS_FIRST_CYCLE_UTC="{stamp(first.cycle_utc)}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    lines = [
        "# VALID_KST VALID_UTC SOURCE PRODUCT CYCLE_UTC FHR FILE",
    ]
    for item in selections:
        lines.append(
            f"{item.valid_kst:%Y%m%d%H} {item.valid_utc:%Y%m%d%H} "
            f"{item.source_type} {item.product} {item.cycle_utc:%Y%m%d%H} "
            f"{item.fhr:03d} {item.path}"
        )
    lines.append("")
    PLAN_TXT.write_text("\n".join(lines), encoding="utf-8")


def read_source_plan() -> dict[str, SourceSelection]:
    result: dict[str, SourceSelection] = {}
    if not PLAN_TXT.exists():
        return result
    with PLAN_TXT.open("r", encoding="utf-8-sig") as f:
        for line in f:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            parts = text.split(maxsplit=6)
            if len(parts) != 7:
                continue
            valid_kst = datetime.strptime(parts[0], "%Y%m%d%H")
            valid_utc = datetime.strptime(parts[1], "%Y%m%d%H")
            source_type = parts[2]
            product = parts[3]
            cycle_utc = datetime.strptime(parts[4], "%Y%m%d%H")
            fhr = int(parts[5])
            result[parts[0]] = SourceSelection(source_type, product, valid_kst, valid_utc, cycle_utc, fhr, Path(parts[6]))
    return result
