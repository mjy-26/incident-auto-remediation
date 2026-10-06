"""
kube.py
=======
The REAL Kubernetes client — a thin wrapper around the official `kubernetes`
Python library that implements the `KubeClient` interface used by Remediator.

Keeping this tiny and separate means:
- All the "dangerous" real API calls live in ONE place.
- The rest of the app (and all tests) depend on the interface, not this file.
"""

from __future__ import annotations

from .config import Settings


class RealKubernetesClient:
    """Implements the KubeClient protocol against a live cluster."""

    def __init__(self, settings: Settings):
        # Imported lazily so unit tests never need the kubernetes library/cluster.
        from kubernetes import client, config

        if settings.in_cluster:
            # Running as a pod inside the cluster (uses the mounted ServiceAccount).
            config.load_incluster_config()
        else:
            # Running locally — use ~/.kube/config (e.g. your kind cluster).
            config.load_kube_config()

        self._core = client.CoreV1Api()
        self._apps = client.AppsV1Api()

    def delete_pod(self, namespace: str, pod: str) -> None:
        # Deleting a managed pod causes its controller to recreate it = restart.
        self._core.delete_namespaced_pod(name=pod, namespace=namespace)

    def get_deployment_replicas(self, namespace: str, deployment: str) -> int:
        dep = self._apps.read_namespaced_deployment(name=deployment, namespace=namespace)
        return dep.spec.replicas or 0

    def scale_deployment(self, namespace: str, deployment: str, replicas: int) -> None:
        # Patch only the replica count — minimal, targeted change.
        self._apps.patch_namespaced_deployment_scale(
            name=deployment,
            namespace=namespace,
            body={"spec": {"replicas": replicas}},
        )
