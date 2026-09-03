"""HTTP surface for Harbour.

    POST /case     {"case_id", "customer_id", "message"[, "loan_id"]}
                -> {"case_id", "summary", "actions_taken", "trace_id"}
    GET  /healthz  -> {"ok": true}

Standard library ``http.server`` so the service starts anywhere with no install
step. All configuration is read from the environment:

    HARBOUR_HOST        bind address (default 127.0.0.1)
    HARBOUR_PORT        bind port (default 8080)
    HARBOUR_DB          SQLite path handed to Backend (default harbour.db)
    HARBOUR_TRACE_FILE  span sink, see tracing.py
    LLM_*               see llm.py
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

try:  # package import when OP-01 is on sys.path, flat import when harbour/ is
    from . import agent
except ImportError:  # pragma: no cover - exercised by direct script runs
    import agent  # type: ignore[no-redef]

MAX_BODY_BYTES = 64 * 1024
_BACKEND_INIT_LOCK = threading.Lock()


def make_backend() -> Any:
    """Build the Backend the handler will use, from environment config."""
    try:
        from . import backend as backend_module  # type: ignore[attr-defined]
    except ImportError:  # pragma: no cover - direct script runs
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from harbour import backend as backend_module  # type: ignore[no-redef]
    try:
        from .seed_data import load_seed
    except ImportError:
        from harbour.seed_data import load_seed
    # SQLite connections belong to their request thread. Seed once on an empty store.
    with _BACKEND_INIT_LOCK:
        backend = backend_module.Backend(os.environ.get("HARBOUR_DB", "harbour.db"))
        if not backend.conn.execute("SELECT 1 FROM customers LIMIT 1").fetchone():
            load_seed(backend.conn)
    return backend


class HarbourHandler(BaseHTTPRequestHandler):
    server_version = "Harbour/1.0"
    protocol_version = "HTTP/1.1"

    # Optional injected test backend; production opens a connection per request.
    backend: Any = None

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        if os.environ.get("HARBOUR_ACCESS_LOG") == "1":
            super().log_message(fmt, *args)

    # ----------------------------------------------------------------- #

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            return None
        try:
            parsed = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    # ----------------------------------------------------------------- #

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == "/healthz":
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/case":
            self._send_json(404, {"error": "not found"})
            return

        payload = self._read_json()
        if payload is None:
            self._send_json(400, {"error": "body must be a JSON object"})
            return

        missing = [k for k in ("case_id", "customer_id", "message") if not payload.get(k)]
        if missing:
            self._send_json(400, {"error": f"missing fields: {', '.join(missing)}"})
            return

        owned_backend = self.backend is None
        backend = self.backend
        try:
            if owned_backend:
                backend = make_backend()
            result = agent.run_case(
                backend,
                case_id=str(payload["case_id"]),
                customer_id=str(payload["customer_id"]),
                message=str(payload["message"]),
                loan_id=payload.get("loan_id"),
            )
        except Exception as exc:  # noqa: BLE001 - never leak a stack trace
            self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return
        finally:
            if owned_backend and backend is not None:
                backend.close()

        self._send_json(
            200,
            {
                "case_id": result["case_id"],
                "summary": result["summary"],
                "actions_taken": result["actions_taken"],
                "trace_id": result["trace_id"],
            },
        )


def make_server(
    host: str | None = None, port: int | None = None, backend: Any = None
) -> ThreadingHTTPServer:
    """Build (but do not start) the HTTP server."""
    bind_host = host if host is not None else os.environ.get("HARBOUR_HOST", "127.0.0.1")
    bind_port = port if port is not None else int(os.environ.get("HARBOUR_PORT", "8080"))

    handler = type("BoundHarbourHandler", (HarbourHandler,), {"backend": backend})
    return ThreadingHTTPServer((bind_host, bind_port), handler)


def main() -> None:
    server = make_server()
    host, port = server.server_address[0], server.server_address[1]
    print(f"harbour listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
