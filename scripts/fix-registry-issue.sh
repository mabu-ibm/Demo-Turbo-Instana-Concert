#!/bin/bash
# Registry Issue Diagnostic and Fix Script
# Resolves ImagePullBackOff errors caused by registry connectivity issues

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="demo-turbo-instana-concert"
DEPLOYMENT_NAME="vulnerable-echo-service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[⚠]${NC} $1"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

log_section() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo ""
}

# Check prerequisites
check_prerequisites() {
    log_section "Checking Prerequisites"
    
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed"
        exit 1
    fi
    log_success "kubectl is installed"
    
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi
    log_success "Connected to Kubernetes cluster"
    
    if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
        log_error "Namespace $NAMESPACE does not exist"
        exit 1
    fi
    log_success "Namespace $NAMESPACE exists"
}

# Diagnose the issue
diagnose_issue() {
    log_section "Diagnosing Registry Issue"
    
    # Get pod status
    log_info "Checking pod status..."
    kubectl get pods -n "$NAMESPACE" -l app="$DEPLOYMENT_NAME" -o wide
    
    echo ""
    log_info "Checking pod events..."
    POD_NAME=$(kubectl get pods -n "$NAMESPACE" -l app="$DEPLOYMENT_NAME" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    
    if [[ -n "$POD_NAME" ]]; then
        kubectl describe pod "$POD_NAME" -n "$NAMESPACE" | grep -A 20 "Events:"
        
        # Extract registry information from error
        log_info "Extracting registry information from errors..."
        CONFIGURED_REGISTRY=$(kubectl describe pod "$POD_NAME" -n "$NAMESPACE" | grep "image:" | head -1 | awk '{print $2}' | cut -d'/' -f1)
        ACTUAL_REGISTRY=$(kubectl describe pod "$POD_NAME" -n "$NAMESPACE" | grep "Failed to pull image" | head -1 | grep -oP 'http://\K[^/]+' || echo "")
        
        echo ""
        log_info "Registry Analysis:"
        echo "  Configured Registry: ${CONFIGURED_REGISTRY:-Not found}"
        echo "  Actual Registry Contacted: ${ACTUAL_REGISTRY:-Not found}"
        
        if [[ "$CONFIGURED_REGISTRY" != "$ACTUAL_REGISTRY" && -n "$ACTUAL_REGISTRY" ]]; then
            log_warning "Registry mismatch detected!"
            echo "  This indicates a DNS or network routing issue"
        fi
    else
        log_warning "No pods found for deployment $DEPLOYMENT_NAME"
    fi
    
    # Check deployment configuration
    echo ""
    log_info "Checking deployment image configuration..."
    kubectl get deployment "$DEPLOYMENT_NAME" -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo "Deployment not found"
    echo ""
}

# Test registry connectivity
test_registry_connectivity() {
    log_section "Testing Registry Connectivity"
    
    # Get the configured registry from deployment
    REGISTRY=$(kubectl get deployment "$DEPLOYMENT_NAME" -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null | cut -d'/' -f1)
    
    if [[ -z "$REGISTRY" ]]; then
        log_error "Could not determine registry from deployment"
        return 1
    fi
    
    log_info "Testing connectivity to registry: $REGISTRY"
    
    # Extract host and port
    REGISTRY_HOST=$(echo "$REGISTRY" | cut -d':' -f1)
    REGISTRY_PORT=$(echo "$REGISTRY" | cut -d':' -f2)
    
    if [[ "$REGISTRY_HOST" == "$REGISTRY_PORT" ]]; then
        REGISTRY_PORT="5000"  # Default registry port
    fi
    
    log_info "Registry Host: $REGISTRY_HOST"
    log_info "Registry Port: $REGISTRY_PORT"
    
    # Test connectivity from a pod in the cluster
    log_info "Testing from within cluster..."
    kubectl run registry-test --rm -i --restart=Never --image=curlimages/curl -n "$NAMESPACE" -- \
        sh -c "curl -v --connect-timeout 10 http://${REGISTRY}/v2/ 2>&1 || echo 'Connection failed'" || true
    
    echo ""
    log_info "Testing DNS resolution..."
    kubectl run dns-test --rm -i --restart=Never --image=busybox -n "$NAMESPACE" -- \
        nslookup "$REGISTRY_HOST" || true
}

# Check Docker daemon configuration on nodes
check_node_docker_config() {
    log_section "Checking Node Docker Configuration"
    
    log_info "Getting node information..."
    kubectl get nodes -o wide
    
    echo ""
    log_warning "To check Docker daemon configuration on nodes, you need to:"
    echo "  1. SSH into each node"
    echo "  2. Check /etc/docker/daemon.json for insecure-registries"
    echo "  3. Verify Docker service is running: systemctl status docker"
    echo "  4. Restart Docker if needed: systemctl restart docker"
    
    echo ""
    log_info "Expected daemon.json content:"
    cat <<'EOF'
{
  "insecure-registries": ["192.168.178.56:3000"]
}
EOF
}

# Provide fix options
provide_fix_options() {
    log_section "Fix Options"
    
    echo "Option 1: Update Deployment with Correct Registry"
    echo "  - Modify the deployment to use the correct registry address"
    echo "  - Command: kubectl set image deployment/$DEPLOYMENT_NAME -n $NAMESPACE ..."
    echo ""
    
    echo "Option 2: Fix Node Docker Configuration"
    echo "  - Add the registry to insecure-registries on all nodes"
    echo "  - Restart Docker daemon on all nodes"
    echo ""
    
    echo "Option 3: Use ImagePullSecrets"
    echo "  - Create a secret with registry credentials"
    echo "  - Add imagePullSecrets to deployment"
    echo ""
    
    echo "Option 4: Fix DNS/Network Routing"
    echo "  - Ensure registry hostname resolves correctly"
    echo "  - Check network policies and firewall rules"
    echo ""
}

# Interactive fix
interactive_fix() {
    log_section "Interactive Fix"
    
    echo "What would you like to do?"
    echo ""
    echo "1) Delete and recreate the deployment"
    echo "2) Update deployment image with correct registry"
    echo "3) Scale deployment to 0 and back to 1 (restart)"
    echo "4) Show manual fix commands"
    echo "5) Exit"
    echo ""
    
    read -p "Enter your choice (1-5): " choice
    
    case $choice in
        1)
            log_info "Deleting deployment..."
            kubectl delete deployment "$DEPLOYMENT_NAME" -n "$NAMESPACE" --ignore-not-found
            log_success "Deployment deleted"
            
            log_info "Please update your deployment YAML with the correct registry"
            log_info "Then apply it with: kubectl apply -f k8s/echo-service-deployment.yaml"
            ;;
        2)
            read -p "Enter the correct registry address (e.g., 192.168.178.56:3000): " NEW_REGISTRY
            read -p "Enter the image repository (e.g., test/demo-turbo-instana-concert/echo-service): " IMAGE_REPO
            read -p "Enter the image tag (default: latest): " IMAGE_TAG
            IMAGE_TAG=${IMAGE_TAG:-latest}
            
            NEW_IMAGE="${NEW_REGISTRY}/${IMAGE_REPO}:${IMAGE_TAG}"
            
            log_info "Updating deployment with image: $NEW_IMAGE"
            kubectl set image deployment/"$DEPLOYMENT_NAME" -n "$NAMESPACE" \
                "$DEPLOYMENT_NAME"="$NEW_IMAGE"
            
            log_info "Waiting for rollout..."
            kubectl rollout status deployment/"$DEPLOYMENT_NAME" -n "$NAMESPACE" --timeout=5m
            log_success "Deployment updated"
            ;;
        3)
            log_info "Scaling deployment to 0..."
            kubectl scale deployment/"$DEPLOYMENT_NAME" -n "$NAMESPACE" --replicas=0
            sleep 5
            
            log_info "Scaling deployment back to 1..."
            kubectl scale deployment/"$DEPLOYMENT_NAME" -n "$NAMESPACE" --replicas=1
            
            log_info "Waiting for pod to be ready..."
            kubectl wait --for=condition=ready pod -l app="$DEPLOYMENT_NAME" -n "$NAMESPACE" --timeout=5m || true
            log_success "Deployment restarted"
            ;;
        4)
            show_manual_fix_commands
            ;;
        5)
            log_info "Exiting..."
            exit 0
            ;;
        *)
            log_error "Invalid choice"
            exit 1
            ;;
    esac
}

# Show manual fix commands
show_manual_fix_commands() {
    log_section "Manual Fix Commands"
    
    cat <<'EOF'
# 1. Check current deployment image
kubectl get deployment vulnerable-echo-service -n demo-turbo-instana-concert -o jsonpath='{.spec.template.spec.containers[0].image}'

# 2. Update deployment with correct registry
kubectl set image deployment/vulnerable-echo-service -n demo-turbo-instana-concert \
  vulnerable-echo-service=192.168.178.56:3000/test/demo-turbo-instana-concert/echo-service:latest

# 3. Or edit deployment directly
kubectl edit deployment vulnerable-echo-service -n demo-turbo-instana-concert

# 4. Check rollout status
kubectl rollout status deployment/vulnerable-echo-service -n demo-turbo-instana-concert

# 5. Check pod status
kubectl get pods -n demo-turbo-instana-concert -l app=vulnerable-echo-service

# 6. Describe pod for detailed error information
kubectl describe pod -n demo-turbo-instana-concert -l app=vulnerable-echo-service

# 7. Check pod logs
kubectl logs -n demo-turbo-instana-concert -l app=vulnerable-echo-service

# 8. Delete pod to force recreation (if needed)
kubectl delete pod -n demo-turbo-instana-concert -l app=vulnerable-echo-service

# 9. Configure Docker on nodes (run on each node)
sudo tee /etc/docker/daemon.json > /dev/null <<DOCKEREOF
{
  "insecure-registries": ["192.168.178.56:3000"]
}
DOCKEREOF
sudo systemctl restart docker

# 10. Verify registry is accessible from cluster
kubectl run test-registry --rm -i --restart=Never --image=curlimages/curl -n demo-turbo-instana-concert -- \
  curl -v http://192.168.178.56:3000/v2/
EOF
}

# Main execution
main() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║                                                           ║${NC}"
    echo -e "${CYAN}║     Registry Issue Diagnostic and Fix Tool               ║${NC}"
    echo -e "${CYAN}║     For Demo Turbo Instana Concert                       ║${NC}"
    echo -e "${CYAN}║                                                           ║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    
    check_prerequisites
    diagnose_issue
    test_registry_connectivity
    check_node_docker_config
    provide_fix_options
    
    echo ""
    read -p "Would you like to apply an interactive fix? (y/N): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        interactive_fix
    else
        log_info "No changes made. Use the manual commands above to fix the issue."
    fi
    
    log_section "Summary"
    log_info "The main issue is: ImagePullBackOff due to registry connectivity"
    log_info "Root cause: Registry IP mismatch or Docker daemon not configured for insecure registry"
    log_info ""
    log_info "Recommended actions:"
    echo "  1. Verify the correct registry address (192.168.178.56:3000 or 192.168.178.65:3000)"
    echo "  2. Update deployment with correct registry address"
    echo "  3. Ensure Docker daemon on all nodes has insecure-registries configured"
    echo "  4. Restart Docker daemon on nodes after configuration changes"
    echo ""
    log_success "Diagnostic complete!"
}

# Run main function
main

# Made with Bob
