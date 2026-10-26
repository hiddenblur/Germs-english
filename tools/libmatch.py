"""Find Psy-Q library functions inside the game EXE (relocated words are masked out).

Usage: python -I tools/libmatch.py extracted/files/SLPS_021.07 psyq/lib/*.LIB
Prints `lib module function ram_address words` for each match, then a per-library total.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops the script dir
import psyqlib

EXE_BASE = 0x80170000 - 0x800
MIN_WORDS = 6
MIN_RUN = 4


def functions(lib):
    for name, d, q in psyqlib.modules(lib):
        try:
            o = psyqlib.parse_obj(d, q)
        except ValueError:
            continue
        text = next((i for i, s in o['sections'].items() if s[0] == '.text'), None)
        if text is None:
            continue
        code = bytes(o['sections'][text][1])
        masked = set()
        for sec, off, tag in o['patches']:
            if sec == text:
                masked.add(off & ~3)
        starts = sorted(set(off for n, (sec, off) in o['xdefs'].items() if sec == text) | {0})
        names = {off: n for n, (sec, off) in o['xdefs'].items() if sec == text}
        for i, s in enumerate(starts):
            e = starts[i + 1] if i + 1 < len(starts) else len(code)
            if e - s >= MIN_WORDS * 4:
                yield name, names.get(s, '<%x>' % s), code[s:e], {m - s for m in masked if s <= m < e}


def mask_words(code, masked):
    out = bytearray(code)
    for off in masked:
        w = struct.unpack_from('<I', code, off)[0]
        keep = 0xFC000000 if (w >> 26) in (2, 3) else 0xFFFF0000
        struct.pack_into('<I', out, off, w & keep)
    return bytes(out)


def match(exe, code, masked):
    n = len(code) // 4
    best, run, cur = (0, 0), 0, 0
    for i in range(n):
        if i * 4 in masked:
            cur = 0
            continue
        cur += 1
        if cur > best[1]:
            best = (i - cur + 1, cur)
    start, ln = best
    if ln < MIN_RUN:
        return []
    pat = code[start * 4:(start + ln) * 4]
    want = mask_words(code, masked)
    hits, p = [], exe.find(pat)
    while p >= 0:
        s = p - start * 4
        if s >= 0 and s % 4 == 0 and s + len(code) <= len(exe):
            if mask_words(exe[s:s + len(code)], masked) == want:
                hits.append(s)
        p = exe.find(pat, p + 4)
    return hits


if __name__ == '__main__':
    exe = open(sys.argv[1], 'rb').read()
    for lib in sys.argv[2:]:
        total = found = 0
        for mod, fn, code, masked in functions(lib):
            total += 1
            for h in match(exe, code, masked):
                found += 1
                print('%s %s %s 0x%08X %d' % (Path(lib).name, mod, fn, EXE_BASE + h, len(code) // 4))
        print('## %s: %d/%d functions found' % (lib, found, total))
