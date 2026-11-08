"""Pruebas sin red: cada fuente, cada regla y el pipeline completo."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from common import Http, iso, load_yaml
from fakenet import FakeNet, gdelt_json, radnet_csv
from notify.rules import plan
from run import run
from scoring.levels import score
from signals import media as media_signal
from signals import radiation
from signals.stats import robust_z
from sources import epa_radnet, gdelt, iaea_rss, safecast

NOW = datetime(2026, 11, 5, 15, 30, tzinfo=timezone.utc)
RULES = load_yaml("rules.yaml")
REGIONS = load_yaml("regions.yaml")["regions"]


def fake_http(net):
    return Http(transport=net, retries=0, sleep=lambda s: None)


# ---------- estadística ----------
def test_robust_z_basic():
    base = [10, 11, 9, 10, 10, 11, 9]
    assert abs(robust_z(10, base)) < 0.01
    assert robust_z(20, base) > 4


def test_robust_z_flat_baseline_uses_floor():
    # datos totalmente planos: MAD=0, el piso evita z infinito
    assert robust_z(10.2, [10] * 50) < 1


# ---------- fuentes ----------
def test_radnet_parse_real_format():
    text = radnet_csv("DC: WASHINGTON", NOW, days=2)
    name, unit, pts = epa_radnet.parse_csv(text)
    assert name == "DC: WASHINGTON" and unit == "nSv/h"
    assert pts[0][0].tzinfo is not None and len(pts) >= 40


def test_radnet_url_encoding():
    url = epa_radnet.station_url("https://x/{year}/fixed/{state}/{city}", 2026, "NY", "NYC (EML)")
    assert url.endswith("/NY/NYC%20%28EML%29")


def test_iaea_parse_and_classify():
    items = iaea_rss.parse_feed((__import__("fakenet").FIX / "iaea_rss.xml").read_text(), "topnews")
    assert len(items) == 4
    out = {i["url"].rsplit("/", 1)[-1]: i for i in iaea_rss.classify(items, REGIONS, RULES["official"]["incident_keywords"])}
    assert out["zaporizhzhia-update"]["kind"] == "incident"
    assert out["zaporizhzhia-update"]["regions"] == ["europa-oriental"]
    assert out["chile-honey"]["kind"] == "statement" and out["chile-honey"]["regions"] == ["sudamerica"]
    assert "rwanda" not in out  # sin región del MVP


def test_iaea_fetch_filters_old_items():
    notices, raw = iaea_rss.fetch(fake_http(FakeNet(NOW)), {"feeds": {"a": "https://www.iaea.org/feeds/topnews"}, "max_age_days": 30}, REGIONS, RULES, NOW)
    assert raw == 4
    assert not any("iran-old" in n["url"] for n in notices)


def test_safecast_parse_and_state():
    from fakenet import safecast_json
    readings = safecast.parse_measurements(safecast_json(NOW))
    assert len(readings) == 12
    state = safecast.merge_state({}, "asia-oriental", safecast.hourly(readings), NOW, 31)
    series = safecast.to_series(state["asia-oriental"])
    assert len(series) == 2 and all(len(s["points"]) == 6 for s in series)


def test_gdelt_parse():
    days = gdelt.parse_timeline(gdelt_json(NOW))
    assert len(days) == 91 and all("count" in v for v in days.values())


# ---------- señales ----------
def _series(values, step_h=1, end=NOW):
    n = len(values)
    return {"station_id": "s", "source": "X", "name": "S", "unit": "nSv/h",
            "points": [(end - timedelta(hours=step_h * (n - 1 - i)), v) for i, v in enumerate(values)]}


def test_station_learning_without_baseline():
    assert radiation.evaluate_station(_series([26] * 10), RULES, NOW)["status"] == "aprendiendo"


def test_station_normal_and_anomalous():
    base = [26 + (i % 5) * 0.4 for i in range(300)]
    assert radiation.evaluate_station(_series(base + [26.5, 26.3]), RULES, NOW)["status"] == "normal"
    assert radiation.evaluate_station(_series(base + [60, 62]), RULES, NOW)["status"] == "anomala"


def test_single_high_reading_is_not_anomalous():
    base = [26 + (i % 5) * 0.4 for i in range(300)]
    assert radiation.evaluate_station(_series(base + [26.4, 80]), RULES, NOW)["status"] == "normal"


def test_stale_station():
    st = radiation.evaluate_station(_series([26] * 300, end=NOW - timedelta(hours=10)), RULES, NOW)
    assert st["status"] == "desactualizada"


def test_media_signal():
    calm = media_signal.evaluate(gdelt.parse_timeline(gdelt_json(NOW)), RULES, NOW)
    assert calm["status"] == "normal" and not calm["active"]
    hot = media_signal.evaluate(gdelt.parse_timeline(gdelt_json(NOW, last_two_mult=4)), RULES, NOW)
    assert hot["active"]
    tiny = media_signal.evaluate(gdelt.parse_timeline(gdelt_json(NOW, base=2, last_two_mult=5)), RULES, NOW)
    assert not tiny["active"]  # volumen mínimo no alcanzado


# ---------- niveles ----------
def _st(status, source="EPA RadNet"):
    return {"station_id": status, "source": source, "name": "N", "unit": "nSv/h", "status": status,
            "last_time": iso(NOW - timedelta(hours=1)), "last_value": 60.0, "z": 9.0, "baseline_median": 26.0}


def _score(stations, media):
    reg = REGIONS[0]
    return score(reg, stations, radiation.region_signal(stations, RULES), media, [], RULES, NOW)


MEDIA_ON = {"status": "activa", "active": True, "recent": [200, 210], "ratio": 4.5, "last_day": "2026-11-04"}
MEDIA_OFF = {"status": "normal", "active": False, "recent": [40, 41], "ratio": 1.0, "last_day": "2026-11-04"}


def test_media_alone_capped_at_level_1():
    assert _score([_st("normal")], MEDIA_ON)["level"] == 1


def test_single_station_is_level_1():
    assert _score([_st("anomala"), _st("normal")], MEDIA_OFF)["level"] == 1


def test_two_stations_level_2_and_with_media_level_3():
    assert _score([_st("anomala"), _st("anomala")], MEDIA_OFF)["level"] == 2
    r = _score([_st("anomala"), _st("anomala")], MEDIA_ON)
    assert r["level"] == 3 and r["confidence"] == "alta"


def test_no_data_is_low_confidence_with_note():
    r = _score([], {"status": "sin_datos", "active": False})
    assert r["level"] == 0 and r["confidence"] == "baja" and r["notes"]


# ---------- notificaciones ----------
def _reg(rid, level, anomalous=2):
    return {"id": rid, "name": rid, "level": level, "level_name": "Elevado",
            "radiation": {"anomalous": anomalous}, "media": {"status": "normal"}}


def test_notification_requires_persistence_and_respects_cooldown():
    state = {}
    msgs, state, _ = plan([_reg("a", 2)], [], state, RULES, NOW)
    assert msgs == []  # primera ejecución: aún no persiste
    msgs, state, _ = plan([_reg("a", 2)], [], state, RULES, NOW + timedelta(hours=1))
    assert len(msgs) == 1 and msgs[0]["topic"] == "region-a"
    msgs, state, _ = plan([_reg("a", 3)], [], state, RULES, NOW + timedelta(hours=2))
    msgs, state, _ = plan([_reg("a", 3)], [], state, RULES, NOW + timedelta(hours=3))
    assert msgs == []  # enfriamiento de 12 h


def test_level_1_never_notifies():
    state = {}
    for h in range(5):
        msgs, state, _ = plan([_reg("a", 1, 1)], [], state, RULES, NOW + timedelta(hours=h))
        assert msgs == []


def test_downgrade_after_hold():
    state = {}
    for h in range(2):
        _, state, _ = plan([_reg("a", 2)], [], state, RULES, NOW + timedelta(hours=h))
    msgs, state, _ = plan([_reg("a", 0, 0)], [], state, RULES, NOW + timedelta(hours=3))
    assert msgs == []
    msgs, state, _ = plan([_reg("a", 0, 0)], [], state, RULES, NOW + timedelta(hours=28))
    assert len(msgs) == 1 and msgs[0]["kind"] == "baja"


def test_breaker_blocks_everything():
    regs = [_reg(f"r{i}", 2) for i in range(4)]
    state = {}
    plan(regs, [], state, RULES, NOW)
    msgs, state, rep = plan(regs, [], state, RULES, NOW + timedelta(hours=1))
    assert msgs == [] and rep["breaker_tripped"]


def test_official_notice_sent_once():
    notice = {"id": "x1", "kind": "incident", "regions": ["a"], "title": "t", "url": "u"}
    msgs, state, _ = plan([_reg("a", 0, 0)], [notice], {}, RULES, NOW)
    assert len(msgs) == 1 and msgs[0]["kind"] == "oficial"
    msgs, state, _ = plan([_reg("a", 0, 0)], [notice], state, RULES, NOW + timedelta(hours=1))
    assert msgs == []


# ---------- pipeline completo ----------
def test_full_run_calm(tmp_path):
    summary = run(tmp_path, http=fake_http(FakeNet(NOW)), now=NOW)
    latest = json.loads((tmp_path / "latest.json").read_text())
    assert set(summary["levels"].values()) == {0}
    assert all(v["ok"] for v in latest["sources"].values())
    assert len(latest["regions"]) == 8 and "disclaimer" in latest
    alerts = json.loads((tmp_path / "alerts.json").read_text())["alerts"]
    assert alerts[0]["kind"] == "incident"
    eo = next(r for r in latest["regions"] if r["id"] == "europa-oriental")
    assert eo["official_alert"] is True and eo["level"] == 0  # la alerta oficial no altera el nivel
    na = json.loads((tmp_path / "regions/norteamerica/detail.json").read_text())
    assert na["radiation"]["evaluated"] == 8 and na["confidence"] == "media"
    assert latest["sources"]["gdelt"]["items"] == 2  # solo 2 regiones consultadas por ejecución
    assert na["context"] == []  # contexto sin verificar no se publica


def test_full_run_source_failure_still_publishes(tmp_path):
    run(tmp_path, http=fake_http(FakeNet(NOW, fail={"gdeltproject"})), now=NOW)
    latest = json.loads((tmp_path / "latest.json").read_text())
    assert latest["sources"]["gdelt"]["ok"] is False and latest["sources"]["iaea"]["ok"] is True


def test_full_run_radiation_event_then_dry_run_notification(tmp_path):
    net = FakeNet(NOW, radnet_spike={"WASHINGTON": 3, "HOUSTON": 3})
    s1 = run(tmp_path, http=fake_http(net), now=NOW)
    assert s1["levels"]["norteamerica"] == 2
    s2 = run(tmp_path, http=fake_http(net), now=NOW + timedelta(minutes=5))
    assert s2["levels"]["norteamerica"] == 2 and s2["messages"] >= 1 and s2["sent"] is False
    outbox = json.loads((tmp_path / "state/outbox.json").read_text())
    assert any(m["region"] == "norteamerica" and m["kind"] == "nivel" for m in outbox)
    hist = json.loads((tmp_path / "regions/norteamerica/history.json").read_text())
    assert len(hist["points"]) == 1  # misma hora: se reemplaza, no se duplica


@pytest.mark.parametrize("bad", ["", "<html>error</html>"])
def test_gdelt_bad_response_raises(bad):
    net = lambda url, params, t: bad  # noqa: E731
    with pytest.raises(Exception):
        gdelt.fetch(fake_http(net), load_yaml("sources.yaml")["gdelt"], REGIONS[0])


def test_gdelt_rotation_covers_all_regions(tmp_path):
    net = FakeNet(NOW)
    for h in range(4):
        run(tmp_path, http=fake_http(net), now=NOW + timedelta(hours=h))
    latest = json.loads((tmp_path / "latest.json").read_text())
    assert latest["sources"]["gdelt"]["items"] == 8
    assert sum("gdeltproject" in c for c in net.calls) == 8  # sin consultas repetidas
    run(tmp_path, http=fake_http(net), now=NOW + timedelta(hours=4))
    assert sum("gdeltproject" in c for c in net.calls) == 8  # caché vigente (< 6 h)


def test_gdelt_429_stops_and_keeps_cache(tmp_path):
    run(tmp_path, http=fake_http(FakeNet(NOW)), now=NOW)
    net = FakeNet(NOW, fail={"gdeltproject"})
    run(tmp_path, http=fake_http(net), now=NOW + timedelta(hours=7))
    latest = json.loads((tmp_path / "latest.json").read_text())
    assert latest["sources"]["gdelt"]["items"] == 2  # las 2 regiones en caché siguen sirviendo


def test_safecast_point_failure_does_not_drop_region():
    calls = {"n": 0}
    from fakenet import safecast_json
    def net(url, params, t):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("lento")
        return safecast_json(NOW)
    reg = next(r for r in REGIONS if r["id"] == "asia-oriental")
    readings, errs = safecast.fetch(fake_http(net), load_yaml("sources.yaml")["safecast"], reg, NOW)
    assert len(errs) == 1 and len(readings) > 0
