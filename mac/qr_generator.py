#!/usr/bin/env python3
"""QR helpers for Discogs now-playing links."""

from __future__ import annotations

import base64
from io import BytesIO

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    qrcode = None
    HAS_QRCODE = False


def generate_qr_png(url: str) -> bytes | None:
    """Generate a PNG QR code for a URL."""
    if not HAS_QRCODE or not url:
        return None
    image = qrcode.make(url)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def generate_qr_data_url(url: str) -> str | None:
    """Generate a data URL PNG QR code for a URL."""
    png = generate_qr_png(url)
    if not png:
        return None
    encoded = base64.b64encode(png).decode("ascii")
    return f"data:image/png;base64,{encoded}"
