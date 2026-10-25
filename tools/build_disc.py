"""Write modified files back into a copy of the disc image, keeping the original layout.

Usage: python tools/build_disc.py <original.bin> <manifest.json> <files_dir> <out.bin>

Every file in <files_dir> whose path matches a manifest entry is written over that
file's original sectors. A file must not need more sectors than the original. Only
sectors whose user data changed are rewritten, with fresh EDC/ECC (Mode 2 Form 1).
If a file's byte size changed, its ISO9660 directory record is updated. A .cue is
written next to <out.bin>.
"""
import json
import shutil
import struct
import sys
from pathlib import Path

SECTOR = 2352
USER = 24          # 12 sync + 4 header + 8 subheader

# EDC: CRC-32 with the CD-ROM polynomial (reflected 0xD8018001)
EDC_LUT = []
for i in range(256):
    e = i
    for _ in range(8):
        e = (e >> 1) ^ (0xD8018001 if e & 1 else 0)
    EDC_LUT.append(e)

# ECC: Reed-Solomon product code over GF(2^8)
ECC_F, ECC_B = [0] * 256, [0] * 256
for i in range(256):
    j = ((i << 1) ^ (0x11D if i & 0x80 else 0)) & 0xFF
    ECC_F[i] = j
    ECC_B[i ^ j] = i


def edc(data):
    e = 0
    for b in data:
        e = (e >> 8) ^ EDC_LUT[(e ^ b) & 0xFF]
    return e


def ecc_block(src, major_count, minor_count, major_mult, minor_inc, dest, dest_off):
    size = major_count * minor_count
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _ in range(minor_count):
            t = src[index]
            index += minor_inc
            if index >= size:
                index -= size
            a ^= t
            b ^= t
            a = ECC_F[a]
        a = ECC_B[ECC_F[a] ^ b]
        dest[dest_off + major] = a
        dest[dest_off + major + major_count] = a ^ b


def fix_sector(sec):
    """Recompute EDC and ECC of a Mode 2 Form 1 sector in place."""
    struct.pack_into("<I", sec, 0x818, edc(sec[16:0x818]))
    header = bytes(sec[12:16])
    sec[12:16] = b"\0\0\0\0"            # Mode 2: ECC is computed with a zero header
    ecc_block(sec[12:0x81C], 86, 24, 2, 86, sec, 0x81C)      # P parity over data + EDC
    ecc_block(sec[12:0x8C8], 52, 43, 86, 88, sec, 0x8C8)     # Q parity also covers P
    sec[12:16] = header


def find_dir_record(img, path):
    """Return the image offset of the directory record for path."""
    def user(lba):
        return img[lba * SECTOR + USER:lba * SECTOR + USER + 2048]
    pvd = user(16)
    lba, size = struct.unpack_from("<I", pvd, 156 + 2)[0], struct.unpack_from("<I", pvd, 156 + 10)[0]
    parts = path.upper().split("/")
    for depth, name in enumerate(parts):
        found = None
        for s in range((size + 2047) // 2048):
            data, pos = user(lba + s), 0
            while pos < 2048 and data[pos]:
                rec_len = data[pos]
                n = data[pos + 32]
                rec_name = bytes(data[pos + 33:pos + 33 + n]).decode("ascii", "replace").split(";")[0]
                if rec_name == name:
                    found = (lba + s) * SECTOR + USER + pos
                    break
                pos += rec_len
            if found:
                break
        if found is None:
            raise SystemExit(f"{path}: not in ISO directory")
        lba = struct.unpack_from("<I", img, found + 2)[0]
        size = struct.unpack_from("<I", img, found + 10)[0]
    return found


def main():
    orig, manifest, files_dir, out = (Path(a) for a in sys.argv[1:5])
    entries = {e["path"]: e for e in json.loads(manifest.read_text())["files"]}
    shutil.copyfile(orig, out)
    with open(out, "r+b") as f:
        img = bytearray(f.read())
    touched = set()
    for p in sorted(x for x in files_dir.rglob("*") if x.is_file()):
        rel = p.relative_to(files_dir).as_posix()
        if rel not in entries:
            continue
        e, data = entries[rel], p.read_bytes()
        if (len(data) + 2047) // 2048 > e["sectors"]:
            raise SystemExit(f"{rel}: {len(data)} bytes needs more than its {e['sectors']} sectors")
        if e["form2_sectors"]:
            raise SystemExit(f"{rel}: has Form 2 sectors, not supported")
        changed = 0
        for i in range(e["sectors"]):
            chunk = data[i * 2048:(i + 1) * 2048].ljust(2048, b"\0")
            o = (e["lba"] + i) * SECTOR
            if img[o + USER:o + USER + 2048] != chunk:
                img[o + USER:o + USER + 2048] = chunk
                sec = img[o:o + SECTOR]
                fix_sector(sec)
                img[o:o + SECTOR] = sec
                touched.add(e["lba"] + i)
                changed += 1
        if len(data) != e["size"]:
            rec = find_dir_record(img, rel)
            struct.pack_into("<I", img, rec + 10, len(data))
            struct.pack_into(">I", img, rec + 14, len(data))
            touched.add((rec // SECTOR))
            o = (rec // SECTOR) * SECTOR
            sec = img[o:o + SECTOR]
            fix_sector(sec)
            img[o:o + SECTOR] = sec
        if changed:
            print(f"{rel}: {changed} sectors rewritten")
    out.write_bytes(img)
    out.with_suffix(".cue").write_text(
        f'FILE "{out.name}" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    print(f"wrote {out} and {out.with_suffix('.cue').name} ({len(touched)} sectors changed)")


if __name__ == "__main__":
    main()
