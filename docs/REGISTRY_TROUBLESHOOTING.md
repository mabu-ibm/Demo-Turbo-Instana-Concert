# Registry Troubleshooting Guide

## Problem: ImagePullBackOff Error

### Symptoms
```
Events:
  Warning  Failed     Failed to pull image "192.168.178.56:3000/test/demo-turbo-instana-concert/echo-service:latest": 
           failed to pull and unpack image: failed to resolve reference: 
           failed to do request: Head "http://192.168.178.65:3000/v2/...": 
           dial tcp 192.168.178.65:3000: connect: connection refused
  Warning  Failed     Error: ErrImagePull
  Warning  Failed     Error: ImagePullBackOff
```

### Root Cause Analysis

The error shows a **registry IP mismatch**:
- **Configured Registry**: `192.168.178.56:3000` (in deployment YAML)
- **Actual Registry Contacted**: `192.168.178.65:3000` (DNS resolution or network routing)

This indicates one of the following issues:

1. **DNS Resolution Issue**: The hostname resolves to a different IP than expected
2. **Network Routing Issue**: Traffic is being redirected to a different IP
3. **Docker Daemon Configuration**: Nodes don't have the registry configured as insecure
4. **Registry Not Running**: The registry service is not accessible on the expected IP/port

---

## Solution 1: Fix Deployment Configuration

### Changes Made

#### 1. Updated `imagePullPolicy` in Deployments

**File**: `k8s/echo-service-deployment.yaml` and `k8s/python-app-deployment.yaml`

**Change**:
```yaml
# Before
imagePullPolicy: Always

# After
imagePullPolicy: IfNotPresent
```

**Reason**: 
- `Always` forces Kubernetes to pull the image on every pod restart, which fails if registry is unreachable
- `IfNotPresent` uses cached images if available, reducing dependency on registry availability
- This provides better resilience during registry connectivity issues

#### 2. Enhanced Gitea Workflow Error Handling

**File**: `.gitea/workflows/build-push-deploy-native-gitea-runner-needtobe-container.yaml`

**Changes**:
- Added registry verification step before deployment
- Enhanced error messages with diagnostic information
- Added automatic pod status checking on deployment failure
- Improved rollout status monitoring with detailed error reporting

---

## Solution 2: Configure Docker Daemon on Kubernetes Nodes

### Why This Is Needed

When using an **insecure HTTP registry** (not HTTPS), Docker daemon on each Kubernetes node must be explicitly configured to allow pulling from that registry.

### Steps to Configure

#### On Each Kubernetes Node:

1. **SSH into the node**:
   ```bash
   ssh user@node-ip
   ```

2. **Create or edit `/etc/docker/daemon.json`**:
   ```bash
   sudo vi /etc/docker/daemon.json
   ```

3. **Add the insecure registry configuration**:
   ```json
   {
     "insecure-registries": ["192.168.178.56:3000"]
   }
   ```
   
   **Important**: Replace `192.168.178.56:3000` with your actual registry address.

4. **Restart Docker daemon**:
   ```bash
   sudo systemctl restart docker
   ```

5. **Verify Docker is running**:
   ```bash
   sudo systemctl status docker
   docker info | grep -A 5 "Insecure Registries"
   ```

6. **Repeat for all nodes** in your Kubernetes cluster.

---

## Solution 3: Verify Registry Accessibility

### Test Registry from Kubernetes Cluster

Run a test pod to verify registry connectivity:

```bash
kubectl run registry-test --rm -i --restart=Never \
  --image=curlimages/curl -n demo-turbo-instana-concert -- \
  curl -v http://192.168.178.56:3000/v2/
```

**Expected Output**: HTTP 200 OK or authentication challenge

**If it fails**: Registry is not accessible from the cluster

### Test DNS Resolution

```bash
kubectl run dns-test --rm -i --restart=Never \
  --image=busybox -n demo-turbo-instana-concert -- \
  nslookup 192.168.178.56
```

### Check Registry Service

On the registry host:

```bash
# Check if registry is running
docker ps | grep registry

# Check registry logs
docker logs <registry-container-id>

# Test locally
curl http://localhost:3000/v2/
```

---

## Solution 4: Update Gitea Secrets

If the registry address has changed, update the Gitea secret:

1. Go to **Repository → Settings → Secrets → Actions**
2. Update `GIT_REGISTRY` secret with the correct address
3. Re-run the workflow

---

## Diagnostic Commands

### Check Pod Status
```bash
kubectl get pods -n demo-turbo-instana-concert -l app=vulnerable-echo-service
```

### Describe Pod for Events
```bash
kubectl describe pod -n demo-turbo-instana-concert -l app=vulnerable-echo-service
```

### Check Deployment Image
```bash
kubectl get deployment vulnerable-echo-service -n demo-turbo-instana-concert \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
```

### Check Node Docker Configuration
```bash
# On each node
sudo cat /etc/docker/daemon.json
sudo systemctl status docker
docker info | grep -A 5 "Insecure Registries"
```

### Test Image Pull Manually
```bash
# On a Kubernetes node
docker pull 192.168.178.56:3000/test/demo-turbo-instana-concert/echo-service:latest
```

---

## Quick Fix Commands

### Force Pod Restart
```bash
kubectl delete pod -n demo-turbo-instana-concert -l app=vulnerable-echo-service
```

### Scale Down and Up
```bash
kubectl scale deployment vulnerable-echo-service -n demo-turbo-instana-concert --replicas=0
sleep 5
kubectl scale deployment vulnerable-echo-service -n demo-turbo-instana-concert --replicas=1
```

### Update Deployment Image
```bash
kubectl set image deployment/vulnerable-echo-service -n demo-turbo-instana-concert \
  vulnerable-echo-service=192.168.178.56:3000/test/demo-turbo-instana-concert/echo-service:latest
```

### Rollout Status
```bash
kubectl rollout status deployment/vulnerable-echo-service -n demo-turbo-instana-concert
```

---

## Prevention Checklist

Before deploying:

- [ ] Verify registry is accessible from all Kubernetes nodes
- [ ] Confirm Docker daemon on all nodes has insecure-registries configured
- [ ] Test image pull manually from a node
- [ ] Verify DNS resolution if using hostnames
- [ ] Check network policies and firewall rules
- [ ] Ensure registry service is running and healthy
- [ ] Verify Gitea secrets have correct registry address
- [ ] Test with `imagePullPolicy: IfNotPresent` for better resilience

---

## Common Scenarios

### Scenario 1: Registry IP Changed
**Solution**: Update `GIT_REGISTRY` secret in Gitea and redeploy

### Scenario 2: New Node Added to Cluster
**Solution**: Configure Docker daemon on the new node with insecure-registries

### Scenario 3: Registry Temporarily Unavailable
**Solution**: Use `imagePullPolicy: IfNotPresent` to use cached images

### Scenario 4: Network Policy Blocking Traffic
**Solution**: Check and update network policies to allow registry traffic

---

## Additional Resources

- [Kubernetes ImagePullBackOff Troubleshooting](https://kubernetes.io/docs/concepts/containers/images/#imagepullbackoff)
- [Docker Insecure Registry Configuration](https://docs.docker.com/registry/insecure/)
- [Kubernetes Private Registry Guide](https://kubernetes.io/docs/tasks/configure-pod-container/pull-image-private-registry/)

---

## Support

If issues persist after following this guide:

1. Check pod logs: `kubectl logs -n demo-turbo-instana-concert -l app=vulnerable-echo-service`
2. Check node logs: `journalctl -u docker -n 100`
3. Verify network connectivity between nodes and registry
4. Contact your cluster administrator for network/firewall issues