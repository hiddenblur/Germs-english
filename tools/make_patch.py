"""Make (and verify) the distributable xdelta3 patch: original disc image -> patched disc image.

Usage: python -I tools/make_patch.py <original.bin> <patched.bin> <out_dir> [--name Germs_EN]

Writes <out_dir>/<name>.xdelta and <out_dir>/<name>.checksums.txt (size, CRC32, MD5 and SHA-1 of
the original and the patched image, which the README quotes). The patch is then applied to the
original with xdelta3 and the result compared with <patched.bin>; it is also applied to a corrupted
copy of the original to confirm xdelta3 refuses the wrong source. Any failure exits non-zero.

xdelta3 is found via $XDELTA3, tools/vendor/xdelta3*.exe, or PATH. The patch only holds our
changes, but it does contain bytes of the translated files, so release only the .xdelta and never
the images.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def find_xdelta():
    env = os.environ.get("XDELTA3")
    if env and Path(env).exists():
        return env
    vendor = sorted((ROOT / "tools" / "vendor").glob("xdelta3*"))
    if vendor:
        return str(vendor[0])
    found = shutil.which("xdelta3")
    if found:
        return found
    raise SystemExit("xdelta3 not found: set $XDELTA3, put it in tools/vendor/, or add it to PATH")


def hashes(path):
    crc, md5, sha1, size = 0, hashlib.md5(), hashlib.sha1(), 0
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            crc = zlib.crc32(chunk, crc)
            md5.update(chunk)
            sha1.update(chunk)
            size += len(chunk)
    return {"size": size, "crc32": f"{crc:08X}", "md5": md5.hexdigest(), "sha1": sha1.hexdigest()}


def same_file(a, b):
    if Path(a).stat().st_size != Path(b).stat().st_size:
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            ca, cb = fa.read(1 << 20), fb.read(1 << 20)
            if ca != cb:
                return False
            if not ca:
                return True


def encode(source, target, patch, xdelta=None):
    # -S none: no secondary compression, so every patcher (including web ones) can read it
    run = subprocess.run([xdelta or find_xdelta(), "-e", "-9", "-S", "none", "-f", "-s", str(source), str(target), str(patch)],
                         capture_output=True, text=True)
    if run.returncode:
        raise RuntimeError("xdelta3 encode failed: " + run.stderr.strip())


def apply(source, patch, out, xdelta=None):
    """Apply a patch; returns True on success, False if xdelta3 refused it."""
    run = subprocess.run([xdelta or find_xdelta(), "-d", "-f", "-s", str(source), str(patch), str(out)],
                         capture_output=True, text=True)
    return run.returncode == 0


def verify(source, target, patch, xdelta=None):
    """Return a list of problems (empty when the patch reproduces target and rejects a wrong source)."""
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "applied.bin"
        if not apply(source, patch, out, xdelta):
            problems.append("patch does not apply to the original")
        elif not same_file(out, target):
            problems.append("applied result differs from the patched image")
        bad = Path(tmp) / "wrong_source.bin"
        data = bytearray(Path(source).read_bytes())
        data[len(data) // 2] ^= 0xFF
        bad.write_bytes(data)
        if apply(bad, patch, Path(tmp) / "bad_out.bin", xdelta):
            problems.append("patch applied to a corrupted source (xdelta3 should refuse)")
    return problems


def checksums_text(name, original, patched, patch):
    lines = [f"{name}: checksums"]
    for label, path in (("Original disc image (supply your own)", original),
                        ("Patched disc image (result)", patched), ("Patch file", patch)):
        h = hashes(path)
        lines += ["", label, f"  file:  {Path(path).name}", f"  size:  {h['size']} bytes",
                  f"  CRC32: {h['crc32']}", f"  MD5:   {h['md5']}", f"  SHA-1: {h['sha1']}"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("original")
    ap.add_argument("patched")
    ap.add_argument("out_dir")
    ap.add_argument("--name", default="Germs_EN")
    a = ap.parse_args(argv)
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    patch = out_dir / f"{a.name}.xdelta"
    xd = find_xdelta()
    encode(a.original, a.patched, patch, xd)
    problems = verify(a.original, a.patched, patch, xd)
    if problems:
        patch.unlink(missing_ok=True)
        print("\n".join("FAIL: " + p for p in problems), file=sys.stderr)
        return 1
    text = checksums_text(a.name, a.original, a.patched, patch)
    (out_dir / f"{a.name}.checksums.txt").write_text(text, encoding="utf-8")
    print(f"{patch} ({patch.stat().st_size} bytes), verified\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
