# K3s Registry Configuration Fix

## Problem
K3s registries configuration has wrong entry, causing registry redirect:
- **Configured in deployment**: `192.168.178.56:3000`
- **Actual connection attempt**: `192.168.178.65:3000`

## Root Cause
K3s uses `/etc/rancher/k3s/registries.yaml` for registry configuration, and it has an incorrect mirror or endpoint configuration.

## Solution

### On Each K3s Node:

1. **Edit the registries configuration**:
   ```bash
   sudo vi /etc/rancher/k3s/registries.yaml
   ```

2. **Correct configuration should be**:
   ```yaml
   mirrors:
     "192.168.178.56:3000":
       endpoint:
         - "http://192.168.178.56:3000"
   
   configs:
     "192.168.178.56:3000":
       tls:
         insecure_skip_verify: true
   ```

3. **Remove any incorrect entries** pointing to `192.168.178.65:3000`

4. **Restart K3s**:
   ```bash
   # On K3s server node
   sudo systemctl restart k3s
   
   # On K3s agent nodes
   sudo systemctl restart k3s-agent
   ```

5. **Verify configuration**:
   ```bash
   sudo cat /etc/rancher/k3s/registries.yaml
   ```

### Alternative: If using Docker runtime with K3s

If K3s is using Docker as the container runtime, also configure:

```bash
sudo tee /etc/docker/daemon.json > /dev/null <<EOF
{
  "insecure-registries": ["192.168.178.56:3000"]
}
EOF
sudo systemctl restart docker
```

## Quick Fix Commands

### Delete failing pods to trigger recreation:
```bash
kubectl delete pod -n demo-turbo-instana-concert -l app=vulnerable-echo-service
```

### Force deployment rollout:
```bash
kubectl rollout restart deployment/vulnerable-echo-service -n demo-turbo-instana-concert
```

### Watch pod status:
```bash
kubectl get pods -n demo-turbo-instana-concert -w
```

## Verification

After fixing the registries.yaml:

1. **Test registry access from node**:
   ```bash
   curl -v http://192.168.178.56:3000/v2/
   ```

2. **Test image pull**:
   ```bash
   sudo crictl pull 192.168.178.56:3000/test/demo-turbo-instana-concert/echo-service:latest
   ```

3. **Check pod events**:
   ```bash
   kubectl describe pod -n demo-turbo-instana-concert -l app=vulnerable-echo-service
   ```

## Common K3s Registry Mistakes

### ❌ Wrong: Mirror pointing to different IP
```yaml
mirrors:
  "192.168.178.56:3000":
    endpoint:
      - "http://192.168.178.65:3000"  # WRONG IP!
```

### ✅ Correct: Mirror pointing to same IP
```yaml
mirrors:
  "192.168.178.56:3000":
    endpoint:
      - "http://192.168.178.56:3000"  # CORRECT
```

### ❌ Wrong: Missing insecure_skip_verify for HTTP
```yaml
configs:
  "192.168.178.56:3000":
    # Missing TLS configuration for HTTP registry
```

### ✅ Correct: Proper insecure configuration
```yaml
configs:
  "192.168.178.56:3000":
    tls:
      insecure_skip_verify: true
```

## Complete Working Example

```yaml
# /etc/rancher/k3s/registries.yaml
mirrors:
  "192.168.178.56:3000":
    endpoint:
      - "http://192.168.178.56:3000"

configs:
  "192.168.178.56:3000":
    tls:
      insecure_skip_verify: true
```

## Troubleshooting

### Check K3s logs:
```bash
# Server node
sudo journalctl -u k3s -f

# Agent node
sudo journalctl -u k3s-agent -f
```

### Check containerd configuration:
```bash
sudo cat /var/lib/rancher/k3s/agent/etc/containerd/config.toml | grep -A 10 registry
```

### Test with crictl:
```bash
# List images
sudo crictl images

# Pull test
sudo crictl pull 192.168.178.56:3000/test/demo-turbo-instana-concert/echo-service:latest
```

## References
- [K3s Private Registry Configuration](https://docs.k3s.io/installation/private-registry)
- [K3s Registries YAML](https://rancher.com/docs/k3s/latest/en/installation/private-registry/)