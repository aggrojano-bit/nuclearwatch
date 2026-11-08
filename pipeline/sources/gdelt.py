"""Volumen de noticias nucleares por región (GDELT DOC 2.0, modo timelinevolraw).

Respuesta esperada:
{"timeline":[{"series":"Article Count","data":[{"date":"20261101T000000Z","value":123,"norm":456789}, ...]}]}
Se agrega por día. Si viene "norm" (total de artículos monitoreados), se guarda
también para poder normalizar más adelante.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from common import Http, iso, parse_iso


def parse_timeline(json_text: str) -> dict[date, dict]:
    data = json.loads(json_text) if json_text.strip() else {}
    days: dict[date, dict] = defaultdict(lambda: {"count": 0, "norm": 0})
    for series in data.get("timeline", []):
        for p in series.get("data", []):
            try:
                d = datetime.strptime(str(p["date"])[:8], "%Y%m%d").date()
                days[d]["count"] += int(p.get("value", 0))
                days[d]["norm"] += int(p.get("norm", 0) or 0)
            except (KeyError, ValueError, TypeError):
                continue
    return dict(sorted(days.items()))


def build_query(cfg: dict, region: dict) -> str:
    return f"{cfg['base_terms']} {region['gdelt_query']}"


def due_regions(state: dict, regions: list[dict], cfg: dict, now: datetime) -> list[dict]:
    """Regiones a consultar en esta ejecución: las de dato más viejo primero,
    sin pasar de max_requests_per_run (GDELT limita por IP compartida)."""
    refresh = timedelta(hours=float(cfg.get("refresh_hours", 6)))
    backoff = timedelta(hours=float(cfg.get("error_backoff_hours", 1)))

    def ts(rid: str, key: str) -> datetime:
        v = state.get(rid, {}).get(key)
        return parse_iso(v) if v else datetime.min.replace(tzinfo=timezone.utc)

    due = [r for r in regions if now - ts(r["id"], "fetched_at") >= refresh and now - ts(r["id"], "last_error_at") >= backoff]
    due.sort(key=lambda r: ts(r["id"], "fetched_at"))
    return due[: int(cfg.get("max_requests_per_run", 2))]


def store(state: dict, region_id: str, days: dict[date, dict], now: datetime) -> None:
    state[region_id] = {"fetched_at": iso(now), "days": {d.isoformat(): v for d, v in days.items()}}


def cached_days(state: dict, region_id: str, cfg: dict, now: datetime) -> dict[date, dict] | None:
    entry = state.get(region_id) or {}
    if not entry.get("fetched_at") or not entry.get("days"):
        return None
    if now - parse_iso(entry["fetched_at"]) > timedelta(hours=float(cfg.get("max_cache_age_hours", 48))):
        return None
    return {date.fromisoformat(d): v for d, v in entry["days"].items()}


def fetch(http: Http, cfg: dict, region: dict) -> dict[date, dict]:
    text = http.get(cfg["url"], {
        "query": build_query(cfg, region),
        "mode": "timelinevolraw",
        "format": "json",
        "timespan": cfg.get("timespan", "3months"),
    }, throttle_key="gdelt", retries=0)
    if text.lstrip().startswith("<") or "timeline" not in text:
        raise RuntimeError(f"respuesta inesperada de GDELT: {text[:120]!r}")
    return parse_timeline(text)
