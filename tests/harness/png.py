"""PNG without Pillow: the decoder `test_s69` counts red pixels with and the twin diff compares with, and an
encoder for the diff's picture. `zlib` is stdlib; the dependency cap (AC-086) is a real constraint."""

from __future__ import annotations

import zlib

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def decode_png(data: bytes) -> tuple[int, int, int, bytes]:
    """`(width, height, channels, pixels)` — `pixels` is the unfiltered, de-interlaced raster,
    `channels` bytes per pixel, rows concatenated. Supports exactly what Chromium's screenshot
    encoder emits: 8-bit, non-interlaced, colour type 2 (RGB) or 6 (RGBA). Anything else raises
    rather than guessing, so a future encoder change is a loud failure, not a silently wrong
    pixel count."""
    if data[:8] != PNG_MAGIC:
        raise ValueError("not a PNG")
    pos = 8
    header: bytes | None = None
    idat = bytearray()
    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos : pos + 4], "big")
        ctype = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length  # 4 length + 4 type + data + 4 crc
        if ctype == b"IHDR":
            header = chunk
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
    if header is None:
        raise ValueError("PNG has no IHDR")
    width = int.from_bytes(header[0:4], "big")
    height = int.from_bytes(header[4:8], "big")
    bit_depth, colour_type, _comp, _filt, interlace = header[8], header[9], header[10], header[11], header[12]
    if bit_depth != 8 or interlace != 0 or colour_type not in (2, 6):
        raise ValueError(
            f"unsupported PNG: depth={bit_depth} colour_type={colour_type} interlace={interlace}"
        )
    channels = 3 if colour_type == 2 else 4
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = bytearray(stride * height)
    prev = bytearray(stride)
    src = 0
    dst = 0
    for _y in range(height):
        ftype = raw[src]
        src += 1
        line = bytearray(raw[src : src + stride])
        src += stride
        if ftype == 1:  # Sub
            for x in range(channels, stride):
                line[x] = (line[x] + line[x - channels]) & 255
        elif ftype == 2:  # Up
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif ftype == 3:  # Average
            for x in range(stride):
                left = line[x - channels] if x >= channels else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 255
        elif ftype == 4:  # Paeth
            for x in range(stride):
                a = line[x - channels] if x >= channels else 0
                b = prev[x]
                c = prev[x - channels] if x >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pred) & 255
        elif ftype != 0:
            raise ValueError(f"unknown PNG filter type {ftype}")
        out[dst : dst + stride] = line
        dst += stride
        prev = line
    return width, height, channels, bytes(out)


def encode_png(width: int, height: int, rgba: bytes) -> bytes:
    """An 8-bit RGBA PNG of `rgba` (rows concatenated), no filtering."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return len(data).to_bytes(4, "big") + kind + data + zlib.crc32(kind + data).to_bytes(4, "big")

    stride = width * 4
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(height))
    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 6, 0, 0, 0])
    return PNG_MAGIC + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
