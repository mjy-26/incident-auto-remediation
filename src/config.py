"""
config.py
=========
Central place for all configuration. Everything is read from environment
variables so we never hard-code secrets or environment-specific values.

Why this matters (SRE / 12-factor app principle):
- The SAME code runs in dev, staging, and prod — only the env vars change.
- Secrets (Slack URL, Jira token) live in the environment, never in git.

Safety switches live here too:
- DRY_RUN            -> if true, we LOG what we *would* do but take no action.
- ALLOWED_NAMESPACES -> we only ever act on these K8s namespaces (blast-radius).
- ALLOWED_ACTIONS    -> allowlist of runbook actions we permit.
- MAX_ACTIONS_PER_MIN-> rate limit so a storm of alerts can't cause a storm
                        of automated changes (a classic auto-remediation danger).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _get_bool(name: str, default: bool) -> bool:
    """Read a boolean env var. Accepts 1/true/yes/on (case-insensitive)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_csv(name: str, default: list[str]) -> list[str]:
    """Read a comma-separated env var into a list, e.g. 'a,b,c' -> ['a','b','c']."""
    raw = os.getenv(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of configuration, built once at startup."""

    # --- Safety ---
    dry_run: bool = field(default_factory=lambda: _get_bool("DRY_RUN", True))
    allowed_namespaces: list[str] = field(
        default_factory=lambda: _get_csv("ALLOWED_NAMESPACES", ["default", "demo"])
    )
    allowed_actions: list[str] = field(
        default_factory=lambda: _get_csv(
            "ALLOWED_ACTIONS", ["restart_pod", "scale_deployment"]
        )
    )
    max_actions_per_min: int = field(
        default_factory=lambda: int(os.getenv("MAX_ACTIONS_PER_MIN", "5"))
    )

    # --- Notifications (all optional; empty => skipped/mocked) ---
    slack_webhook_url: str = field(
        default_factory=lambda: os.getenv("SLACK_WEBHOOK_URL", "")
    )
    jira_base_url: str = field(default_factory=lambda: os.getenv("JIRA_BASE_URL", ""))
    jira_email: str = field(default_factory=lambda: os.getenv("JIRA_EMAIL", ""))
    jira_api_token: str = field(default_factory=lambda: os.getenv("JIRA_API_TOKEN", ""))
    jira_project_key: str = field(
        default_factory=lambda: os.getenv("JIRA_PROJECT_KEY", "OPS")
    )

    # --- Kubernetes ---
    # If true, load in-cluster config (when running as a pod). Otherwise use
    # the local kubeconfig (~/.kube/config) — handy for local kind clusters.
    in_cluster: bool = field(default_factory=lambda: _get_bool("IN_CLUSTER", False))

    @property
    def jira_enabled(self) -> bool:
        return bool(self.jira_base_url and self.jira_email and self.jira_api_token)

    @property
    def slack_enabled(self) -> bool:
        return bool(self.slack_webhook_url)


# A single shared settings instance the rest of the app imports.
settings = Settings()
