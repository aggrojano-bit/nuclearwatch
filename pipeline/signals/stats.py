"""Estadística robusta: mediana y desviación absoluta mediana (MAD)."""
from __future__ import annotations

from statistics import median

MAD_SCALE = 1.4826  # hace que el MAD sea comparable a la desviación estándar en datos normales


def mad(values: list[float], center: float | None = None) -> float:
    if not values:
        return 0.0
    c = median(values) if center is None else center
    return median(abs(v - c) for v in values)


def robust_z(x: float, baseline: list[float], mad_floor_ratio: float = 0.03) -> float | None:
    """z = (x - mediana) / (1.4826 * MAD). None si no hay línea base."""
    if not baseline:
        return None
    med = median(baseline)
    spread = MAD_SCALE * mad(baseline, med)
    floor = abs(med) * mad_floor_ratio
    spread = max(spread, floor, 1e-9)
    return (x - med) / spread
