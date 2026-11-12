"""Start/stop the localhost CPU API and a temporary authenticated HTTPS tunnel."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local'
STATE = LOCAL / 'runtime.json'
SECRET = LOCAL / 'service-secret.json'


def write_private(path, data):
    path.write_text(json.dumps(data, indent=2))
    path.chmod(0o600)


def owned_pid(pid, marker):
    try:
        args = Path(f'/proc/{pid}/cmdline').read_bytes()
        return marker.encode() in args
    except OSError:
        return False


def stop():
    if not STATE.exists():
        print('Local service is not recorded as running.')
        return
    state = json.loads(STATE.read_text())
    for name, marker in [('tunnel_pid', str(LOCAL / 'bin/cloudflared')), ('api_pid', 'slicepoint_model.api:app')]:
        pid = state.get(name)
        if pid and owned_pid(pid, marker):
            os.kill(pid, signal.SIGTERM)
    state['running'] = False
    write_private(STATE, state)
    print('Stopped the tunnel and local API. The public URL is no longer served.')


def start():
    os.umask(0o077)
    LOCAL.mkdir(parents=True, exist_ok=True)
    LOCAL.chmod(0o700)
    if STATE.exists():
        state = json.loads(STATE.read_text())
        if owned_pid(state.get('api_pid', 0), 'slicepoint_model.api:app'):
            print('Service is already running. Use status, or stop before restarting.')
            return
    binary = LOCAL / 'bin/cloudflared'
    if not binary.is_file():
        raise RuntimeError('Run scripts/install_cloudflared.py first')
    if not SECRET.exists():
        write_private(SECRET, {'api_token': secrets.token_urlsafe(48)})
    secret = json.loads(SECRET.read_text())
    if len(secret.get('api_token', '')) < 32:
        raise RuntimeError('Configured token is too short')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    env = os.environ.copy()
    env.update({
        'SLICEPOINT_API_TOKEN': secret['api_token'], 'SLICEPOINT_DEVICE': 'cpu',
        'SLICEPOINT_FAST': '1', 'TOTALSEG_HOME_DIR': str(ROOT / 'models/totalsegmentator'),
        'MPLCONFIGDIR': str(LOCAL / 'matplotlib'), 'OMP_NUM_THREADS': '4', 'MKL_NUM_THREADS': '4',
        'MAX_UPLOAD_MB': '64', 'MAX_REQUESTS_PER_MINUTE': '6',
    })
    python = ROOT / '.venv/bin/python'
    with (LOCAL / 'api.log').open('ab') as log:
        api = subprocess.Popen([str(python), '-m', 'uvicorn', 'slicepoint_model.api:app',
                                '--host', '127.0.0.1', '--port', str(port), '--workers', '1',
                                '--no-access-log', '--no-proxy-headers'],
                               env=env, cwd=ROOT, stdin=subprocess.DEVNULL,
                               stdout=log, stderr=log, start_new_session=True)
    state = {'running': True, 'api_pid': api.pid, 'port': port, 'local_url': f'http://127.0.0.1:{port}'}
    write_private(STATE, state)
    try:
        for _ in range(50):
            if api.poll() is not None:
                raise RuntimeError('API startup failed; inspect .local/api.log')
            try:
                if requests.get(state['local_url'] + '/healthz', timeout=1).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(.2)
        else:
            raise RuntimeError('API startup timed out')
        tunnel_log = LOCAL / 'tunnel.log'
        tunnel_log.write_text('')
        with tunnel_log.open('ab') as log:
            # Keep API credentials out of the tunnel subprocess environment.
            tunnel = subprocess.Popen([str(binary), 'tunnel', '--no-autoupdate', '--protocol', 'http2',
                                       '--metrics', '127.0.0.1:0', '--url', state['local_url']],
                                      cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                      start_new_session=True)
        state['tunnel_pid'] = tunnel.pid
        write_private(STATE, state)
        for _ in range(100):
            if tunnel.poll() is not None:
                raise RuntimeError('Tunnel startup failed; inspect .local/tunnel.log')
            matches = re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com', tunnel_log.read_text())
            if matches:
                state['public_url'] = matches[-1]
                write_private(STATE, state)
                print(f'HTTPS API: {state["public_url"]}', flush=True)
                print('Comparison endpoint: POST /v1/compare', flush=True)
                print(f'API secret is stored privately in {SECRET}; it was not printed.', flush=True)
                return
            time.sleep(.3)
        raise RuntimeError('Tunnel URL was not assigned within 30 seconds')
    except Exception:
        stop()
        raise


def status():
    if not STATE.exists():
        print('Not running.')
        return
    state = json.loads(STATE.read_text())
    print(json.dumps({
        'api_running': owned_pid(state.get('api_pid', 0), 'slicepoint_model.api:app'),
        'tunnel_running': owned_pid(state.get('tunnel_pid', 0), str(LOCAL / 'bin/cloudflared')),
        'public_url': state.get('public_url'), 'local_url': state.get('local_url'),
    }, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    args = parser.parse_args()
    {'start': start, 'stop': stop, 'status': status}[args.action]()
