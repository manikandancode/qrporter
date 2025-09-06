<p align="center">
  <img src="https://raw.githubusercontent.com/manikandancode/qrporter/main/assets/icon.png" 
       alt="QRPorter App Icon" width="120"/>
</p>

[![PyPI - Version](https://img.shields.io/pypi/v/qrporter.svg)](https://pypi.org/project/qrporter/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/qrporter.svg)](https://pypi.org/project/qrporter/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/manikandancode/qrporter/blob/main/LICENSE)
![Status](https://img.shields.io/badge/status-stable-brightgreen.svg)
![Flask](https://img.shields.io/badge/Framework-Flask-000000.svg?logo=flask&logoColor=white)
![PySide6](https://img.shields.io/badge/GUI-PySide6-41CD52.svg?logo=qt&logoColor=white)
![File Transfer](https://img.shields.io/badge/Purpose-File%20Transfer-blue.svg)
![QR Code](https://img.shields.io/badge/QR-Code-black.svg)


# QRPorter — Local Wi‑Fi QR File Transfer

A lightweight desktop + web utility for moving files between a mobile device and a Desktop PC over the local network. Scan a QR code to send or receive files directly on the LAN—no cloud, no cables, no mobile app and no accounts.

---

## Why QRPorter

- Simple: one‑click “Send to mobile” or “Get from mobile” for quick transfers.
- Private: traffic stays on the local network; nothing is uploaded to third‑party servers.
- Cross‑device: works with modern mobile browsers (iOS/Android) and Windows, Linux & MacOS desktop.

---

## Features

- PC → Mobile: Select the file & generate a QR code; scan to download the selected file on your mobile.
- Mobile → PC: Generate the QR code, visit the upload page from the QR on mobile; send a file back to the PC.
- One‑time session tokens and basic rate limiting for local safety.

---

## Screenshots

![QRPorter](https://github.com/user-attachments/assets/f154d18d-4540-4327-8383-2fb6159cb202)  
![QRPorter_download_from_pc](https://github.com/user-attachments/assets/44d0bc42-4f2c-4795-8ec2-cbb715bae90e)  
![QRPorter_Upload_to_pc](https://github.com/user-attachments/assets/657c60ec-6038-4daf-849c-bcf2282e3ce0)  

---

## Installation

You can install **QRPorter** directly from [PyPI](https://pypi.org/project/qrporter/):

```bash
pip install qrporter
```
**Requirements**
Python 3.12+
Works on Windows, macOS, and Linux

**Running the App**
After installation, you can start QRPorter from the terminal:

```bash
qrporter
```

---

## Requirements

- Windows 11 (tested), Linux, MacOS
- Python 3.12+ with pip
- Same Wi‑Fi/LAN for both PC and phone

Required Python packages (minimum versions):
- Flask>=3.1.2
- PySide6>=6.6.1
- qrcode>=8.2
- Werkzeug>=3.1.3
- Pillow>=11.0.0

---

## Setup on Windows 11

1) Install Python
- Download and install Python 3.12+ (ensure “Add Python to PATH” is checked).
- Verify:
```bash
python --version
pip --version
```
2) Clone the repository
```bash
git clone https://github.com/manikandancode/qrporter.git
cd qrporter
```

3) Create and activate a virtual environment
```bash
python -m venv venv
venv\Scripts\activate
```

4) Install dependencies
- If you have a requirements.txt:
  ```
  pip install -r requirements.txt
  ```
- Or install individually with minimum versions:
  ```
  pip install "Flask>=3.1.2" "PySide6>=6.6.1" "qrcode>=8.2" "Werkzeug>=3.1.3" "Pillow>=11.0.0"
  ```

5) Run the desktop app
- If the project provides a launcher:
  ```
  python run.py
  ```

---

## How to Use

- Send file to mobile (PC → Mobile):
1. Click “Send file to mobile.”
2. Pick a file; a QR code appears.
3. Scan the QR with the phone camera/browser to download.

- Get file from mobile (Mobile → PC):
1. Click “Get file from mobile.”
2. Scan the QR displayed on the phone.
3. Choose a file on the phone and upload it; the PC saves it locally.

Default folders (auto‑created):
- Outgoing: `shared/`
- Incoming: `received/`

Use the “Open Outgoing/Incoming Folder” buttons in the UI to open these locations.

---

## Tips & Troubleshooting

1. Phone can’t open the link:
- Ensure PC and phone are on the same Wi‑Fi; avoid guest/isolated networks.
- Allow Python in Windows Defender Firewall for Private networks.

2. Very slow uploads:
- Keep the phone screen on and the browser in the foreground (backgrounding throttles).
- Prefer 5 GHz Wi‑Fi and short distance to the access point.
- Save to an SSD when possible.

3. URL shows a tuple like `('192.168.x.x', 52546)`:
- Ensure the app uses only `getsockname()[0]` (IP string) when forming URLs and restart the app.

---

## Project Rationale

QRPorter focuses on frictionless, local‑only transfers for everyday workflows—moving screenshots, media, or documents between PC and phone—without cloud services, cables, drivers, or mobile app installs on mobile.

---

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
