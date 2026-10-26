#!/bin/sh
# Build the psx variant of old gcc natively on Windows (w64devkit x86). Usage: sh build.sh 2.7.2|2.8.1
# Follows decompals/old-gcc Dockerfiles; host is the 32-bit mingw gcc.
set -e
V=$1
ROOT=C:/gccbuild
W=$ROOT/work-$V
rm -rf "$W"; mkdir -p "$W"; cd "$W"
tar xzf "$ROOT/dl/gcc-$V.tar.gz"
cd gcc-$V
P=$ROOT/repo/patches
sed -i -- 's/include <varargs.h>/include <stdarg.h>/g' *.c
if [ "$V" = 2.7.2 ]; then
  patch -u -p1 obstack.h -i $P/obstack-2.7.2.h.patch
  patch -u -p1 configure -i $P/configure.patch
  patch -u -p1 config.sub -i $P/config.sub.patch
  patch -u -p1 config/mips/mips.h -i $P/mipsel-2.7.patch
  patch -u -p1 < $P/psx-2.5.7.patch
else
  patch -u -p1 obstack.h -i $P/obstack-2.8.1.h.patch
  patch -u -p1 config/mips/mips.h -i $P/mips.patch
  patch -u -p1 < $P/psx.patch
fi
# mingw writes conftest.exe, but gcc 2.8.1's autoconf checks for a file named conftest
sed -i 's/test -s conftest;/{ test -s conftest || test -s conftest.exe; };/; s/test -s conftest \&\&/{ test -s conftest || test -s conftest.exe; } \&\&/' configure
echo "== configure"
ac_cv_prog_cc_works=yes ac_cv_prog_cc_cross=no ac_cv_prog_gcc=yes ac_cv_prog_cc_g=yes CC="gcc -std=gnu89 -w" RANLIB=ranlib AR=ar sh ./configure --target=mips-sony-psx --prefix=/opt/cross --with-endian-little --with-gnu-as \
  --disable-gprof --disable-gdb --disable-werror --host=i386-pc-linux --build=i386-pc-linux > "$W/configure.log" 2>&1 || { tail -30 "$W/configure.log"; exit 1; }
[ "$V" = 2.8.1 ] && touch insn-config.h
echo "== configured"
