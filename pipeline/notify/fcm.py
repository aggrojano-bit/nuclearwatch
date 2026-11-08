"""Envío a Firebase Cloud Messaging (API HTTP v1) por tema.

Solo se usa cuando `notifications.enabled` es true y existe el secreto
FCM_SERVICE_ACCOUNT (JSON de la cuenta de servicio de Firebase).
"""
from __future__ import annotations

import json
import os


def send(messages: list[dict]) -> list[str]:
    raw = os.environ.get("FCM_SERVICE_ACCOUNT")
    if not raw or not messages:
        return []
    import requests
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
    creds.refresh(Request())
    url = f"https://fcm.googleapis.com/v1/projects/{info['project_id']}/messages:send"
    errors = []
    for m in messages:
        payload = {"message": {
            "topic": m["topic"],
            "notification": {"title": m["title"], "body": m["body"]},
            "data": {k: str(v) for k, v in m.items() if k in ("region", "kind", "url")},
            "android": {"priority": "high" if m["kind"] == "oficial" else "normal"},
        }}
        resp = requests.post(url, json=payload, timeout=30, headers={"Authorization": f"Bearer {creds.token}"})
        if resp.status_code >= 300:
            errors.append(f"{m['topic']}: {resp.status_code} {resp.text[:200]}")
    return errors
