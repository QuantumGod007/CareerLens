"""Exercise the real launcher and child cleanup without external source requests."""
import os
import signal
import socket
import subprocess
import sys
import time

import httpx

from app.core.config import ROOT, Settings
from app.persistence.database import Database
from app.persistence.models import WorkerHeartbeat


def environment(directory):
    return {**os.environ, 'CAREERLENS_DATA_DIR': str(directory), 'CAREERLENS_LEASE_SECONDS': '2',
            'CAREERLENS_HEARTBEAT_SECONDS': '.1'}


def test_dev_port_conflict_has_no_child_or_database_side_effect(tmp_path):
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
        directory = tmp_path / 'not-created'
        result = subprocess.run([sys.executable, '-m', 'app.dev', '--port', str(port)], cwd=ROOT,
            env=environment(directory), capture_output=True, text=True, timeout=10)
        assert result.returncode == 1
        assert 'could not reserve' in result.stderr
        assert not directory.exists()


def test_dev_starts_real_api_worker_and_sigterm_cleans_up(tmp_path):
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    directory = tmp_path / 'backend'
    process = subprocess.Popen([sys.executable, '-m', 'app.dev', '--port', str(port)], cwd=ROOT,
        env=environment(directory), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        deadline = time.monotonic() + 15
        ready = False
        while time.monotonic() < deadline:
            assert process.poll() is None, 'Launcher exited during startup'
            try:
                response = httpx.get(f'http://127.0.0.1:{port}/health', timeout=.3, trust_env=False)
                ready = response.status_code == 200 and response.json()['worker']['ready']
                if ready:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.1)
        assert ready
        assert httpx.get(f'http://127.0.0.1:{port}/', trust_env=False).status_code == 200
        # A second launcher must not stop the first launcher's worker.
        with socket.socket() as other:
            other.bind(('127.0.0.1', 0))
            other_port = other.getsockname()[1]
        second = subprocess.run([sys.executable, '-m', 'app.dev', '--port', str(other_port)], cwd=ROOT,
            env=environment(directory), capture_output=True, text=True, timeout=10)
        assert second.returncode == 1 and 'worker already owns' in second.stderr
        assert httpx.get(f'http://127.0.0.1:{port}/health', trust_env=False).json()['worker']['ready']
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
        assert 'CareerLens →' in stdout
        database = Database(Settings(data_dir=directory))
        try:
            with database.read() as session:
                assert session.get(WorkerHeartbeat, 'primary').running is False
        finally:
            database.close()
        with socket.socket() as released:
            released.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            released.bind(('127.0.0.1', port))
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=45)
