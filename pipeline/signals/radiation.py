"""Señal radiológica: cada estación se compara con su propia línea base."""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from common import hours_ago, iso
from signals.stats import robust_z


def evaluate_station(series: dict, rules: dict, now: datetime) -> dict:
    r = rules["radiation"]
    pts = sorted(p for p in series["points"] if p[0] <= now)
    base = {"station_id": series["station_id"], "source": series["source"], "name": series["name"], "unit": series["unit"]}
    if not pts:
        return {**base, "status": "sin_datos"}
    last_t, last_v = pts[-1]
    out = {**base, "last_time": iso(last_t), "last_value": last_v}
    if hours_ago(last_t, now) > r["max_age_hours"]:
        return {**out, "status": "desactualizada"}
    k = int(r["consecutive"])
    recent = pts[-k:]
    cutoff = now - timedelta(days=r["baseline_days"])
    baseline = [v for t, v in pts[:-k] if t >= cutoff]
    if len(baseline) < r["min_baseline_points"] or len(recent) < k:
        return {**out, "status": "aprendiendo", "baseline_points": len(baseline)}
    zs = [robust_z(v, baseline, r["mad_floor_ratio"]) for _, v in recent]
    anomalous = all(z is not None and z >= r["z_threshold"] for z in zs)
    return {
        **out,
        "status": "anomala" if anomalous else "normal",
        "z": round(zs[-1], 2),
        "baseline_median": round(median(baseline), 3),
        "baseline_points": len(baseline),
    }


def region_signal(stations: list[dict], rules: dict) -> dict:
    evaluated = [s for s in stations if s["status"] in ("normal", "anomala")]
    anomalous = [s for s in evaluated if s["status"] == "anomala"]
    need = int(rules["radiation"]["min_anomalous_stations"])
    return {
        "active": len(anomalous) >= need,
        "single": len(anomalous) == 1 and need > 1,
        "anomalous": len(anomalous),
        "evaluated": len(evaluated),
        "total": len(stations),
        "sources": sorted({s["source"] for s in evaluated}),
    }
