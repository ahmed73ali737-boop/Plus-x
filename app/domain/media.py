"""Uploaded media rules: only PNG, JPEG, WebP and MP4 by content signature."""
from __future__ import annotations

from app.domain.errors import fail

MEDIA_MAX_BYTES = 4 * 1024 * 1024


def media_extension(data: bytes) -> str:
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'webp'
    if len(data) > 12 and data[4:8] == b'ftyp':
        return 'mp4'
    fail('MEDIA_PNG_JPEG_WEBP_MP4_ONLY')
