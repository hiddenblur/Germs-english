"""Simulate how the (patched) narration renderer lays text out into rows.

Mirrors 0x80182860 after tools/patch_exe.py: columns are 8 px half-cells, the
window is 32 half-cells wide, and it wraps after a glyph or space reaches column 32.
    0xA0-0xFF   half-width glyph (0xA0 is a space), 1 column
    0x80-0x9F   full-width SJIS, 2 bytes, 2 columns
    0x20        full-cell space, 2 columns
    ','         line break
    other ASCII colour code, no width
"""
WIDTH = 32
ROWS_PER_PAGE = 3

# Strings typed across more than one screen. The game shows this many rows, then
# changes scene and keeps typing the same string, so the text must run past them.
# SCE.S:59008: opening narration, 5 pages on a black screen, then the office window.
SCENE_SPLITS = {"SCE.S:59008": 15}


def char_rows(raw, width=WIDTH):
    """Return [(byte offset, row)] for every visible character."""
    out, col, row, i = [], 0, 0, 0
    while i < len(raw):
        b = raw[i]
        if b >= 0x80 and b < 0xA0:
            out.append((i, row))
            col, i = col + 2, i + 2
        elif b >= 0xA0:
            if b != 0xA0:
                out.append((i, row))
            col, i = col + 1, i + 1
        elif b == 0x20:
            col, i = col + 2, i + 1
        elif b == 0x2C:
            col, row, i = 0, row + 1, i + 1
            continue
        else:
            i += 1
            continue
        if col >= width:
            col, row = 0, row + 1
    return out


def check_scene_split(sid, raw):
    """Raise ValueError if a split string ends before its scene change."""
    rows = SCENE_SPLITS.get(sid)
    if rows is None:
        return
    chars = char_rows(raw)
    if not chars or chars[-1][1] < rows:
        used = chars[-1][1] + 1 if chars else 0
        raise ValueError(f"text fills {used} rows, but the game shows {rows} rows "
                         f"({rows // ROWS_PER_PAGE} pages) before the scene change and then continues "
                         f"typing this string; add text past row {rows}")
