REGISTRY  := docker.io
USERNAME  := mbx1010
TAG       := $(shell git rev-parse --short HEAD 2>/dev/null || echo "latest")
K8S_CTX   := kubernetes
NAMESPACE := load-testing

PYTHON_IMAGE := $(REGISTRY)/$(USERNAME)/load-test-app
JAVA_IMAGE   := $(REGISTRY)/$(USERNAME)/vulnerable-echo-service

.PHONY: build build-python build-java push push-python push-java deploy all patch-build apply-patches status logs clean

# ── Build ──────────────────────────────────────────────────────
build: build-python build-java

build-python:
	docker build --no-cache -t $(PYTHON_IMAGE):$(TAG) -t $(PYTHON_IMAGE):latest python-app/

build-java:
	docker build --no-cache -t $(JAVA_IMAGE):$(TAG) -t $(JAVA_IMAGE):latest java-app/

# ── Push ───────────────────────────────────────────────────────
push: push-python push-java

push-python:
	docker push $(PYTHON_IMAGE):$(TAG)
	docker push $(PYTHON_IMAGE):latest
	@echo "Digest: $$(docker inspect --format='{{index .RepoDigests 0}}' $(PYTHON_IMAGE):$(TAG) 2>/dev/null)"

push-java:
	docker push $(JAVA_IMAGE):$(TAG)
	docker push $(JAVA_IMAGE):latest
	@echo "Digest: $$(docker inspect --format='{{index .RepoDigests 0}}' $(JAVA_IMAGE):$(TAG) 2>/dev/null)"

# ── Deploy ─────────────────────────────────────────────────────
deploy:
	kubectl --context=$(K8S_CTX) apply -f k8s/namespace.yaml
	kubectl --context=$(K8S_CTX) apply -f k8s/configmaps.yaml
	kubectl --context=$(K8S_CTX) apply -f k8s/python-app-deployment.yaml
	kubectl --context=$(K8S_CTX) apply -f k8s/echo-service-deployment.yaml
	kubectl --context=$(K8S_CTX) apply -f k8s/ingress.yaml
	kubectl --context=$(K8S_CTX) apply -f k8s/hpa.yaml
	kubectl --context=$(K8S_CTX) -n $(NAMESPACE) rollout status deployment/load-test-app --timeout=300s
	kubectl --context=$(K8S_CTX) -n $(NAMESPACE) rollout status deployment/vulnerable-echo-service --timeout=300s

# ── Full pipeline ──────────────────────────────────────────────
all: build push deploy

# ── Concert patch integration ──────────────────────────────────
patch-build: apply-patches build push deploy

apply-patches:
	bash scripts/apply-concert-patch.sh

# ── Helpers ────────────────────────────────────────────────────
status:
	kubectl --context=$(K8S_CTX) -n $(NAMESPACE) get pods -o wide
	kubectl --context=$(K8S_CTX) -n $(NAMESPACE) get svc
	kubectl --context=$(K8S_CTX) -n $(NAMESPACE) get ingress

logs:
	kubectl --context=$(K8S_CTX) -n $(NAMESPACE) logs -l app=load-test-app --tail=50
	kubectl --context=$(K8S_CTX) -n $(NAMESPACE) logs -l app=vulnerable-echo-service --tail=50

restart:
	kubectl --context=$(K8S_CTX) -n $(NAMESPACE) rollout restart deployment/load-test-app
	kubectl --context=$(K8S_CTX) -n $(NAMESPACE) rollout restart deployment/vulnerable-echo-service

clean:
	kubectl --context=$(K8S_CTX) delete -f k8s/ --ignore-not-found
