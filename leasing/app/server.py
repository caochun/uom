"""Serve the financing lease OMS workbench and its OAG Agent API."""

from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from leasing.app.agent_runtime import OagAgentRuntime
from uom.workspace import ChangeValidationError


ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
AGENT = OagAgentRuntime(ROOT, domain_dir=ROOT / "leasing")


class LeasingHandler(BaseHTTPRequestHandler):
    server_version = "LeasingOMS/0.1"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/bootstrap":
            self._json(AGENT.bootstrap(include_graph=False))
        elif path == "/api/agent/status":
            self._json(AGENT.status())
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
        try:
            static_path = self._static_path(path)
        except ValueError:
            self.send_response(HTTPStatus.BAD_REQUEST)
            self.end_headers()
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(static_path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(static_path.stat().st_size))
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            if path in {"/api/objects/query", "/api/relations/query"}:
                self._json(AGENT.workspace.query_records(
                    "object" if path == "/api/objects/query" else "relation",
                    filters=body.get("filters"),
                    limit=int(body.get("limit", 200)),
                    offset=int(body.get("offset", 0)),
                    order_by=body.get("order_by"),
                ))
            elif path == "/api/changes/preview":
                self._json(AGENT.workspace.preview_changes(body.get("operations")))
            elif path == "/api/changes/apply":
                self._json(AGENT.apply_changes(
                    operations=body.get("operations"),
                    reason=str(body.get("reason", "")),
                    actor=str(body.get("actor", "web_user")),
                    channel="ui",
                ))
            elif path == "/api/records/history":
                self._json(AGENT.workspace.get_record_history(
                    kind=str(body.get("kind", "")),
                    record_id=str(body.get("record_id", "")),
                    limit=int(body.get("limit", 100)),
                ))
            elif path == "/api/actions/available":
                self._json(AGENT.actions.list_actions(
                    context_id=str(body.get("context_id", "")),
                ))
            elif path == "/api/actions/preview":
                self._json(AGENT.actions.preview_action(
                    action_id=str(body.get("action_id", "")),
                    inputs=body.get("inputs") or {},
                    context_id=str(body.get("context_id", "")),
                ))
            elif path == "/api/actions/apply":
                self._json(AGENT.actions.execute_action(
                    preview_token=str(body.get("preview_token", "")),
                    reason=str(body.get("reason", "")),
                    actor=str(body.get("actor", "web_user")),
                    channel="ui",
                ))
            elif path == "/api/agent/chat":
                self._event_stream(AGENT.chat(str(body.get("message", "")), str(body.get("session_id", "default"))))
            elif path == "/api/agent/confirm":
                self._event_stream(AGENT.confirm(
                    str(body.get("session_id", "default")), bool(body.get("approved")), body.get("answer"),
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

    def _static_path(self, request_path: str) -> Path:
        relative = unquote(request_path).lstrip("/") or "index.html"
        path = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT not in path.parents and path != STATIC_ROOT:
            raise ValueError("Invalid path")
        return path if path.is_file() else STATIC_ROOT / "index.html"

    def _serve_static(self, request_path: str) -> None:
        try:
            path = self._static_path(request_path)
        except ValueError:
            self._json({"error": "Invalid path"}, HTTPStatus.BAD_REQUEST)
            return
        payload = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mimetypes.guess_type(path.name)[0] or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), LeasingHandler)
    print(f"Leasing OMS running at http://{args.host}:{args.port}")
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
