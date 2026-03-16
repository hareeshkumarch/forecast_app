#!/usr/bin/env python3
import subprocess
import requests
import asyncio
import websockets
import time
import sys
import json
import os

# Text styling
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def print_header(title):
    print(f"\n{YELLOW}{'='*50}")
    print(f" > {title}")
    print(f"{'='*50}{RESET}")

def run_cmd(cmd, desc, cwd=None):
    print(f"[*] Running: {desc}...")
    try:
        # Check if Windows to use shell=True for npm/npx
        is_win = sys.platform == "win32"
        shell = is_win and (cmd[0] in ["npm", "npx"])
        if is_win and cmd[0] == "npx":
             cmd = ["npx.cmd"] + cmd[1:]
        elif is_win and cmd[0] == "npm":
             cmd = ["npm.cmd"] + cmd[1:]

        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"[OK] {GREEN}SUCCESS: {desc}{RESET}")
            return True
        else:
            print(f"[X]  {RED}FAILED: {desc}{RESET}")
            print(f"Output:\n{result.stdout}\n{result.stderr}")
            return False
    except Exception as e:
        print(f"[X]  {RED}ERROR: {desc}: {str(e)}{RESET}")
        return False

def check_http_get(url, desc):
    print(f"[*] Checking HTTP GET {url} ({desc})...")
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            print(f"[OK] {GREEN}SUCCESS: {url} is reachable (HTTP {res.status_code}){RESET}")
            return True
        print(f"[X]  {RED}FAILED: {url} returned HTTP {res.status_code}{RESET}")
        return False
    except Exception as e:
        print(f"[X]  {RED}ERROR: Could not reach {url}: {str(e)}{RESET}")
        return False

def check_api_edge_case(url, data, expected_status, desc):
    print(f"[*] Checking Edge Case {desc}...")
    try:
        res = requests.post(url, json=data, timeout=5)
        if res.status_code == expected_status:
            print(f"[OK] {GREEN}SUCCESS: {desc} -> Returned expected HTTP {expected_status}{RESET}")
            return True
        print(f"[X]  {RED}FAILED: {desc} -> Expected {expected_status}, got {res.status_code}{RESET}")
        print(f"Response: {res.text}")
        return False
    except Exception as e:
        print(f"[X]  {RED}ERROR: Edge case test failed: {str(e)}{RESET}")
        return False

async def check_websocket_proxy(ws_url):
    print(f"[*] Checking WebSocket connection {ws_url}...")
    try:
        async with websockets.connect(ws_url) as ws:
            print(f"[OK] {GREEN}SUCCESS: Connected to WebSocket proxy{RESET}")
            
            # Send ping
            await ws.send("ping")
            print(f"   -> Sent ping")
            
            # Wait briefly for any immediate error or response
            try:
                res = await asyncio.wait_for(ws.recv(), timeout=2.0)
                print(f"   <- Received: {res[:50]}")
            except asyncio.TimeoutError:
                print(f"   -> WebSocket open and stable (no immediate error)")
            return True
    except Exception as e:
        print(f"[X]  {RED}ERROR: WebSocket proxy failed: {str(e)}{RESET}")
        return False

def main():
    print_header("Starting ForecastHub Diagnostic Suite")
    
    # 1. Install Ruff if missing
    print_header("Code Formatting & Linting")
    try:
        import ruff
    except ImportError:
        print("[*] Installing ruff...")
        subprocess.run([sys.executable, "-m", "pip", "install", "ruff", "-q"])

    # Python Lint & Format
    passed = []
    passed.append(run_cmd([sys.executable, "-m", "ruff", "check", "ml_engine/"], "Python Linting (Ruff)"))
    passed.append(run_cmd([sys.executable, "-m", "ruff", "format", "ml_engine/"], "Python Formatting (Ruff)"))

    # TS/JS Lint & Format
    passed.append(run_cmd(["npm", "run", "check"], "TypeScript Type Checking"))
    passed.append(run_cmd(["npm", "run", "lint", "--if-present"], "ESLint"))
    passed.append(run_cmd(["npx", "prettier", "--write", "client/", "server/", "shared/"], "Prettier Formatting"))

    # 2. Network & Health Checks
    print_header("Network & Service Health (Requires Docker running)")
    
    # Check if services are up
    express_up = check_http_get("http://localhost:5000/api/health", "Express Server Proxy")
    ml_up = check_http_get("http://localhost:8001/api/health", "FastAPI ML Engine direct")
    
    if not express_up or not ml_up:
         print(f"\n{YELLOW}[!]  WARN: Services are not running locally. Skipping API/Edge Case tests.{RESET}")
         print(f"Please run 'docker-compose up -d' first to test full API suite.\n")
    else:
        # Edge Cases
        print_header("API Edge Cases & Validation")
        
        # Test 1: Invalid Forecast Request (Zod validation should catch this)
        passed.append(check_api_edge_case(
            "http://localhost:5000/api/run-forecast",
            {"datasetId": "missing_mapping_and_horizon"},
            400,
            "Zod request validation (Missing fields)"
        ))

        # Test 2: Invalid Demo ID (FastAPI should return HTTP 404 instead of tuple)
        passed.append(check_api_edge_case(
            "http://localhost:5000/api/load-demo/haxor",
            {},
            404,
            "Invalid Demo Dataset Request"
        ))
        
        # Test 3: WebSocket Connection Proxy (Express -> ML Engine)
        test_job_id = "diagnostic-test-" + str(int(time.time()))
        ws_res = asyncio.run(check_websocket_proxy(f"ws://localhost:5000/ws/{test_job_id}"))
        passed.append(ws_res)

    print_header("Diagnostic Summary")
    total = len(passed)
    success = sum(passed)
    
    if success == total:
        print(f"[OK] {GREEN}ALL {total} CHECKS PASSED PERFECTLY!{RESET}")
        sys.exit(0)
    else:
        print(f"[X]  {RED}{total - success} CHECKS FAILED.{RESET} Review the logs above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
