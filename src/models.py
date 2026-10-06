"""
models.py
=========
Typed models describing the JSON that Prometheus **Alertmanager** POSTs to a
webhook receiver. Using Pydantic gives us automatic validation + clear errors
if the payload is malformed.

Reference: Alertmanager sends a payload shaped like:
{
  "version": "4",
  "status": "firing",                # or "resolved"
  "alerts": [
    {
      "status": "firing",
      "labels":      {"alertname": "...", "severity": "...", "namespace": "...", ...},
      "annotations": {"summary": "...", "action": "restart_pod", ...},
      "startsAt": "2026-10-06T12:00:00Z",
      ...
    }
  ]
}

We only model the fields we actually use and allow extras to pass through.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Alert(BaseModel):
    """A single alert inside the Alertmanager webhook payload."""

    # Allow (and ignore) any extra fields Alertmanager includes.
    model_config = ConfigDict(extra="allow")

    status: str = "firing"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)

    # --- Convenience accessors (keep the rest of the code readable) ---
    @property
    def name(self) -> str:
        return self.labels.get("alertname", "UnknownAlert")

    @property
    def severity(self) -> str:
        return self.labels.get("severity", "none")

    @property
    def namespace(self) -> str:
        # Fall back to "default" if the alert didn't carry a namespace label.
        return self.labels.get("namespace", "default")

    @property
    def deployment(self) -> str | None:
        # Different exporters use different label names — check the common ones.
        return (
            self.labels.get("deployment")
            or self.labels.get("deployment_name")
            or None
        )

    @property
    def pod(self) -> str | None:
        return self.labels.get("pod") or self.labels.get("pod_name") or None

    @property
    def requested_action(self) -> str | None:
        """
        The runbook action to run. We read it from an annotation so alert authors
        declare intent explicitly, e.g. annotations: { action: "restart_pod" }.
        """
        action = self.annotations.get("action")
        return action.strip() if action else None

    @property
    def summary(self) -> str:
        return self.annotations.get("summary", self.name)


class AlertmanagerWebhook(BaseModel):
    """The top-level object Alertmanager POSTs to our /webhook endpoint."""

    model_config = ConfigDict(extra="allow")

    version: str = "4"
    status: str = "firing"
    alerts: list[Alert] = Field(default_factory=list)
