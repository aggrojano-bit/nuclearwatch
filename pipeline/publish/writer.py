"""Escribe los JSON que lee la app.

site/
  latest.json                     estado actual de todas las regiones (liviano)
  alerts.json                     comunicados oficiales de los últimos 30 días
  regions/<id>/history.json       un punto por hora, 90 días
  regions/<id>/detail.json        estaciones y razones de la región
  state/                          estado interno del pipeline (no lo lee la app)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from common import iso, read_json, write_json

SCHEMA_VERSION = 1
DISCLAIMER = ("NuclearWatch no es un sistema oficial de alerta. Ante una emergencia, "
              "sigue las instrucciones de la autoridad local (en Chile, SENAPRED).")


def write_all(site: Path, regions: list[dict], notices: list[dict], health: dict, rules: dict, now: datetime, context: dict) -> None:
    ctx_ok = context.get("status") == "verificado"
    latest = {
        "schema": SCHEMA_VERSION,
        "generated_at": iso(now),
        "rules_version": rules["version"],
        "disclaimer": DISCLAIMER,
        "sources": health,
        "regions": [{
            "id": r["id"], "name": r["name"], "countries": r["countries"],
            "level": r["level"], "level_name": r["level_name"], "confidence": r["confidence"],
            "official_alert": r["official_alert"],
            "summary": r["reasons"][0]["text"],
        } for r in regions],
    }
    write_json(site / "latest.json", latest)

    alerts = [{
        "id": n["id"], "source": n["source"], "kind": n["kind"], "title": n["title"],
        "summary": n["summary"], "url": n["url"], "published": iso(n["published"]), "regions": n["regions"],
    } for n in sorted(notices, key=lambda x: x["published"], reverse=True)]
    write_json(site / "alerts.json", {"schema": SCHEMA_VERSION, "generated_at": iso(now), "alerts": alerts})

    keep = iso(now - timedelta(days=rules["history"]["keep_days"]))
    hour = iso(now.replace(minute=0, second=0))
    for r in regions:
        rdir = site / "regions" / r["id"]
        detail = {k: v for k, v in r.items()}
        detail.update({"schema": SCHEMA_VERSION, "generated_at": iso(now), "rules_version": rules["version"],
                       "context": (context.get("regions", {}).get(r["id"], []) if ctx_ok else [])})
        write_json(rdir / "detail.json", detail)

        hist = read_json(rdir / "history.json", {"schema": SCHEMA_VERSION, "points": []})
        pts = [p for p in hist["points"] if p["t"] >= keep and p["t"] != hour]
        pts.append({"t": hour, "level": r["level"], "conf": r["confidence"],
                    "rad": r["radiation"]["anomalous"], "media": r["media"].get("recent", [None])[-1] if r["media"].get("recent") else None})
        write_json(rdir / "history.json", {"schema": SCHEMA_VERSION, "region": r["id"], "points": pts})
