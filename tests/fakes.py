"""
fakes.py
========
Test doubles that implement the same small interfaces the real code depends on.
Because our business logic talks to PROTOCOLS (not concrete classes), we can
swap these in and unit-test everything with zero network / cluster access.
"""

from __future__ import annotations


class FakeKubernetesClient:
    """In-memory KubeClient. Records every call so tests can assert on them."""

    def __init__(self, replicas: dict[tuple[str, str], int] | None = None):
        # (namespace, deployment) -> current replica count
        self._replicas = replicas or {}
        self.deleted_pods: list[tuple[str, str]] = []
        self.scaled: list[tuple[str, str, int]] = []

    def delete_pod(self, namespace: str, pod: str) -> None:
        self.deleted_pods.append((namespace, pod))

    def get_deployment_replicas(self, namespace: str, deployment: str) -> int:
        return self._replicas.get((namespace, deployment), 1)

    def scale_deployment(self, namespace: str, deployment: str, replicas: int) -> None:
        self.scaled.append((namespace, deployment, replicas))
        self._replicas[(namespace, deployment)] = replicas


class FakeResponse:
    """Minimal stand-in for a `requests.Response`."""

    def __init__(self, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {}

    def json(self) -> dict:
        return self._body


class FakeHttpPoster:
    """Records outbound POSTs and returns a canned response."""

    def __init__(self, response: FakeResponse | None = None,
                 raise_exc: Exception | None = None):
        self._response = response or FakeResponse(200, {"key": "OPS-123"})
        self._raise = raise_exc
        self.calls: list[dict] = []

    def post(self, url: str, *, json: dict, headers: dict, auth, timeout: float):
        self.calls.append({
            "url": url, "json": json, "headers": headers,
            "auth": auth, "timeout": timeout,
        })
        if self._raise is not None:
            raise self._raise
        return self._response
