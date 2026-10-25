"""Translation sheets: export the script to spreadsheets, import English, check it.

    python -I tools/sheets.py export     write sheets/*.csv (Japanese + English side by side)
    python -I tools/sheets.py import     read sheets/*.csv, write translations/*.json
    python -I tools/sheets.py check      check translations/ against every window rule

Sheets hold the Japanese script, so sheets/ is gitignored; translations/*.json hold
only our English and are committed. Export merges what is already in translations/,
so sheets can be deleted and regenerated at any time. One sheet per SCE.S scene
(sce_00..sce_23, in script order), plus exe (system prompts) and res (item names).

Columns: id, window, limit, ja, en, note. Edit only en and note. In en and ja:
{0}-{9} colour, a line break is a real newline in the cell, {20} the game's full-cell
space, {col N} pads to half-column N. Choices with a ○ marker take just the label.
CSV files are UTF-8 with a BOM, so Excel, LibreOffice and Google Sheets open them.
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops the script dir
import insert_script
import sce
import windows

ROOT = Path(__file__).resolve().parent.parent
EXTRACTED = ROOT / "extracted"
SHEETS = ROOT / "sheets"
TRANSLATIONS = ROOT / "translations"
COLUMNS = ["id", "window", "limit", "ja", "en", "note"]


def group_of(entry, scene_table):
    if entry["file"] == "SLPS_021.07":
        return "exe"
    if entry["file"] == "RES.R":
        return "res"
    scene = sum(1 for start in scene_table if start <= entry["offset"]) - 1
    return f"sce_{scene:02d}"


def limit_text(entry):
    kind = windows.classify(entry)
    win = windows.WINDOWS[kind]
    column = windows.marker_column(entry)
    if column is not None:
        return f"label only: ○ goes at half-column {column}"
    parts = [f"{win.width} half-cells per line"]
    if win.wrap:
        parts = [f"auto-wrapped at {windows.WRAP_WIDTH}, 3 lines per page"]
    if entry["cmd"] is None:
        parts.append(f"max {entry['capacity'] - 1} bytes")
    if entry["id"] in windows.NARRATION:
        parts.append("first 15 lines on a black screen, the rest in the next scene")
    if not win.confirmed:
        parts.append("window unconfirmed")
    return "; ".join(parts)


def entries():
    exe = (EXTRACTED / "files" / "SLPS_021.07").read_bytes()
    table = sce.read_scene_table(exe)
    out = []
    for name in ("SCE.S", "SLPS_021.07", "RES.R"):
        dump = json.loads((EXTRACTED / "script" / f"{name}.json").read_text(encoding="utf-8"))
        out += [(group_of(e, table), e) for e in dump]
    return out


def read_translation_files():
    """{id: (text, note)} from translations/*.json."""
    tr = {}
    for p in sorted(TRANSLATIONS.glob("*.json")):
        for k, v in json.loads(p.read_text(encoding="utf-8")).items():
            tr[k] = (v.get("text", ""), v.get("note", "")) if isinstance(v, dict) else (v, "")
    return tr


def export():
    tr = read_translation_files()
    SHEETS.mkdir(exist_ok=True)
    groups = {}
    for group, e in entries():
        groups.setdefault(group, []).append(e)
    for group, rows in groups.items():
        with open(SHEETS / f"{group}.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            for e in rows:
                en, note = tr.get(e["id"], ("", ""))
                w.writerow([e["id"], windows.classify(e), limit_text(e),
                            windows.ja_for_sheet(e["ja"]), en, note])
    print(f"wrote {len(groups)} sheets to {SHEETS}")


def import_():
    written = 0
    for p in sorted(SHEETS.glob("*.csv")):
        with open(p, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        out = {}
        for r in rows:
            en, note = (r.get("en") or "").replace("\r\n", "\n"), (r.get("note") or "").strip()
            if en:
                out[r["id"]] = {"text": en, "note": note} if note else en
        target = TRANSLATIONS / f"{p.stem}.json"
        if out or target.exists():
            TRANSLATIONS.mkdir(exist_ok=True)
            target.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            written += len(out)
    print(f"imported {written} translated strings into {TRANSLATIONS}")


def check():
    tr = insert_script.load_translations([TRANSLATIONS]) if TRANSLATIONS.exists() else {}
    _, problems = insert_script.apply(EXTRACTED, tr)
    total, done = Counter(), Counter()
    for group, e in entries():
        total[group] += 1
        done[group] += e["id"] in tr
    for group in sorted(total):
        if done[group]:
            print(f"  {group:7} {done[group]:5}/{total[group]:<5}")
    print(f"translated {sum(done.values())} of {sum(total.values())} strings")
    for where, msg in problems:
        print(f"PROBLEM {where}: {msg}")
    if problems:
        raise SystemExit(f"{len(problems)} problem(s)")
    print("no problems")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"export": export, "import": import_, "check": check}.get(
        cmd, lambda: sys.exit(__doc__))()
