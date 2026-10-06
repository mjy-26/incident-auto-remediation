"""
remediator.py
=============
Executes runbook actions against Kubernetes.

Design choice (important for testability):
- `KubernetesClient` is a THIN wrapper around the official k8s client.
- Our `Remediator` depends on a small PROTOCOL (interface), not the real client.
- In tests we pass a `FakeKubernetesClient` — so we can unit-test all the logic
  (allowlists, dry-run, rate limiting) WITHOUT a real cluster.

This is dependency injection: the business logic doesn't care whether it's
talking to a real cluster or a fake one.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Protocol

from .config import Settings
from .models import Alert


class ActionResult:
    """Outcome of attempting one remediation action."""

    def __init__(self, action: str, target: str, performed: bool, detail: str):
        self.action = action          # e.g. "restart_pod"
        self.target = target          # e.g. "demo/checkout-abc123"
        self.performed = performed    # True if we actually changed something
        self.detail = detail          # human-readable explanation

    def __repr__(self) -> str:
        state = "PERFORMED" if self.performed else "SKIPPED"
        return f"<ActionResult {state} {self.action} {self.target}: {self.detail}>"

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "target": self.target,
            "performed": self.performed,
            "detail": self.detail,
        }


class KubeClient(Protocol):
    """Minimal interface the Remediator needs. Both the real and fake implement it."""

    def delete_pod(self, namespace: str, pod: str) -> None: ...
    def scale_deployment(self, namespace: str, deployment: str, replicas: int) -> None: ...
    def get_deployment_replicas(self, namespace: str, deployment: str) -> int: ...


class Remediator:
    """
    Turns an Alert into a safe, rate-limited, allowlisted Kubernetes action.

    The ORDER of safety checks matters:
      1. Is the action on our allowlist?
      2. Is the namespace allowed (blast radius)?
      3. Are we under the rate limit?
      4. Is DRY_RUN off? (if on, we log but don't act)
    """

    def __init__(self, kube: KubeClient, settings: Settings):
        self._kube = kube
        self._settings = settings
        # Sliding window of timestamps of actions we actually performed.
        self._recent_actions: deque[float] = deque()

    # ---- public entrypoint ----
    def handle(self, alert: Alert) -> ActionResult:
        action = alert.requested_action

        if not action:
            return ActionResult("none", alert.namespace, False,
                                "alert carried no 'action' annotation")

        # 1) allowlist of actions
        if action not in self._settings.allowed_actions:
            return ActionResult(action, alert.namespace, False,
                                f"action '{action}' not in allowlist")

        # 2) namespace blast-radius guard
        if alert.namespace not in self._settings.allowed_namespaces:
            return ActionResult(action, alert.namespace, False,
                                f"namespace '{alert.namespace}' not allowed")

        # 3) rate limit
        if not self._under_rate_limit():
            return ActionResult(action, alert.namespace, False,
                                "rate limit reached — refusing to act")

        # 4) dry-run?
        if self._settings.dry_run:
            return ActionResult(action, alert.namespace, False,
                                f"DRY_RUN: would run '{action}'")

        # ---- actually do the work ----
        return self._dispatch(action, alert)

    # ---- internal helpers ----
    def _dispatch(self, action: str, alert: Alert) -> ActionResult:
        if action == "restart_pod":
            return self._restart_pod(alert)
        if action == "scale_deployment":
            return self._scale_deployment(alert)
        # Shouldn't happen (allowlist guards it) but be defensive.
        return ActionResult(action, alert.namespace, False, "no handler for action")

    def _restart_pod(self, alert: Alert) -> ActionResult:
        if not alert.pod:
            return ActionResult("restart_pod", alert.namespace, False,
                                "no 'pod' label on alert")
        # Deleting a pod managed by a Deployment makes K8s recreate it = a restart.
        self._kube.delete_pod(alert.namespace, alert.pod)
        self._record_action()
        target = f"{alert.namespace}/{alert.pod}"
        return ActionResult("restart_pod", target, True, "deleted pod to trigger restart")

    def _scale_deployment(self, alert: Alert) -> ActionResult:
        if not alert.deployment:
            return ActionResult("scale_deployment", alert.namespace, False,
                                "no 'deployment' label on alert")
        current = self._kube.get_deployment_replicas(alert.namespace, alert.deployment)
        desired = current + 1  # simple scale-out by one; real runbooks vary
        self._kube.scale_deployment(alert.namespace, alert.deployment, desired)
        self._record_action()
        target = f"{alert.namespace}/{alert.deployment}"
        return ActionResult("scale_deployment", target, True,
                            f"scaled {current} -> {desired} replicas")

    def _under_rate_limit(self) -> bool:
        """Sliding-window rate limit: count actions in the last 60 seconds."""
        now = time.monotonic()
        # Drop timestamps older than 60s.
        while self._recent_actions and now - self._recent_actions[0] > 60:
            self._recent_actions.popleft()
        return len(self._recent_actions) < self._settings.max_actions_per_min

    def _record_action(self) -> None:
        self._recent_actions.append(time.monotonic())
