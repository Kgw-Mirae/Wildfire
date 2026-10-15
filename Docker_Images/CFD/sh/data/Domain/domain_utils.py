from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


CONFIG_NAME = "domain_config.json"
DEFAULT_HALO_CELLS = 2
DEFAULT_TOPO_SOURCE_RES_M = 10
DEFAULT_VERTICAL_RESOLUTION_M = 25.0
DEFAULT_KMAX = 80
DEFAULT_TIME_STEP_S = 0.5
DEFAULT_OUTPUT_INTERVAL_S = 600.0
DEFAULT_FORECAST_DURATION_H = 0
DEFAULT_FORECAST_DURATION_M = 0


def snap_domain_size(domain_size_m: int, resolution_m: int) -> int:
    quotient, remainder = divmod(domain_size_m, resolution_m)
    if remainder == 0:
        return domain_size_m

    lower = quotient * resolution_m
    upper = (quotient + 1) * resolution_m
    if lower <= 0:
        return upper
    if (domain_size_m - lower) < (upper - domain_size_m):
        return lower
    return upper

@dataclass(frozen=True)
class DomainConfig:
    resolution_m: int
    vertical_resolution_m: float
    kmax: int
    time_step_s: float
    output_interval_s: float
    forecast_duration_h: int
    forecast_duration_m: int
    domain_size_m: int
    halo_cells: int
    topo_source_res_m: int

    @property
    def inner_npix(self) -> int:
        return self.domain_size_m // self.resolution_m

    @property
    def model_npix(self) -> int:
        return self.inner_npix + self.halo_cells

    @property
    def outer_npix(self) -> int:
        return self.inner_npix + (2 * self.halo_cells)

    @property
    def topo_ratio(self) -> int:
        return self.resolution_m // self.topo_source_res_m

    @property
    def topo_inner_npix(self) -> int:
        return self.inner_npix * self.topo_ratio

    @property
    def topo_outer_npix(self) -> int:
        return self.outer_npix * self.topo_ratio

    @property
    def topo_halo_cells(self) -> int:
        return self.halo_cells * self.topo_ratio

    @property
    def half_width_m(self) -> float:
        return self.domain_size_m / 2.0

    @property
    def forecast_duration_s(self) -> int:
        return (self.forecast_duration_h * 3600) + (self.forecast_duration_m * 60)


def project_root_from(path: Path) -> Path:
    current = path.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "data" / "Domain" / CONFIG_NAME).exists():
            return candidate
    raise FileNotFoundError(f"Cannot find data/Domain/{CONFIG_NAME} from {path}")


def load_domain_config(project_root: Path | None = None) -> DomainConfig:
    if project_root is None:
        project_root = project_root_from(Path.cwd())

    config_path = project_root / "data" / "Domain" / CONFIG_NAME
    with config_path.open("r", encoding="utf-8") as f:
        raw: Dict[str, Any] = json.load(f)

    resolution_m = int(raw["resolution_m"])
    vertical_resolution_m = float(raw.get("vertical_resolution_m", DEFAULT_VERTICAL_RESOLUTION_M))
    kmax = int(raw.get("kmax", DEFAULT_KMAX))
    time_step_s = float(raw.get("time_step_s", DEFAULT_TIME_STEP_S))
    output_interval_s = float(raw.get("output_interval_s", DEFAULT_OUTPUT_INTERVAL_S))
    forecast_duration_h = int(raw.get("forecast_duration_h", DEFAULT_FORECAST_DURATION_H))
    forecast_duration_m = int(raw.get("forecast_duration_m", DEFAULT_FORECAST_DURATION_M))
    requested_domain_size_m = int(raw["domain_size_m"])
    domain_size_m = snap_domain_size(requested_domain_size_m, resolution_m)

    cfg = DomainConfig(
        resolution_m=resolution_m,
        vertical_resolution_m=vertical_resolution_m,
        kmax=kmax,
        time_step_s=time_step_s,
        output_interval_s=output_interval_s,
        forecast_duration_h=forecast_duration_h,
        forecast_duration_m=forecast_duration_m,
        domain_size_m=domain_size_m,
        halo_cells=DEFAULT_HALO_CELLS,
        topo_source_res_m=DEFAULT_TOPO_SOURCE_RES_M,
    )
    validate_domain_config(cfg)
    return cfg


def validate_domain_config(cfg: DomainConfig) -> None:
    if cfg.resolution_m <= 0:
        raise ValueError("resolution_m must be positive")
    if cfg.vertical_resolution_m <= 0:
        raise ValueError("vertical_resolution_m must be positive")
    if cfg.kmax <= 0:
        raise ValueError("kmax must be positive")
    if cfg.time_step_s <= 0:
        raise ValueError("time_step_s must be positive")
    if cfg.output_interval_s <= 0:
        raise ValueError("output_interval_s must be positive")
    if cfg.forecast_duration_h < 0:
        raise ValueError("forecast_duration_h must be non-negative")
    if cfg.forecast_duration_m < 0 or cfg.forecast_duration_m >= 60:
        raise ValueError("forecast_duration_m must be in 0..59")
    if cfg.domain_size_m <= 0:
        raise ValueError("domain_size_m must be positive")
    if cfg.halo_cells != 2:
        raise ValueError("halo_cells is fixed at 2 for this automation")
    if cfg.topo_source_res_m <= 0:
        raise ValueError("topo_source_res_m must be positive")
    if cfg.domain_size_m % cfg.resolution_m != 0:
        raise ValueError("domain_size_m must be divisible by resolution_m")
    if cfg.resolution_m % cfg.topo_source_res_m != 0:
        raise ValueError("resolution_m must be divisible by topo_source_res_m")


def res_label(resolution_m: int) -> str:
    return f"{int(round(resolution_m))}m"
