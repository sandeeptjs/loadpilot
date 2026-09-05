"""Start the local sandbox and dashboard with one bounded remediation policy."""
import argparse
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--api-port', type=int, default=8000)
    parser.add_argument('--target-port', type=int, default=8080)
    parser.add_argument('--healthy', action='store_true', help='Start with a healthy pool instead of the demo bottleneck')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / '.env')
    binary = os.environ.get('LOADPILOT_K6_BIN') or shutil.which('k6') or str(root / '.tools/k6/k6-v1.6.1-windows-amd64/k6.exe')
    if not Path(binary).is_file() and not shutil.which(binary):
        raise SystemExit('k6 is missing. On Windows run scripts/install_k6.ps1; otherwise install k6 and set LOADPILOT_K6_BIN.')
    if not (root / 'web/dist/index.html').exists():
        raise SystemExit('Build the dashboard first: cd web; npm ci; npm run build')
    if args.api_port == args.target_port:
        raise SystemExit('API and sandbox need different ports')
    for port in (args.api_port, args.target_port):
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
            except OSError:
                raise SystemExit(f'Port {port} is occupied; choose another port') from None
    token = secrets.token_urlsafe(32)
    target = f'http://127.0.0.1:{args.target_port}'
    env = {**os.environ, 'SANDBOX_CONTROL_TOKEN': token, 'LOADPILOT_SANDBOX_CONTROL_TOKEN': token,
           'LOADPILOT_K6_BIN': binary, 'LOADPILOT_SANDBOX_URL': target,
           'LOADPILOT_ALLOW_SANDBOX_REMEDIATION': 'true', 'LOADPILOT_EMBEDDED_WORKER': 'true',
           'LOADPILOT_DB': str(root / 'artifacts/demo.db'),
           'LOADPILOT_GENERATED_DIR': str(root / 'artifacts/generated-tests'),
           'SANDBOX_DB_POOL_SIZE': '12' if args.healthy else '2',
           'SANDBOX_DB_LATENCY_MS': '35' if args.healthy else '80'}
    processes, logs = [], []
    (root / 'artifacts').mkdir(exist_ok=True)
    try:
        for module, port in (('sandbox_target.app', args.target_port), ('loadpilot.api', args.api_port)):
            log = (root / 'artifacts' / f'{module.split(".")[0]}-demo.log').open('a', encoding='utf-8')
            logs.append(log)
            processes.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', module + ':app', '--host', '127.0.0.1', '--port', str(port)], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
        for _ in range(100):
            try:
                with httpx.Client(timeout=1) as client:
                    response = client.get(f'http://127.0.0.1:{args.api_port}/api/health')
                    sandbox = client.get(target + '/openapi.json')
                if response.is_success and sandbox.is_success:
                    break
            except httpx.HTTPError:
                pass
            if any(p.poll() is not None for p in processes):
                raise RuntimeError('A demo service exited; see artifacts/*-demo.log')
            time.sleep(.2)
        else:
            raise RuntimeError('Demo startup timed out; see artifacts/*-demo.log')
        print(f'Dashboard: http://127.0.0.1:{args.api_port}', flush=True)
        print(f'API documentation: http://127.0.0.1:{args.api_port}/docs', flush=True)
        print('Choose New test. The Stress preset finds the modeled pool bottleneck.', flush=True)
        print('After analysis, increase the sandbox pool and verify with the same workload.', flush=True)
        print('Ctrl+C stops both services. Run history remains in artifacts/demo.db.', flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for log in logs:
            log.close()


if __name__ == '__main__':
    main()
