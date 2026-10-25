"""Survey extracted disc files for Shift-JIS text, TIM images and BIOS font use.

Usage: python tools/survey.py <extract_dir> [min_run]

Reads <extract_dir>/files (from extract_disc.py) and writes <extract_dir>/survey.txt.
"""
import math
import sys
from collections import Counter
from pathlib import Path

MIN_RUN = 4  # minimum run of 2-byte Shift-JIS characters to count as text

# Psy-Q / BIOS jump: li t2,0xB0 ; jr t2 ; li t1,<fn>
# B(0x51) = Krom2RawAdd (BIOS Kanji ROM glyph address), B(0x53) = Krom2Offset
BIOS_B_CALL = bytes.fromhex("b0000a24 08004001".replace(" ", ""))
KANJI_BIOS_FUNCS = {0x51: "Krom2RawAdd", 0x53: "Krom2Offset"}


def is_lead(b):
    return 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xEF


def is_trail(b):
    return 0x40 <= b <= 0xFC and b != 0x7F


def sjis_runs(data, min_run):
    """Yield (offset, raw_bytes) for runs of >= min_run 2-byte SJIS characters."""
    i, n = 0, len(data)
    while i < n - 1:
        start = i
        while i < n - 1 and is_lead(data[i]) and is_trail(data[i + 1]):
            i += 2
        if (i - start) // 2 >= min_run:
            yield start, data[start:i]
        if i == start:
            i += 1


def find_tims(data):
    """Yield (offset, bpp, clut_w, clut_h, img_w_px, img_h) for valid TIM headers."""
    pos = data.find(b"\x10\x00\x00\x00")
    while pos != -1:
        hit = parse_tim(data, pos)
        if hit:
            yield (pos,) + hit
        pos = data.find(b"\x10\x00\x00\x00", pos + 4)


def parse_tim(data, pos):
    u32 = lambda o: int.from_bytes(data[o:o + 4], "little")
    u16 = lambda o: int.from_bytes(data[o:o + 2], "little")
    if pos + 20 > len(data):
        return None
    flags = u32(pos + 4)
    if flags & ~0x0B:
        return None
    bpp_mode = flags & 3
    o = pos + 8
    clut_w = clut_h = 0
    if flags & 0x08:
        blen = u32(o)
        clut_w, clut_h = u16(o + 8), u16(o + 10)
        if blen != 12 + clut_w * clut_h * 2 or not clut_w or not clut_h:
            return None
        o += blen
    if o + 12 > len(data):
        return None
    blen = u32(o)
    w16, h = u16(o + 8), u16(o + 10)
    if not w16 or not h or blen != 12 + w16 * h * 2 or o + blen > len(data):
        return None
    bpp = {0: 4, 1: 8, 2: 16, 3: 24}[bpp_mode]
    width_px = w16 * 16 // bpp
    return bpp, clut_w, clut_h, width_px, h


def entropy(data):
    if not data:
        return 0.0
    counts = Counter(data)
    n = len(data)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def bios_kanji_calls(data):
    hits = []
    pos = data.find(BIOS_B_CALL)
    while pos != -1:
        nxt = data[pos + 8:pos + 12]
        if len(nxt) == 4 and nxt[2:] == b"\x09\x24":   # li t1, imm
            fn = int.from_bytes(nxt[:2], "little")
            if fn in KANJI_BIOS_FUNCS:
                hits.append((pos, KANJI_BIOS_FUNCS[fn]))
        pos = data.find(BIOS_B_CALL, pos + 1)
    return hits


def main():
    root = Path(sys.argv[1])
    min_run = int(sys.argv[2]) if len(sys.argv) > 2 else MIN_RUN
    files = sorted(p for p in (root / "files").rglob("*") if p.is_file())
    out = []
    char_freq = Counter()

    out.append(f"{'file':40} {'size':>10} {'entropy':>7} {'sjis_runs':>9} {'tims':>5}  magic")
    details = []
    for path in files:
        rel = path.relative_to(root / "files").as_posix()
        data = path.read_bytes()
        runs = list(sjis_runs(data, min_run))
        tims = list(find_tims(data))
        kanji = bios_kanji_calls(data)
        for _, raw in runs:
            for i in range(0, len(raw), 2):
                char_freq[raw[i:i + 2]] += 1
        out.append(f"{rel:40} {len(data):10d} {entropy(data[:65536]):7.2f} "
                   f"{len(runs):9d} {len(tims):5d}  {data[:8].hex(' ')}")

        if runs or tims or kanji:
            details.append(f"\n=== {rel} ===")
        for off, name in kanji:
            details.append(f"  BIOS Kanji ROM call {name} at file offset 0x{off:X}")
        for off, bpp, cw, ch, w, h in tims[:40]:
            details.append(f"  TIM @0x{off:08X}  {bpp}bpp  {w}x{h}px  clut {cw}x{ch}")
        if len(tims) > 40:
            details.append(f"  ... {len(tims) - 40} more TIMs")
        for off, raw in runs[:25]:
            text = raw.decode("cp932", "replace")
            details.append(f"  SJIS @0x{off:08X} ({len(raw) // 2:3d} ch)  "
                           f"pre={data[max(0, off - 4):off].hex()}  {text[:60]}")
        if len(runs) > 25:
            details.append(f"  ... {len(runs) - 25} more SJIS runs")

    out.extend(details)
    out.append("\n=== Most common characters in SJIS runs ===")
    for raw, count in char_freq.most_common(80):
        out.append(f"  {raw.hex()}  {raw.decode('cp932', 'replace')}  {count}")

    report = "\n".join(out)
    (root / "survey.txt").write_text(report, encoding="utf-8")
    print(report[:20000])


if __name__ == "__main__":
    main()
