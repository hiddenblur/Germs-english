"""Read and write PS1 TIM images (4bpp and 8bpp with a palette), and save them as PNG.

A TIM is: u32 0x10, u32 flags (bits 0-1 depth, bit 3 palette present), then a palette block
and an image block, each u32 length (header included), u16 x, y, w, h, data. Pixel width is
w * 4 (4bpp) or w * 2 (8bpp); 4bpp stores the left pixel in the low nibble.
"""
import struct
import zlib
from dataclasses import dataclass


@dataclass
class Tim:
    offset: int                 # where it sits in its file
    bpp: int
    clut: list                  # PS1 15-bit colours of the first palette
    clut_header: tuple          # (x, y, w, h)
    image_header: tuple         # (x, y, w, h); w in 16-bit units
    pixels: bytearray           # one palette index per byte, row-major
    width: int
    height: int
    size: int                   # bytes the TIM occupies in its file

    def to_bytes(self):
        """Serialise back to the exact retail layout."""
        clut_data = bytes(self.raw_clut)
        packed = pack_pixels(self.pixels, self.bpp)
        x, y, w, h = self.image_header
        out = struct.pack("<II", 0x10, {4: 0, 8: 1}[self.bpp] | 8)
        out += struct.pack("<I4H", 12 + len(clut_data), *self.clut_header) + clut_data
        out += struct.pack("<I4H", 12 + len(packed), x, y, w, h) + packed
        return out


def unpack_pixels(data, bpp, width, height):
    if bpp == 8:
        return bytearray(data[:width * height])
    out = bytearray()
    for b in data[:width * height // 2]:
        out += bytes((b & 0xF, b >> 4))
    return out


def pack_pixels(pixels, bpp):
    if bpp == 8:
        return bytes(pixels)
    return bytes(pixels[i] | pixels[i + 1] << 4 for i in range(0, len(pixels), 2))


def parse(data, off):
    """Parse the TIM at data[off]; raise ValueError if it isn't a 4/8bpp palette TIM."""
    magic, flags = struct.unpack_from("<II", data, off)
    if magic != 0x10 or not flags & 8 or flags & 3 not in (0, 1):
        raise ValueError(f"no 4/8bpp palette TIM at 0x{off:X}")
    bpp = 4 if flags & 3 == 0 else 8
    clen, *chead = struct.unpack_from("<I4H", data, off + 8)
    raw_clut = data[off + 20:off + 8 + clen]
    p = off + 8 + clen
    ilen, x, y, w, h = struct.unpack_from("<I4H", data, p)
    width = w * (4 if bpp == 4 else 2)
    pixels = unpack_pixels(data[p + 12:p + ilen], bpp, width, h)
    colours = 16 if bpp == 4 else 256
    clut = list(struct.unpack_from(f"<{colours}H", raw_clut, 0))
    t = Tim(off, bpp, clut, tuple(chead), (x, y, w, h), pixels, width, h, 8 + clen + ilen)
    t.raw_clut = bytes(raw_clut)
    return t


def rgb(c):
    """PS1 15-bit BGR colour to (r, g, b)."""
    return ((c & 31) * 255 // 31, (c >> 5 & 31) * 255 // 31, (c >> 10 & 31) * 255 // 31)


def png(width, height, pixels, palette):
    """Palette PNG bytes (colour type 3); palette is a list of (r, g, b)."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    rows = b"".join(b"\0" + bytes(pixels[y * width:(y + 1) * width]) for y in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0))
            + chunk(b"PLTE", b"".join(bytes(rgb_) for rgb_ in palette))
            + chunk(b"IDAT", zlib.compress(rows, 9))
            + chunk(b"IEND", b""))


def to_png(t, scale=1):
    w, h = t.width * scale, t.height * scale
    px = bytearray(w * h)
    for y in range(h):
        src = (y // scale) * t.width
        for x in range(w):
            px[y * w + x] = t.pixels[src + x // scale]
    return png(w, h, px, [rgb(c) for c in t.clut])
