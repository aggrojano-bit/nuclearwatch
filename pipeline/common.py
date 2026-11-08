"""Utilidades compartidas: configuración, tiempo UTC y un cliente HTTP inyectable.

Todo acceso a red pasa por `Http.get`, así las pruebas reemplazan la red por
archivos grabados y nunca consultan las fuentes reales.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def load_yaml(name: str, config_dir: Path = CONFIG_DIR) -> dict:
    with open(config_dir / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    value = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def hours_ago(dt: datetime, now: datetime) -> float:
    return (now - dt) / timedelta(hours=1)


def read_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    tmp.replace(path)


class FetchError(Exception):
    pass


@dataclass
class Http:
    """Cliente HTTP mínimo con reintentos. `transport` permite simular la red."""

    user_agent: str = "NuclearWatch/0.1"
    timeout: int = 30
    retries: int = 2
    transport: Callable[[str, dict, int], str] | None = None
    min_interval: dict[str, float] = field(default_factory=dict)
    _last_call: dict[str, float] = field(default_factory=dict)
    sleep: Callable[[float], None] = time.sleep

    def get(self, url: str, params: dict | None = None, throttle_key: str | None = None) -> str:
        params = params or {}
        if throttle_key and throttle_key in self.min_interval:
            wait = self.min_interval[throttle_key] - (time.monotonic() - self._last_call.get(throttle_key, 0))
            if wait > 0:
                self.sleep(wait)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                if self.transport:
                    text = self.transport(url, params, self.timeout)
                else:
                    text = self._real_get(url, params)
                if throttle_key:
                    self._last_call[throttle_key] = time.monotonic()
                return text
            except Exception as exc:  # noqa: BLE001 - se reintenta cualquier fallo de red
                last_error = exc
                if attempt < self.retries:
                    self.sleep(2 * (attempt + 1))
        raise FetchError(f"{url}: {last_error}")

    def _real_get(self, url: str, params: dict) -> str:
        import requests

        resp = requests.get(url, params=params, timeout=self.timeout, headers={"User-Agent": self.user_agent})
        resp.raise_for_status()
        return resp.text


def make_http(sources_cfg: dict) -> Http:
    return Http(
        user_agent=sources_cfg.get("user_agent", "NuclearWatch/0.1"),
        timeout=int(sources_cfg.get("timeout_seconds", 30)),
        retries=int(sources_cfg.get("retries", 2)),
        min_interval={"gdelt": float(sources_cfg["gdelt"].get("seconds_between_requests", 6))},
    )
