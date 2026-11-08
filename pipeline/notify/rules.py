"""Decide qué notificaciones enviar. Aplica persistencia, enfriamiento,
espera para bajadas e interruptor de seguridad. No envía nada por sí mismo."""
from __future__ import annotations

from datetime import datetime, timedelta

from common import iso, parse_iso
from scoring.levels import LEVEL_NAMES


def _brief(region: dict) -> str:
    rad = region["radiation"]
    if rad["anomalous"]:
        return f"{rad['anomalous']} estaciones con radiación sobre lo habitual."
    if region["media"].get("status") == "activa":
        return "Aumento fuerte de noticias nucleares."
    return "Cambio en las señales medidas."


def plan(regions: list[dict], notices: list[dict], state: dict, rules: dict, now: datetime) -> tuple[list[dict], dict, dict]:
    """Devuelve (mensajes, nuevo_estado, informe)."""
    n = rules["notifications"]
    st_regions = state.setdefault("regions", {})
    sent_ids = set(state.setdefault("sent_official_ids", []))
    ups, downs, officials = [], [], []

    for reg in regions:
        rid, level = reg["id"], reg["level"]
        st = st_regions.setdefault(rid, {"pending_level": 0, "pending_runs": 0, "notified_level": 0, "last_sent": None, "below_since": None})
        if level == st["pending_level"]:
            st["pending_runs"] += 1
        else:
            st["pending_level"], st["pending_runs"] = level, 1

        cooldown_ok = not st["last_sent"] or now - parse_iso(st["last_sent"]) >= timedelta(hours=n["cooldown_hours"])
        if level >= n["min_level"] and level > st["notified_level"] and st["pending_runs"] >= n["persist_runs"] and cooldown_ok:
            ups.append((reg, st))
            st["below_since"] = None
        elif level < st["notified_level"]:
            st["below_since"] = st["below_since"] or iso(now)
            if now - parse_iso(st["below_since"]) >= timedelta(hours=n["downgrade_hold_hours"]):
                downs.append((reg, st))
        else:
            st["below_since"] = None

    for notice in notices:
        if notice["kind"] == "incident" and notice["id"] not in sent_ids:
            officials.append(notice)

    report = {"breaker_tripped": False, "candidates_up": len(ups)}
    if len(ups) > n["breaker_max_regions"]:
        # Muchas regiones a la vez = casi seguro un fallo de datos. No se envía nada.
        report["breaker_tripped"] = True
        report["breaker_regions"] = [r["id"] for r, _ in ups]
        for notice in officials:
            sent_ids.add(notice["id"])  # se registran para no reenviarlos tras la revisión
        state["sent_official_ids"] = sorted(sent_ids)[-500:]
        return [], state, report

    messages = []
    for reg, st in ups:
        messages.append({
            "topic": f"region-{reg['id']}", "kind": "nivel",
            "title": f"{reg['name']}: nivel {reg['level_name']}",
            "body": f"{_brief(reg)} Toca para ver fuentes.",
            "region": reg["id"],
        })
        st["notified_level"], st["last_sent"] = reg["level"], iso(now)
    for reg, st in downs:
        if st["notified_level"] >= n["min_level"]:
            messages.append({
                "topic": f"region-{reg['id']}", "kind": "baja",
                "title": f"{reg['name']}: baja a {LEVEL_NAMES[reg['level']]}",
                "body": "Las señales volvieron a valores habituales. Toca para ver detalles.",
                "region": reg["id"],
            })
            st["last_sent"] = iso(now)
        st["notified_level"], st["below_since"] = reg["level"], None
    for notice in officials:
        for rid in notice["regions"]:
            name = next((r["name"] for r in regions if r["id"] == rid), rid)
            messages.append({
                "topic": f"region-{rid}", "kind": "oficial",
                "title": f"{name}: comunicado del OIEA",
                "body": notice["title"][:150],
                "region": rid, "url": notice["url"],
            })
        sent_ids.add(notice["id"])
    state["sent_official_ids"] = sorted(sent_ids)[-500:]
    return messages, state, report
