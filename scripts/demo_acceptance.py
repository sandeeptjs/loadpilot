"""Exercise the public API with real k6 traffic and save judge-reviewable evidence.

Starts isolated local API/target processes and stops only those processes on exit.
No provider key is required; provider mode must be verified separately.
"""
import argparse
import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--k6', default='.tools/k6/k6-v1.6.1-windows-amd64/k6.exe')
    parser.add_argument('--output', default='artifacts/demo-acceptance')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = (root / args.output / datetime.now(UTC).strftime('%Y%m%d-%H%M%S')).resolve()
    output.mkdir(parents=True, exist_ok=True)
    api_port, target_port = free_port(), free_port()
    api, target = f'http://127.0.0.1:{api_port}', f'http://127.0.0.1:{target_port}'
    token = secrets.token_urlsafe(24)
    env = {**os.environ, 'SANDBOX_CONTROL_TOKEN': token, 'LOADPILOT_SANDBOX_CONTROL_TOKEN': token,
           'LOADPILOT_DB': str(output / 'runs.db'), 'LOADPILOT_GENERATED_DIR': str(output / 'scripts'),
           'LOADPILOT_K6_BIN': str((root / args.k6).resolve()), 'LOADPILOT_SANDBOX_URL': target,
           'LOADPILOT_ALLOW_SANDBOX_REMEDIATION': 'true', 'LOADPILOT_EMBEDDED_WORKER': 'true',
           'LOADPILOT_LLM_MODEL': '', 'LOADPILOT_LLM_API_KEY': ''}
    processes, logs = [], []

    def launch(module, port):
        log = (output / f'{module.split(".")[0]}-{len(logs)}.log').open('w', encoding='utf-8')
        logs.append(log)
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', module + ':app', '--host', '127.0.0.1', '--port', str(port)], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        processes.append(process)
        return process

    launch('sandbox_target.app', target_port)
    api_process = launch('loadpilot.api', api_port)
    evidence = {'mode': 'real-k6-offline-analysis', 'started_at': datetime.now(UTC).isoformat(), 'runs': {}}
    async with httpx.AsyncClient(timeout=20) as client:
        async def request(method, path, **kwargs):
            response = await client.request(method, api + path, **kwargs)
            if response.is_error:
                raise AssertionError(f'{method} {path}: {response.status_code} {response.text}')
            return response.json()

        async def ready(url):
            for _ in range(100):
                try:
                    if (await client.get(url)).is_success:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(.2)
            raise RuntimeError(f'Service did not start: {url}')

        async def complete(run_id):
            for _ in range(800):
                detail = await request('GET', '/api/runs/' + run_id)
                if detail['run']['state'] in {'COMPLETED', 'FAILED', 'CANCELED', 'TIMED_OUT'}:
                    assert detail['run']['state'] == 'COMPLETED', detail['run']
                    return detail
                await asyncio.sleep(.2)
            raise AssertionError('Run did not finish')

        async def create(label, prompt, **kwargs):
            run = await request('POST', '/api/tests', json={'prompt': prompt, 'source_url': target + '/openapi.json', 'auto_start': True, **kwargs})
            print(f'{label}: started {run["id"]}', flush=True)
            detail = await complete(run['id'])
            report = await request('GET', f'/api/runs/{run["id"]}/report')
            evidence['runs'][label] = report
            print(f'{label}: completed; p95={detail["run"]["metrics"].get("http_req_duration.p(95)", 0):.1f} ms; SLO pass={detail["run"]["slo_passed"]}', flush=True)
            return detail

        async def control(values):
            response = await client.post(target + '/control', headers={'X-Control-Token': token}, json=values)
            response.raise_for_status()

        try:
            await ready(api + '/api/health')
            await ready(target + '/openapi.json')
            baseline = await create('baseline', 'Baseline checkout with 2 users for 10 seconds, p95 under 500 ms and errors under 1%.')
            assert baseline['run']['slo_passed'] is True
            journey = [s['operation_id'] for s in baseline['plan']['journeys'][0]['steps']]
            assert journey == ['login', 'listProducts', 'createCart', 'checkout'], journey
            await request('POST', '/api/baselines', json={'id': baseline['run']['id'], 'name': 'Healthy sandbox'})
            rejected = await client.post(target + '/control', json={'db_pool_size': 20})
            assert rejected.status_code == 403
            await control({'db_pool_size': 2, 'db_latency_ms': 80})
            await request('POST', '/api/alerts', json={'alerts': [{'labels': {'alertname': 'UnrelatedCacheWarning', 'environment': 'another-environment', 'target': 'http://unrelated.test', 'service': 'cache'}, 'startsAt': datetime.now(UTC).isoformat()}]})
            stress = await create('stress', 'Stress checkout from 5 to 40 users for 35 seconds, p95 under 500 ms and errors under 1%.')
            assert stress['run']['slo_passed'] is False
            assert stress['investigation']['likely_root_cause'] == 'Modeled connection-pool contention'
            correlation = evidence['runs']['stress']['report']['correlation']
            assert correlation['duplicates_removed'] > 0, correlation
            assert correlation['excluded_unrelated_notifications'] >= 1
            await asyncio.sleep(.5)
            denied = await client.post(api + f'/api/runs/{stress["run"]["id"]}/remediate', json={'action': 'ExecuteShell', 'pool_size': 12})
            assert denied.status_code == 422
            action = await request('POST', f'/api/runs/{stress["run"]["id"]}/remediate', json={'pool_size': 12})
            verification = await complete(action['verification_run_id'])
            evidence['runs']['verification'] = await request('GET', f'/api/runs/{verification["run"]["id"]}/report')
            comparison = await request('GET', f'/api/runs/{verification["run"]["id"]}/compare/{stress["run"]["id"]}')
            assert comparison['same_workload'] is True
            assert verification['run']['metrics']['http_req_duration.p(95)'] < stress['run']['metrics']['http_req_duration.p(95)']
            evidence['remediation'], evidence['comparison'] = action, comparison
            print('remediation: exact workload rerun improved measured p95', flush=True)
            await asyncio.sleep(.5)
            evidence['rollback'] = await request('POST', f'/api/remediations/{action["id"]}/rollback')
            await control({'db_pool_size': 12, 'db_latency_ms': 35, 'memory_growth_kb': 16})
            await create('short_soak', 'Soak checkout with 3 users for 10 seconds, p95 under 500 ms and errors under 1%.')
            assert evidence['runs']['short_soak']['report']['evidence']['soak_memory']['growth_bytes'] > 0
            run = await request('POST', '/api/tests', json={'prompt': 'Baseline products with 1 user for 5 seconds', 'source_url': target + '/openapi.json', 'run_at': (datetime.now(UTC) + timedelta(seconds=5)).isoformat()})
            assert run['state'] == 'SCHEDULED'
            api_process.terminate()
            api_process.wait(timeout=10)
            api_process = launch('loadpilot.api', api_port)
            await ready(api + '/api/health')
            scheduled = await complete(run['id'])
            evidence['scheduled_after_restart'] = scheduled['run']['id']
            run = await request('POST', '/api/tests', json={'prompt': 'Soak checkout with 2 users for 60 seconds', 'source_url': target + '/openapi.json', 'auto_start': True})
            for _ in range(100):
                detail = await request('GET', f'/api/runs/{run["id"]}')
                if detail['run']['state'] == 'RUNNING':
                    break
                await asyncio.sleep(.1)
            await request('POST', f'/api/runs/{run["id"]}/cancel', json={'reason': 'Acceptance test checks real cancellation'})
            await asyncio.sleep(1)
            assert (await request('GET', f'/api/runs/{run["id"]}'))['run']['state'] == 'CANCELED'
            evidence['canceled_run_id'] = run['id']
            evidence['audit'] = await request('GET', '/api/audit?limit=1000')
            evidence['status'] = 'passed'
        except Exception as exc:
            evidence['status'] = 'failed'
            evidence['error'] = str(exc)
            raise
        finally:
            (output / 'evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            for log in logs:
                log.close()
            print(f'Evidence saved: {output / "evidence.json"}', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
