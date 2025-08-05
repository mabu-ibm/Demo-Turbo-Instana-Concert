#!/bin/bash
# Build und Push Script für Load Testing Application
# Usage: ./build-and-push.sh [version]

set -euo pipefail

# Configuration
DOCKER_REGISTRY="docker.io"
DOCKER_USERNAME="mbx1010"
PYTHON_APP_NAME="load-test-app"
JAVA_APP_NAME="vulnerable-echo-service"
VERSION="${1:-2.0}"

# Directory paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_DIR="$SCRIPT_DIR/python-app"
JAVA_DIR="$SCRIPT_DIR/java-app"

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

# Check if Docker is running
check_docker() {
    if ! docker info >/dev/null 2>&1; then
        log_error "Docker is not running. Please start Docker and try again."
        exit 1
    fi
    log_info "Docker is running"
}

# Check directory structure
check_structure() {
    log_info "Checking directory structure..."
    
    # Check Python app directory
    if [[ ! -d "$PYTHON_DIR" ]]; then
        log_error "Python app directory not found: $PYTHON_DIR"
        exit 1
    fi
    
    if [[ ! -f "$PYTHON_DIR/app.py" ]]; then
        log_error "Python app.py not found: $PYTHON_DIR/app.py"
        exit 1
    fi
    
    if [[ ! -f "$PYTHON_DIR/requirements.txt" ]]; then
        log_error "Python requirements.txt not found: $PYTHON_DIR/requirements.txt"
        exit 1
    fi
    
    # Check Java app directory
    if [[ ! -d "$JAVA_DIR" ]]; then
        log_error "Java app directory not found: $JAVA_DIR"
        exit 1
    fi
    
    if [[ ! -f "$JAVA_DIR/pom.xml" ]]; then
        log_error "Java pom.xml not found: $JAVA_DIR/pom.xml"
        exit 1
    fi
    
    if [[ ! -f "$JAVA_DIR/src/main/java/com/loadtest/vulnerable/VulnerableEchoService.java" ]]; then
        log_error "Java source file not found: $JAVA_DIR/src/main/java/com/loadtest/vulnerable/VulnerableEchoService.java"
        exit 1
    fi
    
    log_success "Directory structure is correct"
}

# Create missing files if needed
create_missing_files() {
    log_info "Creating missing files if needed..."
    
    # Create Python Dockerfile if missing
    if [[ ! -f "$PYTHON_DIR/Dockerfile" ]]; then
        log_info "Creating Python Dockerfile..."
        cat > "$PYTHON_DIR/Dockerfile" << 'EOF'
# Multi-stage build für optimierte Container-Größe
FROM python:3.11-slim as builder

# Build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir --user -r /tmp/requirements.txt

# Production stage
FROM python:3.11-slim

# Metadata
LABEL maintainer="mbx1010" \
      version="2.0" \
      description="Load Testing Application with Echo Service Integration" \
      org.opencontainers.image.source="https://github.com/mbx1010/load-test-app"

# System dependencies für stress-ng und monitoring
RUN apt-get update && apt-get install -y \
    stress-ng \
    htop \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Non-root user erstellen
RUN groupadd -r appuser && useradd -r -g appuser -u 1000 appuser

# Working directory
WORKDIR /app

# Python packages von builder stage kopieren
COPY --from=builder /root/.local /home/appuser/.local

# Application code kopieren
COPY --chown=appuser:appuser app.py /app/
COPY --chown=appuser:appuser requirements.txt /app/

# Environment variables
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    FLASK_ENV=production \
    PORT=8080 \
    HOST=0.0.0.0 \
    ECHO_SERVICE_URL=http://vulnerable-echo-service:8085

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# User wechseln
USER appuser

# Port exposieren
EXPOSE 8080

# Application starten
CMD ["python", "app.py"]
EOF
        log_success "Python Dockerfile created"
    fi
    
    # Create Java Dockerfile if missing
    if [[ ! -f "$JAVA_DIR/Dockerfile" ]]; then
        log_info "Creating Java Dockerfile..."
        cat > "$JAVA_DIR/Dockerfile" << 'EOF'
# Multi-stage build für Java Application
FROM maven:3.8.6-openjdk-11-slim as builder

# Metadata
LABEL stage=builder

# Working directory
WORKDIR /build

# Copy pom.xml first for dependency caching
COPY pom.xml .

# Download dependencies
RUN mvn dependency:go-offline -B

# Copy source code
COPY src ./src

# Build application
RUN mvn clean package -DskipTests -B

# Production stage
FROM openjdk:11-jre-slim

# Metadata
LABEL maintainer="mbx1010" \
      version="1.0.0-VULNERABLE" \
      description="Vulnerable Echo Service with Log4j CVE-2021-44228" \
      vulnerability="CVE-2021-44228" \
      security.policy="test-only" \
      org.opencontainers.image.source="https://github.com/mbx1010/vulnerable-echo-service"

# System dependencies
RUN apt-get update && apt-get install -y \
    curl \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

# Non-root user erstellen
RUN groupadd -r appuser && useradd -r -g appuser -u 1000 appuser

# Working directory
WORKDIR /app

# Create log directory
RUN mkdir -p /app/logs && chown -R appuser:appuser /app/logs

# Copy JAR from builder stage
COPY --from=builder /build/target/vulnerable-echo-service-*.jar app.jar

# Change ownership
RUN chown -R appuser:appuser /app

# Environment variables
ENV JAVA_OPTS="-Xmx512m -Xms256m" \
    SERVER_PORT=8085 \
    LOG4J_FORMAT_MSG_NO_LOOKUPS=false \
    LOG4J2_DISABLE_JNDI=false

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${SERVER_PORT}/health || exit 1

# User wechseln
USER appuser

# Port exposieren
EXPOSE 8085

# Application starten
CMD java $JAVA_OPTS -jar app.jar --server.port=$SERVER_PORT
EOF
        log_success "Java Dockerfile created"
    fi
    
    # Create log4j2.xml if missing
    if [[ ! -f "$JAVA_DIR/src/main/resources/log4j2.xml" ]]; then
        log_info "Creating log4j2.xml..."
        mkdir -p "$JAVA_DIR/src/main/resources"
        cat > "$JAVA_DIR/src/main/resources/log4j2.xml" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!-- 
WARNUNG: Diese Log4j2 Konfiguration ist absichtlich VULNERABLE (CVE-2021-44228)
NUR für Testing/Demonstration in isolierten Umgebungen verwenden!
-->
<Configuration status="INFO">
    <Properties>
        <!-- VULNERABLE: JNDI Lookups sind aktiviert -->
        <Property name="LOG_PATTERN">%d{yyyy-MM-dd HH:mm:ss.SSS} [%t] %-5level %logger{36} - %msg%n</Property>
        <Property name="LOG_LEVEL">INFO</Property>
    </Properties>
    
    <Appenders>
        <!-- Console Appender -->
        <Console name="Console" target="SYSTEM_OUT">
            <PatternLayout pattern="${LOG_PATTERN}"/>
        </Console>
        
        <!-- File Appender für Application Logs -->
        <File name="FileAppender" fileName="/app/logs/vulnerable-echo-service.log">
            <PatternLayout pattern="${LOG_PATTERN}"/>
        </File>
        
        <!-- Rolling File Appender für Request Logs -->
        <RollingFile name="RequestLog" 
                     fileName="/app/logs/requests.log"
                     filePattern="/app/logs/requests-%d{yyyy-MM-dd}-%i.log.gz">
            <PatternLayout pattern="%d{yyyy-MM-dd HH:mm:ss.SSS} - REQUEST: %msg%n"/>
            <Policies>
                <TimeBasedTriggeringPolicy />
                <SizeBasedTriggeringPolicy size="50MB"/>
            </Policies>
            <DefaultRolloverStrategy max="10"/>
        </RollingFile>
    </Appenders>
    
    <Loggers>
        <!-- Application Logger -->
        <Logger name="com.loadtest.vulnerable" level="${LOG_LEVEL}" additivity="false">
            <AppenderRef ref="Console"/>
            <AppenderRef ref="FileAppender"/>
            <AppenderRef ref="RequestLog"/>
        </Logger>
        
        <!-- Spring Boot Loggers -->
        <Logger name="org.springframework" level="INFO" additivity="false">
            <AppenderRef ref="Console"/>
            <AppenderRef ref="FileAppender"/>
        </Logger>
        
        <!-- Root Logger -->
        <Root level="${LOG_LEVEL}">
            <AppenderRef ref="Console"/>
            <AppenderRef ref="FileAppender"/>
        </Root>
    </Loggers>
</Configuration>
EOF
        log_success "log4j2.xml created"
    fi
}

# Login to Docker Hub
docker_login() {
    log_info "Logging into Docker Hub..."
    if ! docker login --username "$DOCKER_USERNAME"; then
        log_error "Docker login failed"
        exit 1
    fi
    log_success "Docker login successful"
}

# Build Python Load Test Application
build_python_app() {
    log_info "Building Python Load Test Application..."
    
    cd "$PYTHON_DIR"
    
    local image_tag="${DOCKER_REGISTRY}/${DOCKER_USERNAME}/${PYTHON_APP_NAME}:${VERSION}"
    local latest_tag="${DOCKER_REGISTRY}/${DOCKER_USERNAME}/${PYTHON_APP_NAME}:latest"
    
    log_info "Building image: $image_tag"
    if docker build -t "$image_tag" -t "$latest_tag" .; then
        log_success "Python app built successfully"
    else
        log_error "Failed to build Python app"
        exit 1
    fi
    
    # Push to registry
    log_info "Pushing Python app to registry..."
    if docker push "$image_tag" && docker push "$latest_tag"; then
        log_success "Python app pushed successfully"
    else
        log_error "Failed to push Python app"
        exit 1
    fi
    
    echo "Python App Images:"
    echo "  - $image_tag"
    echo "  - $latest_tag"
    
    cd "$SCRIPT_DIR"
}

# Build Java Vulnerable Echo Service
build_java_app() {
    log_info "Building Java Vulnerable Echo Service..."
    
    cd "$JAVA_DIR"
    
    local image_tag="${DOCKER_REGISTRY}/${DOCKER_USERNAME}/${JAVA_APP_NAME}:${VERSION}"
    local latest_tag="${DOCKER_REGISTRY}/${DOCKER_USERNAME}/${JAVA_APP_NAME}:latest"
    
    log_info "Building image: $image_tag"
    if docker build -t "$image_tag" -t "$latest_tag" .; then
        log_success "Java app built successfully"
    else
        log_error "Failed to build Java app"
        exit 1
    fi
    
    # Push to registry
    log_info "Pushing Java app to registry..."
    if docker push "$image_tag" && docker push "$latest_tag"; then
        log_success "Java app pushed successfully"
    else
        log_error "Failed to push Java app"
        exit 1
    fi
    
    echo "Java App Images:"
    echo "  - $image_tag"
    echo "  - $latest_tag"
    
    cd "$SCRIPT_DIR"
}

# Show build information
show_build_info() {
    echo ""
    echo "=== BUILD INFORMATION ==="
    echo "Script Directory: $SCRIPT_DIR"
    echo "Python App Directory: $PYTHON_DIR"
    echo "Java App Directory: $JAVA_DIR"
    echo "Version: $VERSION"
    echo "Docker Username: $DOCKER_USERNAME"
    echo ""
}

# Main execution
main() {
    log_info "Starting build and push process for Load Testing Applications"
    
    show_build_info
    check_docker
    check_structure
    create_missing_files
    docker_login
    
    build_python_app
    build_java_app
    
    log_success "All applications built and pushed successfully!"
    
    echo ""
    echo "=== DEPLOYMENT READY ==="
    echo "Images are now available in Docker Hub:"
    echo "  - ${DOCKER_USERNAME}/${PYTHON_APP_NAME}:${VERSION}"
    echo "  - ${DOCKER_USERNAME}/${PYTHON_APP_NAME}:latest"
    echo "  - ${DOCKER_USERNAME}/${JAVA_APP_NAME}:${VERSION}"
    echo "  - ${DOCKER_USERNAME}/${JAVA_APP_NAME}:latest"
    echo ""
    echo "Next steps:"
    echo "  1. Review the Kubernetes manifest: kubernetes-manifest.yaml"
    echo "  2. Deploy with: ./deploy.sh deploy"
    echo "  3. Check status: ./deploy.sh status"
}

# Run main function
main "$@"
