"""Insert translated text and rebuild SCE.S, RES.R and the EXE.

Usage: python tools/insert_script.py <extract_dir> <out_dir> <translation.json>...

Translation files are lists of dump entries (tools/dump_script.py) or
{"id": text} maps, where text is a string (half-width) or
{"text": "...", "width": "full"} for windows whose renderer isn't patched yet.
Entries with an empty text are left alone. With no translated entries, the
output is byte-identical to the input.

Text syntax:
    {0}..{9}   colour change (the game's single-byte colour codes)
    newline    line break (the game's ",")
    {xx}       raw byte in hex, e.g. {81}{9b} for the circle button glyph
Half-width (needs tools/patch_exe.py): printable ASCII becomes byte + 0x80
(0xA0 space, 0xA1-0xFE), drawn from the BIOS 8x15 font. \\ and ~ are rejected
(that font draws them as yen and overline). Other characters become full-width SJIS.
Full-width: space is one full 16 px cell (0x20); other ASCII becomes its full-width
form. " becomes “ ” and ' becomes ’ (the full-width forms are extension codes the
font draws as blanks).
In both modes, a character the BIOS fonts can't draw is rejected.

SCE.S command strings can change length freely; the archive is rebuilt and the
EXE scene table patched. Strings outside commands (SCE.S fixed fields, RES.R,
EXE) are written in place and must fit their dumped capacity.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops the script dir
import layout
import sce

TOKEN = re.compile(r"\{([0-9])\}|\{([0-9a-fA-F]{2})\}|(\n)|(.)", re.S)


def rom_has_glyph(code):
    """SJIS ranges the Kanji ROM lookup at 0x801B1370 draws; anything else comes out blank."""
    return 0x8140 <= code <= 0x84BE or 0x889F <= code <= 0x9872


def encode(text, half=True):
    out = bytearray()
    quote_open = True
    for colour, raw, newline, ch in TOKEN.findall(text):
        if half and " " <= ch <= "~":
            if ch in "\\~":
                raise ValueError(f"{ch!r} has no glyph in the BIOS 8x15 font")
            out.append(ord(ch) + 0x80)
            continue
        if ch == '"':
            ch, quote_open = ("“" if quote_open else "”"), not quote_open
        elif ch == "'":
            ch = "’"
        if colour:
            out += colour.encode()
        elif raw:
            out.append(int(raw, 16))
        elif newline:
            out += b","
        elif ch == " ":
            out += b" "
        else:
            if "!" <= ch <= "~":
                ch = chr(ord(ch) - 0x21 + 0xFF01)                  # full-width form
            sj = ch.encode("cp932")
            if len(sj) != 2 or not rom_has_glyph(sj[0] << 8 | sj[1]):
                raise ValueError(f"{ch!r} has no glyph in the BIOS font")
            out += sj
    return bytes(out)


def load_translations(paths):
    tr = {}
    for p in paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        items = data.items() if isinstance(data, dict) else ((e["id"], e.get("en", "")) for e in data)
        for k, v in items:
            text, half = (v["text"], v.get("width", "half") != "full") if isinstance(v, dict) else (v, True)
            if text:
                tr[k] = (text, half)
    return tr


def write_in_place(buf, off, raw, capacity, sid):
    if len(raw) + 1 > capacity:
        raise SystemExit(f"{sid}: {len(raw) + 1} bytes doesn't fit in-place capacity {capacity}")
    buf[off:off + capacity] = raw + b"\0" * (capacity - len(raw))


def main():
    root, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    tr = load_translations(sys.argv[3:])
    files = root / "files"
    dumps = {}
    for p in (root / "script").glob("*.json"):
        for e in json.loads(p.read_text(encoding="utf-8")):
            dumps[e["id"]] = e
    unknown = set(tr) - set(dumps)
    if unknown:
        raise SystemExit(f"unknown ids: {sorted(unknown)[:10]}")

    bufs = {name: bytearray((files / name).read_bytes()) for name in ("SCE.S", "RES.R", "SLPS_021.07")}

    # 1. strings outside commands go in place, before SCE.S is parsed
    cmd_edits = {}
    for sid, (text, half) in tr.items():
        e = dumps[sid]
        try:
            raw = encode(text, half)
            layout.check_scene_split(sid, raw)
        except ValueError as err:
            raise SystemExit(f"{sid}: {err}")
        if e["cmd"] is not None:
            cmd_edits[e["offset"]] = (sid, raw)
        else:
            write_in_place(bufs[e["file"]], e["offset"], raw, e["capacity"], sid)

    # 2. command strings: parse, edit, rebuild
    scenes = sce.parse(bytes(bufs["SCE.S"]), bytes(bufs["SLPS_021.07"]))
    old_table = sce.read_scene_table(bufs["SLPS_021.07"])
    for *_, cmd in sce.iter_commands(scenes):
        for i, off in enumerate(cmd.arg_offsets):
            if off in cmd_edits:
                cmd.args[i] = cmd_edits.pop(off)[1]
    if cmd_edits:
        raise SystemExit(f"command strings not found: {[s for s, _ in cmd_edits.values()][:10]}")
    sce_bytes, table = sce.build(scenes)
    bufs["SCE.S"] = bytearray(sce_bytes)
    bufs["SLPS_021.07"] = bytearray(sce.patch_exe(bufs["SLPS_021.07"], table))

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, buf in bufs.items():
        (out_dir / name).write_bytes(buf)
    orig = (files / "SCE.S").stat().st_size
    print(f"{len(tr)} strings inserted. SCE.S {orig:#x} -> {len(sce_bytes):#x} "
          f"({(len(sce_bytes) - orig) // sce.SECTOR:+d} sectors)")
    for i, (a, b) in enumerate(zip(old_table, table)):
        if a != b:
            print(f"  scene {i:2d} moved {a:#x} -> {b:#x}")


if __name__ == "__main__":
    main()
