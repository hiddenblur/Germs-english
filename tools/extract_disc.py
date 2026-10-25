"""Extract every file from a PS1 MODE2/2352 BIN image (ISO9660).

Usage: python tools/extract_disc.py <image.bin> <out_dir>

Writes:
  <out_dir>/files/...          extracted files (Form 1 user data, 2048 bytes/sector)
  <out_dir>/raw/...            full 2352-byte sectors for files containing Form 2
                               sectors (XA audio / STR video), for jPSXdec etc.
  <out_dir>/manifest.json      LBA, size and sector form of every file, in disc
                               order, so the image can be rebuilt with the same layout
"""
import json
import sys
from pathlib import Path

SECTOR = 2352
USER_OFFSET = 24          # 12 sync + 4 header + 8 subheader
SUBMODE_FORM2 = 0x20


class Disc:
    def __init__(self, path):
        self.f = open(path, "rb")
        self.f.seek(0, 2)
        self.sector_count = self.f.tell() // SECTOR

    def raw(self, lba):
        self.f.seek(lba * SECTOR)
        return self.f.read(SECTOR)

    def user(self, lba):
        return self.raw(lba)[USER_OFFSET:USER_OFFSET + 2048]

    def is_form2(self, lba):
        return bool(self.raw(lba)[18] & SUBMODE_FORM2)


def parse_dir(disc, lba, size, prefix, out):
    data = b"".join(disc.user(lba + i) for i in range((size + 2047) // 2048))
    pos = 0
    while pos < len(data):
        rec_len = data[pos]
        if rec_len == 0:
            # records never cross sector boundaries; skip to the next sector
            pos = (pos // 2048 + 1) * 2048
            continue
        rec = data[pos:pos + rec_len]
        pos += rec_len
        ext_lba = int.from_bytes(rec[2:6], "little")
        ext_size = int.from_bytes(rec[10:14], "little")
        flags = rec[25]
        name_len = rec[32]
        name = rec[33:33 + name_len]
        if name in (b"\x00", b"\x01"):
            continue
        name = name.decode("ascii", "replace").split(";")[0]
        path = f"{prefix}/{name}" if prefix else name
        if flags & 0x02:
            parse_dir(disc, ext_lba, ext_size, path, out)
        else:
            out.append({"path": path, "lba": ext_lba, "size": ext_size})


def main():
    image, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    disc = Disc(image)

    pvd = disc.user(16)
    if pvd[1:6] != b"CD001":
        sys.exit("No ISO9660 primary volume descriptor at sector 16")
    root = pvd[156:156 + 34]
    root_lba = int.from_bytes(root[2:6], "little")
    root_size = int.from_bytes(root[10:14], "little")

    files = []
    parse_dir(disc, root_lba, root_size, "", files)
    files.sort(key=lambda e: e["lba"])

    for entry in files:
        n_sectors = (entry["size"] + 2047) // 2048
        lbas = range(entry["lba"], entry["lba"] + n_sectors)
        form2 = sum(disc.is_form2(l) for l in lbas)
        entry["sectors"] = n_sectors
        entry["form2_sectors"] = form2

        dest = out_dir / "files" / entry["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for l in lbas:
                f.write(disc.user(l))
            f.truncate(entry["size"])

        if form2:
            raw_dest = out_dir / "raw" / entry["path"]
            raw_dest.parent.mkdir(parents=True, exist_ok=True)
            with open(raw_dest, "wb") as f:
                for l in lbas:
                    f.write(disc.raw(l))

        kind = f"{form2}/{n_sectors} form2" if form2 else "form1"
        print(f"{entry['lba']:7d}  {entry['size']:10d}  {kind:>16}  {entry['path']}")

    manifest = {
        "image": image.name,
        "volume_id": pvd[40:72].decode("ascii", "replace").strip(),
        "total_sectors": disc.sector_count,
        "files": files,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\n{len(files)} files, volume '{manifest['volume_id']}', "
          f"{disc.sector_count} sectors")


if __name__ == "__main__":
    main()
