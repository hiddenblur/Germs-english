# Decomp setup notes

## Toolchain (installed 2026-10-25)

- `psyq/` (gitignored): Psy-Q programmer tools CD DTL-S2002 (11/26/96) plus `zips/Lib44.zip`, `Lib45.zip`.
  `bin/CC1PSX.EXE`, `CPPPSX.EXE`, `ASPSX.EXE`, `CCPSX.EXE` are **Win32 PE**: they run natively on Windows.
  `PSYLIB.EXE` and `DUMPOBJ.EXE` do not (DOS), so `tools/psyqlib.py` reads the LIB/LNK format itself.
- splat64 0.51.0 (`pip install` of the wheel, plus rabbitizer, spimdisasm, n64img, crunch64).
- maspsx: not on PyPI; cloned to `tools/vendor/maspsx` (gitignored), run as `python tools/vendor/maspsx/maspsx.py`.
- objdiff and Ghidra 12.2 sit in the repo root (gitignored).

## SDK version

`tools/libmatch.py` masks relocated words and searches the EXE for each Psy-Q library function.
Unique functions found (main SDK / Lib44 / Lib45):

| Library | main | Lib44 | Lib45 |
|---|---|---|---|
| LIBCARD | 4/11 | **11/11** | 4/10 |
| LIBMCRD | 19/34 | **30/30** | 24/32 |
| LIBCD | 26/64 | **35/60** | 32/60 |
| LIBSND | 124/254 | **131/254** | 130/254 |
| LIBGTE | 65/534 | **70/527** | 70/527 |
| LIBGPU | 36/106 | **40/106** | 40/106 |

Lib44 (SDK 4.4 libraries) is the best match; LIBCARD and LIBMCRD match completely. Use `Lib44` for
decomp linking. Unmatched counts are mostly functions the game never linked in. Not yet done: check
that remaining partial libraries (LIBCD, LIBAPI) differ only because of unlinked modules and not
version skew. `LIBSN.LIB` has an opcode `psyqlib.py` doesn't parse (irrelevant for matching).
Match list: `python -I tools/libmatch.py extracted/files/SLPS_021.07 <lib>...` (output stays in `extracted/`).

## EXE memory map (from the code; confirmed by the library matches)

| Range (RAM) | Contents |
|---|---|
| `0x80170000-0x80173054` | `.rdata` (strings, tables) |
| `0x80173054-0x801ACA50` | game code (518 functions found by splat) |
| `0x801ACA50-0x801D1E60` | Psy-Q 4.4 libraries (libc2, libgpu, libgs, libgte, libcd, libetc, libmath, libsnd, libspu, libsn, libmcrd, libcard, libapi) |
| `0x801D1E60-0x801D7330` | more text, not yet identified |
| `0x801D7330-0x801DFE50` | `.data` / `.sdata` |
| `0x801DFE50-0x801E7A10` | bss, zeroed by `__SN_ENTRY_POINT` (`0x801C8840`) |

`gp = 0x801DFC58`, `main = 0x8018BDE8`. The kanji ROM font call is `Krom2RawAdd2` at `0x801B1370`
(libgpu), with `kanjitrans` at `0x801B141C`.

## Splat

`decomp/germs.yaml` is the first-draft config; `tools/gen_symbols.py` writes `decomp/symbol_addrs.txt`
(437 named library functions) from `extracted/libmatch.txt`. From `decomp/`: `python -m splat split germs.yaml`.
Generated asm, linker script and macros are gitignored (they contain game code). Limits of the draft:
the game and library text are single blobs (no per-object boundaries), `.data` and `.rdata` are not
split per object, and short library functions (under 8 words) are skipped as ambiguous.
