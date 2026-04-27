# Gitea Deployment Guide for Demo Turbo Instana Concert

This guide explains how to deploy the `demo-turbo-instana-concert` application using Gitea Actions.

## Overview

The application consists of two components:
1. **Java Echo Service** - A vulnerable echo service with Log4j CVE-2021-44228 for demonstration
2. **Python Load Test App** - A load testing application that interacts with the echo service

Both applications are built, pushed to your Gitea registry, and deployed to Kubernetes in the `demo-turbo-instana-concert` namespace.

## Prerequisites

1. **Gitea Instance** with Actions enabled
2. **Gitea Runner** configured and running
3. **Kubernetes Cluster** with kubectl access
4. **Container Registry** (can be Gitea's built-in registry or external)
5. **Ingress Controller** (nginx or traefik) installed in your cluster

## Required Gitea Secrets

Navigate to your repository in Gitea:
```
Repository → Settings → Secrets → Actions
```

Add the following secrets:

### 1. GIT_REGISTRY
**Description:** Your container registry URL  
**Example:** `gitea.example.com:5000` or `registry.example.com`  
**Format:** `hostname:port` (no http:// or https://)

### 2. GIT_USERNAME
**Description:** Username for registry authentication  
**Example:** `gitea-user` or your Gitea username  
**Note:** For Gitea's built-in registry, use your Gitea username

### 3. GIT_TOKEN
**Description:** Password or access token for registry  
**Example:** Your Gitea password or a generated access token  
**Note:** For Gitea, generate a token at: User Settings → Applications → Generate New Token  
**Required Scopes:** `write:package` (for pushing images)

### 4. KUBECONFIG
**Description:** Kubernetes configuration file for cluster access  
**Format:** Base64 encoded or plain text YAML  

**To get your kubeconfig:**
```bash
# Option 1: Base64 encoded (recommended)
cat ~/.kube/config | base64 -w 0

# Option 2: Plain text (also works)
cat ~/.kube/config
```

### 5. INGRESS_HOST
**Description:** Hostname for accessing the application  
**Example:** `demo-turbo-instana-concert.example.com`  
**Format:** Fully qualified domain name (FQDN)

**Note:** Add this to your DNS or `/etc/hosts` file:
```bash
# Add to /etc/hosts on your local machine
<KUBERNETES_NODE_IP>  demo-turbo-instana-concert.example.com
```

## Workflow Trigger

The workflow is triggered automatically on:
- Push to `main` or `master` branch
- Manual trigger via Gitea Actions UI

### Manual Trigger
1. Go to your repository in Gitea
2. Click on "Actions" tab
3. Select "Build, Push and Deploy Demo Turbo Instana Concert"
4. Click "Run workflow"

## Deployment Process

The workflow performs these steps:

1. **Validation** - Validates all required secrets
2. **Environment Setup** - Installs Docker and kubectl
3. **Build & Push** - Builds and pushes both Docker images
4. **SBOM Generation** - Creates Software Bill of Materials
5. **Kubernetes Deployment** - Deploys to cluster
6. **Verification** - Shows deployment status and access URLs

## Accessing the Application

After successful deployment:

### HTTP Access
```bash
curl http://demo-turbo-instana-concert.example.com/health
```

### HTTPS Access (self-signed certificate)
```bash
curl -k https://demo-turbo-instana-concert.example.com/health
```

### Available Endpoints

**Load Test App (Python):**
- `/` - Main application
- `/health` - Health check
- `/metrics` - Prometheus metrics
- `/stress` - Stress test endpoint
- `/echo` - Echo test
- `/ramp` - Ramp load test
- `/wave` - Wave load test
- `/flood` - Flood load test
- `/status` - Status information

**Echo Service (Java):**
- `/api/echo` - Echo API endpoint
- `/health` - Health check

## Kubernetes Resources

Resources created in `demo-turbo-instana-concert` namespace:

- **Namespace:** `demo-turbo-instana-concert`
- **ServiceAccount:** `demo-turbo-instana-concert-sa`
- **Deployments:** `vulnerable-echo-service`, `load-test-app`
- **Services:** `vulnerable-echo-service`, `load-test-service`, `load-test-loadbalancer`
- **ConfigMaps:** `load-test-config`, `vulnerable-echo-config`
- **Ingress:** `demo-turbo-instana-concert-ingress`
- **Secret:** `demo-turbo-instana-concert-tls`

## Troubleshooting

### Check Workflow Status
```bash
# In Gitea UI: Actions tab shows workflow runs
```

### Check Kubernetes Resources
```bash
# Check namespace
kubectl get ns demo-turbo-instana-concert

# Check all resources
kubectl get all -n demo-turbo-instana-concert

# Check pods
kubectl get pods -n demo-turbo-instana-concert

# Check logs
kubectl logs -n demo-turbo-instana-concert deployment/load-test-app
kubectl logs -n demo-turbo-instana-concert deployment/vulnerable-echo-service

# Check ingress
kubectl get ingress -n demo-turbo-instana-concert
kubectl describe ingress demo-turbo-instana-concert-ingress -n demo-turbo-instana-concert
```

### Common Issues

**Issue:** Workflow fails with "Missing Required Secrets"  
**Solution:** Ensure all 5 required secrets are configured in Gitea

**Issue:** Image push fails  
**Solution:** Verify GIT_REGISTRY, GIT_USERNAME, and GIT_TOKEN are correct

**Issue:** Deployment fails  
**Solution:** Check KUBECONFIG has proper permissions

**Issue:** Cannot access application  
**Solution:** Verify INGRESS_HOST is in /etc/hosts and ingress controller is running

## Manual Deployment

If you prefer to deploy manually without Gitea Actions:

```bash
# 1. Build images
docker build -t your-registry/demo-turbo-instana-concert/echo-service:latest -f java-app/Dockerfile java-app/
docker build -t your-registry/demo-turbo-instana-concert/load-test-app:latest -f python-app/Dockerfile python-app/

# 2. Push images
docker push your-registry/demo-turbo-instana-concert/echo-service:latest
docker push your-registry/demo-turbo-instana-concert/load-test-app:latest

# 3. Deploy to Kubernetes
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmaps.yaml

# Update image references in deployments
sed -e "s|\${IMAGE_REGISTRY}|your-registry|g" \
    -e "s|\${IMAGE_REPOSITORY}|demo-turbo-instana-concert/echo-service|g" \
    -e "s|\${IMAGE_TAG}|latest|g" \
    k8s/echo-service-deployment.yaml | kubectl apply -f -

sed -e "s|\${IMAGE_REGISTRY}|your-registry|g" \
    -e "s|\${IMAGE_REPOSITORY}|demo-turbo-instana-concert/load-test-app|g" \
    -e "s|\${IMAGE_TAG}|latest|g" \
    k8s/python-app-deployment.yaml | kubectl apply -f -

# Update ingress hostname
sed -e "s|\${INGRESS_HOST}|demo-turbo-instana-concert.example.com|g" \
    k8s/ingress.yaml | kubectl apply -f -
```

## Next Steps

1. Configure monitoring with Instana
2. Set up IBM Concert integration for vulnerability tracking
3. Configure alerts and dashboards
4. Review security policies and network policies

## Support

For issues or questions:
- Check Gitea Actions logs
- Review Kubernetes pod logs
- Consult the main README.md