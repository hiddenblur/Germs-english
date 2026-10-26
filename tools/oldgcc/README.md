# Building the psx variants of old gcc on Windows (no admin, no WSL)

The retail game was built with gcc 2.8.1 (Psy-Q runtime library 4.4). Sony's SDK here only has
gcc 2.95.2, so we build 2.7.2 / 2.8.1 from source with the patches of
[decompals/old-gcc](https://github.com/decompals/old-gcc), using a portable 32-bit MinGW.
Everything lands in `tools/vendor/oldgcc` (gitignored). Result: `bin/cc1-2.7.2.exe`, `bin/cc1-2.8.1.exe`.

What was downloaded (2026-10-26):

| File | Size | From |
|---|---|---|
| `w64devkit-x86-2.10.1.7z.exe` (run it with `-y -o"kit"`) | 61.2 MB | github.com/skeeto/w64devkit releases v2.10.1 |
| `gcc-2.7.2.tar.gz` | 7.1 MB | ftp.gnu.org/old-gnu/gcc/ |
| `gcc-2.8.1.tar.gz` | 8.4 MB | ftp.gnu.org/gnu/gcc/ |
| old-gcc repo (patches) | small | `git clone --depth 1 https://github.com/decompals/old-gcc.git repo` |

Must be the **x86** kit: gcc 2.x needs a 32-bit host (`long` and pointers the same size).

Steps (Git Bash; the repo path has a space, so make a junction first):

```
cmd /c mklink /J C:\gccbuild "C:\...\Germs Recomp\tools\vendor\oldgcc"
cd /c/gccbuild
cp /path/to/tools/oldgcc/build.sh .; cp -r /path/to/tools/oldgcc/shim .
mkdir shimbin; for n in gcc cc ar ranlib sed awk; do : > shimbin/$n; done   # autoconf's `test -f gcc`
export PATH="/c/gccbuild/kit/w64devkit/bin:/c/gccbuild/shimbin:$PATH"
sh build.sh 2.7.2        # unpacks, patches, configures
cd work-2.7.2/gcc-2.7.2
gcc -c -O1 -w ../../shim/bsd.c -o bsd.o
make cc1 CFLAGS="-std=gnu89 -w -O1 -IC:/gccbuild/shim" CLIB="bsd.o"
cp cc1.exe /c/gccbuild/bin/cc1-2.7.2.exe          # same for 2.8.1
```

Why the shims: mingw has no `sys/resource.h`, `sys/times.h`, `bcmp`, `index`. `build.sh` also patches
the 2.8.1 autoconf test (`conftest.exe`), passes `-std=gnu89` (gcc 16 rejects implicit int) and busybox
`patch` has no `-s`.

Using it: `cc1` needs `TMPDIR` to point at a writable directory (mips.c writes a temp file there) and
`-G8` (ccpsx's default; 2.8.1 defaults to 0). `tools/cc_check.py --cc1 2.8.1` does both. Old gcc writes
`.comm` after the code, but ASPSX is single-pass and needs it before to emit `$gp` accesses, so
`cc_check.py` moves those lines up before assembling (`hoist_comm`).
