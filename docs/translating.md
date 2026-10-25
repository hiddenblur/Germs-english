# Translating

## The loop

```
python -I tools/sheets.py export      # sheets/*.csv: id, window, limit, ja, en, note
  ...translate in the en column (Excel, LibreOffice, Google Sheets)...
python -I tools/sheets.py import      # en -> translations/*.json (commit these)
python -I tools/sheets.py check       # every rule below, plus progress per sheet
```

- `sheets/` holds the Japanese script, so it is gitignored. `translations/` holds only English
  and is committed.
- `export` merges what is already in `translations/`, so a sheet can always be regenerated.
  Run `import` before `export` if a sheet has unimported edits.
- There is one sheet per scene (`sce_00` .. `sce_23`, in script order), plus `exe` (system
  prompts and messages) and `res` (item names).
- Leave `en` empty to keep the Japanese.

## Writing en

| Write | Meaning |
|---|---|
| a newline in the cell | line break |
| `{0}`-`{9}` | colour change: copy them from `ja`, where retail colours show the same way |
| `{20}` | the game's full-cell (16 px) space |
| `{col N}` | pad to half-column N |
| `"` `'` | straight quotes and apostrophes from the BIOS font |

The font has no `\` (it draws ¥) and no `~` (it draws an overline). Accented letters aren't
available either.

## Windows (the `window` and `limit` columns)

Widths are in half-cells: one English character = 1, one Japanese character = 2.

- **dialogue**: wrapped automatically at 31 half-cells. A page holds 3 lines and the game waits
  for a button between pages. Keep a leading space if the Japanese has one: continuation lines
  repeat the indent.
- **choice**: a menu line. If `limit` says "label only", type only the label (at most the stated
  width); the indent, padding and ○ marker are added for you. Other choices are free text,
  one line of 32.
- **panel / prompt / item**: one line of 32 per break, not wrapped.
- Strings with "max N bytes" are fixed-size fields: one byte per English character.

**The opening narration (`SCE.S:59008`)** is shown in two scenes: the first 15 wrapped lines on
a black screen, the rest in the office. It must run past 15 lines.

## Space

Script strings can grow, but each script area has a fixed amount of free space, and the disc
layout can't grow. `check` reports `scene S area A: N bytes over its free space` and lists the
translated strings in that area. Some areas have none to spare (the office, scene 0 area 0).
English usually takes about the same bytes as the Japanese, but trim there if needed.

## Building a test disc

See CLAUDE.md: `insert_script.py` takes the `translations` folder directly.
