#!/bin/bash
# Kubernetes Deployment Script für Load Testing Application
# Usage: ./deploy.sh [action] [namespace]

set -euo pipefail

# Configuration
NAMESPACE="${2:-load-testing}"
ACTION="${1:-deploy}"
MANIFEST_FILE="kubernetes-manifest.yaml"
KUBECTL_TIMEOUT="300s"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Show usage
show_usage() {
    echo "Usage: $0 [action] [namespace]"
    echo ""
    echo "Actions:"
    echo "  deploy     - Deploy the application (default)"
    echo "  delete     - Delete the application"
    echo "  restart    - Restart the application"
    echo "  status     - Show deployment status"
    echo "  logs       - Show application logs"
    echo "  port-forward - Set up port forwarding"
    echo "  test       - Run connectivity tests"
    echo ""
    echo "Examples:"
    echo "  $0 deploy load-testing"
    echo "  $0 status"
    echo "  $0 logs"
    echo "  $0 delete"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check kubectl
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed or not in PATH"
        exit 1
    fi
    
    # Check cluster connectivity
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi
    
    # Check if manifest exists
    if [[ ! -f "$MANIFEST_FILE" ]]; then
        log_error "Manifest file $MANIFEST_FILE not found"
        exit 1
    fi
    
    log_success "All prerequisites met"
}

# Deploy application
deploy_application() {
    log_info "Deploying Load Testing Application to namespace: $NAMESPACE"
    
    # Apply manifest
    if kubectl apply -f "$MANIFEST_FILE" --timeout="$KUBECTL_TIMEOUT"; then
        log_success "Manifest applied successfully"
    else
        log_error "Failed to apply manifest"
        exit 1
    fi
    
    # Wait for deployments to be ready
    log_info "Waiting for deployments to be ready..."
    
    kubectl wait --for=condition=available --timeout="$KUBECTL_TIMEOUT" \
        deployment/load-test-app -n "$NAMESPACE" || {
        log_error "load-test-app deployment failed to become ready"
        exit 1
    }
    
    kubectl wait --for=condition=available --timeout="$KUBECTL_TIMEOUT" \
        deployment/vulnerable-echo-service -n "$NAMESPACE" || {
        log_error "vulnerable-echo-service deployment failed to become ready"
        exit 1
    }
    
    log_success "All deployments are ready"
    
    # Show service information
    show_service_info
}

# Delete application
delete_application() {
    log_warning "Deleting Load Testing Application from namespace: $NAMESPACE"
    
    read -p "Are you sure you want to delete the application? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Deletion cancelled"
        exit 0
    fi
    
    if kubectl delete -f "$MANIFEST_FILE" --timeout="$KUBECTL_TIMEOUT"; then
        log_success "Application deleted successfully"
    else
        log_error "Failed to delete application"
        exit 1
    fi
}

# Restart application
restart_application() {
    log_info "Restarting Load Testing Application..."
    
    kubectl rollout restart deployment/load-test-app -n "$NAMESPACE"
    kubectl rollout restart deployment/vulnerable-echo-service -n "$NAMESPACE"
    
    # Wait for rollout to complete
    kubectl rollout status deployment/load-test-app -n "$NAMESPACE" --timeout="$KUBECTL_TIMEOUT"
    kubectl rollout status deployment/vulnerable-echo-service -n "$NAMESPACE" --timeout="$KUBECTL_TIMEOUT"
    
    log_success "Application restarted successfully"
}

# Show deployment status
show_status() {
    log_info "Showing deployment status for namespace: $NAMESPACE"
    
    echo ""
    echo "=== NAMESPACE ==="
    kubectl get namespace "$NAMESPACE" 2>/dev/null || log_warning "Namespace $NAMESPACE does not exist"
    
    echo ""
    echo "=== DEPLOYMENTS ==="
    kubectl get deployments -n "$NAMESPACE" -o wide
    
    echo ""
    echo "=== PODS ==="
    kubectl get pods -n "$NAMESPACE" -o wide
    
    echo ""
    echo "=== SERVICES ==="
    kubectl get services -n "$NAMESPACE" -o wide
    
    echo ""
    echo "=== INGRESS ==="
    kubectl get ingress -n "$NAMESPACE" -o wide
    
    echo ""
    echo "=== PERSISTENT VOLUME CLAIMS ==="
    kubectl get pvc -n "$NAMESPACE"
    
    echo ""
    echo "=== HORIZONTAL POD AUTOSCALERS ==="
    kubectl get hpa -n "$NAMESPACE"
    
    # Check pod health
    echo ""
    echo "=== POD HEALTH STATUS ==="
    kubectl get pods -n "$NAMESPACE" -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.phase}{"\t"}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' | column -t
}

# Show service information
show_service_info() {
    log_info "Service Access Information:"
    
    # Get LoadBalancer IP
    LB_IP=$(kubectl get service load-test-loadbalancer -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
    LB_HOSTNAME=$(kubectl get service load-test-loadbalancer -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
    
    # Get NodePort
    NODE_PORT=$(kubectl get service load-test-loadbalancer -n "$NAMESPACE" -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || echo "")
    
    # Get Ingress info
    INGRESS_IP=$(kubectl get ingress load-test-ingress -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
    
    echo ""
    echo "=== ACCESS INFORMATION ==="
    
    if [[ -n "$LB_IP" ]]; then
        echo "🌐 LoadBalancer IP: http://$LB_IP"
        echo "🌐 Echo Service: http://$LB_IP/api/echo"
    elif [[ -n "$LB_HOSTNAME" ]]; then
        echo "🌐 LoadBalancer Hostname: http://$LB_HOSTNAME"
        echo "🌐 Echo Service: http://$LB_HOSTNAME/api/echo"
    fi
    
    if [[ -n "$INGRESS_IP" ]]; then
        echo "🌐 Ingress IP: http://$INGRESS_IP"
        echo "🌐 Load Test App: http://$INGRESS_IP/load-test"
        echo "🌐 Echo Service: http://$INGRESS_IP/api/echo"
    fi
    
    if [[ -n "$NODE_PORT" ]]; then
        NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}' 2>/dev/null || kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
        echo "🌐 NodePort: http://$NODE_IP:$NODE_PORT"
    fi
    
    echo ""
    echo "=== PORT FORWARD COMMANDS ==="
    echo "kubectl port-forward -n $NAMESPACE service/load-test-service 8080:80"
    echo "kubectl port-forward -n $NAMESPACE service/vulnerable-echo-service 8085:8085"
}

# Show application logs
show_logs() {
    log_info "Showing application logs..."
    
    echo ""
    echo "=== LOAD TEST APP LOGS ==="
    kubectl logs -n "$NAMESPACE" -l app=load-test-app --tail=50 --timestamps
    
    echo ""
    echo "=== VULNERABLE ECHO SERVICE LOGS ==="
    kubectl logs -n "$NAMESPACE" -l app=vulnerable-echo-service --tail=50 --timestamps
    
    echo ""
    echo "To follow logs in real-time:"
    echo "kubectl logs -n $NAMESPACE -l app=load-test-app -f"
    echo "kubectl logs -n $NAMESPACE -l app=vulnerable-echo-service -f"
}

# Set up port forwarding
setup_port_forward() {
    log_info "Setting up port forwarding..."
    
    # Check if ports are already in use
    if lsof -Pi :8080 -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_warning "Port 8080 is already in use"
    fi
    
    if lsof -Pi :8085 -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_warning "Port 8085 is already in use"
    fi
    
    log_info "Starting port forwarding (Press Ctrl+C to stop)..."
    log_info "Load Test App will be available at: http://localhost:8080"
    log_info "Echo Service will be available at: http://localhost:8085"
    
    # Start port forwarding in background
    kubectl port-forward -n "$NAMESPACE" service/load-test-service 8080:80 &
    PF1_PID=$!
    
    kubectl port-forward -n "$NAMESPACE" service/vulnerable-echo-service 8085:8085 &
    PF2_PID=$!
    
    # Wait for port forwards to be ready
    sleep 3
    
    # Test connectivity
    if curl -s http://localhost:8080/health >/dev/null; then
        log_success "Load Test App is accessible at http://localhost:8080"
    else
        log_warning "Load Test App may not be ready yet"
    fi
    
    if curl -s http://localhost:8085/health >/dev/null; then
        log_success "Echo Service is accessible at http://localhost:8085"
    else
        log_warning "Echo Service may not be ready yet"
    fi
    
    # Cleanup function
    cleanup() {
        log_info "Stopping port forwarding..."
        kill $PF1_PID $PF2_PID 2>/dev/null || true
        exit 0
    }
    
    trap cleanup SIGINT SIGTERM
    
    # Wait for user to stop
    wait
}

# Run connectivity tests
run_tests() {
    log_info "Running connectivity tests..."
    
    # Get service endpoints
    LOAD_TEST_EP=$(kubectl get service load-test-service -n "$NAMESPACE" -o jsonpath='{.spec.clusterIP}')
    ECHO_SERVICE_EP=$(kubectl get service vulnerable-echo-service -n "$NAMESPACE" -o jsonpath='{.spec.clusterIP}')
    
    # Test from within cluster using temporary pod
    kubectl run test-pod --rm -i --tty --restart=Never --image=curlimages/curl -n "$NAMESPACE" -- /bin/sh -c "
        echo '=== Testing Load Test App ==='
        curl -s http://$LOAD_TEST_EP/health | head -10
        echo ''
        echo '=== Testing Echo Service ==='
        curl -s http://$ECHO_SERVICE_EP:8085/health | head -10
        echo ''
        echo '=== Testing Echo Functionality ==='
        curl -s -X POST http://$ECHO_SERVICE_EP:8085/echo -H 'Content-Type: application/json' -d '{\"message\":\"Test from deployment script\"}' | head -10
    " || log_warning "Cluster internal tests failed"
    
    # Test external access if available
    LB_IP=$(kubectl get service load-test-loadbalancer -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
    
    if [[ -n "$LB_IP" ]]; then
        log_info "Testing external LoadBalancer access..."
        if curl -s --connect-timeout 10 "http://$LB_IP/health" >/dev/null; then
            log_success "External access is working"
        else
            log_warning "External access may not be ready yet"
        fi
    fi
}

# Get resource usage
show_resource_usage() {
    log_info "Showing resource usage..."
    
    echo ""
    echo "=== POD RESOURCE USAGE ==="
    kubectl top pods -n "$NAMESPACE" 2>/dev/null || log_warning "Metrics server may not be available"
    
    echo ""
    echo "=== NODE RESOURCE USAGE ==="
    kubectl top nodes 2>/dev/null || log_warning "Metrics server may not be available"
    
    echo ""
    echo "=== RESOURCE QUOTAS ==="
    kubectl get resourcequota -n "$NAMESPACE" 2>/dev/null || echo "No resource quotas found"
    
    echo ""
    echo "=== LIMIT RANGES ==="
    kubectl get limitrange -n "$NAMESPACE" 2>/dev/null || echo "No limit ranges found"
}

# Main execution
main() {
    case "$ACTION" in
        "deploy"|"apply")
            check_prerequisites
            deploy_application
            ;;
        "delete"|"remove")
            check_prerequisites
            delete_application
            ;;
        "restart"|"rollout")
            check_prerequisites
            restart_application
            ;;
        "status"|"get")
            check_prerequisites
            show_status
            show_resource_usage
            ;;
        "logs"|"log")
            check_prerequisites
            show_logs
            ;;
        "port-forward"|"pf")
            check_prerequisites
            setup_port_forward
            ;;
        "test"|"check")
            check_prerequisites
            run_tests
            ;;
        "info"|"service-info")
            check_prerequisites
            show_service_info
            ;;
        "help"|"-h"|"--help")
            show_usage
            ;;
        *)
            log_error "Unknown action: $ACTION"
            show_usage
            exit 1
            ;;
    esac
}

# Ensure we have at least one argument
if [[ $# -eq 0 ]]; then
    ACTION="deploy"
fi

# Run main function
main
