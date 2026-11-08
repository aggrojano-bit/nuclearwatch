"""Reglas fijas y públicas: señales -> nivel 0-3, confianza y razones legibles.

Nunca se calcula una probabilidad. El nivel solo resume qué señales medidas
están activas; la alerta oficial va aparte y no la decide este módulo.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from common import parse_iso

LEVEL_NAMES = {0: "Normal", 1: "Atención", 2: "Elevado", 3: "Alto"}


def confidence(rad: dict, media: dict, stations: list[dict], rules: dict, now: datetime) -> str:
    fresh_h = rules["confidence"]["fresh_hours"]
    fresh_sources = set()
    for s in stations:
        if s["status"] in ("normal", "anomala") and (now - parse_iso(s["last_time"])) <= timedelta(hours=fresh_h):
            fresh_sources.add(s["source"])
    if media.get("status") in ("normal", "activa"):
        fresh_sources.add("GDELT")
    if len(fresh_sources) >= 2:
        return "alta"
    if len(fresh_sources) == 1:
        return "media"
    return "baja"


def official_badge(notices: list[dict], region_id: str, rules: dict, now: datetime) -> list[dict]:
    cutoff = now - timedelta(days=rules["official"]["active_days"])
    return [n for n in notices if region_id in n["regions"] and n["kind"] == "incident" and n["published"] >= cutoff]


def score(region: dict, stations: list[dict], rad: dict, media: dict, notices: list[dict], rules: dict, now: datetime) -> dict:
    conf = confidence(rad, media, stations, rules, now)
    level = 0
    if media.get("active") or rad.get("single"):
        level = 1
    if rad.get("active"):
        level = 2
        if media.get("active") and conf in ("media", "alta"):
            level = 3

    reasons = []
    for s in stations:
        if s["status"] == "anomala":
            reasons.append({
                "type": "radiacion", "source": s["source"], "time": s["last_time"],
                "text": f"{s['name']}: {s['last_value']:g} {s['unit']} (habitual ≈ {s['baseline_median']:g}).",
            })
    if media.get("active"):
        reasons.append({
            "type": "medios", "source": "GDELT", "time": media["last_day"],
            "text": f"Noticias nucleares: {media['recent'][-1]} artículos/día, {media['ratio']:g} veces lo habitual.",
        })
    if not reasons:
        reasons.append({"type": "ninguna", "source": None, "time": None, "text": "Sin señales activas en las fuentes consultadas."})

    alerts = official_badge(notices, region["id"], rules, now)
    notes = []
    if rad["evaluated"] == 0:
        notes.append("Sin estaciones de radiación con línea base suficiente en esta región.")
    if media.get("status") in ("aprendiendo", "sin_datos"):
        notes.append("La señal de noticias aún no tiene suficiente historial.")
    if conf == "baja":
        notes.append("Confianza baja: pocos datos recientes. El nivel puede no reflejar la situación real.")

    return {
        "id": region["id"],
        "name": region["name"],
        "countries": region["countries"],
        "level": level,
        "level_name": LEVEL_NAMES[level],
        "confidence": conf,
        "official_alert": bool(alerts),
        "official_alert_ids": [a["id"] for a in alerts],
        "reasons": reasons,
        "notes": notes,
        "radiation": {k: rad[k] for k in ("anomalous", "evaluated", "total", "sources")},
        "media": {k: media.get(k) for k in ("status", "recent", "baseline_median", "ratio")},
        "stations": [{k: s.get(k) for k in ("station_id", "source", "name", "unit", "status", "last_time", "last_value", "z", "baseline_median")} for s in stations],
    }
