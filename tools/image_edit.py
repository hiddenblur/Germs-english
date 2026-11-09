"""Hand-edited menu images: export the translated TIMs as PNGs, apply edited PNGs on build.

    python -I tools/image_edit.py export [--scale 4] [--force]   # build/ images -> edits/<name>.png
    python -I tools/image_edit.py list

Run the inserter first (it writes build/). Every PNG in edits/ is drawn over its TIM by the
inserter, after the text regions, so a file here wins over translations/screens.json for that
image. edits/ holds game artwork and is gitignored.

File names are "<FILE>_<OFFSET>.png", e.g. "SH1_B9004.png" for M/A/SH1.RM@B9004 and
"RES_1A101C.png" for RES.R@1A101C. A PNG can be 1x the TIM size or any whole multiple
(each block is read at its centre pixel, so scaled-up edits are fine). Colours are matched
to the TIM's own palette: a pixel that keeps the colour it already had keeps its palette
index (several palette entries share a colour), anything else gets the nearest entry.

The HUD clock (RES_8901C) is special: see SEGMENT_DIGITS. Its digits can be moved freely, but each
must keep its original shape and colours (move it, don't redraw it); the tool finds every digit in
the PNG and puts its palette indices back at the new spot, and reports each move it found.
"""
import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops the script dir
import images
import tim

ROOT = Path(__file__).resolve().parent.parent
EDITS = ROOT / "edits"
SHORT = {"RES.R": "RES", "SCE.S": "SCE"}

# Images whose digits are lit by the game rewriting palette entries: the HUD clock (RES.R@8901C)
# gives each of the 7 segments of each of its 6 digits its own palette index, and the game
# writes the lit/unlit colour of those entries into the CLUT at VRAM (0, 484) every time the time
# changes (seen live: entries 2-0x2B change, the pixels never do). A digit is only ever "which
# indices sit where", so a PNG edit that merges equal colours would break it. These are the
# segment index ranges per digit, in reading order: day tens, day ones, hour tens/ones, minute tens/ones.
SEGMENT_DIGITS = {
    "RES.R@8901C": [("day tens", 0x02, 0x08), ("day ones", 0x09, 0x0F), ("hour tens", 0x10, 0x16),
                    ("hour ones", 0x17, 0x1D), ("minute tens", 0x1E, 0x24), ("minute ones", 0x25, 0x2B)],
}


def short_name(sid):
    name, off = images.parse_id(sid)
    stem = SHORT.get(name) or Path(name).stem
    return f"{stem}_{off:X}"


def read_png(path):
    """(width, height, [(r, g, b)] per pixel) of a non-interlaced 8-bit PNG."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path}: not a PNG")
    pos, idat, plte, hdr = 8, b"", None, None
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            plte = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif kind == b"IDAT":
            idat += body
    w, h, depth, ctype, _, _, interlace = hdr
    if depth != 8 or interlace:
        raise ValueError(f"{path}: need an 8-bit, non-interlaced PNG")
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw, stride = zlib.decompress(idat), w * bpp
    rows, prev = [], bytearray(stride)
    for y in range(h):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        prev = line
    px = []
    for line in rows:
        for x in range(w):
            if ctype == 3:
                px.append(plte[line[x]])
            elif ctype in (0, 4):
                v = line[x * bpp]
                px.append((v, v, v))
            else:
                px.append(tuple(line[x * bpp:x * bpp + 3]))
    return w, h, px


def place_digits(t, pal, base, color, digits):
    """Where each segment digit (name, lo, hi index range) sits in an edited PNG, as
    [(name, dx, dy)] shifts from its place in `base`. The digit's whole box must appear
    unchanged in the PNG (same shape and colours); digits are assigned to the matches that move
    them least. Raises ValueError if a digit can't be found."""
    W, H = t.width, t.height
    found = []
    for name, lo, hi in digits:
        cells = [(i % W, i // W) for i, v in enumerate(base) if lo <= v <= hi]
        x0, x1 = min(c[0] for c in cells), max(c[0] for c in cells)
        y0, y1 = min(c[1] for c in cells), max(c[1] for c in cells)
        box = [(x - x0, y - y0, pal[base[y * W + x]]) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
        spots = [(nx, ny, nx - x0, ny - y0)
                 for ny in range(0, H - (y1 - y0)) for nx in range(0, W - (x1 - x0))
                 if all(color(nx + bx, ny + by) == c for bx, by, c in box)]
        if not spots:
            raise ValueError(f"clock digit {name!r} not found: each digit must keep its original "
                             f"{x1 - x0 + 1}x{y1 - y0 + 1} shape and colours (move it, don't redraw it)")
        found.append((name, spots))
    best = None

    def search(k, used, cost, pick):
        nonlocal best
        if best is not None and cost >= best[0]:
            return
        if k == len(found):
            best = (cost, list(pick))
            return
        for ax, ay, dx, dy in found[k][1]:
            if (ax, ay) not in used:
                search(k + 1, used | {(ax, ay)}, cost + abs(dx) + abs(dy), pick + [(found[k][0], dx, dy)])

    search(0, frozenset(), 0, [])
    if best is None:
        raise ValueError("clock digits overlap: two digits matched the same spot")
    return best[1]


def apply_png(t, path, base_pixels, digits=None):
    """New pixel indices for TIM t from an edited PNG; base_pixels = what the build drew.
    digits: segment digit ranges (SEGMENT_DIGITS) whose palette indices must follow the digit."""
    w, h, px = read_png(path)
    sx, sy = w // t.width, h // t.height
    if (w, h) != (t.width * sx, t.height * sy) or sx != sy or sx < 1:
        raise ValueError(f"{path}: {w}x{h} is not a whole multiple of {t.width}x{t.height}")
    pal = [tim.rgb(c) for c in t.clut]
    reserved = {k for _, lo, hi in digits or () for k in range(lo, hi + 1)}   # segment indices: placed, never picked

    def index_for(rgb):
        ok = [k for k in range(len(pal)) if k not in reserved] or list(range(len(pal)))
        exact = [k for k in ok if pal[k] == rgb]
        return exact[0] if exact else min(ok, key=lambda k: sum((a - b) ** 2 for a, b in zip(pal[k], rgb)))

    out = bytearray(base_pixels)
    for y in range(t.height):
        for x in range(t.width):
            rgb = px[(y * sx + sx // 2) * w + x * sx + sx // 2]
            i = y * t.width + x
            if pal[base_pixels[i]] == rgb and base_pixels[i] not in reserved:
                continue
            if pal[base_pixels[i]] == rgb and not digits:
                continue
            out[i] = index_for(rgb)
    if digits:
        color = lambda x, y: px[(y * sx + sx // 2) * w + x * sx + sx // 2]
        W = t.width
        moves = place_digits(t, pal, base_pixels, color, digits)
        for (name, lo, hi), (_, dx, dy) in zip(digits, moves):
            for i, v in enumerate(base_pixels):
                if lo <= v <= hi:
                    out[(i // W + dy) * W + i % W + dx] = v
            if (dx, dy):
                print(f"clock digit {name}: moved by ({dx}, {dy})")
    return out


def apply_edits(bufs, problems, wanted):
    """Draw every PNG in edits/ into its TIM (bufs: file name -> bytearray, edited in place).
    Only images that are being translated in this run (ids in wanted) are touched."""
    if not EDITS.is_dir():
        return
    ids = {short_name(sid): sid for sid in wanted}
    for png in sorted(EDITS.glob("*.png")):
        sid = ids.get(png.stem)
        if sid is None:
            continue
        try:
            name, off = images.parse_id(sid)
            t = tim.parse(bufs[name], off)
            t.pixels = apply_png(t, png, t.pixels, SEGMENT_DIGITS.get(sid))
            bufs[name][off:off + t.size] = t.to_bytes()
        except (ValueError, KeyError) as err:
            problems.append((png.name, str(err)))


def export(scale, force):
    build = ROOT / "build"
    ids = json.loads((ROOT / "translations" / "screens.json").read_text(encoding="utf-8"))
    EDITS.mkdir(exist_ok=True)
    n = 0
    for sid in ids:
        name, off = images.parse_id(sid)
        if not name.startswith("M/"):
            continue                        # the room-file menus; RES.R and SCE.S screens stay region-driven
        dest = EDITS / f"{short_name(sid)}.png"
        if dest.exists() and not force:
            print(f"keeping {dest.name} (use --force to overwrite)")
            continue
        t = tim.parse((build / name).read_bytes(), off)
        dest.write_bytes(tim.to_png(t, scale))
        n += 1
    print(f"wrote {n} PNGs to {EDITS}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "export":
        scale = int(sys.argv[sys.argv.index("--scale") + 1]) if "--scale" in sys.argv else 1
        export(scale, "--force" in sys.argv)
    elif cmd == "list":
        for sid in json.loads((ROOT / "translations" / "screens.json").read_text(encoding="utf-8")):
            print(f"{short_name(sid)}.png  <- {sid}")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
