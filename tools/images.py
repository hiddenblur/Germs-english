"""Text that the game stores as images: the computer's mail pages and inbox rows (RES.R TIMs).

Ids look like "RES.R@1F5030" (file @ TIM offset) and live in the translation files next to
the string ids. English is drawn with our own font (tools/font.py) in the TIM's own palette
and written back in place: same size, same palette, only the pixels change.

kind        TIMs                           en text
mail page   79 x 240x128, 2 colours         up to 8 lines, word-wrapped, 16 px apart
inbox row   32 x 240x16                     "From | Subject": each part one line in its box;
                                           the checkbox and frame are kept
"""
from collections import Counter
from pathlib import Path

import font
import tim

PAGE_SIZE = (240, 128)
ROW_SIZE = (240, 16)
NOT_TEXT = {0xDC80C, 0x1E281C}           # compass strip, MAIL LIST/FROM/SUBJECT header

PAGE_LEFT, PAGE_TOP, PAGE_LINE, PAGE_LINES = 10, 3, 16, 8
PAGE_WIDTH = PAGE_SIZE[0] - PAGE_LEFT - 4
ROW_BOXES = [(13, 82), (97, 141)]        # (x, width) of the FROM and SUBJECT boxes
ROW_TOP, ROW_HEIGHT, ROW_PAD = 2, 12, 2


def image_id(off):
    return f"RES.R@{off:X}"


def parse_id(sid):
    name, off = sid.split("@")
    return name, int(off, 16)


def text_images(res):
    """[(id, kind, Tim)] for every RES.R TIM that holds text."""
    from survey import find_tims
    out = []
    for off, *_ in find_tims(res):
        if off in NOT_TEXT:
            continue
        t = tim.parse(res, off)
        size = (t.width, t.height)
        if size == PAGE_SIZE:
            out.append((image_id(off), "mail page", t))
        elif size == ROW_SIZE:
            out.append((image_id(off), "inbox row", t))
    return out


def kind_of(t):
    return {PAGE_SIZE: "mail page", ROW_SIZE: "inbox row"}[(t.width, t.height)]


def limit_text(kind):
    if kind == "mail page":
        return f"up to {PAGE_LINES} lines of {PAGE_WIDTH} px, word-wrapped; one page of a mail"
    return (f"From | Subject: one line each, From up to {ROW_BOXES[0][1] - 2 * ROW_PAD} px, "
            f"Subject up to {ROW_BOXES[1][1] - 2 * ROW_PAD} px")


def render_page(t, text):
    colours = Counter(t.pixels).most_common()
    bg, ink = colours[0][0], colours[1][0] if len(colours) > 1 else 0
    lines = font.wrap(text, PAGE_WIDTH)
    if len(lines) > PAGE_LINES:
        raise ValueError(f"{len(lines)} lines; a mail page holds {PAGE_LINES}")
    px = bytearray([bg]) * (t.width * t.height)
    for i, line in enumerate(lines):
        font.draw(px, t.width, PAGE_LEFT, PAGE_TOP + i * PAGE_LINE, line, ink)
    return px


def render_row(t, text):
    parts = [p.strip() for p in text.split("|")]
    if len(parts) != 2:
        raise ValueError('inbox row text must be "From | Subject"')
    px = bytearray(t.pixels)
    for (x0, w), part in zip(ROW_BOXES, parts):
        box = [px[y * t.width + x] for y in range(ROW_TOP, ROW_TOP + ROW_HEIGHT) for x in range(x0, x0 + w)]
        colours = Counter(box).most_common()
        bg, ink = colours[0][0], colours[1][0]
        font.check_chars(part)
        if font.text_width(part) > w - 2 * ROW_PAD:
            raise ValueError(f"{part!r} is {font.text_width(part)} px; the box holds {w - 2 * ROW_PAD}")
        for y in range(ROW_TOP, ROW_TOP + ROW_HEIGHT):
            px[y * t.width + x0:y * t.width + x0 + w] = bytes([bg]) * w
        font.draw(px, t.width, x0 + ROW_PAD, ROW_TOP + 1, part, ink)
    return px


def render(t, text):
    """New pixels for a text image; raises ValueError if the text doesn't fit."""
    return render_page(t, text) if kind_of(t) == "mail page" else render_row(t, text)


def apply(buf, tr, problems):
    """Draw translated text into the TIMs in RES.R (buf, edited in place)."""
    for sid, (text, _half) in tr.items():
        try:
            name, off = parse_id(sid)
            t = tim.parse(buf, off)
            t.pixels = render(t, text)
            new = t.to_bytes()
            assert len(new) == t.size
            buf[off:off + t.size] = new
        except (ValueError, KeyError) as err:
            problems.append((sid, str(err)))


def export_png(t, path, scale=2):
    Path(path).write_bytes(tim.to_png(t, scale))
