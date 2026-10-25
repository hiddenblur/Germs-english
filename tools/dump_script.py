"""Dump every text string from the game files into editable JSON.

Usage: python tools/dump_script.py <extract_dir> [out_dir]

Script files (SCE.S, RES.R) hold script commands of the form
    u32 size        bytes after this field, up to the next command
    u16 opcode
    u16 flag
    u32 zero
    u32 argc
    argc null-terminated string args, zero-padded to 4 bytes
Text is just a string argument. Commands are found by validating that layout at
every 4-byte boundary. SJIS strings that aren't inside a command (and all
strings in the EXE) are dumped as "loose" entries.

Each entry:
    id        stable key, "<file>:<offset hex>"
    file      path inside extracted/files
    offset    file offset of the first byte of the string
    length    byte length without the terminator
    capacity  bytes available in place, including the terminator, before the next
              arg/command or the end of padding (writing past this needs relocation)
    cmd       for script strings: {offset, opcode, flag, argc, arg, args}
    ja        original text (cp932)
    en        translation (empty)
"""
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops the script dir
from find_text import is_kana, is_lead, scan

SCRIPT_FILES = ["SCE.S", "RES.R"]
LOOSE_FILES = ["SLPS_021.07"]

# Short EXE strings the scan can't find (too few kana), with their slot sizes: the profile
# panel's stats line (0x80182D34, line 2) is sprintf("%s才 %s %sｃｍ %s", age, sex, height,
# blood) with the format at 0x801704F0 and word tables at 0x801D76C4 / 0x801D76D0.
FIXED_EXE = {
    0xCF0: 20,                                  # stats format (next string at 0xD04)
    0x704B4: 4, 0x704B8: 4, 0x704BC: 4,         # sex: 男, 女, ？
    0x704C0: 8, 0x704C8: 8, 0x704D0: 8, 0x704D8: 8, 0x704E0: 8,   # blood: AB, O, B, A, ？
}
# RES.R weapon table: a "WEPN" chunk of 0x60-byte records after an 8-byte header, the name
# in a 32-byte field at +4 (stats from +0x24), drawn by 0x8018C864 (12 cells).
WEAPON_RECORD, WEAPON_NAME, WEAPON_NAME_SIZE = 0x60, 4, 0x20


def weapon_names(data):
    """{offset: capacity} of the weapon names in RES.R."""
    base = data.find(b"WEPN") + 8
    out = {}
    for r in range(base, base + struct.unpack_from("<I", data, base - 4)[0] - WEAPON_RECORD + 1, WEAPON_RECORD):
        if data[r + WEAPON_NAME] == 0:
            break
        out[r + WEAPON_NAME] = WEAPON_NAME_SIZE
    return out


MAX_CMD = 0x2000
MAX_ARGC = 64


def has_sjis(raw):
    return any(is_lead(b) for b in raw)


def parse_cmd(data, p):
    """Return (end, opcode, flag, args[(offset, raw)]) if a command starts at p."""
    if p + 20 > len(data):
        return None
    size = int.from_bytes(data[p:p + 4], "little")
    opcode = int.from_bytes(data[p + 4:p + 6], "little")
    flag = int.from_bytes(data[p + 6:p + 8], "little")
    zero = int.from_bytes(data[p + 8:p + 12], "little")
    argc = int.from_bytes(data[p + 12:p + 16], "little")
    end = p + 4 + size
    if (zero or not 1 <= argc <= MAX_ARGC or size % 4 or not 16 <= size <= MAX_CMD
            or end > len(data) or opcode == 0 or opcode > 0x200):
        return None
    args, q = [], p + 16
    for _ in range(argc):
        z = data.find(b"\x00", q, end)
        if z == -1:
            return None
        raw = data[q:z]
        if not all(0x20 <= b < 0x7F or b >= 0x80 for b in raw):
            return None
        if has_sjis(raw):
            try:
                raw.decode("cp932")
            except UnicodeDecodeError:
                return None
        args.append((q, raw))
        q = z + 1
    # the rest of the command must be zero padding shorter than 4 bytes
    if any(data[q:end]) or end - q > 3:
        return None
    return end, opcode, flag, args


def dump_script_file(data, rel):
    entries, covered = [], set()
    p = 0
    while p < len(data) - 20:
        cmd = parse_cmd(data, p)
        if not cmd:
            p += 4
            continue
        end, opcode, flag, args = cmd
        arg_texts = [raw.decode("cp932", "replace") for _, raw in args]
        for i, (off, raw) in enumerate(args):
            if not has_sjis(raw):
                continue
            nxt = args[i + 1][0] if i + 1 < len(args) else end
            entries.append({
                "id": f"{rel}:{off:X}", "file": rel, "offset": off, "length": len(raw),
                "capacity": nxt - off,
                "cmd": {"offset": p, "opcode": opcode, "flag": flag, "argc": len(args),
                        "arg": i, "args": arg_texts},
                "ja": raw.decode("cp932"), "en": "",
            })
            covered.add(off)
        p = end
    return entries, covered


def loose_entries(data, rel, skip=()):
    out = []
    for off, raw in scan(data, 1):
        # real strings start after a terminator/padding byte; noise in binary data doesn't
        if off in skip or len(raw) < 4 or (off and data[off - 1] != 0):
            continue
        try:
            text = raw.decode("cp932")
        except UnicodeDecodeError:
            continue
        if sum(ord(ch) > 0x7F for ch in text) < 2 or not any(
                is_kana(raw[i] << 8 | raw[i + 1]) for i in range(len(raw) - 1) if is_lead(raw[i])):
            continue
        end = off + len(raw) + 1
        while end < len(data) and end % 4 and data[end] == 0:
            end += 1
        out.append({"id": f"{rel}:{off:X}", "file": rel, "offset": off, "length": len(raw),
                    "capacity": end - off, "cmd": None, "ja": text, "en": ""})
    return out


def main():
    root = Path(sys.argv[1])
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else root / "script"
    out_dir.mkdir(parents=True, exist_ok=True)
    for rel in SCRIPT_FILES + LOOSE_FILES:
        data = (root / "files" / rel).read_bytes()
        if rel in SCRIPT_FILES:
            entries, covered = dump_script_file(data, rel)
            fixed = weapon_names(data) if rel == "RES.R" else {}
            loose = [e for e in loose_entries(data, rel, covered) if e["offset"] not in fixed]
            for off, cap in fixed.items():
                raw = data[off:off + cap].split(bytes(1))[0]
                loose.append({"id": f"{rel}:{off:X}", "file": rel, "offset": off,
                              "length": len(raw), "capacity": cap, "cmd": None,
                              "window": "weapon", "ja": raw.decode("cp932", "replace"), "en": ""})
        else:
            entries, loose = [], loose_entries(data, rel)
            found = {e["offset"] for e in loose}
            for off, cap in FIXED_EXE.items():
                if off not in found:
                    raw = data[off:off + cap].split(b"\0")[0]
                    loose.append({"id": f"{rel}:{off:X}", "file": rel, "offset": off,
                                  "length": len(raw), "capacity": cap, "cmd": None,
                                  "ja": raw.decode("cp932"), "en": ""})
        all_entries = sorted(entries + loose, key=lambda e: e["offset"])
        name = rel.replace("/", "_") + ".json"
        (out_dir / name).write_text(json.dumps(all_entries, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
        opcodes = sorted({e["cmd"]["opcode"] for e in entries})
        print(f"{rel:12} {len(entries):5d} in commands, {len(loose):4d} loose  "
              f"opcodes with text: {[hex(o) for o in opcodes]}")


if __name__ == "__main__":
    main()
