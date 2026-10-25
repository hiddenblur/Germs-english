"""Which window each string is drawn in, and how translated text is laid out for it.

Widths are in 8 px half-cells (all text renderers are patched; see docs/disc-survey.md).

window        strings                               width  layout
dialogue      SCE.S opcode 5 flag 0, opening/ending 32     auto word-wrap, 3 rows per page
              narration (typewriter 0x80182860)
choice        SCE.S opcode 5 flag 1                 32     one line; label-style choices get
                                                           their indent, padding and ○ marker
                                                           added automatically
profile       other SCE.S strings: profile names    32     one centred line, in place
              and titles (panel 0x80182D34)
profile text  profile descriptions (40+ bytes)      26     word-wrapped into 5 rows, in place
prompt        EXE strings                           32     no wrap, in place
item          RES.R strings (item names)            32     no wrap, in place
weapon        RES.R WEPN record names               12     one line of 8 px cells, in place
              (renderer 0x8018C864)

Only "dialogue" and the EXE desk prompt (a "prompt") are confirmed in the emulator; the
other assignments come from how the strings are stored. Re-check a window when it is
first seen in game, and update CONFIRMED.
"""
import re
from dataclasses import dataclass

import layout


@dataclass(frozen=True)
class Window:
    name: str
    width: int
    wrap: bool
    confirmed: bool
    note: str


WINDOWS = {
    "dialogue": Window("dialogue", 32, True, True, "auto-wrapped, 3 rows per page"),
    "choice": Window("choice", 32, False, False, "one line; type only the label"),
    "profile": Window("profile", 32, False, False, "name or title, one centred line"),
    "profile text": Window("profile text", 26, True, False, "description, up to 3 rows"),
    "prompt": Window("prompt", 32, False, True, "one line per break, fixed size"),
    "item": Window("item", 32, False, False, "one line, fixed size"),
    "weapon": Window("weapon", 12, False, True, "weapon name, one line of 12 cells"),
}

# Profile records in SCE.S (drawn by the panel renderer 0x80182D34): name at +0x0C and title
# at +0x2C (lines 0-1, centred), a stats line built from EXE strings (line 2), and the
# description at +0x4C (lines 3-7). The renderer wraps lines 3+ mid-word at half-column 30
# (rows start at 2), so descriptions are word-wrapped here into PROFILE_ROWS rows of
# PROFILE_ROW half-cells, each padded so a blank full-width space crosses column 30.
PROFILE_ROW = 26
PROFILE_ROWS = 5                        # lines 3-7: the line y table (0x801D76A4) has 8 entries
PROFILE_TEXT_MIN_CAPACITY = 40          # descriptions; names and titles are much shorter
NARRATION = {"SCE.S:59008", "SCE.S:59808"}
# a word-wrapped line must stay below the width: a line that ends exactly at the
# edge wraps by itself and the line break after it would add an empty row
WRAP_WIDTH = 31

CHOICE = re.compile(r"^ ?(?P<label>.*?) *3○$", re.S)


def classify(entry):
    """Return the window name for a dump entry."""
    if entry.get("window"):                 # set by the dumper (fixed-layout records)
        return entry["window"]
    if entry["id"] in NARRATION:
        return "dialogue"
    if entry["cmd"]:
        return "choice" if entry["cmd"]["flag"] == 1 else "dialogue"
    if entry["file"] == "SCE.S":
        return "profile text" if entry["capacity"] >= PROFILE_TEXT_MIN_CAPACITY else "profile"
    return {"SLPS_021.07": "prompt", "RES.R": "item"}[entry["file"]]


def marker_column(entry):
    """Half-column of the ○ marker in a label-style choice, else None."""
    if classify(entry) != "choice" or not CHOICE.match(entry["ja"]):
        return None
    raw = entry["ja"].encode("cp932")
    return layout.line_widths(raw[:raw.rindex("3○".encode("cp932"))])[-1]


def ja_for_sheet(ja):
    """Show retail control codes in translation syntax: colours as {n}, breaks as newlines."""
    return re.sub(r"[0-9]", lambda m: "{" + m.group() + "}", ja.replace(",", "\n"))


def wrap(text, width=WRAP_WIDTH, measure=None):
    """Greedy word-wrap of translation text. Explicit newlines are kept; continuation
    lines repeat the paragraph's leading spaces (the game indents dialogue by one cell)."""
    out = []
    for para in text.split("\n"):
        indent = para[:len(para) - len(para.lstrip(" "))]
        words, line = para.split(" "), ""
        words = [w for w in words if w] or [""]
        line = indent + words[0]
        for w in words[1:]:
            if measure(line + " " + w) <= width:
                line += " " + w
            else:
                out.append(line)
                line = indent + w
        out.append(line)
    return "\n".join(out)
