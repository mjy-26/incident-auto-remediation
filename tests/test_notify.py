"""
test_notify.py
==============
Unit tests for the Slack/Jira notifier using a FakeHttpPoster — no real network.
"""

from __future__ import annotations

from src.config import Settings
from src.models import Alert
from src.notify import Notifier
from src.remediator import ActionResult

from .fakes import FakeHttpPoster, FakeResponse


def _alert() -> Alert:
    return Alert(
        status="firing",
        labels={"alertname": "HighErrorRate", "severity": "critical", "namespace": "demo"},
        annotations={"summary": "errors spiking", "action": "restart_pod"},
    )


def _result() -> ActionResult:
    return ActionResult("restart_pod", "demo/checkout-abc", True, "deleted pod")


def test_no_channels_configured_sends_nothing():
    http = FakeHttpPoster()
    settings = Settings(slack_webhook_url="", jira_base_url="")
    notifier = Notifier(settings, http=http)

    results = notifier.notify(_alert(), _result())

    assert results == []
    assert http.calls == []


def test_slack_enabled_posts_message():
    http = FakeHttpPoster(response=FakeResponse(200))
    settings = Settings(slack_webhook_url="https://hooks.slack.test/abc")
    notifier = Notifier(settings, http=http)

    results = notifier.notify(_alert(), _result())

    assert len(results) == 1
    assert results[0].channel == "slack"
    assert results[0].sent is True
    assert http.calls[0]["url"] == "https://hooks.slack.test/abc"
    assert "HighErrorRate" in http.calls[0]["json"]["text"]


def test_slack_http_error_is_not_fatal():
    http = FakeHttpPoster(response=FakeResponse(500))
    settings = Settings(slack_webhook_url="https://hooks.slack.test/abc")
    notifier = Notifier(settings, http=http)

    results = notifier.notify(_alert(), _result())

    assert results[0].sent is False
    assert "HTTP 500" in results[0].detail


def test_slack_exception_is_swallowed():
    http = FakeHttpPoster(raise_exc=RuntimeError("boom"))
    settings = Settings(slack_webhook_url="https://hooks.slack.test/abc")
    notifier = Notifier(settings, http=http)

    results = notifier.notify(_alert(), _result())

    assert results[0].sent is False
    assert "boom" in results[0].detail


def test_jira_enabled_creates_issue():
    http = FakeHttpPoster(response=FakeResponse(201, {"key": "OPS-42"}))
    settings = Settings(
        jira_base_url="https://jira.test",
        jira_email="bot@test.io",
        jira_api_token="token",
        jira_project_key="OPS",
    )
    notifier = Notifier(settings, http=http)

    results = notifier.notify(_alert(), _result())

    assert len(results) == 1
    assert results[0].channel == "jira"
    assert results[0].sent is True
    assert "OPS-42" in results[0].detail
    call = http.calls[0]
    assert call["url"] == "https://jira.test/rest/api/2/issue"
    assert call["auth"] == ("bot@test.io", "token")
    assert call["json"]["fields"]["project"]["key"] == "OPS"


def test_both_channels_fire_when_both_enabled():
    http = FakeHttpPoster(response=FakeResponse(200, {"key": "OPS-1"}))
    settings = Settings(
        slack_webhook_url="https://hooks.slack.test/abc",
        jira_base_url="https://jira.test",
        jira_email="bot@test.io",
        jira_api_token="token",
    )
    notifier = Notifier(settings, http=http)

    results = notifier.notify(_alert(), _result())

    channels = {r.channel for r in results}
    assert channels == {"slack", "jira"}
    assert len(http.calls) == 2
