"""Red simulada con respuestas en el formato real de cada fuente (sin internet)."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures"
RADNET_HEADER = ("LOCATION_NAME,SAMPLE COLLECTION TIME,DOSE EQUIVALENT RATE (nSv/h),GAMMA COUNT RATE R02 (CPM),"
                 "GAMMA COUNT RATE R03 (CPM),GAMMA COUNT RATE R04 (CPM),GAMMA COUNT RATE R05 (CPM),GAMMA COUNT RATE R06 (CPM),"
                 "GAMMA COUNT RATE R07 (CPM),GAMMA COUNT RATE R08 (CPM),GAMMA COUNT RATE R09 (CPM),STATUS")


def wobble(i: int, base: float, amp: float) -> float:
    return round(base + amp * math.sin(i / 5.0) + amp * 0.5 * math.cos(i / 2.3), 2)


def radnet_csv(name: str, now: datetime, days: int = 40, spike_hours: int = 0, spike: float = 3.0) -> str:
    lines = [RADNET_HEADER]
    start = now - timedelta(days=days)
    hours = days * 24
    for i in range(hours):
        t = start + timedelta(hours=i, minutes=50)
        if t > now:
            break
        dose = wobble(i, 26.0, 1.5)
        if spike_hours and i >= hours - spike_hours:
            dose *= spike
        lines.append(f"{name},{t.strftime('%m/%d/%Y %H:%M:%S')},{dose:.2f},884.00,505.00,137.00,92.00,59.00,86.00,75.00,33.00,APPROVED")
    return "\n".join(lines) + "\n"


def safecast_json(now: datetime, devices=(101, 102), hours: int = 6) -> str:
    out = []
    for d in devices:
        for h in range(hours):
            t = now - timedelta(hours=h, minutes=10)
            out.append({"id": d * 1000 + h, "value": wobble(h + d, 35.0, 2.0), "unit": "cpm", "device_id": d,
                        "captured_at": t.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "latitude": 35.68, "longitude": 139.76,
                        "location_name": f"Sensor {d}"})
    return json.dumps(out)


def gdelt_json(now: datetime, days: int = 90, base: int = 40, last_two_mult: float = 1.0) -> str:
    data = []
    for i in range(days, -1, -1):
        d = (now - timedelta(days=i)).date()
        v = base + (i % 7)
        if i in (1, 2):
            v = int(v * last_two_mult)
        data.append({"date": d.strftime("%Y%m%dT000000Z"), "value": v, "norm": 90000})
    return json.dumps({"query_details": {}, "timeline": [{"series": "Article Count", "data": data}]})


class FakeNet:
    def __init__(self, now: datetime, radnet_spike: dict | None = None, gdelt_mult: dict | None = None, fail: set | None = None):
        self.now = now
        self.radnet_spike = radnet_spike or {}
        self.gdelt_mult = gdelt_mult or {}
        self.fail = fail or set()
        self.calls: list[str] = []

    def __call__(self, url: str, params: dict, timeout: int) -> str:
        self.calls.append(url)
        for f in self.fail:
            if f in url:
                raise ConnectionError(f"simulado: {f} caído")
        if "iaea.org/feeds" in url:
            return (FIX / "iaea_rss.xml").read_text(encoding="utf-8")
        if "safecast" in url:
            return safecast_json(self.now)
        if "radnet" in url:
            city = url.rsplit("/", 1)[-1]
            return radnet_csv(city, self.now, spike_hours=self.radnet_spike.get(city, 0))
        if "gdeltproject" in url:
            q = params.get("query", "")
            mult = next((m for key, m in self.gdelt_mult.items() if key in q), 1.0)
            return gdelt_json(self.now, last_two_mult=mult)
        raise ValueError(url)
