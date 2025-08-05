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

