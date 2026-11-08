"""Mediciones ciudadanas de radiación de Safecast (licencia CC0).

Cada dispositivo (device_id) se trata como una estación. Las lecturas se
agrupan por hora (mediana) y se acumulan en un estado propio, porque la API
solo se consulta para las últimas horas: así la línea base de 30 días se
construye sola con el tiempo.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median

from common import Http, iso, parse_iso


def parse_measurements(json_text: str) -> list[dict]:
    data = json.loads(json_text)
    if isinstance(data, dict):  # algunas versiones envuelven la lista
        data = data.get("measurements") or data.get("data") or []
    out = []
    for m in data:
        try:
            value = float(m["value"])
            when = parse_iso(str(m["captured_at"]))
        except (KeyError, TypeError, ValueError):
            continue
        dev = m.get("device_id") or m.get("sensor_id") or m.get("station_id")
        if dev is None or value <= 0:
            continue  # lecturas sin dispositivo no permiten línea base propia
        out.append({
            "device": str(dev),
            "value": value,
            "unit": (m.get("unit") or "cpm").lower(),
            "time": when,
            "lat": m.get("latitude"),
            "lon": m.get("longitude"),
            "name": m.get("location_name") or "",
        })
    return out


def hourly(readings: list[dict]) -> dict[str, dict]:
    """device -> {unit, name, lat, lon, points: {hora_iso: mediana}}"""
    buckets: dict[tuple, list[float]] = defaultdict(list)
    meta: dict[str, dict] = {}
    for r in readings:
        hour = r["time"].replace(minute=0, second=0, microsecond=0)
        key = f"safecast:{r['device']}:{r['unit']}"
        buckets[(key, iso(hour))].append(r["value"])
        meta[key] = {"unit": r["unit"], "name": r["name"], "lat": r["lat"], "lon": r["lon"]}
    out: dict[str, dict] = {}
    for (key, hour), vals in buckets.items():
        out.setdefault(key, {**meta[key], "points": {}})["points"][hour] = round(median(vals), 4)
    return out


def merge_state(state: dict, region_id: str, new: dict[str, dict], now: datetime, keep_days: int) -> dict:
    """Añade lecturas nuevas al estado de la región y recorta lo viejo."""
    region_state = state.setdefault(region_id, {})
    cutoff = iso(now - timedelta(days=keep_days))
    for key, info in new.items():
        st = region_state.setdefault(key, {"unit": info["unit"], "name": info["name"], "lat": info["lat"], "lon": info["lon"], "points": {}})
        st["points"].update(info["points"])
    for key in list(region_state):
        pts = {h: v for h, v in region_state[key]["points"].items() if h >= cutoff}
        if pts:
            region_state[key]["points"] = dict(sorted(pts.items()))
        else:
            del region_state[key]
    return state


def fetch(http: Http, cfg: dict, region: dict, now: datetime) -> tuple[list[dict], list[str]]:
    """Cada punto se consulta aparte: si uno falla, los demás siguen."""
    after = (now - timedelta(hours=int(cfg.get("lookback_hours", 6)))).strftime("%Y-%m-%dT%H:%M:%S")
    readings: list[dict] = []
    errors: list[str] = []
    for lat, lon, radius_km in region.get("safecast_points", []):
        try:
            text = http.get(cfg["url"], {
                "latitude": lat,
                "longitude": lon,
                "distance": int(radius_km * 1000),
                "captured_after": after,
                "per_page": cfg.get("per_page", 500),
            }, timeout=int(cfg.get("timeout_seconds", 45)), retries=int(cfg.get("retries", 0)))
            readings.extend(parse_measurements(text))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"({lat},{lon}) {str(exc)[:120]}")
    return readings, errors


def to_series(region_state: dict) -> list[dict]:
    series = []
    for key, st in region_state.items():
        series.append({
            "station_id": key,
            "source": "Safecast",
            "name": st.get("name") or key.split(":")[1],
            "unit": st["unit"],
            "points": [(parse_iso(h), v) for h, v in st["points"].items()],
        })
    return series
