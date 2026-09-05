"""Run a saved scenario through the public API with bounded client polling."""
import argparse
import json
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('file', type=Path)
    parser.add_argument('--api', default='http://127.0.0.1:8018')
    parser.add_argument('--target', help='Override the target base URL')
    parser.add_argument('--wait-seconds', type=int, default=120)
    args = parser.parse_args()
    payload = json.loads(args.file.read_text(encoding='utf-8'))
    if args.target:
        payload['base_url'] = args.target
    payload['auto_start'] = True
    with httpx.Client(base_url=args.api, timeout=60) as client:
        response = client.post('/api/tests', json=payload)
        response.raise_for_status()
        identifier = response.json()['id']
        print(f'Run: {identifier}', flush=True)
        deadline = time.monotonic() + args.wait_seconds
        while time.monotonic() < deadline:
            response = client.get(f'/api/runs/{identifier}')
            response.raise_for_status()
            run = response.json()['run']
            if run['state'] in {'COMPLETED', 'FAILED', 'CANCELED', 'TIMED_OUT'}:
                print(json.dumps(run, indent=2))
                return 0 if run['state'] == 'COMPLETED' else 1
            time.sleep(1)
    print('Polling timed out; the run remains available in the dashboard.')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
