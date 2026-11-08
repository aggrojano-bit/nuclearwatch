"""Señal mediática: volumen diario de noticias nucleares frente a su mediana de 90 días."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median


def evaluate(days: dict[date, dict], rules: dict, now: datetime) -> dict:
    m = rules["media"]
    today = now.date()
    complete = {d: v["count"] for d, v in days.items() if d < today}  # hoy está incompleto
    ordered = sorted(complete)
    k = int(m["consecutive_days"])
    if len(ordered) < k:
        return {"status": "sin_datos", "active": False}
    recent_days = ordered[-k:]
    cutoff = today - timedelta(days=m["baseline_days"])
    baseline = [complete[d] for d in ordered[:-k] if d >= cutoff]
    recent = [complete[d] for d in recent_days]
    out = {"recent": recent, "last_day": recent_days[-1].isoformat()}
    if len(baseline) < m["min_baseline_days"]:
        return {**out, "status": "aprendiendo", "active": False}
    med = max(median(baseline), 1.0)
    ratios = [c / med for c in recent]
    active = all(r >= m["ratio_threshold"] and c >= m["min_daily_articles"] for r, c in zip(ratios, recent))
    return {**out, "status": "activa" if active else "normal", "active": active,
            "baseline_median": round(med, 1), "ratio": round(ratios[-1], 2)}
