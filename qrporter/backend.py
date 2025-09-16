# qrporter/backend.py

import os
import signal
import threading
import time
import re
import hmac
import hashlib
import base64
import logging
from logging.handlers import RotatingFileHandler
from collections import defaultdict, deque

from platformdirs import user_data_dir, user_log_dir

from flask import (
    Flask, request, send_from_directory,
    render_template, abort, make_response, jsonify
)
from werkzeug.utils import secure_filename

from qrporter.session_manager import (
    verify_session, mark_used, clear_all_sessions,
    prune_expired, enforce_max_active, MAX_ACTIVE_SESSIONS
)
from qrporter.utils import allowed_file
from qrporter.event_bus import push_event

import zipfile
import io
from datetime import datetime

APP_NAME = "QRPorter"

# -------- Cross-platform, per-user data locations --------
DATA_ROOT = user_data_dir(APP_NAME, roaming=True, ensure_exists=True)
DOWNLOAD_FOLDER = os.path.join(DATA_ROOT, "shared")
RECEIVED_FOLDER = os.path.join(DATA_ROOT, "received")
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(RECEIVED_FOLDER, exist_ok=True)
CURRENT_DOWNLOAD_FOLDER = DOWNLOAD_FOLDER
CURRENT_RECEIVED_FOLDER = RECEIVED_FOLDER

app = Flask(
    __name__,
    template_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), 'templates')),
    static_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), 'static'))
)

# ----- Logging configuration (file only;) -----
LOG_DIR = user_log_dir(APP_NAME, ensure_exists=True)
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, 'qrporter.log')
app.logger.setLevel(logging.INFO)
file_handler = RotatingFileHandler(LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_fmt = logging.Formatter('[%(asctime)s] %(levelname)s %(message)s')
file_handler.setFormatter(file_fmt)
if not any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
    app.logger.addHandler(file_handler)
for h in list(app.logger.handlers):
    if not isinstance(h, RotatingFileHandler):
        app.logger.removeHandler(h)
import logging as _logging
werk_logger = _logging.getLogger("werkzeug")
werk_logger.setLevel(_logging.ERROR)
werk_logger.propagate = False
for h in list(werk_logger.handlers):
    werk_logger.removeHandler(h)

app.secret_key = os.environ.get("QRPORTER_SECRET_KEY", "change-this-to-a-strong-random-value")
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024 * 1024

_filename_safe_re = re.compile(r'[^A-Za-z0-9.\-_ ]+')

def sanitize_filename(name: str) -> str:
    base = secure_filename(name or '')
    base = _filename_safe_re.sub('', base)
    if not base:
        base = 'file'
    base = re.sub(r'\s{2,}', ' ', base).strip()
    base = re.sub(r'\.{2,}', '.', base)
    return base

def _ensure_within_dir(base_dir: str, candidate_path: str) -> bool:
    base_dir = os.path.abspath(base_dir)
    candidate_path = os.path.abspath(candidate_path)
    try:
        return os.path.commonpath([base_dir]) == os.path.commonpath([base_dir, candidate_path])
    except Exception:
        return False

def _client_ip() -> str:
    return request.remote_addr or "-"

def _log_event(event: str, **fields):
    kv = " ".join(f"{k}={repr(v)}" for k, v in fields.items())
    app.logger.info("%s %s", event, kv)

# --- CSRF protection: HMAC token tied to session token and user agent ---
def _csrf_key() -> bytes:
    return hashlib.sha256(app.secret_key.encode("utf-8")).digest()

def generate_csrf_token(session_token: str) -> str:
    ua = request.headers.get("User-Agent", "")
    msg = f"{session_token}:{ua}".encode("utf-8")
    sig = hmac.new(_csrf_key(), msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")

def validate_csrf_token(session_token: str, token_from_form: str) -> bool:
    if not token_from_form:
        return False
    ua = request.headers.get("User-Agent", "")
    msg = f"{session_token}:{ua}".encode("utf-8")
    expected = hmac.new(_csrf_key(), msg, hashlib.sha256).digest()
    try:
        raw = base64.urlsafe_b64decode(token_from_form + "===")
    except Exception:
        return False
    return hmac.compare_digest(expected, raw)

@app.after_request
def _set_security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline';"
    )
    return resp

@app.after_request
def _no_cache_sensitive(resp):
    if request.path.startswith(app.static_url_path or "/static"):
        return resp
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# --- Simple in-memory rate limiting (per IP) ---
_rate_buckets = defaultdict(lambda: defaultdict(deque))
UPLOAD_PER_MIN = 5
UPLOAD_PER_HOUR = 50
DL_PER_MIN = 30

def _now():
    return time.time()

def _prune_window(dq: deque, window_sec: int, now_t: float):
    while dq and now_t - dq[0] > window_sec:
        dq.popleft()

def _check_limit(bucket_name: str, limit: int, window_sec: int, ip: str, now_t: float) -> bool:
    dq = _rate_buckets[ip][bucket_name]
    _prune_window(dq, window_sec, now_t)
    if len(dq) >= limit:
        return False
    dq.append(now_t)
    return True

def _too_many(msg: str):
    resp = make_response(msg, 429)
    resp.headers["Retry-After"] = "60"
    return resp

def _is_maintenance_path(path: str) -> bool:
    return path.startswith("/__shutdown__") or path.startswith("/__clear_sessions__") or path.startswith("/__cleanup_parts__") or path.startswith("/__set_folders__")

@app.before_request
def _apply_rate_limits():
    path = request.path or ""
    if path.startswith(app.static_url_path or "/static") or _is_maintenance_path(path):
        return None
    ip = _client_ip()
    t = _now()
    if path.startswith("/receive/") and request.method == "POST":
        if not _check_limit("upload_min", UPLOAD_PER_MIN, 60, ip, t):
            _log_event("rate_limit_block", ip=ip, path=path, method="POST", rule="upload_minute")
            return _too_many("Too many uploads. Please wait and try again.")
        if not _check_limit("upload_hour", UPLOAD_PER_HOUR, 3600, ip, t):
            _log_event("rate_limit_block", ip=ip, path=path, method="POST", rule="upload_hour")
            return _too_many("Too many uploads in the last hour. Please try later.")
        return None
    if path.startswith("/download/") and request.method == "GET":
        if not _check_limit("dl_min", DL_PER_MIN, 60, ip, t):
            _log_event("rate_limit_block", ip=ip, path=path, method="GET", rule="download_minute")
            return _too_many("Too many downloads. Please wait and try again.")
        return None
    if path.startswith("/send/") and request.method == "GET":
        if not _check_limit("send_min", DL_PER_MIN, 60, ip, t):
            _log_event("rate_limit_block", ip=ip, path=path, method="GET", rule="send_minute")
            return _too_many("Too many requests. Please wait and try again.")
        return None
    return None

_failed_window = 120.0  # seconds
_failed_threshold = 5  # failures within window
_failed_attempts = defaultdict(deque)

def _note_failure(ip: str):
    dq = _failed_attempts[ip]
    now = _now()
    _prune_window(dq, int(_failed_window), now)
    dq.append(now)
    if len(dq) >= _failed_threshold:
        push_event("suspicious_activity", {
            "ip": ip,
            "reason": "multiple_failures",
            "count": len(dq),
            "window_sec": _failed_window
        })

def _is_private_ip(ip: str) -> bool:
    return (
        ip.startswith("10.") or ip.startswith("192.168.") or
        any(ip.startswith(f"172.{i}.") for i in range(16, 32)) or
        ip == "127.0.0.1" or ip == "::1"
    )

def _unique_path(directory: str, filename: str) -> str:
    directory = os.path.abspath(directory)
    base = os.path.basename(filename)
    stem, ext = os.path.splitext(base)
    candidate = os.path.join(directory, base)
    if not os.path.exists(candidate):
        return candidate
    n = 1
    while True:
        candidate = os.path.join(directory, f"{stem} ({n}){ext}")
        if not os.path.exists(candidate):
            return candidate
        n += 1

@app.route('/__set_folders__', methods=['POST'])
def __set_folders():
    ip = _client_ip()
    if ip not in ('127.0.0.1', '::1'):
        _log_event("set_folders_denied", ip=ip)
        return abort(403)
    try:
        data = request.get_json(silent=True) or {}
        dl = data.get("download")
        rc = data.get("received")
        global CURRENT_DOWNLOAD_FOLDER, CURRENT_RECEIVED_FOLDER
        if dl:
            dl_abs = os.path.abspath(dl)
            os.makedirs(dl_abs, exist_ok=True)
            CURRENT_DOWNLOAD_FOLDER = dl_abs
        if rc:
            rc_abs = os.path.abspath(rc)
            os.makedirs(rc_abs, exist_ok=True)
            CURRENT_RECEIVED_FOLDER = rc_abs
        _log_event("set_folders_ok", download=CURRENT_DOWNLOAD_FOLDER, received=CURRENT_RECEIVED_FOLDER)
        return jsonify(ok=True), 200
    except Exception as e:
        _log_event("set_folders_error", error=str(e))
        return jsonify(ok=False, error="failed"), 500

# --- Send file to mobile route ---
@app.route('/send/<token>', methods=['GET'])
def send_file(token):
    ip = _client_ip()
    ok, sess = verify_session(token, ip, password=None)
    if not ok:
        _log_event("auth_failed", ip=ip, route="/send", method="GET", token=token, reason=sess)
        _note_failure(ip)
        return sess, 403

    filepath = sess.get("file_path")
    if not filepath or not os.path.isfile(filepath):
        _log_event("download_prepare_missing", ip=ip, token=token, filepath=filepath)
        return "File not found on server", 404

    filename = os.path.basename(filepath)
    _log_event("download_prepare_ok", ip=ip, token=token, filename=filename)
    csrf_token = generate_csrf_token(token)
    push_event("device_connected", {"ip": ip, "token": token, "route": "/send"})
    return render_template('send_file.html', filename=filename, token=token, csrf_token=csrf_token)

# --- Download file from PC route ---
@app.route('/download/<token>/<filename>', methods=['GET'])
def download_file(token, filename):
    ip = _client_ip()
    ok, sess = verify_session(token, ip, password=None)
    if not ok:
        _log_event("auth_failed", ip=ip, route="/download", method="GET", token=token, reason=sess)
        _note_failure(ip)
        return sess, 403

    session_path = sess.get("file_path") or ""
    if not session_path or not os.path.isfile(session_path):
        _log_event("download_missing_session_path", ip=ip, token=token, path=session_path)
        return "File not found", 404

    if not _ensure_within_dir(CURRENT_DOWNLOAD_FOLDER, session_path):
        _log_event("download_outside_dir", ip=ip, token=token, path=session_path, base=CURRENT_DOWNLOAD_FOLDER)
        return "Invalid path", 400

    mark_used(token)
    try:
        fsize = os.path.getsize(session_path)
    except Exception:
        fsize = -1

    _log_event("download_success", ip=ip, token=token, filename=os.path.basename(session_path), size=fsize)
    push_event("device_connected", {"ip": ip, "token": token, "route": "/download"})
    base = os.path.dirname(session_path)
    safe_name = os.path.basename(session_path)
    return send_from_directory(base, safe_name, as_attachment=True)

# --- Receive files from mobile (supports multiple files) ---
@app.route('/receive/<token>', methods=['GET', 'POST'])
def receive_file(token):
    import shutil  # local import to keep global imports unchanged
    ip = _client_ip()
    ok, sess = verify_session(token, ip, password=None)
    if not ok:
        _log_event("auth_failed", ip=ip, route="/receive", method=request.method, token=token, reason=sess)
        _note_failure(ip)
        return sess, 403

    if request.method == 'POST':
        form_csrf = request.form.get("_csrf", "")
        if not validate_csrf_token(token, form_csrf):
            _log_event("csrf_failed", ip=ip, route="/receive", token=token)
            _note_failure(ip)
            return "Invalid CSRF token", 403

        files = request.files.getlist('files')
        if not files or all(not f.filename for f in files):
            _log_event("upload_no_file", ip=ip, token=token)
            return "No files provided", 400

        size_hint_raw = request.form.get("size")
        try:
            total_size_hint = int(size_hint_raw) if size_hint_raw else None
        except:
            total_size_hint = None

        if total_size_hint and total_size_hint > 0:
            try:
                total, used, free = shutil.disk_usage(CURRENT_RECEIVED_FOLDER)
            except:
                total = used = free = -1
            
            required = int(total_size_hint * 1.05)
            if free >= 0 and free < required:
                _log_event("upload_insufficient_space", ip=ip, token=token, 
                          files_count=len(files), need=required, free=free)
                return "Insufficient disk space for upload", 507

        saved_files = []
        total_saved_size = 0
        
        for file_idx, file in enumerate(files):
            if not file or not file.filename:
                continue
                
            original_name = file.filename
            cleaned_name = sanitize_filename(os.path.basename(original_name))
            
            if not allowed_file(cleaned_name):
                _log_event("upload_invalid_type", ip=ip, token=token, 
                          filename=cleaned_name, file_index=file_idx)
                continue

            final_path = _unique_path(CURRENT_RECEIVED_FOLDER, cleaned_name)
            
            if not _ensure_within_dir(CURRENT_RECEIVED_FOLDER, final_path):
                _log_event("upload_invalid_path", ip=ip, token=token, 
                          filename=cleaned_name, file_index=file_idx)
                continue

            base_part = final_path + ".part"
            part_path = base_part
            suffix = 1
            while os.path.exists(part_path):
                part_path = f"{base_part}.{suffix}"
                suffix += 1

            try:
                os.makedirs(os.path.dirname(final_path), exist_ok=True)
                _log_event("upload_start", ip=ip, token=token, 
                          filename=os.path.basename(final_path), file_index=file_idx)
                file.save(part_path)
                try:
                    part_size = os.path.getsize(part_path)
                except:
                    part_size = -1
                if part_size > app.config['MAX_CONTENT_LENGTH']:
                    try:
                        os.remove(part_path)
                    except:
                        pass
                    _log_event("upload_too_large", ip=ip, token=token, 
                              filename=os.path.basename(final_path), 
                              size=part_size, file_index=file_idx)
                    continue
                try:
                    os.replace(part_path, final_path)
                except FileExistsError:
                    final_path = _unique_path(CURRENT_RECEIVED_FOLDER, os.path.basename(final_path))
                    os.replace(part_path, final_path)
                try:
                    saved_size = os.path.getsize(final_path)
                    total_saved_size += saved_size
                except:
                    saved_size = -1
                saved_files.append({
                    'filename': os.path.basename(final_path),
                    'path': final_path,
                    'size': saved_size
                })
                _log_event("upload_success", ip=ip, token=token, 
                          filename=os.path.basename(final_path), 
                          size=saved_size, file_index=file_idx)

            except Exception as e:
                try:
                    if os.path.exists(part_path):
                        os.remove(part_path)
                except:
                    pass
                _log_event("upload_failed", ip=ip, token=token, 
                          filename=cleaned_name, error=str(e), file_index=file_idx)
                continue

        if not _is_private_ip(ip):
            push_event("suspicious_activity", {
                "ip": ip,
                "reason": "unexpected_ip_upload",
                "file_count": len(saved_files)
            })

        if saved_files:
            mark_used(token)
            push_event("device_connected", {
                "ip": ip,
                "token": token,
                "route": "/receive"
            })
            if len(saved_files) == 1:
                return f"File received: {saved_files[0]['filename']}"
            else:
                file_list = ", ".join([f['filename'] for f in saved_files])
                return f"{len(saved_files)} files received: {file_list}"
        else:
            return "No valid files were uploaded", 400

    csrf_token = generate_csrf_token(token)
    _log_event("upload_form_render", ip=ip, token=token)
    return render_template('receive_file.html', token=token, csrf_token=csrf_token)

@app.route('/__clear_sessions__', methods=['POST'])
def __clear_sessions():
    ip = _client_ip()
    if ip not in ('127.0.0.1', '::1'):
        _log_event("clear_sessions_denied", ip=ip)
        return abort(403)
    clear_all_sessions()
    _log_event("clear_sessions_ok", ip=ip)
    return "Sessions cleared", 200

@app.route('/__cleanup_parts__', methods=['POST'])
def __cleanup_parts():
    ip = _client_ip()
    if ip not in ('127.0.0.1', '::1'):
        _log_event("cleanup_parts_denied", ip=ip)
        return abort(403)
    removed = 0
    try:
        for name in os.listdir(CURRENT_RECEIVED_FOLDER):
            if not name.endswith(".part"):
                continue
            path = os.path.join(CURRENT_RECEIVED_FOLDER, name)
            try:
                os.remove(path)
                removed += 1
            except Exception as e:
                _log_event("cleanup_parts_error", file=name, error=str(e))
    except Exception as e:
        _log_event("cleanup_iter_error", error=str(e))
    _log_event("cleanup_parts_ok", removed=removed)
    return f"Removed {removed} unfinished files", 200

@app.route('/__shutdown__', methods=['POST'])
def __shutdown():
    ip = _client_ip()
    if ip not in ('127.0.0.1', '::1'):
        _log_event("shutdown_denied", ip=ip)
        return abort(403)
    func = request.environ.get('werkzeug.server.shutdown')
    if func is not None:
        _log_event("shutdown_ok", ip=ip, mode="werkzeug")
        func()
        return "Server shutting down...", 200
    try:
        os.kill(os.getpid(), signal.SIGINT)
        _log_event("shutdown_ok", ip=ip, mode="signal")
    except Exception as e:
        _log_event("shutdown_error", ip=ip, error=str(e))
    return "Shutdown attempted", 200

from werkzeug.exceptions import BadRequest, Forbidden, NotFound, TooManyRequests

@app.errorhandler(BadRequest)
def handle_400(e):
    _log_event("http_400", ip=_client_ip(), path=request.path, method=request.method)
    return "Bad request", 400

@app.errorhandler(Forbidden)
def handle_403(e):
    _log_event("http_403", ip=_client_ip(), path=request.path, method=request.method)
    return "Forbidden", 403

@app.errorhandler(NotFound)
def handle_404(e):
    _log_event("http_404", ip=_client_ip(), path=request.path, method=request.method)
    return "Not found", 404

@app.errorhandler(TooManyRequests)
def handle_429(e):
    _log_event("http_429", ip=_client_ip(), path=request.path, method=request.method)
    resp = make_response("Too many requests", 429)
    resp.headers["Retry-After"] = "60"
    return resp

@app.errorhandler(Exception)
def handle_500(e):
    try:
        msg = str(e)
    except Exception:
        msg = "exception"
    _log_event("http_500", ip=_client_ip(), path=request.path, method=request.method, error=msg)
    return "Internal server error", 500

# --- Background session cleanup and unfinished .part cleanup ---
CLEAN_INTERVAL_SEC = 30
PART_RETENTION_SEC = 6 * 60 * 60

def _cleanup_unfinished_parts(root_dir: str, now: float):
    try:
        for name in os.listdir(root_dir):
            if not name.endswith(".part"):
                continue
            path = os.path.join(root_dir, name)
            try:
                st = os.stat(path)
                if now - st.st_mtime > PART_RETENTION_SEC:
                    os.remove(path)
                    app.logger.info("cleanup_removed_stale_part file=%r", name)
            except Exception as e:
                app.logger.info("cleanup_stale_part_error file=%r error=%r", name, str(e))
    except Exception as e:
        app.logger.info("cleanup_iter_error error=%r", str(e))

def _session_cleaner():
    while True:
        try:
            now = time.time()
            prune_expired(now)
            enforce_max_active(MAX_ACTIVE_SESSIONS)
            _cleanup_unfinished_parts(CURRENT_RECEIVED_FOLDER, now)
        except Exception as e:
            app.logger.info("session_cleaner_error error=%r", str(e))
        time.sleep(CLEAN_INTERVAL_SEC)

def start_secure_flask():
    cleaner = threading.Thread(target=_session_cleaner, daemon=True)
    cleaner.start()
    app.logger.info("server_start host=%r port=%r debug=%r", "0.0.0.0", 5000, False)
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
