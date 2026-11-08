"""Volumen de noticias nucleares por región (GDELT DOC 2.0, modo timelinevolraw).

Respuesta esperada:
{"timeline":[{"series":"Article Count","data":[{"date":"20261101T000000Z","value":123,"norm":456789}, ...]}]}
Se agrega por día. Si viene "norm" (total de artículos monitoreados), se guarda
también para poder normalizar más adelante.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime

from common import Http


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


def fetch(http: Http, cfg: dict, region: dict) -> dict[date, dict]:
    text = http.get(cfg["url"], {
        "query": build_query(cfg, region),
        "mode": "timelinevolraw",
        "format": "json",
        "timespan": cfg.get("timespan", "3months"),
    }, throttle_key="gdelt")
    if text.lstrip().startswith("<") or "timeline" not in text:
        raise RuntimeError(f"respuesta inesperada de GDELT: {text[:120]!r}")
    return parse_timeline(text)
