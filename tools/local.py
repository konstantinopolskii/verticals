"""Docker-free local development. Persistent, isolated PostgreSQL; Ctrl-C stops services.

Usage: python3 tools/local.py setup | start
Requires Python 3.12, Node 22+, and PostgreSQL 16 (including pg_trgm).
Never reads the repository .env or touches an existing database.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.local-verticals'
PGDATA = STATE / 'postgres'
PYTHON = ROOT / '.venv/bin/python'


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, cwd=ROOT, **kwargs)


def pg_bin():
    candidates = [os.environ.get('VERTICALS_PG_BIN', ''),
                  '/opt/homebrew/opt/postgresql@16/bin',
                  '/usr/local/opt/postgresql@16/bin', '/usr/lib/postgresql/16/bin']
    found = shutil.which('pg_ctl')
    if found:
        candidates.append(str(Path(found).parent))
    for candidate in candidates:
        if candidate and (Path(candidate) / 'pg_ctl').is_file():
            version = subprocess.check_output([str(Path(candidate) / 'pg_ctl'), '--version'], text=True)
            if ' 16.' in version:
                return Path(candidate)
    raise SystemExit('PostgreSQL 16 required. Set VERTICALS_PG_BIN to its bin directory.')


def config():
    STATE.mkdir(mode=0o700, exist_ok=True)
    path = STATE / 'config.json'
    if not path.exists():
        with open(path, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as stream:
            json.dump({'token': secrets.token_urlsafe(32), 'password': secrets.token_urlsafe(32)}, stream)
    return json.loads(path.read_text())


def environment(settings):
    env = os.environ.copy()
    # Explicit values prevent dotenv from selecting a user's production/test database.
    env.update(VERTICALS_DATABASE_URL=f"postgresql://verticals:{settings['password']}@127.0.0.1:55439/verticals",
               VERTICALS_TOKEN=settings['token'], VERTICALS_OWNER='local',
               VERTICALS_BIND='127.0.0.1:8099', VERTICALS_POOL_MIN='1', VERTICALS_POOL_MAX='4',
               VITE_VERTICALS_TOKEN=settings['token'], VITE_ENABLE_DEV_TUNING='0',
               VITE_API_PROXY_TARGET='http://127.0.0.1:8099')
    return env


def port_free(port):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            raise SystemExit(f'Port {port} is occupied. Stop its owner first; no process was killed.')


def database(pg, settings):
    port_free(55439)
    if not PGDATA.exists():
        password = STATE / 'pg-password'
        try:
            with open(password, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as stream:
                stream.write(settings['password'])
            run([pg / 'initdb', '-D', PGDATA, '-U', 'verticals', '--auth=scram-sha-256',
                 '--pwfile', password, '--encoding=UTF8', '--no-locale'])
        finally:
            password.unlink(missing_ok=True)
    run([pg / 'pg_ctl', '-D', PGDATA, '-l', STATE / 'postgres.log', '-w', 'start',
         '-o', "-h 127.0.0.1 -p 55439 -k '' -c shared_buffers=32MB -c max_connections=20"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['setup', 'start'])
    args = parser.parse_args()
    pg = pg_bin()
    settings = config()
    env = environment(settings)
    if args.command == 'setup':
        lock = json.loads((ROOT / 'web/package-lock.json').read_text())
        for name in ['konstantinopolskii-design-system-2.1.1.tgz', 'konstantinopolskii-vue-2.1.1.tgz']:
            archive = ROOT / 'web/vendor' / name
            if not archive.is_file():
                raise SystemExit(f'Missing vendored dependency web/vendor/{name}; see README.')
            package = 'design-system' if 'design-system' in name else 'vue'
            expected = lock['packages'][f'node_modules/@konstantinopolskii/{package}']['integrity']
            actual = 'sha512-' + base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()
            if actual != expected:
                raise SystemExit(f'Integrity mismatch: web/vendor/{name}. Supply the lockfile-matching archive.')
        if not PYTHON.exists():
            run(['python3.12', '-m', 'venv', ROOT / '.venv'])
        run([PYTHON, '-m', 'pip', 'install', '-e', '.[dev]'])
        run(['npm', '--prefix', 'web', 'ci'])
        run(['npm', '--prefix', 'web', 'run', 'typecheck'])
        run(['npm', '--prefix', 'web', 'run', 'build'], env=env)
        print('Setup complete. Run: python3 tools/local.py start', flush=True)
        return
    if not PYTHON.exists() or not (ROOT / 'web/dist/index.html').exists():
        raise SystemExit('Run python3 tools/local.py setup first.')
    port_free(8099)
    port_free(8088)
    processes = []
    started = False
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        database(pg, settings)
        started = True
        run([PYTHON, '-c', '''import os, psycopg
from psycopg.conninfo import make_conninfo
url = os.environ['VERTICALS_DATABASE_URL']
with psycopg.connect(make_conninfo(url, dbname='postgres'), autocommit=True) as conn:
    if not conn.execute("SELECT 1 FROM pg_database WHERE datname='verticals'").fetchone():
        conn.execute('CREATE DATABASE verticals')
'''], env=env)
        run([PYTHON, '-m', 'verticals.db.runner', 'up'], env=env)
        if not (STATE / 'seeded').exists():
            run([PYTHON, '-c', '''import os, pathlib, psycopg
with psycopg.connect(os.environ['VERTICALS_DATABASE_URL']) as conn:
    if not conn.execute('SELECT 1 FROM goals LIMIT 1').fetchone():
        conn.execute(pathlib.Path('verticals/db/seed_sample.sql').read_text())
'''], env=env)
            (STATE / 'seeded').touch()
        # Rebuild with this isolated instance's token, never a token from web/.env.local.
        run(['npm', '--prefix', 'web', 'run', 'build'], env=env)
        for command in [[str(PYTHON), '-m', 'verticals.api.app'],
                        ['npm', '--prefix', 'web', 'run', 'preview', '--', '--host', '127.0.0.1', '--port', '8088', '--strictPort']]:
            processes.append(subprocess.Popen(command, cwd=ROOT, env=env, start_new_session=True))
        for attempt in range(60):
            if any(p.poll() is not None for p in processes):
                raise RuntimeError('A local service exited during startup.')
            try:
                with urllib.request.urlopen('http://127.0.0.1:8088/healthz', timeout=1) as response:
                    if json.load(response).get('db') == 'ok':
                        break
            except (OSError, ValueError):
                time.sleep(0.5)
        else:
            raise RuntimeError('Local health check timed out.')
        print('Verticals ready: http://127.0.0.1:8088/ — isolated sample database. Ctrl-C stops; data stays.', flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(1)
        raise RuntimeError('A local service exited; stopping remaining services.')
    except KeyboardInterrupt:
        print('Stopping local Verticals; preserving database.')
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
        if started:
            run([pg / 'pg_ctl', '-D', PGDATA, '-m', 'fast', '-w', 'stop'])


if __name__ == '__main__':
    main()
