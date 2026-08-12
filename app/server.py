"""Serve the OMS workspace and its OAG Agent API."""

from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.agent_runtime import OagAgentRuntime
from oms.spatial import SpatialViewService
from oms.store import ChangeValidationError


ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = ROOT / "app" / "static"
AGENT = OagAgentRuntime(ROOT)
SPATIAL = SpatialViewService(AGENT.repository) if AGENT.repository is not None else None


class OmsHandler(BaseHTTPRequestHandler):
    server_version = "OMS/0.1"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/bootstrap":
            self._json(AGENT.bootstrap())
        elif path == "/api/agent/status":
            self._json(AGENT.status())
        elif path == "/api/map/config":
            self._json(SpatialViewService.map_config())
        elif path.startswith("/api/spatial/objects/"):
            if SPATIAL is None:
                raise RuntimeError("OMS spatial service is unavailable")
            object_id = unquote(path.removeprefix("/api/spatial/objects/"))
            if not object_id:
                self._json({"error": "Object ID is required"}, HTTPStatus.BAD_REQUEST)
            else:
                try:
                    self._json(SPATIAL.get_view(object_id))
                except KeyError as exc:
                    self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        elif path.startswith("/api/"):
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        else:
            self._serve_static(path)

    def do_HEAD(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self.end_headers()
            return
        relative = unquote(path).lstrip("/") or "index.html"
        static_path = (STATIC_ROOT / relative).resolve()
        if not static_path.is_file():
            static_path = STATIC_ROOT / "index.html"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(static_path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(static_path.stat().st_size))
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/api/changes/preview":
                self._json(AGENT.call_domain(
                    "preview_changes",
                    operations=body.get("operations"),
                ))
            elif path == "/api/changes/apply":
                self._json(AGENT.call_domain(
                    "apply_changes",
                    operations=body.get("operations"),
                ))
            elif path == "/api/actions/available":
                self._json(AGENT.call_domain(
                    "get_available_actions",
                    context_id=str(body.get("context_id", "")),
                ))
            elif path == "/api/actions/preview":
                self._json(AGENT.call_domain(
                    "preview_action",
                    action_id=str(body.get("action_id", "")),
                    inputs=body.get("inputs") or {},
                    context_id=str(body.get("context_id", "")),
                ))
            elif path == "/api/actions/apply":
                self._json(AGENT.call_domain(
                    "apply_action",
                    preview_token=str(body.get("preview_token", "")),
                    reason=str(body.get("reason", "")),
                    actor=str(body.get("actor", "web_user")),
                    channel="ui",
                ))
            elif path == "/api/agent/chat":
                self._event_stream(AGENT.chat(str(body.get("message", "")), str(body.get("session_id", "default"))))
            elif path == "/api/agent/confirm":
                self._event_stream(AGENT.confirm(
                    str(body.get("session_id", "default")),
                    bool(body.get("approved")),
                    body.get("answer"),
                ))
            else:
                self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except ChangeValidationError as exc:
            self._json({"error": "Validation failed", "errors": exc.errors}, HTTPStatus.BAD_REQUEST)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format_string: str, *args) -> None:
        print(f"{self.address_string()} - {format_string % args}")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        return value

    def _json(self, value, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _event_stream(self, events) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        for event in events:
            self.wfile.write(json.dumps(event, ensure_ascii=False, default=str).encode("utf-8") + b"\n")
            self.wfile.flush()

    def _serve_static(self, request_path: str) -> None:
        relative = unquote(request_path).lstrip("/") or "index.html"
        path = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT not in path.parents and path != STATIC_ROOT:
            self._json({"error": "Invalid path"}, HTTPStatus.BAD_REQUEST)
            return
        if not path.is_file():
            path = STATIC_ROOT / "index.html"
        payload = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), OmsHandler)
    print(f"OMS running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        AGENT.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
