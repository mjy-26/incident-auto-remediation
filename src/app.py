"""
app.py
======
The HTTP entrypoint. Prometheus **Alertmanager** POSTs firing/resolved alerts
to our `/webhook` endpoint; for each *firing* alert we:

  1. Parse + validate the payload (models.AlertmanagerWebhook).
  2. Run it through the Remediator (allowlist + blast-radius + rate-limit + dry-run).
  3. Notify the configured channels (Slack / Jira) about what happened.

Endpoints:
  GET  /healthz   -> liveness/readiness probe (always cheap, no side-effects).
  GET  /          -> tiny status page showing the active safety settings.
  POST /webhook   -> the Alertmanager receiver.

Dependency wiring:
- We build ONE Remediator and ONE Notifier at startup and reuse them. The
  Remediator holds the rate-limit sliding window, so it must be a singleton.
- The real Kubernetes client is only constructed if DRY_RUN is off, so you can
  boot and test the webhook locally with no cluster at all.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import settings
from .models import AlertmanagerWebhook
from .notify import Notifier
from .remediator import KubeClient, Remediator


def _build_kube_client() -> KubeClient:
    """
    Construct the client the Remediator will call.

    In DRY_RUN we never touch a cluster, so we hand back a no-op client. This
    lets the service run anywhere (CI, laptop) without a kubeconfig.
    """
    if settings.dry_run:
        return _NoopKubeClient()
    from .kube import RealKubernetesClient

    return RealKubernetesClient(settings)


class _NoopKubeClient:
    """A KubeClient that does nothing — used when DRY_RUN is on."""

    def delete_pod(self, namespace: str, pod: str) -> None:  # pragma: no cover
        return None

    def scale_deployment(self, namespace: str, deployment: str, replicas: int) -> None:  # pragma: no cover
        return None

    def get_deployment_replicas(self, namespace: str, deployment: str) -> int:  # pragma: no cover
        return 0


def create_app(remediator: Remediator | None = None,
               notifier: Notifier | None = None) -> FastAPI:
    """
    Application factory. Tests can inject a Remediator/Notifier built on fakes;
    production calls it with no args and gets the real wiring.
    """
    app = FastAPI(title="Incident Auto-Remediation", version="0.1.0")

    # Build the singletons once (unless injected for tests).
    _remediator = remediator or Remediator(_build_kube_client(), settings)
    _notifier = notifier or Notifier(settings)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/")
    def index() -> dict:
        # Surface the safety posture so operators can see it at a glance.
        return {
            "service": "incident-auto-remediation",
            "dry_run": settings.dry_run,
            "allowed_actions": settings.allowed_actions,
            "allowed_namespaces": settings.allowed_namespaces,
            "max_actions_per_min": settings.max_actions_per_min,
            "slack_enabled": settings.slack_enabled,
            "jira_enabled": settings.jira_enabled,
        }

    @app.post("/webhook")
    async def webhook(request: Request) -> JSONResponse:
        raw = await request.json()
        payload = AlertmanagerWebhook.model_validate(raw)

        handled = []
        for alert in payload.alerts:
            # Only act on firing alerts; "resolved" needs no remediation.
            if alert.status != "firing":
                handled.append({
                    "alert": alert.name,
                    "skipped": True,
                    "reason": f"status={alert.status}",
                })
                continue

            result = _remediator.handle(alert)
            notifications = _notifier.notify(alert, result)
            handled.append({
                "alert": alert.name,
                "result": result.as_dict(),
                "notifications": [n.as_dict() for n in notifications],
            })

        return JSONResponse({"received": len(payload.alerts), "handled": handled})

    return app


# The ASGI app uvicorn serves: `uvicorn src.app:app`
app = create_app()
