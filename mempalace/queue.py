"""Persistent FIFO queue for MemPalace write operations.

Qdrant Server handles its own concurrency (HTTP API is thread-safe).
This queue is now an **application-level coordinator** that provides:

- Cross-process FIFO ordering across multiple Claude Code instances
- Durable write requests (survive crashes / restarts)
- Automatic retry with exponential backoff
- Duplicate suppression via atomic claim

No fcntl locks needed — Qdrant Server manages database-level locking.
"""

import json
import time
import uuid
from pathlib import Path
from functools import wraps

QUEUE_DIR = Path.home() / ".mempalace" / "queue"
FAILED_DIR = QUEUE_DIR / "failed"
PROCESSING_SUFFIX = ".processing"


def init_queue():
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(exist_ok=True)


def enqueue_request(operation: str, *args, **kwargs) -> str:
    """Enqueue a write request. Returns request ID."""
    init_queue()
    timestamp = time.time_ns()
    request_id = f"{timestamp}_{uuid.uuid4().hex[:12]}"
    request = {
        "id": request_id,
        "operation": operation,
        "args": args,
        "kwargs": kwargs,
        "created_at_ns": timestamp,
        "retry_count": 0,
    }
    with open(QUEUE_DIR / f"{request_id}.json", "w") as f:
        json.dump(request, f)
    return request_id


def get_next_request() -> dict | None:
    """Get the oldest pending request (skipping stale .processing files)."""
    init_queue()
    request_files = sorted(QUEUE_DIR.glob("*.json"), key=lambda x: x.name)
    if not request_files:
        return None

    for f in request_files:
        try:
            req = json.load(open(f))
            if "created_at_ns" in req:
                return req
        except Exception:
            continue
    return None


def _claim_request(request_id: str) -> bool:
    """Atomically claim a request for processing.

    Uses atomic rename — only one process wins. Returns True if claimed.
    """
    req_path = QUEUE_DIR / f"{request_id}.json"
    processing_path = QUEUE_DIR / f"{request_id}{PROCESSING_SUFFIX}"
    try:
        req_path.rename(processing_path)
        return True
    except FileNotFoundError:
        return False


def _release_request(request_id: str, success: bool):
    """Clean up after processing: delete on success, retry or fail on error."""
    processing_path = QUEUE_DIR / f"{request_id}{PROCESSING_SUFFIX}"
    if not processing_path.exists():
        return

    if success:
        processing_path.unlink(missing_ok=True)
        return

    # Failure — read current state for retry
    try:
        req = json.load(open(processing_path))
    except Exception:
        processing_path.unlink(missing_ok=True)
        return

    if req.get("retry_count", 0) < 3:
        req["retry_count"] = req.get("retry_count", 0) + 1
        # Exponential backoff: 2s, 4s, 8s
        backoff_ns = (2 ** req["retry_count"]) * 1_000_000_000
        req["next_retry_at"] = time.time_ns() + backoff_ns
        with open(QUEUE_DIR / f"{request_id}.json", "w") as f:
            json.dump(req, f)
        processing_path.unlink(missing_ok=True)
    else:
        # Max retries reached — move to failed directory
        processing_path.rename(FAILED_DIR / f"{request_id}.json")


def process_queue(handler):
    """Process all pending requests in strict FIFO order.

    Safe for concurrent callers from multiple Claude Code instances:
    only one caller will win each request via atomic rename claim.

    Args:
        handler: callable with signature (operation, args, kwargs)

    Returns:
        Number of requests successfully processed this call.
    """
    init_queue()
    processed = 0

    while True:
        req = get_next_request()
        if not req:
            break

        # Skip requests that are backing off from a previous failure
        next_retry = req.get("next_retry_at")
        if next_retry and time.time_ns() < next_retry:
            break

        # Atomic claim — if another process got here first, move on
        if not _claim_request(req["id"]):
            continue

        try:
            handler(req["operation"], req["args"], req["kwargs"])
            _release_request(req["id"], success=True)
            processed += 1
        except Exception:
            _release_request(req["id"], success=False)

    return processed


def queued(operation_name: str):
    """Decorator: automatically queue a function's execution."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            enqueue_request(operation_name, *args, **kwargs)
            process_queue(lambda op, a, kw: func(*a, **kw))
        return wrapper
    return decorator
