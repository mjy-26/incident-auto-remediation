"""
test_app.py
===========
Integration-ish tests for the FastAPI webhook using the TestClient and a
Remediator/Notifier built on fakes — the full request path, no cluster/network.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.app import create_app
from src.config import Settings
from src.notify import Notifier
from src.remediator import Remediator

from .fakes import FakeHttpPoster, FakeKubernetesClient, FakeResponse


def _client(kube: FakeKubernetesClient, settings: Settings,
            http: FakeHttpPoster) -> TestClient:
    remediator = Remediator(kube, settings)
    notifier = Notifier(settings, http=http)
    app = create_app(remediator=remediator, notifier=notifier)
    return TestClient(app)


def _settings(**overrides) -> Settings:
    base = dict(
        dry_run=False,
        allowed_namespaces=["demo"],
        allowed_actions=["restart_pod", "scale_deployment"],
        max_actions_per_min=5,
        slack_webhook_url="",
        jira_base_url="",
    )
    base.update(overrides)
    return Settings(**base)


def _payload(action: str = "restart_pod", status: str = "firing") -> dict:
    return {
        "version": "4",
        "status": "firing",
        "alerts": [
            {
                "status": status,
                "labels": {
                    "alertname": "HighErrorRate",
                    "severity": "critical",
                    "namespace": "demo",
                    "pod": "checkout-abc",
                    "deployment": "checkout",
                },
                "annotations": {"summary": "errors spiking", "action": action},
            }
        ],
    }


def test_healthz():
    client = _client(FakeKubernetesClient(), _settings(), FakeHttpPoster())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_webhook_restarts_pod():
    kube = FakeKubernetesClient()
    client = _client(kube, _settings(), FakeHttpPoster())

    resp = client.post("/webhook", json=_payload(action="restart_pod"))

    assert resp.status_code == 200
    body = resp.json()
    assert body["received"] == 1
    assert body["handled"][0]["result"]["performed"] is True
    assert kube.deleted_pods == [("demo", "checkout-abc")]


def test_webhook_skips_resolved_alerts():
    kube = FakeKubernetesClient()
    client = _client(kube, _settings(), FakeHttpPoster())

    resp = client.post("/webhook", json=_payload(status="resolved"))

    body = resp.json()
    assert body["handled"][0]["skipped"] is True
    assert kube.deleted_pods == []


def test_webhook_fires_notifications():
    kube = FakeKubernetesClient()
    http = FakeHttpPoster(response=FakeResponse(200))
    settings = _settings(slack_webhook_url="https://hooks.slack.test/abc")
    client = _client(kube, settings, http)

    resp = client.post("/webhook", json=_payload())

    body = resp.json()
    notifications = body["handled"][0]["notifications"]
    assert any(n["channel"] == "slack" and n["sent"] for n in notifications)
    assert len(http.calls) == 1


def test_index_reports_safety_posture():
    client = _client(FakeKubernetesClient(), _settings(), FakeHttpPoster())
    resp = client.get("/")
    assert resp.status_code == 200
    assert "dry_run" in resp.json()
