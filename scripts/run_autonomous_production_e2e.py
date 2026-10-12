#!/usr/bin/env python3
"""
Autonomous Code Builder V2 Production E2E Runner

Waits for Render deployment to complete, then runs Playwright tests
against the production URL using LUMINA_E2E_EMAIL and LUMINA_E2E_PASSWORD.

Usage:
  python scripts/run_autonomous_production_e2e.py [--base-url URL] [--spec SPEC] [--timeout SECONDS]

Environment variables:
  LUMINA_E2E_BASE_URL  - Production URL (default: https://lumina-ai-studio.onrender.com)
  LUMINA_E2E_EMAIL     - Test account email (REQUIRED)
  LUMINA_E2E_PASSWORD  - Test account password (REQUIRED)
  LUMINA_E2E_MODEL     - Model to use (default: openai/gpt-oss-120b)
  RENDER_API_KEY       - Optional Render API key for deployment status checks
  RENDER_SERVICE_ID    - Optional Render service ID for deployment status checks
"""

import argparse
import os
import sys
import time
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_BASE_URL = "https://lumina-ai-studio.onrender.com"
DEFAULT_TIMEOUT = 600  # 10 minutes for Render to be reachable
DEPLOYMENT_TIMEOUT = 1800  # 30 minutes for deployment to complete


def log(msg: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    print(f"[AUTONOMOUS-E2E {timestamp}] {msg}", flush=True)


def check_render_deployment(api_key: str, service_id: str, timeout: int = DEPLOYMENT_TIMEOUT) -> bool:
    """Check Render deployment status via API."""
    if not api_key or not service_id:
        log("No Render API credentials provided, skipping deployment check")
        return True
    
    log(f"Checking Render deployment status for service {service_id}...")
    start = time.time()
    
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(
                f"https://api.render.com/v1/services/{service_id}/deploys",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status != 200:
                    log(f"Render API returned {response.status}")
                    time.sleep(30)
                    continue
                
                import json
                deploys = json.loads(response.read().decode())
                if not deploys:
                    log("No deploys found")
                    time.sleep(30)
                    continue
                
                latest = deploys[0]
                status = latest.get("status", "unknown")
                log(f"Latest deployment status: {status}")
                
                if status == "live":
                    log("Deployment is live!")
                    return True
                elif status in ("build_failed", "update_failed", "canceled"):
                    log(f"Deployment failed with status: {status}")
                    return False
                elif status in ("created", "building", "updating", "predeploy"):
                    log(f"Deployment in progress: {status}")
                    time.sleep(30)
                    continue
                else:
                    log(f"Unknown deployment status: {status}")
                    time.sleep(30)
                    
        except urllib.error.HTTPError as e:
            if e.code == 401:
                log("Render API authentication failed - check RENDER_API_KEY")
                return False
            elif e.code == 404:
                log(f"Render service not found - check RENDER_SERVICE_ID")
                return False
            log(f"Render API error: {e}")
            time.sleep(30)
        except Exception as e:
            log(f"Error checking Render deployment: {e}")
            time.sleep(30)
    
    log("Deployment check timed out")
    return False


def wait_for_render(base_url: str, timeout: int = DEFAULT_TIMEOUT) -> bool:
    """Wait for Render app to be reachable."""
    log(f"Waiting for Render app at {base_url} to be reachable...")
    start = time.time()
    
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(base_url, headers={"Accept": "text/html"})
            req.add_header("User-Agent", "Lumina-Autonomous-E2E/1.0")
            with urllib.request.urlopen(req, timeout=10) as response:
                code = response.status
                if code in (200, 301, 302, 401, 403):
                    log(f"Render app reachable (HTTP {code})")
                    return True
        except urllib.error.HTTPError as e:
            if e.code in (200, 301, 302, 401, 403):
                log(f"Render app reachable (HTTP {e.code})")
                return True
        except Exception:
            pass
        
        elapsed = int(time.time() - start)
        log(f"Waiting... ({elapsed}s/{timeout}s)")
        time.sleep(20)
    
    log(f"Render app was not reachable at {base_url} within {timeout}s")
    return False


def run_playwright_tests(base_url: str, email: str, password: str, model: str, spec: str, timeout: int = 900000) -> int:
    """Run Playwright tests against production."""
    env = os.environ.copy()
    env.update({
        "LUMINA_E2E_BASE_URL": base_url,
        "LUMINA_E2E_EMAIL": email,
        "LUMINA_E2E_PASSWORD": password,
        "LUMINA_E2E_MODEL": model,
        "LUMINA_E2E_API_URL": f"{base_url}/api",
    })
    
    cmd = [
        "npx", "playwright", "test",
        spec,
        "--workers=1",
        "--reporter=list",
        f"--timeout={timeout}"
    ]
    
    log(f"Running: {' '.join(cmd)}")
    log(f"Base URL: {base_url}")
    log(f"Email: {email}")
    log(f"Model: {model}")
    
    try:
        process = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        
        for line in process.stdout:
            # Redact sensitive info
            safe = line.replace(password, "[REDACTED]").replace(email, "[REDACTED]")
            print(safe, end="", flush=True)
        
        code = process.wait()
        return code
        
    except FileNotFoundError:
        log("npx not found - ensure Node.js and Playwright are installed")
        return 1
    except Exception as e:
        log(f"Error running Playwright: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(description="Run autonomous Code Builder V2 E2E tests against production")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Production base URL")
    parser.add_argument("--spec", default="e2e/code-builder-v2-autonomous.spec.js", help="Playwright spec file")
    parser.add_argument("--timeout", type=int, default=900000, help="Playwright timeout in ms")
    parser.add_argument("--skip-deployment-check", action="store_true", help="Skip Render deployment API check")
    args = parser.parse_args()
    
    base_url = args.base_url or os.environ.get("LUMINA_E2E_BASE_URL", DEFAULT_BASE_URL)
    email = os.environ.get("LUMINA_E2E_EMAIL")
    password = os.environ.get("LUMINA_E2E_PASSWORD")
    model = os.environ.get("LUMINA_E2E_MODEL", "openai/gpt-oss-120b")
    
    if not email or not password:
        log("ERROR: LUMINA_E2E_EMAIL and LUMINA_E2E_PASSWORD must be set")
        log("These should be a dedicated test account, never an owner/personal account")
        return 1
    
    render_api_key = os.environ.get("RENDER_API_KEY")
    render_service_id = os.environ.get("RENDER_SERVICE_ID")
    
    log("=" * 60)
    log("AUTONOMOUS CODE BUILDER V2 PRODUCTION E2E")
    log("=" * 60)
    log(f"Base URL: {base_url}")
    log(f"Test account: {email}")
    log(f"Model: {model}")
    log(f"Spec: {args.spec}")
    
    # Step 1: Check Render deployment (if API credentials provided)
    if not args.skip_deployment_check and render_api_key and render_service_id:
        if not check_render_deployment(render_api_key, render_service_id):
            log("Render deployment check failed")
            return 1
    elif not args.skip_deployment_check:
        log("Skipping Render deployment API check (no RENDER_API_KEY/RENDER_SERVICE_ID)")
    
    # Step 2: Wait for Render to be reachable
    if not wait_for_render(base_url):
        return 1
    
    # Step 3: Run Playwright tests
    log("Starting Playwright tests...")
    exit_code = run_playwright_tests(base_url, email, password, model, args.spec, args.timeout)
    
    if exit_code == 0:
        log("=" * 60)
        log("AUTONOMOUS E2E TESTS PASSED")
        log("=" * 60)
    else:
        log("=" * 60)
        log(f"AUTONOMOUS E2E TESTS FAILED (exit code: {exit_code})")
        log("=" * 60)
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())