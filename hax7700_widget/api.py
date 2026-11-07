"""Send each finished scan session to the anti-theft server as one sale, keeping unsent sales on disk.

Shared by the GTK and Tk widgets. Stop -> `TransactionOutbox.submit()` saves the sale as
`pending/<endedAt>-<clientTransactionId>.json` -> a background thread POSTs that exact file to
`{serverUrl}/api/v1/transactions` until the server confirms it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import http.client
import json
import math
import os
from pathlib import Path
import random
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

TRANSACTIONS_PATH = "/api/v1/transactions"
MAX_TAGS = 200
MAX_TEXT_LENGTH = 120
REQUEST_TIMEOUT = 10.0
# Seconds to wait after each failed attempt in a row; the last value repeats until the server answers
RETRY_DELAYS = (5.0, 10.0, 20.0, 40.0, 60.0)
# Gap between requests while sending a backlog: at most 60 a minute, under the server's 100 per minute per IP
MIN_REQUEST_GAP = 1.0
_EPC_PATTERN = re.compile(r"[0-9A-F]{24}")


@dataclass(frozen=True)
class Settings:
    server_url: str
    store_code: str
    device_id: str
    cashier_name: str | None = None

    @property
    def transactions_url(self) -> str:
        return self.server_url.rstrip("/") + TRANSACTIONS_PATH


def load_settings(path: str | Path) -> tuple[Settings | None, str]:
    """Read settings.json. Returns (settings, "") or (None, a message to show in the window)."""
    path = Path(path)
    name = path.name
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None, f"{name} not found. Copy settings.example.json to {name} and fill it in."
    except json.JSONDecodeError as err:
        return None, f"{name} is not valid JSON (line {err.lineno}, column {err.colno})."
    except (OSError, UnicodeDecodeError) as err:
        return None, f"Cannot read {name}: {err}"
    if not isinstance(raw, dict):
        return None, f"{name} must be one {{ ... }} object with serverUrl, storeCode and deviceId."

    values: dict[str, str | None] = {}
    missing: list[str] = []
    for key in ("serverUrl", "storeCode", "deviceId", "cashierName"):
        value = raw.get(key)
        if isinstance(value, str):
            value = value.strip()
        if value is None or value == "":
            values[key] = None
            if key != "cashierName":
                missing.append(key)
        elif not isinstance(value, str):
            return None, f"{name}: {key} must be text in quotes."
        elif key != "serverUrl" and len(value) > MAX_TEXT_LENGTH:
            return None, f"{name}: {key} is longer than {MAX_TEXT_LENGTH} characters."
        else:
            values[key] = value
    if missing:
        return None, f"{name} is missing {', '.join(missing)}."
    url = urllib.parse.urlsplit(values["serverUrl"])
    if url.scheme not in ("http", "https") or not url.netloc:
        return None, f"{name}: serverUrl must start with http:// or https://"
    return Settings(values["serverUrl"], values["storeCode"], values["deviceId"], values["cashierName"]), ""


def iso_utc(value: datetime | str) -> str:
    """Format a timezone-aware time as UTC ISO 8601 with milliseconds and a Z: 2026-11-02T10:14:05.000Z."""
    moment = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if moment.tzinfo is None:
        raise ValueError(f"time without a timezone: {value!r}")
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def build_transaction(snapshot: dict, settings: Settings) -> dict | None:
    """Build the POST /api/v1/transactions body from a finished ScanSession snapshot; None if no tags."""
    if snapshot["ended_at"] is None:
        raise ValueError("finish() the session before building its transaction")
    if not snapshot["items"]:
        return None
    body = {
        "clientTransactionId": snapshot["session_id"],
        "storeCode": settings.store_code,
        "deviceId": settings.device_id,
    }
    if settings.cashier_name:
        body["cashierName"] = settings.cashier_name
    body["startedAt"] = iso_utc(snapshot["started_at"])
    body["endedAt"] = iso_utc(snapshot["ended_at"])
    # Snapshot items are newest first; send them in scan order with only the fields the server accepts
    body["tags"] = [
        {"epc": item["epc"], "scannedAt": iso_utc(item["first_seen_at"])} for item in reversed(snapshot["items"])
    ]
    return body


def transaction_problem(body: dict) -> str:
    """Why the server would refuse this sale (too many tags or a malformed EPC); "" if it can be sent."""
    tags = body["tags"]
    if len(tags) > MAX_TAGS:
        return f"{len(tags)} tags, more than the {MAX_TAGS} allowed in one sale"
    for tag in tags:
        if not _EPC_PATTERN.fullmatch("".join(tag["epc"].split()).upper()):
            return f"EPC {tag['epc']} is not 24 hex characters"
    return ""


@dataclass(frozen=True)
class SendResult:
    outcome: str  # "sent", "rejected" (400/409, never retried) or "retry"
    reason: str  # short text for the status line
    status: int | None = None  # HTTP status; None when the server was not reached
    item_count: int = 0
    retry_after: float | None = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # urllib would follow a redirect by re-sending the POST as a GET without its body; report the 3xx instead
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def post_transaction(
    url: str, body: bytes, client_transaction_id: str, timeout: float = REQUEST_TIMEOUT
) -> SendResult:
    """POST one sale (the exact saved bytes) and sort the reply by the server's rules."""
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"hax7700-widget/{__version__}",
        },
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            status, headers, raw = response.status, response.headers, response.read()
    except urllib.error.HTTPError as err:
        status, headers = err.code, err.headers
        try:
            raw = err.read()
        except (OSError, http.client.HTTPException):
            raw = b""
    except (OSError, http.client.HTTPException, ValueError) as err:
        return SendResult("retry", _network_reason(err))

    reply = _json_object(raw)
    if status in (200, 201):
        data = reply.get("data")
        if isinstance(data, dict) and str(data.get("clientTransactionId", "")).lower() == client_transaction_id.lower():
            count = data.get("itemCount")
            return SendResult("sent", "sent", status, item_count=count if isinstance(count, int) else 0)
        # Only the server's receipt for this ID proves the sale was stored (not some other web page)
        return SendResult("retry", f"HTTP {status} without a receipt", status)
    if status in (400, 409):
        message = _server_message(reply)
        return SendResult("rejected", f"HTTP {status}: {message}" if message else f"HTTP {status}", status)
    retry_after = _seconds(headers.get("Retry-After")) if status == 429 else None
    return SendResult("retry", f"HTTP {status}", status, retry_after=retry_after)


@dataclass(frozen=True)
class OutboxState:
    """What the widget shows about sending. Read it from any thread with `TransactionOutbox.state()`."""

    phase: str = "idle"  # idle, setup, empty, sending, sent, retry, rejected or error
    message: str = ""
    item_count: int = 0
    pending: int = 0  # sales saved in the pending folder, still waiting to be sent
    rejected: int = 0  # sales kept in pending/rejected for inspection, never retried
    retry_at: float = 0.0  # time.monotonic() of the next attempt while phase == "retry"


class TransactionOutbox:
    """Keeps every finished sale on disk until the server confirms it, sending from a background thread.

    - 201 (new) or 200 (already stored) with this clientTransactionId: the file is deleted.
    - 400 or 409: the file moves to `pending/rejected/` with a `.error.txt` note and is never retried.
    - 429, 5xx, any other reply, or no connection: the same file (same body, same ID) is retried
      with backoff, also after an app restart.
    """

    def __init__(
        self,
        pending_dir: str | Path,
        settings: Settings | None,
        settings_error: str = "",
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
        min_request_gap: float = MIN_REQUEST_GAP,
        timeout: float = REQUEST_TIMEOUT,
    ) -> None:
        self.pending_dir = Path(pending_dir)
        self.rejected_dir = self.pending_dir / "rejected"
        self.settings = settings
        self._retry_delays = retry_delays
        self._min_request_gap = min_request_gap
        self._timeout = timeout
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Only the sender touches these two
        self._failures = 0  # failed attempts in a row, for the backoff
        self._attempts: dict[str, int] = {}  # failed attempts per file, so one bad sale cannot block newer ones
        # Shared with submit(), so read and written under _lock
        self._next_try = 0.0
        self._rate_limited = False
        self._last_request = -math.inf
        self._state = OutboxState() if settings else OutboxState(phase="setup", message=settings_error)
        self._refresh_counts()

    @property
    def ready(self) -> bool:
        """True when settings.json is complete, so sales can be recorded and sent."""
        return self.settings is not None

    def state(self) -> OutboxState:
        with self._lock:
            return self._state

    def start(self) -> None:
        """Start the background sender (only with complete settings; safe to call twice)."""
        with self._lock:
            if self.settings is None or self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run, name="hax7700-outbox", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Ask the sender to stop. Unsent sales stay on disk and go out on the next start."""
        self._stop.set()
        self._wake.set()

    def submit(self, snapshot: dict) -> None:
        """Save a finished ScanSession snapshot as one sale and wake the sender. Never waits on the network."""
        if self.settings is None:
            return
        body = build_transaction(snapshot, self.settings)
        if body is None:
            self._update(phase="empty", message="", item_count=0)
            return
        problem = transaction_problem(body)
        try:
            path = _write_json(self.rejected_dir if problem else self.pending_dir, _file_name(body), body)
            if problem:
                _write_note(path, problem)
        except OSError as err:
            self._update(phase="error", message=f"Could not save this sale: {err}")
            return
        if problem:
            self._update(phase="rejected", message=self._kept(problem))
        else:
            with self._lock:
                if not self._rate_limited:
                    # A new sale is worth trying right away, even in the middle of a backoff
                    self._next_try = 0.0
                    self._state = replace(self._state, phase="sending", message="", item_count=len(body["tags"]))
            self._wake.set()
        self._refresh_counts()

    def send_next(self) -> SendResult | None:
        """Send the next waiting sale once, right now, and file it by the reply. None if nothing is waiting."""
        if self.settings is None:
            return None
        waiting = sorted(_json_files(self.pending_dir), key=lambda p: (self._attempts.get(p.name, 0), p.name))
        if not waiting:
            return None
        path = waiting[0]
        item_count = 0
        try:
            body = path.read_bytes()
            sale = json.loads(body.decode("utf-8"))
            sale_id, item_count = str(sale["clientTransactionId"]), len(sale["tags"])
        except FileNotFoundError:
            return None
        except OSError as err:
            result = SendResult("retry", f"cannot read the saved sale ({err.strerror or err})")
        except (ValueError, KeyError, TypeError) as err:
            result = SendResult("rejected", f"saved file is not a valid sale ({err})")
        else:
            self._update(phase="sending", message="", item_count=item_count)
            with self._lock:
                self._last_request = time.monotonic()
            result = post_transaction(self.settings.transactions_url, body, sale_id, self._timeout)

        if result.outcome == "sent":
            path.unlink(missing_ok=True)
            self._attempts.pop(path.name, None)
            self._failures = 0
            with self._lock:
                self._rate_limited = False
            self._update(phase="sent", message="", item_count=result.item_count or item_count)
        elif result.outcome == "rejected":
            self.rejected_dir.mkdir(parents=True, exist_ok=True)
            target = self.rejected_dir / path.name
            _replace(path, target)
            _write_note(target, result.reason)
            self._attempts.pop(path.name, None)
            self._failures = 0
            with self._lock:
                self._rate_limited = False
            self._update(phase="rejected", message=self._kept(result.reason))
        else:
            self._attempts[path.name] = self._attempts.get(path.name, 0) + 1
            self._schedule_retry(result)
        self._refresh_counts()
        return result

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                wait = max(self._next_try, self._last_request + self._min_request_gap) - time.monotonic()
            if not _json_files(self.pending_dir):
                wait = 30.0  # nothing to send: look again now and then, or as soon as a sale is submitted
            if wait > 0:
                self._wake.wait(wait)
                self._wake.clear()
                continue
            try:
                self.send_next()
            except Exception as err:  # one odd file or reply must never stop the sender for good
                self._schedule_retry(SendResult("retry", f"error: {err}"))

    def _schedule_retry(self, result: SendResult) -> None:
        self._failures += 1
        delay = self._retry_delays[min(self._failures, len(self._retry_delays)) - 1]
        # Never retry sooner than the server asked; the jitter keeps several tills from retrying in step
        delay = max(delay, result.retry_after or 0.0) * random.uniform(1.0, 1.2)
        with self._lock:
            self._next_try = time.monotonic() + delay
            self._rate_limited = result.status == 429
            self._state = replace(self._state, phase="retry", message=result.reason, retry_at=self._next_try)

    def _kept(self, reason: str) -> str:
        return f"{_clip(reason)}. Kept in {self.pending_dir.name}/{self.rejected_dir.name}"

    def _update(self, **changes) -> None:
        with self._lock:
            self._state = replace(self._state, **changes)

    def _refresh_counts(self) -> None:
        with self._lock:
            self._state = replace(
                self._state,
                pending=len(_json_files(self.pending_dir)),
                rejected=len(_json_files(self.rejected_dir)),
            )


def status_line(state: OutboxState, now: float | None = None) -> tuple[str, str]:
    """Text and tone ("muted", "busy", "ok", "warn" or "error") for the widget's status line."""
    if state.phase == "sending":
        return f"Sending {_items(state.item_count)}...", "busy"
    if state.phase == "sent":
        return f"Sent {_items(state.item_count)}", "ok"
    if state.phase == "retry":
        seconds = max(0, math.ceil(state.retry_at - (time.monotonic() if now is None else now)))
        return f"Saved offline, will retry in {seconds}s ({state.message})", "warn"
    if state.phase == "rejected":
        return f"Not sent: {state.message}", "error"
    if state.phase == "empty":
        return "No tags scanned, nothing sent", "muted"
    if state.phase in ("setup", "error"):
        return state.message, "error"
    return "", "muted"


def pending_line(state: OutboxState) -> tuple[str, str]:
    """Text and tone for the count of sales still waiting to be sent."""
    text = f"Waiting to send: {state.pending}"
    if state.rejected:
        return f"{text} · Rejected: {state.rejected}", "error"
    return text, "warn" if state.pending else "muted"


def _items(count: int) -> str:
    return "1 item" if count == 1 else f"{count} items"


def _clip(text: str, limit: int = 90) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _seconds(value: str | None) -> float | None:
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:
        return None


def _json_object(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _server_message(reply: dict) -> str:
    message = reply.get("message") or reply.get("error") or ""
    if isinstance(message, list):  # validation errors arrive as a list of strings
        message = "; ".join(str(part) for part in message)
    return str(message).strip()


def _network_reason(err: BaseException) -> str:
    reason = err.reason if isinstance(err, urllib.error.URLError) else err
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return "timed out"
    if isinstance(reason, ConnectionRefusedError):
        return "connection refused"
    if isinstance(reason, socket.gaierror):
        return "server name not found"
    if isinstance(reason, ssl.SSLError):
        return "TLS/certificate error"
    if isinstance(reason, (ConnectionError, http.client.HTTPException)):
        return "connection dropped"
    return "no connection"


def _json_files(folder: Path) -> list[Path]:
    return sorted(path for path in folder.glob("*.json") if path.is_file())


def _file_name(body: dict) -> str:
    # endedAt first so sorting by name is oldest first; the ID makes each file unique and easy to find
    stamp = re.sub(r"[^0-9TZ]", "", body["endedAt"])
    return f"{stamp}-{body['clientTransactionId']}.json"


def _write_json(folder: Path, name: str, body: dict) -> Path:
    """Write via a temp file + rename so a crash or power cut never leaves half a sale on disk."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    tmp = folder / (name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(body, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    _replace(tmp, path)
    return path


def _write_note(sale_path: Path, reason: str) -> None:
    """Explain next to a rejected sale why it was not sent (best effort: the sale file is what matters)."""
    try:
        sale_path.with_suffix(".error.txt").write_text(
            f"Not sent: {reason}\n"
            f"Noted at: {iso_utc(datetime.now(timezone.utc))}\n"
            "This sale is kept here for inspection and is never retried automatically.\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _replace(src: Path, dst: Path) -> None:
    # Antivirus on Windows can hold a brand-new file open for a moment; retry briefly before giving up
    for attempt in range(5):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05)
