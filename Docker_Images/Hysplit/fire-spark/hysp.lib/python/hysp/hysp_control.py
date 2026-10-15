#!/usr/bin/env python3
"""
hysp_control.py

Python CONTROL-file utilities corresponding to the user's IDL routines:

    hysp_control_read.pro
    hysp_control_write.pro
    hysp_control_update.pro
    hysp_control_update2.pro

No NOAA hysplitdata dependency is used.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from numbers import Integral, Real
from pathlib import Path
from typing import Any

try:
    from .hysp_arl import hysp_arl_find  # type: ignore
except ImportError:
    from hysp_arl import hysp_arl_find


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    if isinstance(value, Integral):
        text = str(int(value))
    elif isinstance(value, Real):
        if not float(value).is_integer():
            raise ValueError(f"Non-integer time value: {value}")
        text = str(int(value))
    else:
        text = str(value).strip()

    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 14:
        return datetime.strptime(digits[:14], "%Y%m%d%H%M%S")
    if len(digits) >= 12:
        return datetime.strptime(digits[:12], "%Y%m%d%H%M")
    if len(digits) >= 10:
        return datetime.strptime(digits[:10], "%Y%m%d%H")
    if len(digits) >= 8:
        return datetime.strptime(digits[:8], "%Y%m%d")

    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _control_lines(file: str | os.PathLike[str]) -> list[str]:
    lines: list[str] = []
    with Path(file).open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if line:
                lines.append(line)
    return lines


def _is_int_text(value: str) -> bool:
    try:
        int(value.strip())
        return True
    except ValueError:
        return False


def hysp_control_read(file: str | os.PathLike[str]) -> dict[str, Any]:
    """Read trajectory or dispersion HYSPLIT CONTROL into a dict."""
    dd = _control_lines(file)
    if not dd:
        raise ValueError(f"Empty CONTROL file: {file}")

    i = 0

    def take() -> str:
        nonlocal i
        if i >= len(dd):
            raise ValueError(f"Unexpected end of CONTROL: {file}")
        value = dd[i]
        i += 1
        return value

    cc: dict[str, Any] = {"starting_time": take()}

    nloc = int(take())
    cc["starting_locations"] = [take() for _ in range(nloc)]

    cc["run_time"] = take()
    cc["vertical_motion"] = take()
    cc["top_of_model"] = take()

    nmet = int(take())
    cc["meteorological_data"] = [take() + take() for _ in range(nmet)]

    if i >= len(dd):
        return cc

    if not _is_int_text(dd[i]):
        cc["tdump"] = take() + take()
        return cc

    npol = int(take())
    cc["pollutant"] = [
        {
            "identification": take(),
            "emission_rate": take(),
            "hours_of_emission": take(),
            "release_start_time": take(),
        }
        for _ in range(npol)
    ]

    if i >= len(dd):
        return cc

    ngrid = int(take())
    cc["grid"] = [
        {
            "center": take(),
            "spacing": take(),
            "span": take(),
            "output": take() + take(),
            "nlevel": take(),
            "levels": take(),
            "sampling_start": take(),
            "sampling_end": take(),
            "sampling_interval": take(),
        }
        for _ in range(ngrid)
    ]

    if i >= len(dd):
        return cc

    ndep = int(take())
    cc["deposition"] = [
        {
            "particle": take(),
            "velocity": take(),
            "wet_removal": take(),
            "decay": take(),
            "resuspension": take(),
        }
        for _ in range(ndep)
    ]
    return cc


def _path_pair(path: str | os.PathLike[str]) -> tuple[str, str]:
    p = Path(str(path)).expanduser()
    parent = str(p.parent)
    if parent in ("", "."):
        parent = "."
    if not parent.endswith("/"):
        parent += "/"
    return parent, p.name


def hysp_control_write(
    cc: Mapping[str, Any],
    filename: str | os.PathLike[str] = "CONTROL",
) -> Path:
    """Write a CONTROL dict."""
    ofile = Path(filename)
    ofile.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [str(cc["starting_time"])]

    loc = list(cc.get("starting_locations", []))
    lines.append(str(len(loc)))
    lines.extend(str(x) for x in loc)

    lines.extend(
        [
            str(cc["run_time"]),
            str(cc["vertical_motion"]),
            str(cc["top_of_model"]),
        ]
    )

    met = list(cc.get("meteorological_data", []))
    lines.append(str(len(met)))
    for path in met:
        lines.extend(_path_pair(path))

    if "tdump" in cc:
        lines.extend(_path_pair(cc["tdump"]))

    if "pollutant" in cc:
        pol = list(cc["pollutant"])
        lines.append(str(len(pol)))
        for x in pol:
            lines.extend(
                [
                    str(x["identification"]),
                    str(x["emission_rate"]),
                    str(x["hours_of_emission"]),
                    str(x["release_start_time"]),
                ]
            )

    if "grid" in cc:
        grd = list(cc["grid"])
        lines.append(str(len(grd)))
        for x in grd:
            d, b = _path_pair(x["output"])
            lines.extend(
                [
                    str(x["center"]),
                    str(x["spacing"]),
                    str(x["span"]),
                    d,
                    b,
                    str(x["nlevel"]),
                    str(x["levels"]),
                    str(x["sampling_start"]),
                    str(x["sampling_end"]),
                    str(x["sampling_interval"]),
                ]
            )

    if "deposition" in cc:
        dep = list(cc["deposition"])
        lines.append(str(len(dep)))
        for x in dep:
            lines.extend(
                [
                    str(x["particle"]),
                    str(x["velocity"]),
                    str(x["wet_removal"]),
                    str(x["decay"]),
                    str(x["resuspension"]),
                ]
            )

    ofile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ofile


def _norm_key(key: Any) -> str:
    return str(key).strip().lower().replace(" ", "_")


def _merge_fields(target: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(target)
    index = {_norm_key(k): k for k in out}
    for key, value in patch.items():
        nk = _norm_key(key)
        real_key = index.get(nk, nk)
        out[real_key] = str(value)
        index[nk] = real_key
    return out


def _set_scalar(cc: dict[str, Any], key: str, value: Any) -> None:
    lookup = {_norm_key(k): k for k in cc}
    nk = _norm_key(key)
    cc[lookup.get(nk, nk)] = str(value)


def _update_section(
    cc: dict[str, Any],
    section: str,
    patch: Mapping[str, Any],
    index: int | None = None,
) -> None:
    lookup = {_norm_key(k): k for k in cc}
    skey = lookup.get(_norm_key(section), _norm_key(section))
    if skey not in cc:
        raise KeyError(f"CONTROL has no section {section!r}")

    value = cc[skey]
    if isinstance(value, list):
        if index is None:
            cc[skey] = [_merge_fields(item, patch) for item in value]
        else:
            if index < 0 or index >= len(value):
                raise IndexError(f"{section}[{index}] out of range")
            new_value = list(value)
            new_value[index] = _merge_fields(new_value[index], patch)
            cc[skey] = new_value
    elif isinstance(value, Mapping):
        cc[skey] = _merge_fields(value, patch)
    else:
        raise TypeError(f"CONTROL item {section!r} is not structured")


def hysp_control_update2(
    control: Mapping[str, Any],
    update: Any,
) -> dict[str, Any]:
    """
    Direct CONTROL update corresponding to hysp_control_update2.pro.

    Examples
    --------
    IDL-like flat form::

        uu = [
            "pollutant", {"hours_of_emission": 3},
            "pollutant", 2, {"hours_of_emission": 1},
        ]

    Tuple form::

        uu = [
            ("run_time", 48),
            ("pollutant", 0, {"hours_of_emission": 24}),
        ]

    Dict form::

        uu = {"run_time": 48}
    """
    cc = dict(control)
    if update is None:
        return cc

    if isinstance(update, Mapping):
        items: list[tuple[Any, ...]] = [(k, v) for k, v in update.items()]
    else:
        seq = list(update)
        if seq and all(isinstance(x, (tuple, list)) for x in seq):
            items = [tuple(x) for x in seq]
        else:
            items = []
            i = 0
            while i < len(seq):
                if i + 1 >= len(seq):
                    raise ValueError("Incomplete CONTROL update list")

                key = seq[i]
                real_key = next(
                    (k for k in cc if _norm_key(k) == _norm_key(key)),
                    str(key),
                )
                current = cc.get(real_key)

                if (
                    isinstance(current, list)
                    and i + 2 < len(seq)
                    and isinstance(seq[i + 1], Integral)
                    and isinstance(seq[i + 2], Mapping)
                ):
                    items.append((key, int(seq[i + 1]), seq[i + 2]))
                    i += 3
                else:
                    items.append((key, seq[i + 1]))
                    i += 2

    for item in items:
        if len(item) == 2:
            key, value = item
            real_key = next(
                (k for k in cc if _norm_key(k) == _norm_key(key)),
                _norm_key(key),
            )
            current = cc.get(real_key)
            if isinstance(current, (list, Mapping)) and isinstance(value, Mapping):
                _update_section(cc, str(key), value)
            else:
                _set_scalar(cc, str(key), value)
        elif len(item) == 3:
            key, index, patch = item
            if not isinstance(index, Integral) or not isinstance(patch, Mapping):
                raise TypeError(f"Invalid CONTROL update: {item!r}")
            _update_section(cc, str(key), patch, int(index))
        else:
            raise ValueError(f"Invalid CONTROL update: {item!r}")

    return cc


def _starting_time_text(value: Any) -> str:
    return _parse_time(value).strftime("%y %m %d %H")


def _starting_time_datetime(text: str) -> datetime:
    p = text.split()
    if len(p) < 4:
        raise ValueError(f"Invalid CONTROL starting_time: {text!r}")
    yy, mm, dd, hh = (int(x) for x in p[:4])
    return datetime(1900 + yy if yy > 40 else 2000 + yy, mm, dd, hh)


def _run_time_met_window(stime: datetime, run_time: Any) -> tuple[datetime, datetime]:
    """IDL date(time,run_time,/make) followed by date(...,/margin)."""
    nhour = int(float(str(run_time).strip()))
    if nhour == 0:
        last = stime
    else:
        sign = 1 if nhour > 0 else -1
        last = stime + timedelta(hours=sign * (abs(nhour) - 1))
    return min(stime, last) - timedelta(days=1), max(stime, last) + timedelta(days=1)


def _location_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        p = list(value)
        if len(p) < 2:
            raise ValueError(f"Invalid location: {value!r}")
        return f"{p[0]} {p[1]} {p[2] if len(p) >= 3 else 0}"
    raise TypeError(f"Invalid location: {value!r}")


def hysp_control_update(
    sfile: str | os.PathLike[str] | None = None,
    ofile: str | os.PathLike[str] | None = None,
    *,
    stime: Any | None = None,
    location: Sequence[Any] | None = None,
    arl: str | Sequence[str] | None = None,
    met_file: str | os.PathLike[str] | Sequence[str | os.PathLike[str]] | None = None,
    update: Any = None,
    run_time: Any | None = None,
    top_of_model: Any | None = None,
    vertical_motion: Any | None = None,
    ini: str | os.PathLike[str] = "hysp.ini",
    nowrite: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    """Update CONTROL corresponding to hysp_control_update.pro."""
    src = Path(sfile or "./CONTROL")
    if src.is_dir():
        src = src / "CONTROL"
    dst = Path(ofile or "./CONTROL")
    if dst.is_dir():
        dst = dst / "CONTROL"
    if not src.is_file():
        raise FileNotFoundError(f"NOFILE {src}")

    if verbose:
        print(f"SFILE = {src}")
        print(f"OFILE = {dst}")

    cc = hysp_control_read(src)

    if run_time is not None:
        cc["run_time"] = str(run_time)
    if top_of_model is not None:
        cc["top_of_model"] = str(top_of_model)
    if vertical_motion is not None:
        cc["vertical_motion"] = str(vertical_motion)

    if location is not None:
        cc["starting_locations"] = [_location_text(x) for x in location]

    if stime is not None:
        cc["starting_time"] = _starting_time_text(stime)

    if arl is not None:
        start = _starting_time_datetime(str(cc["starting_time"]))
        t1, t2 = _run_time_met_window(start, cc["run_time"])

        if met_file is not None:
            if isinstance(met_file, (str, os.PathLike)):
                values = [met_file]
            else:
                values = list(met_file)
            met = [str(Path(x).expanduser().resolve()) for x in values]
        else:
            met = hysp_arl_find(arl, time=[t1, t2], ini=ini, verbose=verbose)

        if not met:
            raise FileNotFoundError(
                f"No ARL files found for {t1:%Y%m%d%H} - {t2:%Y%m%d%H}"
            )
        cc["meteorological_data"] = met

    # Same ordering as the IDL routine: structured update comes last.
    if update is not None:
        cc = hysp_control_update2(cc, update)

    if not nowrite:
        hysp_control_write(cc, dst)
    return cc


__all__ = [
    "hysp_control_read",
    "hysp_control_write",
    "hysp_control_update",
    "hysp_control_update2",
]
