# qrporter/session_manager.py

import uuid
import time

_sessions = {}

# Hard cap on active sessions to prevent memory exhaustion (tune as needed)
MAX_ACTIVE_SESSIONS = 500

def create_session(mode, file_path=None, password=None, expires_in=600):
    token = uuid.uuid4().hex
    now = time.time()
    _sessions[token] = {
        "mode": mode,  # "send" or "receive"
        "file_path": file_path,  # for send
        "password": password,  # unused in current no-password flow
        "expires_at": now + expires_in,
        "client_ip": None,  # bound on first access
        "used": False,
        "last_access": now,
        "created_at": now,
    }
    enforce_max_active(MAX_ACTIVE_SESSIONS)
    return token

def verify_session(token, request_ip, password=None):
    prune_expired(time.time())
    data = _sessions.get(token)
    if not data:
        return False, "Invalid token"
    now = time.time()
    if now > data["expires_at"]:
        _sessions.pop(token, None)
        return False, "Token expired"
    if data["used"]:
        return False, "Token already used"
    if data.get("password"):
        if password != data["password"]:
            return False, "Wrong password"
    if data["client_ip"] and data["client_ip"] != request_ip:
        return False, "Token bound to another device"
    if not data["client_ip"]:
        data["client_ip"] = request_ip
    data["last_access"] = now
    return True, data

def mark_used(token):
    if token in _sessions:
        _sessions[token]["used"] = True
        _sessions[token]["last_access"] = time.time()

def expire_session(token):
    _sessions.pop(token, None)

def clear_all_sessions():
    _sessions.clear()

def prune_expired(now: float):
    expired = [t for t, s in _sessions.items() if now > s.get("expires_at", 0)]
    for t in expired:
        _sessions.pop(t, None)

def enforce_max_active(max_sessions: int):
    if not isinstance(max_sessions, int) or max_sessions <= 0:
        return
    n = len(_sessions)
    if n <= max_sessions:
        return
    excess = n - max_sessions
    sorted_tokens = sorted(_sessions.items(), key=lambda kv: kv[1].get("last_access", 0))
    for i in range(excess):
        _sessions.pop(sorted_tokens[i], None)
