"""Work list for writing C: the game functions that have no C yet, and parking of near misses.

Usage:
  python -I tools/fn_todo.py list [--max-bytes 0xC0] [--count 40]   unmatched game functions, smallest first
  python -I tools/fn_todo.py park <batch.c> "<note>" <addr> ...    move functions to decomp/wip/near_miss.c

`list` reads the `nonmatching func_XXXXXXXX, 0xSIZE` lines of splat's asm (python -m splat split germs.yaml, run
in decomp/; the files are gitignored), keeps the game range (below the first library module, 0x801AC9D0), and
leaves out what is in decomp/functions.txt or parked in decomp/wip/near_miss.c. Disassemble one with
`python -I tools/fdis.py 0xADDR`.
`park` cuts each `/* 0xADDR ... */` function out of the batch file (up to the next `/* 0x` marker), appends it
to decomp/wip/near_miss.c under the note, and removes it from decomp/functions.txt.
"""
import argparse
import glob
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAME_END = 0x801AC9D0


def have():
    out = set()
    for line in (ROOT / "decomp" / "functions.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            out.add(int(line.split()[1], 16))
    return out


def parked():
    text = (ROOT / "decomp" / "wip" / "near_miss.c").read_text()
    return {int(a, 16) for a in re.findall(r"0x([0-9A-F]{8})", text)}


def todo():
    skip = have() | parked()
    found = []
    for f in glob.glob(str(ROOT / "decomp" / "asm" / "game_*.s")):
        for m in re.finditer(r"nonmatching func_([0-9A-F]{8}), 0x([0-9A-F]+)", Path(f).read_text()):
            addr, size = int(m.group(1), 16), int(m.group(2), 16)
            if addr < GAME_END and addr not in skip:
                found.append((size, addr))
    return sorted(found)


def park(batch, note, addrs):
    batch = Path(batch)
    s = batch.read_text()
    moved = []
    for a in (x.upper().replace("0X", "") for x in addrs):
        m = re.search(r"/\* 0x%s[^\n]*\*/\n" % a, s)
        if not m:
            sys.exit("no /* 0x%s */ marker in %s" % (a, batch))
        nxt = re.search(r"\n(?=/\* 0x[0-9A-F]{8})", s[m.end():])
        stop = m.end() + nxt.start() + 1 if nxt else len(s)
        moved.append(s[m.start():stop].rstrip() + "\n")
        s = s[:m.start()] + s[stop:]
    batch.write_text(s.rstrip() + "\n")
    wip = ROOT / "decomp" / "wip" / "near_miss.c"
    wip.write_text(wip.read_text().rstrip() + "\n\n/* " + note + " */\n" + "\n".join(moved))
    ft = ROOT / "decomp" / "functions.txt"
    keep = [l for l in ft.read_text().splitlines(True) if not any(l.split()[-1].upper() == "0X" + a.upper().replace("0X", "") for a in addrs)]
    ft.write_text("".join(keep))
    print("parked", ", ".join(addrs), "(declarations between functions go with the previous one: check the batch file)")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("list")
    l.add_argument("--max-bytes", type=lambda x: int(x, 0), default=0xC0)
    l.add_argument("--count", type=int, default=40)
    p = sub.add_parser("park")
    p.add_argument("batch")
    p.add_argument("note")
    p.add_argument("addrs", nargs="+")
    args = ap.parse_args()
    if args.cmd == "list":
        rows = [r for r in todo() if r[0] <= args.max_bytes]
        print(f"{len(todo())} game functions without C; {len(rows)} up to 0x{args.max_bytes:X} bytes")
        print(" ".join(f"{a:X}:{s:X}" for s, a in rows[:args.count]))
    else:
        park(args.batch, args.note, args.addrs)


if __name__ == "__main__":
    main()
