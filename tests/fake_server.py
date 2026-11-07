"""Local stand-in for the anti-theft server's POST /api/v1/transactions, for tests and manual runs.

Mirrors Geoplan-Philippines/rfid-anti-theft-server: the same validation (unknown fields rejected),
201 for a new sale, 200 for the same sale again, 409 for the same ID with a different body, the
{statusCode, message, data} wrapper, and 100 requests per minute per IP.

    python tests/fake_server.py --port 3000            # answer like the real server
    python tests/fake_server.py --port 3000 --fail 2   # answer 503 to the first 2 requests first

Each request is printed as one JSON line, so you can check exactly what the widget sent.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import sys
import threading
import time
import uuid

PATH = "/api/v1/transactions"
FIELDS = {"clientTransactionId", "storeCode", "deviceId", "cashierName", "startedAt", "endedAt", "tags"}
TAG_FIELDS = {"epc", "scannedAt"}
EPC = re.compile(r"[0-9A-F]{24}")
ISO_DATE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})")
UUID_TEXT = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
RATE_LIMIT = 100  # requests per minute per IP
REASONS = {
    400: "Bad Request",
    404: "Not Found",
    409: "Conflict",
    429: "ThrottlerException",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _instant_ms(value: str) -> int:
    # Pad the fraction to 6 digits: before Python 3.11, fromisoformat() only reads 3 or 6
    value = re.sub(r"\.(\d{1,6})", lambda m: "." + m.group(1).ljust(6, "0"), value.replace("Z", "+00:00"))
    return round(datetime.fromisoformat(value).timestamp() * 1000)


def _validate(body: object) -> list[str]:
    """class-validator style messages for CreateTransactionDTO; [] when the body is acceptable."""
    if not isinstance(body, dict):
        return ["request body must be a JSON object"]
    errors = [f"property {key} should not exist" for key in body if key not in FIELDS]
    sale_id = body.get("clientTransactionId")
    if not isinstance(sale_id, str) or not UUID_TEXT.fullmatch(sale_id):
        errors.append("clientTransactionId must be a UUID")
    for key in ("storeCode", "deviceId"):
        value = body.get(key)
        if not isinstance(value, str) or value == "":
            errors.append(f"{key} should not be empty")
        elif len(value) > 120:
            errors.append(f"{key} must be shorter than or equal to 120 characters")
    cashier = body.get("cashierName")
    if cashier is not None and (not isinstance(cashier, str) or len(cashier) > 120):
        errors.append("cashierName must be a string shorter than or equal to 120 characters")
    for key in ("startedAt", "endedAt"):
        if not isinstance(body.get(key), str) or not ISO_DATE_TIME.fullmatch(body[key]):
            errors.append(f"{key} must be a valid ISO 8601 date string")
    tags = body.get("tags")
    if not isinstance(tags, list):
        errors.append("tags must be an array")
    elif not tags:
        errors.append("tags must contain at least 1 elements")
    elif len(tags) > 200:
        errors.append("tags must contain no more than 200 elements")
    else:
        for index, tag in enumerate(tags):
            if not isinstance(tag, dict):
                errors.append(f"tags.{index} must be an object")
                continue
            errors += [f"tags.{index}.property {key} should not exist" for key in tag if key not in TAG_FIELDS]
            if not isinstance(tag.get("epc"), str) or tag["epc"] == "":
                errors.append(f"tags.{index}.epc should not be empty")
            if not isinstance(tag.get("scannedAt"), str) or not ISO_DATE_TIME.fullmatch(tag["scannedAt"]):
                errors.append(f"tags.{index}.scannedAt must be a valid ISO 8601 date string")
    return errors


class FakeTransactionServer:
    """In-memory transactions endpoint. `requests` records every POST: status, raw body, JSON, headers."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0, echo: bool = False) -> None:
        self.requests: list[dict] = []
        self._sales: dict[str, dict] = {}
        self._sold: set[str] = set()
        self._forced: list[tuple[int, float | None]] = []
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._echo = echo
        self._thread: threading.Thread | None = None
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                status, reply, headers = server.handle(self.path, self.client_address[0], raw, dict(self.headers))
                payload = json.dumps(reply).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args) -> None:
                pass

        self.httpd = ThreadingHTTPServer((host, port), Handler)

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def fail_next(self, *statuses: int, retry_after: float | None = None) -> None:
        """Answer the next requests with these statuses (e.g. 503, 429) before behaving normally again."""
        with self._lock:
            self._forced += [(status, retry_after) for status in statuses]

    def start(self) -> "FakeTransactionServer":
        self._thread = threading.Thread(target=self.httpd.serve_forever, args=(0.05,), daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def handle(self, path: str, client_ip: str, raw: bytes, request_headers: dict) -> tuple[int, dict, dict]:
        with self._lock:
            status, reply, headers = self._answer(path, client_ip, raw)
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except ValueError:
                parsed = None
            self.requests.append({"status": status, "raw": raw, "json": parsed, "headers": request_headers})
        if self._echo:
            sale = parsed if isinstance(parsed, dict) else {}
            tags = sale.get("tags") if isinstance(sale.get("tags"), list) else []
            line = {
                "at": _now(),
                "status": status,
                "clientTransactionId": sale.get("clientTransactionId"),
                "tags": [tag.get("epc") for tag in tags if isinstance(tag, dict)],
                "bodySha256": hashlib.sha256(raw).hexdigest(),
            }
            print(json.dumps(line), flush=True)
        return status, reply, headers

    def _answer(self, path: str, client_ip: str, raw: bytes) -> tuple[int, dict, dict]:
        now = time.monotonic()
        hits = [at for at in self._hits.get(client_ip, []) if now - at < 60.0]
        self._hits[client_ip] = hits + [now]
        if len(hits) >= RATE_LIMIT:
            wait = int(60.0 - (now - hits[0])) + 1
            return self._error(429, "ThrottlerException: Too Many Requests", path, {"Retry-After": str(wait)})
        if path != PATH:
            return self._error(404, f"Cannot POST {path}", path)
        if self._forced:
            status, retry_after = self._forced.pop(0)
            headers = {"Retry-After": str(retry_after)} if retry_after is not None else {}
            return self._error(status, "Forced failure from the fake server", path, headers)
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            return self._error(400, "Unexpected token in JSON", path)
        errors = _validate(body)
        if errors:
            return self._error(400, errors, path)

        tags: dict[str, int] = {}
        duplicates = 0
        for tag in body["tags"]:
            epc = "".join(tag["epc"].split()).upper()
            if not EPC.fullmatch(epc):
                return self._error(400, "EPC must be 24 hexadecimal characters", path)
            if epc in tags:
                duplicates += 1
                continue
            tags[epc] = _instant_ms(tag["scannedAt"])
        cashier = (body.get("cashierName") or "").strip() or None
        canonical = {
            "storeCode": body["storeCode"].strip(),
            "deviceId": body["deviceId"].strip(),
            "cashierName": cashier,
            "startedAt": _instant_ms(body["startedAt"]),
            "endedAt": _instant_ms(body["endedAt"]),
            "tags": tags,
        }
        sale_id = body["clientTransactionId"]
        stored = self._sales.get(sale_id)
        if stored is not None:
            if stored["canonical"] != canonical:
                return self._error(409, "This clientTransactionId was stored with a different body", path)
            return 200, {"statusCode": 200, "message": "Success", "data": stored["receipt"]}, {}
        receipt = {
            "id": str(uuid.uuid4()),
            "clientTransactionId": sale_id,
            "itemCount": len(tags),
            "duplicateEpcsIgnored": duplicates,
            "alreadySoldEpcs": [epc for epc in tags if epc in self._sold],
            "createdAt": _now(),
        }
        self._sold.update(tags)
        self._sales[sale_id] = {"canonical": canonical, "receipt": receipt}
        return 201, {"statusCode": 201, "message": "Success", "data": receipt}, {}

    @staticmethod
    def _error(
        status: int, message: str | list[str], path: str, headers: dict | None = None
    ) -> tuple[int, dict, dict]:
        body = {
            "statusCode": status,
            "message": message,
            "error": REASONS.get(status, "Error"),
            "path": path,
            "timestamp": _now(),
        }
        return status, body, headers or {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fake anti-theft server for POST /api/v1/transactions")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--fail", type=int, default=0, help="answer the first N requests with --fail-status")
    parser.add_argument("--fail-status", type=int, default=503)
    args = parser.parse_args()

    server = FakeTransactionServer(args.host, args.port, echo=True)
    server.fail_next(*[args.fail_status] * args.fail)
    print(f"Fake transactions server on {server.url}{PATH}", file=sys.stderr, flush=True)
    try:
        server.httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
