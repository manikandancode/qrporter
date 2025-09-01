# qrporter/event_bus.py

import queue
import time
from typing import Optional, Dict, Any

# Global, process-local event queue
_events = queue.Queue()

def push_event(event_type: str, payload: Optional[Dict[str, Any]] = None):
    """
    Publish an event for the GUI to consume.
    event_type: short code, e.g., "device_connected", "suspicious_activity"
    payload: dict with details (ip, token, route, reason, count, etc.)
    """
    _events.put({
        "ts": time.time(),
        "type": event_type,
        "payload": payload or {}
    })

def try_pop_event() -> Optional[Dict[str, Any]]:
    """
    Non-blocking pop. Returns None if no event is waiting.
    """
    try:
        return _events.get_nowait()
    except queue.Empty:
        return None
