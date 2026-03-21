# IBM AIOps Demo Environment

Integrated demo for **Instana**, **Turbonomic**, **IBM Concert**, and **Granite AI** on Kubernetes.

## Architecture

```
Mac (Claude Code / Bob)  ──git push──>  GitHub
         │                                  │
    docker context                   self-hosted runner
         │                                  │
         v                                  v
   Linux Build Host  ──docker push──>  Docker Hub (mbx1010)
                                            │
                                            v
                                    K8s Cluster (192.168.178.35)
                                            │
                              ┌─────────────┼─────────────┐
                              v             v             v
                          Instana     Turbonomic     Concert
```

## Quick Start

```bash
# Build on Linux, push to Docker Hub, deploy to K8s
make all

# Just build
make build

# Apply Concert patches + full pipeline
make patch-build

# Check status
make status
```

## Repository Structure

```
├── .github/workflows/          # GitHub Actions CI/CD
├── python-app/                 # Load Test App (Python 3.9 / Flask)
│   ├── Dockerfile
│   ├── app.py
│   └── requirements.txt
├── java-app/                   # Vulnerable Echo Service (Java 11 / Log4j)
│   ├── Dockerfile
│   ├── pom.xml
│   └── src/
├── k8s/                        # Kubernetes manifests (split by resource)
│   ├── namespace.yaml
│   ├── configmaps.yaml
│   ├── python-app-deployment.yaml
│   ├── echo-service-deployment.yaml
│   ├── ingress.yaml
│   └── hpa.yaml
├── scripts/                    # Deployment & patch scripts
│   ├── deploy.sh
│   └── apply-concert-patch.sh
├── concert-patches/            # IBM Concert remediation patches
├── docs/                       # Presentation & documentation
├── Makefile                    # Build + push + deploy shortcuts
└── README.md
```

## Setup

### 1. Remote Docker Context (Mac to Linux)

```bash
docker context create linux-builder \
  --docker "host=ssh://manfred@linux"
docker context use linux-builder
```

### 2. Docker Hub Login (on Linux)

```bash
ssh linux
docker login -u mbx1010
```

### 3. Self-Hosted GitHub Runner (on Linux)

See [GitHub Actions runner setup](https://docs.github.com/en/actions/hosting-your-own-runners).
Add `DOCKERHUB_TOKEN` as a repository secret.

### 4. Kubeconfig

```bash
scp root@192.168.178.35:/etc/kubernetes/admin.conf ~/.kube/config
```

## Applications

| App | Port | Image | Purpose |
|-----|------|-------|---------|
| Load Test App | 8080 | `mbx1010/load-test-app` | CPU/memory stress, echo flood, ramp & wave patterns |
| Echo Service | 8085 | `mbx1010/vulnerable-echo-service` | Intentionally vulnerable (Log4j CVE-2021-44228) |

## IBM Product Integration

- **Instana** — traces, metrics, AI Actions (local Granite on vLLM + NVIDIA GPU)
- **Turbonomic** — resize/scale actions triggered by load patterns
- **Concert** — CVE detection, digest-matched build artifacts, remediation patches
- **MCP Servers** — Instana + Kubernetes MCP connected to Claude & watsonx
