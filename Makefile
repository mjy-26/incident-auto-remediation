# Incident Auto-Remediation — Makefile
# All targets are LOCAL and FREE: build locally, load into kind, deploy.
# No registry, no cloud, no cost.

IMAGE      ?= incident-auto-remediation:local
KIND_CLUST ?= kind
NAMESPACE  ?= remediation

.PHONY: help venv test build load deploy undeploy logs port-forward smoke clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv: ## Create venv + install deps
	python3 -m venv .venv && . .venv/bin/activate && pip install -q -r requirements.txt

test: ## Run the unit tests
	. .venv/bin/activate && python -m pytest -q

build: ## Build the container image locally
	docker build -t $(IMAGE) .

load: ## Load the local image into the kind cluster (no registry needed)
	kind load docker-image $(IMAGE) --name $(KIND_CLUST)

deploy: ## Apply all manifests (creates ns, rbac, config, deployment, svc)
	kubectl apply -f k8s/00-namespace.yaml
	kubectl apply -f k8s/10-rbac.yaml
	kubectl apply -f k8s/20-configmap.yaml
	@# Use the example secret if you haven't created a real one.
	@kubectl -n $(NAMESPACE) get secret remediator-secrets >/dev/null 2>&1 || \
		kubectl apply -f k8s/30-secret.example.yaml
	kubectl apply -f k8s/40-deployment.yaml
	kubectl -n $(NAMESPACE) rollout status deploy/remediator

undeploy: ## Delete the deployment/service/config (keeps the namespace)
	kubectl delete -f k8s/40-deployment.yaml --ignore-not-found
	kubectl delete -f k8s/20-configmap.yaml --ignore-not-found

logs: ## Tail the remediator logs
	kubectl -n $(NAMESPACE) logs -l app=remediator -f

port-forward: ## Forward the service to localhost:8080
	kubectl -n $(NAMESPACE) port-forward svc/remediator 8080:80

smoke: ## POST a sample firing alert to a running port-forward (localhost:8080)
	curl -sS -X POST localhost:8080/webhook \
		-H 'Content-Type: application/json' \
		-d @hack/sample-alert.json | python3 -m json.tool

clean: ## Remove venv + caches
	rm -rf .venv .pytest_cache **/__pycache__

all: build load deploy ## Build -> load -> deploy
