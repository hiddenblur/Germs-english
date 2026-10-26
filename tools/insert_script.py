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
import image_edit
import images
import layout
import sce
import windows

TOKEN = re.compile(r"\{([0-9])\}|\{([0-9a-fA-F]{2})\}|\{col (\d+)\}|(%[sd])|(\n)|(.)", re.S)


def rom_has_glyph(code):
    """SJIS ranges the Kanji ROM lookup at 0x801B1370 draws; anything else comes out blank."""
    return 0x8140 <= code <= 0x84BE or 0x889F <= code <= 0x9872


def encode(text, half=True):
    out = bytearray()
    quote_open = True
    for colour, raw, col, fmt, newline, ch in TOKEN.findall(text):
        if fmt:
            out += fmt.encode()                                 # sprintf placeholder stays ASCII
            continue
        if col:
            pad = int(col) - layout.line_widths(bytes(out))[-1]
            if pad < 0 or (pad % 2 and not half):
                raise ValueError(f"text is already past column {col}")
            out += b" " * (pad // 2) + b"\xA0" * (pad % 2)    # full cells: 2 columns per byte
            continue
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
    """Read translation files (or every *.json in a folder): {id: (text, half)}."""
    tr = {}
    files = []
    for p in map(Path, paths):
        files += sorted(p.glob("*.json")) if p.is_dir() else [p]
    for p in files:
        data = json.loads(p.read_text(encoding="utf-8"))
        items = data.items() if isinstance(data, dict) else ((e["id"], e.get("en", "")) for e in data)
        for k, v in items:
            if isinstance(v, dict) and "regions" in v:
                tr[k] = (v, True)                   # image screen: regions, see images.py
                continue
            text, half = (v.get("text", ""), v.get("width", "half") != "full") if isinstance(v, dict) else (v, True)
            if text:
                tr[k] = (text, half)
    return tr


def load_dumps(root):
    dumps = {}
    for p in (root / "script").glob("*.json"):
        for e in json.loads(p.read_text(encoding="utf-8")):
            dumps[e["id"]] = e
    return dumps


def prepare(entry, text, half=True):
    """Lay out translated text for its window and encode it.

    Label-style choices (retail: indent, label, padding, 3○) take just the label: the
    indent, padding to the retail marker column and the marker are added here. Dialogue
    is word-wrapped. Raises ValueError for text that can't be drawn or doesn't fit."""
    kind = windows.classify(entry)
    win = windows.WINDOWS[kind]
    column = windows.marker_column(entry)
    if half and column is not None and "○" not in text:
        width = layout.line_widths(encode(text))[0]
        if width > column - 2:
            raise ValueError(f"choice label is {width} half-cells; at most {column - 2} fit before the ○")
        text = "{20}" + text + "{col %d}{3}○" % column
    if kind == "profile text":
        return profile_text(text, half)
    if win.wrap:
        text = windows.wrap(text, measure=lambda t: layout.line_widths(encode(t, half))[0])
    raw = encode(text, half)
    widest = max(layout.line_widths(raw))
    if widest > win.width:
        raise ValueError(f"{kind} line is {widest} half-cells wide, limit {win.width}")
    layout.check_scene_split(entry["id"], raw)
    return raw


def profile_text(text, half=True):
    """Profile description for the panel renderer, which ignores line breaks and wraps
    mid-word: word-wrap into rows, pad each row to the wrap column with half spaces, and end
    it with a blank full-width space (drawn as a glyph, so it triggers the wrap)."""
    measure = lambda t: layout.line_widths(encode(t, half))[0]
    rows = windows.wrap(text, width=windows.PROFILE_ROW, measure=measure).split("\n")
    if len(rows) > windows.PROFILE_ROWS:
        raise ValueError(f"{len(rows)} rows; a profile description holds {windows.PROFILE_ROWS}")
    out = bytearray()
    for i, row in enumerate(rows):
        raw = encode(row, half)
        width = layout.line_widths(raw)[0]
        if width > windows.PROFILE_ROW:
            raise ValueError(f"profile row is {width} half-cells, limit {windows.PROFILE_ROW}")
        out += raw
        if i < len(rows) - 1:
            pad = windows.PROFILE_ROW - width      # full-cell spaces: 2 half-cells per byte
            out += b" " * (pad // 2) + b"\xA0" * (pad % 2) + "　".encode("cp932")
    return bytes(out)


def write_in_place(buf, off, raw, capacity):
    if len(raw) + 1 > capacity:
        raise ValueError(f"{len(raw) + 1} bytes, but only {capacity} fit in place")
    buf[off:off + capacity] = raw + b"\0" * (capacity - len(raw))


def apply(root, tr):
    """Apply translations to copies of the game files.

    Returns (bufs, problems): bufs maps file name -> bytes, problems is a list of
    (id or area, message). Nothing is valid to build while problems is non-empty."""
    files = root / "files"
    dumps = load_dumps(root)
    image_tr = {sid: v for sid, v in tr.items() if "@" in sid}      # text stored as images
    tr = {sid: v for sid, v in tr.items() if "@" not in sid}
    problems = [(sid, "unknown id") for sid in sorted(set(tr) - set(dumps))]
    bufs = {name: bytearray((files / name).read_bytes()) for name in ("SCE.S", "RES.R", "SLPS_021.07")}
    for name in sorted({images.parse_id(sid)[0] for sid in image_tr}):
        if name not in bufs:                # menus in the room files (M/A/*.RM)
            bufs[name] = bytearray((files / name).read_bytes())
        images.apply(bufs[name], image_tr, problems, name)
    image_edit.apply_edits(bufs, problems, set(image_tr))  # hand-edited PNGs in edits/ win over the text regions

    # 1. strings outside commands go in place, before SCE.S is parsed
    cmd_edits = {}
    for sid, (text, half) in tr.items():
        e = dumps.get(sid)
        if e is None:
            continue
        try:
            raw = prepare(e, text, half)
            if e["cmd"] is not None:
                cmd_edits[e["offset"]] = (sid, raw)
            else:
                if sid in layout.TIMED:
                    raw += layout.TIMED_MARKER      # keeps the retail typing pace
                write_in_place(bufs[e["file"]], e["offset"], raw, e["capacity"])
        except ValueError as err:
            problems.append((sid, str(err)))

    # 2. command strings: parse, edit, rebuild
    scenes = sce.parse(bytes(bufs["SCE.S"]), bytes(bufs["SLPS_021.07"]))
    edited = {off: sid for off, (sid, _) in cmd_edits.items()}
    for si, area, rec, cmd in sce.iter_commands(scenes):
        for i, off in enumerate(cmd.arg_offsets):
            if off in cmd_edits:
                cmd.args[i] = cmd_edits.pop(off)[1]
    problems += [(sid, "command string not found") for sid, _ in cmd_edits.values()]
    for si, ai, over, offs in sce.aset_overflows(scenes):
        sids = [edited[o] for o in offs if o in edited]
        problems.append((f"scene {si} area {ai}",
                         f"{over} bytes over its free space; shorten some of: {', '.join(sids[:8])}"
                         + (" ..." if len(sids) > 8 else "")))
    sce_bytes, table = sce.build(scenes)
    bufs["SCE.S"] = bytearray(sce_bytes)
    bufs["SLPS_021.07"] = bytearray(sce.patch_exe(bufs["SLPS_021.07"], table))
    return bufs, problems


def main():
    root, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    tr = load_translations(sys.argv[3:])
    bufs, problems = apply(root, tr)
    if problems:
        for where, msg in problems:
            print(f"{where}: {msg}")
        raise SystemExit(f"{len(problems)} problem(s); nothing written")
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, buf in bufs.items():
        (out_dir / name).parent.mkdir(parents=True, exist_ok=True)
        (out_dir / name).write_bytes(buf)
    print(f"{len(tr)} strings inserted; all files keep their size")


if __name__ == "__main__":
    main()
