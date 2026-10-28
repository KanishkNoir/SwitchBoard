import base64
import struct

from switchboard.masks import _png_rgba, overlay_pngs_b64


def test_png_encoder_structure():
    png = _png_rgba(2, 2, bytearray(2 * 2 * 4))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", png[16:24]) == (2, 2)


def test_overlay_invalid_text_returns_empty():
    assert overlay_pngs_b64("not sam output", 10, 10) == []
    assert overlay_pngs_b64("", 10, 10) == []
