"""Comunicados oficiales del OIEA (IAEA) vía RSS.

El modelo NO interpreta los comunicados: solo los asocia a una región por
nombres geográficos y marca como "incidente" los que contienen palabras de
incidente. El texto se muestra tal cual, con enlace al original.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from common import Http, parse_iso

ATOM = "{http://www.w3.org/2005/Atom}"


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _text(el, *names) -> str:
    """Busca hijos por nombre local, sin importar el espacio de nombres (RSS 2.0, RSS 1.0/RDF o Atom)."""
    wanted = [_local(n) for n in names]
    children = list(el)
    for name in wanted:
        for found in children:
            if _local(found.tag) != name:
                continue
            if found.text and found.text.strip():
                return found.text.strip()
            href = found.get("href") or found.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about")
            if href:
                return href.strip()
    return ""


def _date(value: str) -> datetime | None:
    if not value:
        return None
    value = " ".join(value.split())
    # El feed del OIEA usa "AA-MM-DD HH:MM" (ej. "26-11-06 14:46"), hora de Viena: se trata como UTC
    # (error máximo de 1-2 h, irrelevante para una ventana de 7 días).
    m = re.fullmatch(r"(\d{2})-(\d{2})-(\d{2}) (\d{1,2}):(\d{2})", value)
    if m:
        y, mo, d, h, mi = (int(x) for x in m.groups())
        try:
            return datetime(2000 + y, mo, d, h, mi, tzinfo=timezone.utc)
        except ValueError:
            return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = parse_iso(value)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


def parse_feed(xml_text: str, feed_name: str) -> list[dict]:
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    items = [el for el in root.iter() if _local(el.tag) in ("item", "entry")]
    out = []
    for it in items:
        title = _text(it, "title", f"{ATOM}title")
        link = _text(it, "link", f"{ATOM}link")
        published = _date(_text(it, "pubDate", f"{ATOM}published", f"{ATOM}updated", "{http://purl.org/dc/elements/1.1/}date"))
        summary = _strip_html(_text(it, "description", f"{ATOM}summary", f"{ATOM}content"))[:400]
        if not title or not link or not published:
            continue
        out.append({
            "id": hashlib.sha1(link.encode()).hexdigest()[:12],
            "source": "IAEA",
            "feed": feed_name,
            "title": title,
            "summary": summary,
            "url": link,
            "published": published,
        })
    return out


def _contains(text: str, words: list[str]) -> list[str]:
    low = text.lower()
    return [w for w in words if re.search(r"(?<![a-záéíóúñ])" + re.escape(w.lower()), low)]


def classify(items: list[dict], regions: list[dict], incident_keywords: list[str]) -> list[dict]:
    """Asocia cada comunicado a regiones y decide si es un incidente."""
    out = []
    for item in items:
        text = f"{item['title']} {item['summary']}"
        region_ids = [r["id"] for r in regions if _contains(text, r.get("names", []))]
        if not region_ids:
            continue
        hits = _contains(text, incident_keywords)
        out.append({**item, "regions": region_ids, "kind": "incident" if hits else "statement", "matched": hits})
    return out


def fetch(http: Http, cfg: dict, regions: list[dict], rules: dict, now: datetime) -> list[dict]:
    seen: dict[str, dict] = {}
    errors = []
    for name, url in cfg["feeds"].items():
        try:
            text = http.get(url)
            items = parse_feed(text, name)
            if not items:
                errors.append(f"{name}: 0 elementos; inicio de la respuesta: {text[:160]!r}")
            for item in items:
                seen.setdefault(item["id"], item)
        except Exception as exc:  # noqa: BLE001 - un feed caído no detiene a los demás
            errors.append(f"{name}: {exc}")
    if errors and not seen:
        raise RuntimeError(" | ".join(errors))
    cutoff = now - timedelta(days=int(cfg.get("max_age_days", 30)))
    recent = [i for i in seen.values() if i["published"] >= cutoff]
    return classify(recent, regions, rules["official"]["incident_keywords"]), len(seen)
