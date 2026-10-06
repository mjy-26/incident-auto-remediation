# Incident Auto-Remediation

[![CI](https://github.com/mjy-26/incident-auto-remediation/actions/workflows/ci.yml/badge.svg)](https://github.com/mjy-26/incident-auto-remediation/actions/workflows/ci.yml)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)

A small, **safety-first** service that receives Prometheus **Alertmanager**
webhooks and runs allowlisted Kubernetes runbook actions (restart a pod, scale a
deployment) — with dry-run, namespace blast-radius limits, and rate limiting
baked in. Optional Slack/Jira notifications.

> **Cost: $0.** Everything runs locally (kind + Colima). No registry, no cloud,
> no managed services. Slack/Jira are optional and OFF by default.

> **Companion project:** This is the *act* half of a detect→act SRE loop. Its
> sibling, [k8s-observability-platform](https://github.com/mjy-26/k8s-observability-platform),
> provides the Prometheus/Grafana/Loki/Tempo stack with SLO burn-rate alerting
> that *detects* incidents — point its Alertmanager at this service's `/webhook`
> to close the loop and auto-remediate.

## Proof it works

**Automated:** every push runs lint + the full unit-test suite in GitHub Actions
(the green **CI** badge above is live). Reproduce locally in ~30s:

```bash
make venv && make test
# ....................                                     [100%]
# 20 passed in 0.2s
```

**Interactive:** boot it (no cluster needed — `DRY_RUN` is on) and POST a real
Alertmanager-shaped alert:

```bash
uvicorn src.app:app --port 8080 &
curl -s localhost:8080/ | jq           # shows the live safety posture
curl -s -X POST localhost:8080/webhook -H 'Content-Type: application/json' \
     -d @hack/sample-alert.json | jq
```

```jsonc
// response — note it decided the action but SAFELY stopped at the dry-run guard
{
  "received": 1,
  "handled": [{
    "alert": "PodCrashLooping",
    "result": {
      "action": "restart_pod",
      "target": "demo",
      "performed": false,
      "detail": "DRY_RUN: would run 'restart_pod'"
    }
  }]
}
```

Flip `DRY_RUN=false` against a real kind cluster (`make build load deploy`) and
the same request restarts the pod for real — the safety checks (allowlist,
namespace, rate limit) run identically either way.

## How it works

```
Alertmanager --POST /webhook--> FastAPI (app.py)
                                   │
                                   ▼
                              Remediator  ── safety checks ──►  Kubernetes API
                              (allowlist, blast-radius,         (delete pod /
                               rate-limit, dry-run)              scale deployment)
                                   │
                                   ▼
                               Notifier ──► Slack / Jira (optional)
```

An alert declares its own intent via annotations/labels:

| field                  | meaning                                             |
| ---------------------- | --------------------------------------------------- |
| `annotations.action`   | `restart_pod` or `scale_deployment` (allowlisted)   |
| `labels.namespace`     | must be in `ALLOWED_NAMESPACES`                      |
| `labels.pod`           | target pod for `restart_pod`                         |
| `labels.deployment`    | target deployment for `scale_deployment`             |
| `labels.remediate`     | `"true"` so Alertmanager routes it to this service   |

## Safety switches (env / ConfigMap)

| var                   | default                        | purpose                              |
| --------------------- | ------------------------------ | ------------------------------------ |
| `DRY_RUN`             | `true`                         | log-only; take no real action        |
| `ALLOWED_NAMESPACES`  | `default,demo`                 | blast-radius guard                   |
| `ALLOWED_ACTIONS`     | `restart_pod,scale_deployment` | allowlist of runbook actions         |
| `MAX_ACTIONS_PER_MIN` | `5`                            | rate limit (storm protection)        |
| `IN_CLUSTER`          | `false`                        | use in-cluster SA vs local kubeconfig|

## Local dev (no cluster needed)

```bash
make venv          # create .venv + install deps
make test          # run the 20 unit tests
. .venv/bin/activate
uvicorn src.app:app --reload --port 8080
curl -X POST localhost:8080/webhook -H 'Content-Type: application/json' \
     -d @hack/sample-alert.json
```

With `DRY_RUN=true` (the default) the app uses a no-op Kubernetes client, so it
runs anywhere with no kubeconfig.

## Deploy to a local kind cluster

```bash
export PATH="$HOME/.local/bin:$PATH"   # if kubectl/kind live there

make build      # docker build -t incident-auto-remediation:local .
make load       # kind load docker-image ... (no registry!)
make deploy     # namespace + rbac + config + deployment + service

make port-forward   # -> localhost:8080
make smoke          # POST the sample alert
make logs           # watch what it did
```

### Wire it to Alertmanager

- Merge [k8s/50-alertmanager-receiver.yaml](k8s/50-alertmanager-receiver.yaml)
  into your Alertmanager config (webhook URL points at the in-cluster Service).
- Apply [k8s/60-prometheusrule-example.yaml](k8s/60-prometheusrule-example.yaml)
  for example alert rules that carry the `action` annotation.

## Going live (carefully)

1. Keep `DRY_RUN=true` and watch the logs until you trust the decisions.
2. Flip `DRY_RUN=false` in [k8s/20-configmap.yaml](k8s/20-configmap.yaml) and
   `kubectl rollout restart deploy/remediator -n remediation`.
3. RBAC in [k8s/10-rbac.yaml](k8s/10-rbac.yaml) is a **namespaced** Role (demo
   only) — least privilege. Add more namespaces explicitly if ever needed.

## Notifications (optional, still free)

Copy `k8s/30-secret.example.yaml` to `k8s/30-secret.yaml`, fill in
`SLACK_WEBHOOK_URL` and/or Jira creds, and apply it. Empty values => channel
disabled, no external calls.

## Project layout

```
src/        config, models, kube client, remediator, notifier, FastAPI app
tests/      unit tests + fakes (no cluster/network needed)
k8s/        namespace, rbac, config, secret example, deployment, alerting
hack/       sample alert payload
Dockerfile  non-root, minimal image
Makefile    build / load / deploy / test helpers
```

## License

[MIT](LICENSE)
