import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import structlog

log = structlog.get_logger("gdrive-assistant-bot.health")


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/healthz", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok\n")
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: ARG002
        # silence stdlib access logs; we do structured logs ourselves
        return


def start_health_server(host: str, port: int, *, component: str) -> None:
    """
    Starts a tiny HTTP server in a daemon thread that exposes /healthz.
    """
    if port <= 0:
        return

    def _run() -> None:
        try:
            srv = ThreadingHTTPServer((host, port), _Handler)
            log.info(
                "health_server_started",
                component=component,
                flow="health",
                meta={
                    "host": host,
                    "port": port,
                    "thread": threading.current_thread().name,
                    "paths": ["/health", "/healthz"],
                },
            )
            srv.serve_forever()
        except Exception:
            log.exception(
                "health_server_failed",
                component=component,
                flow="health",
                meta={"host": host, "port": port, "thread": threading.current_thread().name},
            )

    threading.Thread(target=_run, name=f"{component}-health", daemon=True).start()
