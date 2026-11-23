"""Run the RoomSphere API on your own computer (development only).

    docker compose up -d db          # Postgres 16 with schema + demo rooms loaded
    pip install pg8000==1.31.2
    python backend/local_server.py   # http://localhost:8000

It calls the same handler.py that runs in Lambda. API Gateway is replaced by this file:
  * the route table below plays the part of the API Gateway routes;
  * the Authorization header is a real Cognito ID token, but its signature is NOT verified here
    (API Gateway does that on AWS). Never expose this server beyond localhost.
  * SNS messages are printed to the console instead of being published.
Without a token, protected routes return 401. Sign in through the front end to get one.
"""
import base64
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "roomsphere")
os.environ.setdefault("DB_USER", "roomsphere_admin")
os.environ.setdefault("DB_PASSWORD", "localdev-password")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import handler  # noqa: E402

ALLOWED_ORIGINS = {"http://localhost:5500", "http://127.0.0.1:5500", "http://localhost:8080",
                   "http://localhost:3000", "https://seaweed3021.github.io"}

# (method, regex, routeKey used by the handler, needs token)
ROUTES = [
    ("GET", r"/health", "GET /health", False),
    ("GET", r"/rooms", "GET /rooms", False),
    ("GET", r"/rooms/(?P<id>[^/]+)", "GET /rooms/{id}", False),
    ("POST", r"/applications", "POST /applications", True),
    ("GET", r"/applications", "GET /applications", True),
    ("GET", r"/applications/mine", "GET /applications/mine", True),
    ("PATCH", r"/applications/(?P<id>[^/]+)", "PATCH /applications/{id}", True),
    ("POST", r"/applications/(?P<id>[^/]+)/payment", "POST /applications/{id}/payment", True),
    ("GET", r"/dashboard", "GET /dashboard", True),
]


def _print_notify(subject, message):
    print("[local SNS] %s | %s" % (subject, message))
    return True


handler._notify = _print_notify


def _claims_from_token(header):
    if not header or not header.lower().startswith("bearer "):
        return None
    try:
        payload = header.split(" ", 1)[1].split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None


class Api(BaseHTTPRequestHandler):
    def _cors(self):
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "authorization,content-type")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,OPTIONS")

    def _send(self, status, body, ctype="application/json"):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _handle(self, method):
        path = self.path.split("?")[0].rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode() if length else None
        # most specific route first, as API Gateway does ("/applications/mine" beats "/applications/{id}")
        for m, rx, key, protected in sorted(ROUTES, key=lambda r: ("{" in r[2], r[1])):
            hit = re.fullmatch(rx, path)
            if m != method or not hit:
                continue
            claims = {}
            if protected:
                claims = _claims_from_token(self.headers.get("Authorization"))
                if claims is None:
                    return self._send(401, json.dumps({"message": "Unauthorized"}))
            event = {"routeKey": key, "pathParameters": hit.groupdict() or None, "body": body,
                     "requestContext": {"authorizer": {"jwt": {"claims": claims}}}}
            out = handler.handler(event, None)
            return self._send(out["statusCode"], out["body"])
        self._send(404, json.dumps({"message": "Not Found"}))

    def do_GET(self): self._handle("GET")
    def do_POST(self): self._handle("POST")
    def do_PATCH(self): self._handle("PATCH")

    def log_message(self, fmt, *args):
        print("%s %s" % (self.command, self.path), "->", args[1] if len(args) > 1 else "")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print("RoomSphere local API on http://localhost:%d (dev only, tokens not verified)" % port)
    ThreadingHTTPServer(("127.0.0.1", port), Api).serve_forever()
