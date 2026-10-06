"""
test_remediator.py
==================
Unit tests for the safety logic: allowlists, blast-radius, rate limiting,
dry-run, and the actual restart/scale dispatch — all against a FakeKubernetesClient.
"""

from __future__ import annotations

from src.config import Settings
from src.models import Alert
from src.remediator import Remediator

from .fakes import FakeKubernetesClient


def _settings(**overrides) -> Settings:
    """Build Settings with safe test defaults, overridable per-test."""
    base = dict(
        dry_run=False,
        allowed_namespaces=["demo"],
        allowed_actions=["restart_pod", "scale_deployment"],
        max_actions_per_min=5,
    )
    base.update(overrides)
    return Settings(**base)


def _alert(action: str | None = "restart_pod", namespace: str = "demo",
           pod: str | None = "checkout-abc", deployment: str | None = "checkout") -> Alert:
    labels = {"alertname": "HighErrorRate", "severity": "critical", "namespace": namespace}
    if pod:
        labels["pod"] = pod
    if deployment:
        labels["deployment"] = deployment
    annotations = {"summary": "errors spiking"}
    if action:
        annotations["action"] = action
    return Alert(status="firing", labels=labels, annotations=annotations)


def test_restart_pod_deletes_pod():
    kube = FakeKubernetesClient()
    rem = Remediator(kube, _settings())

    result = rem.handle(_alert(action="restart_pod"))

    assert result.performed is True
    assert kube.deleted_pods == [("demo", "checkout-abc")]


def test_scale_deployment_scales_out_by_one():
    kube = FakeKubernetesClient(replicas={("demo", "checkout"): 3})
    rem = Remediator(kube, _settings())

    result = rem.handle(_alert(action="scale_deployment"))

    assert result.performed is True
    assert kube.scaled == [("demo", "checkout", 4)]


def test_action_not_in_allowlist_is_skipped():
    kube = FakeKubernetesClient()
    rem = Remediator(kube, _settings(allowed_actions=["scale_deployment"]))

    result = rem.handle(_alert(action="restart_pod"))

    assert result.performed is False
    assert "not in allowlist" in result.detail
    assert kube.deleted_pods == []


def test_namespace_outside_blast_radius_is_skipped():
    kube = FakeKubernetesClient()
    rem = Remediator(kube, _settings(allowed_namespaces=["demo"]))

    result = rem.handle(_alert(namespace="kube-system"))

    assert result.performed is False
    assert "not allowed" in result.detail
    assert kube.deleted_pods == []


def test_dry_run_takes_no_action():
    kube = FakeKubernetesClient()
    rem = Remediator(kube, _settings(dry_run=True))

    result = rem.handle(_alert(action="restart_pod"))

    assert result.performed is False
    assert "DRY_RUN" in result.detail
    assert kube.deleted_pods == []


def test_missing_action_annotation_is_noop():
    kube = FakeKubernetesClient()
    rem = Remediator(kube, _settings())

    result = rem.handle(_alert(action=None))

    assert result.performed is False
    assert result.action == "none"


def test_rate_limit_blocks_after_threshold():
    kube = FakeKubernetesClient()
    rem = Remediator(kube, _settings(max_actions_per_min=2))

    r1 = rem.handle(_alert(pod="p1"))
    r2 = rem.handle(_alert(pod="p2"))
    r3 = rem.handle(_alert(pod="p3"))

    assert r1.performed is True
    assert r2.performed is True
    assert r3.performed is False
    assert "rate limit" in r3.detail
    # Only the first two actually deleted pods.
    assert kube.deleted_pods == [("demo", "p1"), ("demo", "p2")]


def test_restart_without_pod_label_is_skipped():
    kube = FakeKubernetesClient()
    rem = Remediator(kube, _settings())

    result = rem.handle(_alert(action="restart_pod", pod=None))

    assert result.performed is False
    assert "no 'pod' label" in result.detail


def test_scale_without_deployment_label_is_skipped():
    kube = FakeKubernetesClient()
    rem = Remediator(kube, _settings())

    result = rem.handle(_alert(action="scale_deployment", deployment=None))

    assert result.performed is False
    assert "no 'deployment' label" in result.detail
