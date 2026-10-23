"""One loopback-only development command; owns and cleans up its worker process."""
import argparse
import os
import signal
import socket
import subprocess
import sys
import threading
import time

import uvicorn

from app.core.config import ROOT, load_settings
from app.persistence.database import Database
from app.persistence.models import WorkerHeartbeat, utcnow
from app.tools.init_db import initialize


def run(port: int = 8000) -> int:
    os.umask(0o077)
    stop = threading.Event()
    previous = {s: signal.signal(s, lambda *_: stop.set()) for s in (signal.SIGINT, signal.SIGTERM)}
    worker = None
    database = None
    server = None
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        # Reserve before initialization or spawning; never disturb another running instance.
        try:
            listener.bind(('127.0.0.1', port))
            listener.listen(128)
        except OSError:
            print(f'CareerLens could not reserve 127.0.0.1:{port}. Stop the existing server or choose --port.', file=sys.stderr)
            return 1
        if port != 8000:
            os.environ['CAREERLENS_ALLOWED_ORIGINS'] = f'http://127.0.0.1:{port},http://localhost:{port}'
        settings = load_settings()
        initialize(settings)
        database = Database(settings)
        with database.read() as session:
            heartbeat = session.get(WorkerHeartbeat, 'primary')
            if heartbeat and heartbeat.running and heartbeat.lease_expires_at > utcnow():
                print('A source worker already owns this workspace. Stop it before using the combined command.', file=sys.stderr)
                return 1
        worker = subprocess.Popen([sys.executable, '-m', 'app.worker'], cwd=ROOT,
                                  env=os.environ.copy(), start_new_session=True)
        deadline = time.monotonic() + 10
        while not stop.is_set() and time.monotonic() < deadline:
            if worker.poll() is not None:
                print('The source worker could not start. See the terminal message above.', file=sys.stderr)
                return 1
            with database.read() as session:
                heartbeat = session.get(WorkerHeartbeat, 'primary')
                if heartbeat and heartbeat.running and heartbeat.lease_expires_at > utcnow():
                    break
            stop.wait(0.1)
        else:
            if not stop.is_set():
                print('Worker startup timed out. Retry after its previous lease expires.', file=sys.stderr)
            return 1 if not stop.is_set() else 0

        from app.main import create_app
        server = uvicorn.Server(uvicorn.Config(create_app(settings), host='127.0.0.1', port=port,
                                                access_log=False, proxy_headers=False, log_level='warning'))

        def watch():
            while not stop.wait(0.2):
                if worker.poll() is not None:
                    print('Source worker stopped unexpectedly; shutting down CareerLens.', file=sys.stderr)
                    stop.set()
            server.should_exit = True

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        print(f'CareerLens → http://127.0.0.1:{port}/  (Ctrl+C stops API and worker)', flush=True)
        server.run(sockets=[listener])
        return 0 if worker.poll() is None else 1
    finally:
        stop.set()
        if worker and worker.poll() is None:
            worker.send_signal(signal.SIGTERM)
            try:
                worker.wait(timeout=40)  # Finish the bounded public source read.
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait()
        listener.close()
        if database:
            database.close()
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000, choices=range(1, 65536), metavar='PORT')
    args = parser.parse_args()
    try:
        return run(args.port)
    except Exception:
        # Startup errors may contain configured paths or credentials: no raw traceback.
        print('CareerLens startup failed. Check local configuration and run python -m app.tools.init_db.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
