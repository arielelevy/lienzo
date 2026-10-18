"""Opt-in bridge for a Claude-owned child. No Claude credentials enter this module."""

import hashlib
import hmac
import json
import secrets
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_TEXT = 16000


class ClaudePipeBridge:
    """One in-memory bridge per explicitly launched session; never retries delivery."""

    def __init__(self, session_id: str):
        self.session_id = str(uuid.UUID(session_id))
        self._secret = secrets.token_urlsafe(32)
        self._condition = threading.Condition()
        self._jobs = {}
        self._closed = False
        self.resume = False
        self.last_poll = 0.0
        self.adapter_pid = None
        self.registered = threading.Event()
        self.before_first_poll = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def handle(self):
                try:
                    super().handle()
                except OSError, TimeoutError:
                    # Disconnects are transport outcomes, not traceback/log payloads.
                    return

            def log_message(self, *_):
                """HTTP access logging is intentionally disabled: credentials are private."""

            def do_POST(self):
                self.connection.settimeout(3)
                if not hmac.compare_digest(
                    self.headers.get("Authorization", "").encode(), ("Bearer " + owner._secret).encode()
                ):
                    self.send_error(403)
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size < 100000:
                        raise ValueError("invalid_size")
                    data = json.loads(self.rfile.read(size))
                    if not isinstance(data, dict):
                        raise TypeError("json_object_required")
                    if data.get("session_id") != owner.session_id:
                        self.send_error(409)
                        return
                    response = owner._request(self.path, data)
                except ValueError, KeyError, TypeError:
                    self.send_error(400)
                    return
                except OSError:
                    return
                encoded = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                try:
                    self.wfile.write(encoded)
                except BrokenPipeError, ConnectionResetError:
                    # A lost response never puts a dequeued job back in the queue.
                    return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def environment(self):
        return {
            "LIENZO_CLAUDE_BRIDGE_URL": f"http://127.0.0.1:{self._server.server_port}",
            "LIENZO_CLAUDE_BRIDGE_SECRET": self._secret,
            "LIENZO_CLAUDE_BRIDGE_SESSION": self.session_id,
        }

    @property
    def available(self):
        """Historical registration alone is never a capability signal."""
        return not self._closed and time.monotonic() - self.last_poll < 3

    def hook_settings(self):
        script = Path(__file__).with_name("claude_pipe_adapter.py").as_posix()
        command = f'"{Path(sys.executable).as_posix()}" "{script}" --hook'
        return {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": command, "timeout": 10}]}]}}

    def _request(self, route, data):
        # Closing takes lifecycle locks before the job condition. Persisting
        # registration must therefore happen outside this condition.
        if route == "/poll" and not self.registered.is_set() and self.before_first_poll is not None:
            self.before_first_poll(data.get("adapter_pid"))
        with self._condition:
            if self._closed:
                return {"stop": True, "resume": self.resume}
            if route == "/poll":
                self.last_poll = time.monotonic()
                self.adapter_pid = data.get("adapter_pid")
                self.registered.set()
                deadline = time.monotonic() + 1
                while not self._closed:
                    for key, job in self._jobs.items():
                        if job["status"] == "queued":
                            job["status"] = "writing"
                            return {"id": key, "text": job["text"]}
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return {}
                    self._condition.wait(remaining)
                return {"stop": True, "resume": self.resume}
            if route == "/result":
                job = self._jobs[data["id"]]
                if job["status"] not in ("writing", "unknown"):
                    raise ValueError("unexpected_result")
                if data["status"] not in ("pipe_written", "unknown"):
                    raise ValueError("invalid_status")
                job["status"] = data["status"]
                job.pop("text", None)
                self._condition.notify_all()
                return {"recorded": True}
            raise ValueError("unknown_route")

    def send(self, text: str, message_id: str, timeout: float = 5):
        key = str(uuid.UUID(message_id))
        if not isinstance(text, str) or not text or len(text.encode()) > MAX_TEXT:
            raise ValueError("invalid_text")
        if not 0 < timeout <= 30:
            raise ValueError("invalid_timeout")
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self._condition:
            if self._closed:
                raise RuntimeError("bridge_closed")
            if key in self._jobs:
                job = self._jobs[key]
                if job["digest"] != digest:
                    raise ValueError("message_id_conflict")
                return {"id": key, "status": job["status"]}
            if len(self._jobs) >= 1000:
                raise RuntimeError("bridge_capacity")
            job = {"text": text, "digest": digest, "status": "queued"}
            self._jobs[key] = job
            self._condition.notify_all()
            deadline = time.monotonic() + timeout
            while job["status"] in ("queued", "writing"):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    # Even a queued timeout is final: never deliver unexpectedly later.
                    job["status"] = "unknown"
                    job.pop("text", None)
                    break
                self._condition.wait(remaining)
            return {"id": key, "status": job["status"]}

    def close(self):
        with self._condition:
            self._closed = True
            for job in self._jobs.values():
                if job["status"] in ("queued", "writing"):
                    job["status"] = "unknown"
                    job.pop("text", None)
            self._condition.notify_all()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(3)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
