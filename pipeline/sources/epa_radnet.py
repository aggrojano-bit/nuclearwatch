"""Monitores oficiales EPA RadNet (EE. UU.).

El CSV anual de cada estación ya trae el historial, así que la línea base de
30 días se calcula directamente del archivo, sin estado propio.
Formato verificado (nov 2026):
LOCATION_NAME,SAMPLE COLLECTION TIME,DOSE EQUIVALENT RATE (nSv/h),GAMMA COUNT RATE R02 (CPM),...,STATUS
Fecha: MM/DD/YYYY HH:MM:SS en UTC.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from common import Http

DOSE_COL = "DOSE EQUIVALENT RATE (nSv/h)"
COUNT_COL = "GAMMA COUNT RATE R02 (CPM)"
TIME_COL = "SAMPLE COLLECTION TIME"


def _float(value: str) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def parse_csv(text: str) -> tuple[str, str, list[tuple[datetime, float]]]:
    """Devuelve (nombre, unidad, puntos). Usa dosis si existe; si no, conteo gamma R02."""
    rows = list(csv.DictReader(io.StringIO(text)))
    rows = [r for r in rows if (r.get("STATUS") or "").strip().upper() != "REJECTED"]
    use_dose = sum(1 for r in rows if _float(r.get(DOSE_COL))) >= len(rows) * 0.5 if rows else False
    col, unit = (DOSE_COL, "nSv/h") if use_dose else (COUNT_COL, "cpm")
    name = rows[0].get("LOCATION_NAME", "").strip() if rows else ""
    points = []
    for r in rows:
        v = _float(r.get(col))
        try:
            t = datetime.strptime(r[TIME_COL].strip(), "%m/%d/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError, AttributeError):
            continue
        if v is not None:
            points.append((t, v))
    points.sort()
    return name, unit, points


def station_url(template: str, year: int, state: str, city: str) -> str:
    return template.format(year=year, state=quote(state), city=quote(city))


def fetch(http: Http, cfg: dict, region: dict, now: datetime, baseline_days: int) -> list[dict]:
    series, errors = [], []
    since = now - timedelta(days=baseline_days + 2)
    for state, city in region.get("radnet_stations", []):
        try:
            years = [now.year] if since.year == now.year else [since.year, now.year]
            name, unit, pts = "", "", []
            for y in years:
                n, u, p = parse_csv(http.get(station_url(cfg["url_template"], y, state, city)))
                name, unit = n or name, u or unit
                pts.extend(p)
            pts = [(t, v) for t, v in pts if t >= since]
            if pts:
                series.append({"station_id": f"radnet:{state}:{city}", "source": "EPA RadNet", "name": name or f"{city}, {state}", "unit": unit, "points": pts})
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{state}/{city}: {exc}")
    if errors and not series:
        raise RuntimeError("; ".join(errors[:3]))
    return series
