# qrporter/gui.py

import sys
import threading
import socket
import time
import os
import shutil
import urllib.request
import urllib.error

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QMessageBox, QFrame, QGridLayout,
    QDialog, QProgressBar, QDialogButtonBox, QTextEdit
)
from PySide6.QtGui import QPixmap, QFont, QDesktopServices, QIcon
from PySide6.QtCore import Qt, QSize, QTimer, QUrl

from qrporter.backend import start_secure_flask
from qrporter.qr_generator import generate_qr_qimage
from qrporter.session_manager import create_session
from qrporter.event_bus import try_pop_event

APP_TITLE = "QRPorter"
QR_SIZE = 320
PADDING = 14
SERVER_PORT = 5000

# About dialog metadata
APP_VERSION = "1.0.0"
APP_WEBSITE = "https://due.im/"
APP_AUTHOR = "Manikandan D"
APP_LICENSE_TEXT = """MIT License
Copyright (c) 2025 Manikandan D

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""

def _icon_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "static", "assets", "icon.png"))

def get_local_ip() -> str:
    # Return only the IP string
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()

def _post_local(path: str):
    req = urllib.request.Request(
        url=f"http://127.0.0.1:{SERVER_PORT}{path}",
        method="POST",
        data=b""
    )
    try:
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass

class Toast(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.ToolTip)
        self.label = QLabel("", self)
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.label.setStyleSheet("""
        QLabel {
            background-color: rgba(33,33,33, 0.92);
            color: #fff; padding: 8px 12px;
            border-radius: 8px; font-size: 12pt;
        }
        """)
        self.hide()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, duration_ms: int = 3500):
        self.label.setText(text)
        self.label.adjustSize()
        if self.parent():
            pw = self.parent().width()
            x = pw - self.label.width() - 16
            y = 16
            self.setGeometry(x, y, self.label.width(), self.label.height())
        self.show()
        self._timer.start(duration_ms)

class CopyProgressDialog(QDialog):
    def __init__(self, parent=None, filename=""):
        super().__init__(parent)
        self.setWindowTitle("Preparing file")
        self.setModal(True)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        title = QLabel(f"Preparing “{filename}” to send to mobile")
        title.setWordWrap(True)
        layout.addWidget(title)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.detail = QLabel("0%")
        self.detail.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.detail)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._cancelled = False

    def update_progress(self, pct: int, text: str = ""):
        self.progress.setValue(max(0, min(100, pct)))
        self.detail.setText(text or f"{pct}%")
        QApplication.processEvents()

    def cancelled(self) -> bool:
        return self._cancelled

    def reject(self):
        self._cancelled = True
        super().reject()

class QRPorterApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(500, 720)

        # Title bar / window icon
        icon_file = _icon_path()
        if os.path.isfile(icon_file):
            self.setWindowIcon(QIcon(icon_file))

        # Folders (must match backend)
        self.shared_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "../shared"))
        self.received_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "../received"))
        os.makedirs(self.shared_folder, exist_ok=True)
        os.makedirs(self.received_folder, exist_ok=True)

        # Layout
        root = QVBoxLayout(self)
        root.setContentsMargins(PADDING, PADDING, PADDING, PADDING)
        root.setSpacing(PADDING)

        self.title_label = QLabel(APP_TITLE)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        root.addWidget(self.title_label)

        # Action buttons
        action_row = QHBoxLayout()
        action_row.setSpacing(PADDING)

        self.btn_send = QPushButton("Send file to mobile")
        self.btn_send.setFixedHeight(40)
        self.btn_send.clicked.connect(self.send_file)
        action_row.addWidget(self.btn_send, 1)

        self.btn_receive = QPushButton("Get file from mobile")
        self.btn_receive.setFixedHeight(40)
        self.btn_receive.clicked.connect(self.receive_file)
        action_row.addWidget(self.btn_receive, 1)

        root.addLayout(action_row)

        # Info and QR
        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color: #777;")
        root.addWidget(self.info_label)

        qr_container = QFrame()
        qr_container.setObjectName("qrContainer")
        qr_container.setStyleSheet("""
        QFrame#qrContainer {
            border: 1px solid #ddd;
            border-radius: 8px;
            background: #fafafa;
        }
        """)
        qr_layout = QVBoxLayout(qr_container)
        qr_layout.setContentsMargins(16, 16, 16, 16)
        qr_layout.setSpacing(8)

        self.qr_title = QLabel("Scan QR with your phone")
        self.qr_title.setAlignment(Qt.AlignCenter)
        self.qr_title.setFont(QFont("Segoe UI", 11, QFont.Medium))
        qr_layout.addWidget(self.qr_title)

        self.qr_code_label = QLabel()
        self.qr_code_label.setFixedSize(QR_SIZE, QR_SIZE)
        self.qr_code_label.setAlignment(Qt.AlignCenter)
        qr_layout.addWidget(self.qr_code_label, alignment=Qt.AlignCenter)

        root.addWidget(qr_container, alignment=Qt.AlignCenter)

        # Folder openers only (removed Set Outgoing/Incoming)
        folders_grid = QGridLayout()
        folders_grid.setHorizontalSpacing(PADDING)
        folders_grid.setVerticalSpacing(8)

        self.btn_open_shared = QPushButton("Open Outgoing Folder")
        self.btn_open_shared.setFixedHeight(36)
        self.btn_open_shared.setToolTip("Open the outgoing folder in the file manager.")
        self.btn_open_shared.clicked.connect(self.open_shared_folder)
        folders_grid.addWidget(self.btn_open_shared, 0, 0)

        self.btn_open_received = QPushButton("Open Incoming Folder")
        self.btn_open_received.setFixedHeight(36)
        self.btn_open_received.setToolTip("Open the incoming folder in the file manager.")
        self.btn_open_received.clicked.connect(self.open_received_folder)
        folders_grid.addWidget(self.btn_open_received, 0, 1)

        root.addLayout(folders_grid)

        # Tip text
        self.hint_label = QLabel("Tip: Both devices must be on the same Wi‑Fi/LAN.")
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setStyleSheet("color: #FF4500;")
        root.addWidget(self.hint_label)

        # Status row
        status_row = QHBoxLayout()
        status_row.setSpacing(PADDING)

        self.status_label = QLabel("QRPorter: Starting…")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_label.setFont(QFont("Segoe UI", 10))
        status_row.addWidget(self.status_label, 1)

        self.btn_toggle_server = QPushButton("Stop QRPorter")
        self.btn_toggle_server.setFixedHeight(36)
        self.btn_toggle_server.clicked.connect(self.toggle_server)
        status_row.addWidget(self.btn_toggle_server, 0)

        # Add About button (no other logic changed)
        self.btn_about = QPushButton("About")
        self.btn_about.setFixedHeight(36)
        self.btn_about.clicked.connect(self.show_about)
        status_row.addWidget(self.btn_about, 0)

        root.addLayout(status_row)

        divider1 = QFrame()
        divider1.setFrameShape(QFrame.HLine)
        divider1.setFrameShadow(QFrame.Sunken)
        root.addWidget(divider1)

        # Server state
        self.server_thread = None
        self.server_running = False

        # Toast for alerts
        self.toast = Toast(self)

        # Poll events from backend
        self.event_timer = QTimer(self)
        self.event_timer.setInterval(500)
        self.event_timer.timeout.connect(self._poll_events)
        self.event_timer.start()

        # Auto-start server on launch
        self.start_server_on_launch()

    # ---- Server control ----
    def start_server_on_launch(self):
        if self.server_running:
            return
        self.server_thread = threading.Thread(target=start_secure_flask, daemon=True)
        self.server_thread.start()
        time.sleep(1)
        self.server_running = True
        self.status_label.setText("QRPorter: Running")
        self.btn_toggle_server.setText("Stop QRPorter")

    def _cleanup_temp_parts(self):
        _post_local("/__cleanup_parts__")

    def toggle_server(self):
        if self.server_running:
            _post_local("/__clear_sessions__")
            self._cleanup_temp_parts()
            _post_local("/__shutdown__")
            time.sleep(0.7)
            self.server_running = False
            self.status_label.setText("QRPorter: Stopped")
            self.btn_toggle_server.setText("Start QRPorter")
            self.qr_code_label.clear()
            self.qr_title.setText("Scan QR with your phone")
            self.info_label.setText("")
        else:
            self.start_server_on_launch()

    # ---- Open in file manager ----
    def _open_folder(self, path: str):
        try:
            if not path:
                return
            os.makedirs(path, exist_ok=True)
            url = QUrl.fromLocalFile(path)
            QDesktopServices.openUrl(url)
        except Exception as e:
            QMessageBox.warning(self, "Open Folder", f"Unable to open folder:\n{path}\n\n{e}")

    def open_shared_folder(self):
        self._open_folder(self.shared_folder)

    def open_received_folder(self):
        self._open_folder(self.received_folder)

    # ---- Actions ----
    def _copy_with_progress(self, src: str, dst: str, progress_dialog: CopyProgressDialog):
        # Copy with 1 MiB chunks and update the dialog
        total = 0
        try:
            total = os.path.getsize(src)
        except Exception:
            total = 0
        copied = 0
        chunk = 1024 * 1024
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, 'rb') as f_in, open(dst, 'wb') as f_out:
            while True:
                if progress_dialog.cancelled():
                    raise KeyboardInterrupt("Copy cancelled")
                buf = f_in.read(chunk)
                if not buf:
                    break
                f_out.write(buf)
                copied += len(buf)
                pct = int((copied / total) * 100) if total > 0 else 0
                # Show MB copied out of MB total
                mb_copied = copied / (1024 * 1024)
                mb_total = total / (1024 * 1024) if total > 0 else 0
                progress_dialog.update_progress(pct, f"{mb_copied:.1f} MB / {mb_total:.1f} MB")

    def _normalize_ip_for_url(self, ip: str) -> str:
        # Final guard against tuple-like strings showing up in the URL
        ip = str(ip)
        if ip.startswith("("):
            pos1 = ip.find("'")
            pos2 = ip.find("'", pos1 + 1)
            if pos1 != -1 and pos2 != -1:
                ip = ip[pos1 + 1:pos2]
        return ip

    def send_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select file to send", self.shared_folder)
        if not file_path:
            return

        filename = os.path.basename(file_path)
        dest_path = os.path.join(self.shared_folder, filename)

        try:
            if os.path.abspath(file_path) != os.path.abspath(dest_path):
                # Show progress dialog only when a copy is needed
                dlg = CopyProgressDialog(self, filename=filename)
                dlg.show()
                QApplication.processEvents()
                # Perform the copy with progress
                self._copy_with_progress(file_path, dest_path, dlg)
                dlg.accept()
            else:
                # No copy needed; already in outgoing
                pass
        except KeyboardInterrupt:
            # User cancelled
            try:
                if os.path.exists(dest_path):
                    os.remove(dest_path)
            except Exception:
                pass
            QMessageBox.information(self, "Cancelled", "Copy cancelled.")
            return
        except Exception as e:
            QMessageBox.critical(self, "Copy Error", f"Failed to copy to shared folder:\n{e}")
            return

        token = create_session("send", file_path=dest_path, password=None, expires_in=600)
        ip = get_local_ip()
        ip = self._normalize_ip_for_url(ip)
        url = f"http://{ip}:{SERVER_PORT}/send/{token}"

        qr_img = generate_qr_qimage(url, size=QR_SIZE)
        self.qr_code_label.setPixmap(QPixmap.fromImage(qr_img).scaled(
            QSize(QR_SIZE, QR_SIZE), Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))
        self.qr_title.setText("PC → Mobile")
        self.info_label.setText(f"Scan to download:\n{filename}")

    def receive_file(self):
        token = create_session("receive", file_path=None, password=None, expires_in=600)
        ip = get_local_ip()
        ip = self._normalize_ip_for_url(ip)
        url = f"http://{ip}:{SERVER_PORT}/receive/{token}"

        qr_img = generate_qr_qimage(url, size=QR_SIZE)
        self.qr_code_label.setPixmap(QPixmap.fromImage(qr_img).scaled(
            QSize(QR_SIZE, QR_SIZE), Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))
        self.qr_title.setStyleSheet("color: #000000;")
        self.qr_title.setText("Mobile → PC")
        self.info_label.setText("Scan to upload a file to this PC.")

    # ---- About dialog ----
    def show_about(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("About QRPorter")
        dlg.setModal(True)
        dlg.setMinimumSize(460, 520)

        vbox = QVBoxLayout(dlg)

        title = QLabel(f"{APP_TITLE} v{APP_VERSION}")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        vbox.addWidget(title)

        meta = QLabel(
            "License: MIT\n"
            f"Author: {APP_AUTHOR}\n"
            "Copyright (c) 2025 Manikandan D\n"
            f"Project website: {APP_WEBSITE}"
        )
        meta.setAlignment(Qt.AlignCenter)
        meta.setWordWrap(True)
        vbox.addWidget(meta)

        license_box = QTextEdit()
        license_box.setReadOnly(True)
        license_box.setPlainText(APP_LICENSE_TEXT)
        vbox.addWidget(license_box, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        btn_copy = QPushButton("Copy License")
        buttons.addButton(btn_copy, QDialogButtonBox.ActionRole)

        def _copy_license():
            QApplication.clipboard().setText(APP_LICENSE_TEXT)
            try:
                self.toast.show_message("License copied to clipboard", 1800)
            except Exception:
                pass

        btn_copy.clicked.connect(_copy_license)
        buttons.rejected.connect(dlg.reject)
        vbox.addWidget(buttons)

        dlg.exec()

    # ---- Alerts polling ----
    def _poll_events(self):
        while True:
            evt = try_pop_event()
            if not evt:
                break
            etype = evt.get("type")
            payload = evt.get("payload", {})
            if etype == "device_connected":
                ip = payload.get("ip", "?")
                self.toast.show_message(f"New device connected: {ip}")
            elif etype == "suspicious_activity":
                ip = payload.get("ip", "?")
                reason = payload.get("reason", "suspicious")
                if reason == "multiple_failures":
                    cnt = payload.get("count", 0)
                    self.toast.show_message(f"Suspicious: {cnt} failed attempts from {ip}")
                elif reason == "unexpected_ip_upload":
                    self.toast.show_message(f"Suspicious upload from {ip}")

    # Ensure cleanup on window close
    def closeEvent(self, event):
        try:
            if self.server_running:
                _post_local("/__clear_sessions__")
                self._cleanup_temp_parts()
                _post_local("/__shutdown__")
                time.sleep(0.7)
                self.server_running = False
        except Exception:
            pass
        event.accept()

def start_gui_app():
    app = QApplication(sys.argv)

    # Windows 10/11: set explicit AppUserModelID so taskbar uses our icon
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("com.qrporter.desktop")
    except Exception:
        pass

    icon_file = _icon_path()
    if os.path.isfile(icon_file):
        app.setWindowIcon(QIcon(icon_file))

    app.setStyleSheet("""
    QWidget { font-family: "Segoe UI", Arial, sans-serif; font-size: 11pt; }
    QPushButton { background: #1976d2; color: white; border: none; border-radius: 6px; padding: 6px 10px; }
    QPushButton:hover { background: #1565c0; }
    QPushButton:pressed { background: #0d47a1; }
    """)

    window = QRPorterApp()
    window.show()
    app.exec()
