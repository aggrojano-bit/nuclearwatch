"""Punto de entrada del pipeline. Lo ejecuta GitHub Actions cada hora.

Uso:  python run.py --site ../site
Cada fuente se aísla: si una falla, las demás siguen y el fallo queda
registrado en latest.json -> "sources" (la app baja la confianza).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import CONFIG_DIR, Http, iso, load_yaml, make_http, read_json, utcnow, write_json  # noqa: E402
from notify import fcm  # noqa: E402
from notify.rules import plan  # noqa: E402
from publish.writer import write_all  # noqa: E402
from scoring.levels import score  # noqa: E402
from signals import media as media_signal  # noqa: E402
from signals import radiation  # noqa: E402
from sources import epa_radnet, gdelt, iaea_rss, safecast  # noqa: E402


def _health(health: dict, prev: dict, name: str, ok: bool, now: datetime, detail: str = "", count: int | None = None) -> None:
    entry = {"ok": ok, "checked_at": iso(now), "last_success": iso(now) if ok else prev.get(name, {}).get("last_success")}
    if detail:
        entry["error"] = detail[:300]
    if count is not None:
        entry["items"] = count
    health[name] = entry


def run(site: Path, http: Http | None = None, now: datetime | None = None, config_dir: Path = CONFIG_DIR) -> dict:
    now = now or utcnow()
    regions_cfg = load_yaml("regions.yaml", config_dir)["regions"]
    rules = load_yaml("rules.yaml", config_dir)
    sources = load_yaml("sources.yaml", config_dir)
    context = load_yaml("context.yaml", config_dir)
    http = http or make_http(sources)

    state_dir = site / "state"
    prev_health = read_json(state_dir / "health.json", {})
    health: dict = {}

    # 1. Comunicados oficiales
    try:
        notices, raw_count = iaea_rss.fetch(http, sources["iaea"], regions_cfg, rules, now)
        _health(health, prev_health, "iaea", raw_count > 0, now, "" if raw_count else "feeds sin elementos", len(notices))
        health["iaea"]["read"] = raw_count
    except Exception as exc:  # noqa: BLE001
        notices = []
        _health(health, prev_health, "iaea", False, now, str(exc))

    # 2. Radiación (Safecast acumula estado; RadNet trae su historial)
    sc_state = read_json(state_dir / "safecast.json", {})
    sc_ok, sc_err, sc_count = True, [], 0
    rn_ok, rn_err, rn_count, rn_used = True, [], 0, False
    region_stations: dict[str, list[dict]] = {}
    for reg in regions_cfg:
        series = []
        readings, errs = safecast.fetch(http, sources["safecast"], reg, now)
        sc_count += len(readings)
        safecast.merge_state(sc_state, reg["id"], safecast.hourly(readings), now, rules["radiation"]["baseline_days"] + 1)
        if errs:
            sc_err.extend(f"{reg['id']}: {e}" for e in errs)
            sc_ok = sc_ok and len(errs) < len(reg.get("safecast_points", []))
        series.extend(safecast.to_series(sc_state.get(reg["id"], {})))
        if reg.get("radnet_stations"):
            rn_used = True
            try:
                rn = epa_radnet.fetch(http, sources["epa_radnet"], reg, now, rules["radiation"]["baseline_days"])
                rn_count += len(rn)
                series.extend(rn)
            except Exception as exc:  # noqa: BLE001
                rn_ok = False
                rn_err.append(f"{reg['id']}: {exc}")
        region_stations[reg["id"]] = [radiation.evaluate_station(s, rules, now) for s in series]
    write_json(state_dir / "safecast.json", sc_state)
    _health(health, prev_health, "safecast", sc_ok, now, "; ".join(sc_err), sc_count)
    if rn_used:
        _health(health, prev_health, "epa_radnet", rn_ok, now, "; ".join(rn_err), rn_count)

    # 3. Noticias (GDELT): pocas consultas por ejecución, el resto sale del caché
    gd_cfg = sources["gdelt"]
    gd_state = read_json(state_dir / "gdelt.json", {})
    md_err, md_done = [], 0
    for reg in gdelt.due_regions(gd_state, regions_cfg, gd_cfg, now):
        try:
            gdelt.store(gd_state, reg["id"], gdelt.fetch(http, gd_cfg, reg), now)
            md_done += 1
        except Exception as exc:  # noqa: BLE001
            md_err.append(f"{reg['id']}: {exc}")
            gd_state.setdefault(reg["id"], {})["last_error_at"] = iso(now)
            if "429" in str(exc):
                break  # límite de uso: no insistir en esta ejecución
    write_json(state_dir / "gdelt.json", gd_state)
    region_media: dict[str, dict] = {}
    fresh = 0
    for reg in regions_cfg:
        days = gdelt.cached_days(gd_state, reg["id"], gd_cfg, now)
        if days is None:
            region_media[reg["id"]] = {"status": "sin_datos", "active": False}
        else:
            fresh += 1
            region_media[reg["id"]] = media_signal.evaluate(days, rules, now)
    _health(health, prev_health, "gdelt", fresh > 0 and not (md_err and md_done == 0), now,
            "; ".join(md_err), fresh)

    # 4. Niveles
    scored = []
    for reg in regions_cfg:
        st = region_stations[reg["id"]]
        scored.append(score(reg, st, radiation.region_signal(st, rules), region_media[reg["id"]], notices, rules, now))

    # 5. Notificaciones (en calibración solo se registran)
    notify_state = read_json(state_dir / "notify.json", {})
    messages, notify_state, report = plan(scored, notices, notify_state, rules, now)
    enabled = bool(rules["notifications"]["enabled"])
    send_errors = fcm.send(messages) if enabled else []
    outbox = read_json(state_dir / "outbox.json", [])
    outbox.extend({**m, "at": iso(now), "sent": enabled and not send_errors} for m in messages)
    write_json(state_dir / "outbox.json", outbox[-300:])
    write_json(state_dir / "notify.json", notify_state)
    if report["breaker_tripped"]:
        write_json(state_dir / "breaker.json", {"at": iso(now), **report})
        print(f"::warning::Interruptor de seguridad: {report['breaker_regions']} subieron a la vez. No se envió nada.")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
                fh.write(f"breaker=true\nbreaker_regions={','.join(report['breaker_regions'])}\n")

    # 6. Publicación
    write_json(state_dir / "health.json", health)
    write_all(site, scored, notices, health, rules, now, context)
    summary = {"generated_at": iso(now), "levels": {r["id"]: r["level"] for r in scored},
               "messages": len(messages), "sent": enabled, "send_errors": send_errors,
               "breaker": report["breaker_tripped"], "sources": {k: v["ok"] for k, v in health.items()}}
    print(summary)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="../site", help="carpeta de salida (rama gh-pages)")
    args = ap.parse_args()
    run(Path(args.site).resolve())


if __name__ == "__main__":
    main()
