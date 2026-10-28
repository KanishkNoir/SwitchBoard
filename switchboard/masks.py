"""Rasterize SAM 3.1 masks into full-frame RGBA overlay PNGs (stdlib PNG encoder)."""
import base64
import struct
import zlib

AMBER = (232, 163, 61, 130)


def _png_rgba(width: int, height: int, rgba: bytearray) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride:(y + 1) * stride])
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b""))


def overlay_pngs_b64(sam_text: str, frame_w: int, frame_h: int) -> list[str]:
    """One overlay PNG (base64) per segmented object, aligned with parser record order.

    Returns [] if the parser is unavailable or the output has no masks — callers
    fall back to bounding boxes, never to a fabricated mask.
    """
    try:
        import meta_sam_parser as msp
    except Exception:
        return []
    try:
        snapshot = msp.image_segmentation_format().create_parser().push(sam_text)[-1]
    except Exception:
        return []
    boxes = [r for r in snapshot.records if r.kind == "box"]
    masks = {r.object_id: r for r in snapshot.records if r.kind == "mask"}
    out: list[str] = []
    for box in boxes:
        rec = masks.get(box.object_id)
        if rec is None:
            out.append("")
            continue
        try:
            mask = rec.mask
            raster = msp.decode_mask_to_raster(mask)
        except Exception:
            out.append("")
            continue
        rgba = bytearray(frame_w * frame_h * 4)
        mw, mh = mask.width, mask.height
        x0, y0 = int(box.left), int(box.top)
        for my in range(mh):
            fy = y0 + my
            if fy < 0 or fy >= frame_h:
                continue
            src_row = my * mw
            dst_row = fy * frame_w * 4
            for mx in range(mw):
                if raster[src_row + mx]:
                    idx = dst_row + (x0 + mx) * 4
                    if 0 <= idx < len(rgba) - 3:
                        rgba[idx:idx + 4] = bytes(AMBER)
        out.append(base64.b64encode(_png_rgba(frame_w, frame_h, rgba)).decode())
    return out
