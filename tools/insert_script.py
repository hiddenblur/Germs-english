"""Insert translated text and rebuild SCE.S, RES.R and the EXE.

Usage: python tools/insert_script.py <extract_dir> <out_dir> <translation.json>...

Translation files are lists of dump entries (tools/dump_script.py) or
{"id": "en text"} maps. Entries with an empty "en" are left alone. With no
translated entries, the output is byte-identical to the input.

Text syntax in "en" (until the half-width font hack exists, letters are written
as full-width SJIS, as the game does for words like "Vitality"):
    {0}..{9}   colour change (the game's single-byte colour codes)
    newline    line break (the game's ",")
    space      one full 16 px cell (the game's 0x20)
    {xx}       raw byte in hex, e.g. {81}{9b} for the circle button glyph
Everything else is converted to its full-width form and encoded as Shift-JIS.

SCE.S command strings can change length freely; the archive is rebuilt and the
EXE scene table patched. Strings outside commands (SCE.S fixed fields, RES.R,
EXE) are written in place and must fit their dumped capacity.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops the script dir
import sce

TOKEN = re.compile(r"\{([0-9])\}|\{([0-9a-fA-F]{2})\}|(\n)|(.)", re.S)


def encode(text):
    out = bytearray()
    for colour, raw, newline, ch in TOKEN.findall(text):
        if colour:
            out += colour.encode()
        elif raw:
            out.append(int(raw, 16))
        elif newline:
            out += b","
        elif ch == " ":
            out += b" "
        elif "!" <= ch <= "~":
            out += chr(ord(ch) - 0x21 + 0xFF01).encode("cp932")   # full-width form
        else:
            out += ch.encode("cp932")
    return bytes(out)


def load_translations(paths):
    tr = {}
    for p in paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        items = data.items() if isinstance(data, dict) else ((e["id"], e.get("en", "")) for e in data)
        tr.update({k: v for k, v in items if v})
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
    for sid, text in tr.items():
        e = dumps[sid]
        raw = encode(text)
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
