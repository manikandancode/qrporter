# qrporter/qr_generator.py

import io
import qrcode
from PySide6.QtGui import QImage


def generate_qr_qimage(data: str, size: int = 320) -> QImage:
    """
    Generate a QR code as a QImage in memory, never writing to disk.
    """
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)

    pil_img = qr.make_image(fill_color="black", back_color="white").resize((size, size))

    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    buf.seek(0)

    qimg = QImage()
    qimg.loadFromData(buf.read(), "PNG")
    return qimg
