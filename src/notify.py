"""
notify.py
=========
Outbound notifications about what the remediator did.

Two sinks, both OPTIONAL and independently toggled via config:
  - Slack   -> a short chat message (nice for on-call visibility).
  - Jira    -> an incident ticket (nice for the paper trail / post-mortems).

Design notes:
- If a sink isn't configured (empty env vars), we silently skip it. This keeps
  local dev friction-free — you don't need Slack/Jira creds to run the service.
- We NEVER let a notification failure crash remediation. Observability is a
  side-effect; a flaky Slack webhook must not block (or undo) a fix we already
  applied. So every send is wrapped and failures are swallowed into a result.
- `requests` is imported lazily so unit tests don't need the network stack and
  can inject a fake transport instead.
"""

from __future__ import annotations

from typing import Protocol

from .config import Settings
from .models import Alert
from .remediator import ActionResult


class NotifyResult:
    """Outcome of attempting to send one notification."""

    def __init__(self, channel: str, sent: bool, detail: str):
        self.channel = channel    # "slack" | "jira"
        self.sent = sent          # True if the remote accepted it
        self.detail = detail      # human-readable explanation / error / ref

    def __repr__(self) -> str:
        state = "SENT" if self.sent else "SKIPPED"
        return f"<NotifyResult {state} {self.channel}: {self.detail}>"

    def as_dict(self) -> dict:
        return {"channel": self.channel, "sent": self.sent, "detail": self.detail}


class HttpPoster(Protocol):
    """Minimal HTTP interface we need. The real one wraps `requests`."""

    def post(self, url: str, *, json: dict, headers: dict, auth: tuple | None,
             timeout: float) -> HttpResponse: ...


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> dict: ...


class RequestsHttpPoster:
    """Real HttpPoster backed by the `requests` library (imported lazily)."""

    def post(self, url: str, *, json: dict, headers: dict, auth: tuple | None,
             timeout: float):
        import requests  # lazy: tests inject a fake instead

        return requests.post(url, json=json, headers=headers, auth=auth,
                             timeout=timeout)


class Notifier:
    """Fans out an ActionResult to the configured notification channels."""

    def __init__(self, settings: Settings, http: HttpPoster | None = None):
        self._settings = settings
        self._http = http or RequestsHttpPoster()

    def notify(self, alert: Alert, result: ActionResult) -> list[NotifyResult]:
        """Send to every enabled channel; returns one result per channel."""
        results: list[NotifyResult] = []
        if self._settings.slack_enabled:
            results.append(self._send_slack(alert, result))
        if self._settings.jira_enabled:
            results.append(self._send_jira(alert, result))
        return results

    # ---- Slack ----
    def _send_slack(self, alert: Alert, result: ActionResult) -> NotifyResult:
        verb = "performed" if result.performed else "skipped"
        text = (
            f":rotating_light: *{alert.name}* ({alert.severity})\n"
            f"> {alert.summary}\n"
            f"Remediation *{verb}*: `{result.action}` on `{result.target}` — {result.detail}"
        )
        try:
            resp = self._http.post(
                self._settings.slack_webhook_url,
                json={"text": text},
                headers={"Content-Type": "application/json"},
                auth=None,
                timeout=5.0,
            )
            if 200 <= resp.status_code < 300:
                return NotifyResult("slack", True, "message posted")
            return NotifyResult("slack", False, f"slack returned HTTP {resp.status_code}")
        except Exception as exc:  # never let notification break remediation
            return NotifyResult("slack", False, f"slack error: {exc}")

    # ---- Jira ----
    def _send_jira(self, alert: Alert, result: ActionResult) -> NotifyResult:
        verb = "performed" if result.performed else "skipped"
        summary = f"[auto-remediation] {alert.name} on {result.target}"
        description = (
            f"Alert: {alert.name} (severity={alert.severity})\n"
            f"Summary: {alert.summary}\n"
            f"Remediation {verb}: {result.action} on {result.target}\n"
            f"Detail: {result.detail}"
        )
        payload = {
            "fields": {
                "project": {"key": self._settings.jira_project_key},
                "summary": summary,
                "description": description,
                "issuetype": {"name": "Incident"},
            }
        }
        url = self._settings.jira_base_url.rstrip("/") + "/rest/api/2/issue"
        try:
            resp = self._http.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                auth=(self._settings.jira_email, self._settings.jira_api_token),
                timeout=10.0,
            )
            if 200 <= resp.status_code < 300:
                key = ""
                try:
                    key = resp.json().get("key", "")
                except Exception:
                    pass
                return NotifyResult("jira", True, f"created issue {key}".strip())
            return NotifyResult("jira", False, f"jira returned HTTP {resp.status_code}")
        except Exception as exc:
            return NotifyResult("jira", False, f"jira error: {exc}")
