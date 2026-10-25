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
import images
import insert_script
import sce
import windows

ROOT = Path(__file__).resolve().parent.parent
EXTRACTED = ROOT / "extracted"
SHEETS = ROOT / "sheets"
TRANSLATIONS = ROOT / "translations"
COLUMNS = ["id", "window", "limit", "ja", "en", "note"]
TIGHT = 64          # areas with less free space than this are flagged


def load_game():
    return ((EXTRACTED / "files" / "SCE.S").read_bytes(),
            (EXTRACTED / "files" / "SLPS_021.07").read_bytes())


def area_budgets(sce_bytes, exe):
    """{(scene, area): (free bytes, set of arg offsets)} for every script area."""
    scenes = sce.parse(sce_bytes, exe)
    return {(si, ai): (free, set(offs)) for si, ai, free, offs in sce.aset_budgets(scenes)}


def area_of(budgets):
    """{arg offset: (scene, area)}; offsets are the retail ones, kept through rebuilds."""
    return {o: key for key, (_, offs) in budgets.items() for o in offs}


def group_of(entry, scene_table):
    if entry["file"] == "SLPS_021.07":
        return "exe"
    if entry["file"] == "RES.R":
        return "res"
    scene = sum(1 for start in scene_table if start <= entry["offset"]) - 1
    return f"sce_{scene:02d}"


def limit_text(entry, budgets=None, areas=None):
    kind = windows.classify(entry)
    win = windows.WINDOWS[kind]
    column = windows.marker_column(entry)
    space = ""
    if entry["cmd"] is not None and areas and entry["offset"] in areas:
        si, ai = areas[entry["offset"]]
        free = budgets[(si, ai)][0]
        space = f"; area {ai}: {free} bytes free" + (" (tight)" if free < TIGHT else "")
    if column is not None:
        return f"label only: ○ goes at half-column {column}" + space
    parts = [f"{win.width} half-cells per line"]
    if win.wrap:
        parts = [f"auto-wrapped at {windows.WRAP_WIDTH}, 3 lines per page"]
    if entry["cmd"] is None:
        parts.append(f"max {entry['capacity'] - 1} bytes")
    if entry["id"] in windows.NARRATION:
        parts.append("first 15 lines on a black screen, the rest in the next scene")
    if not win.confirmed:
        parts.append("window unconfirmed")
    return "; ".join(parts) + space


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
    budgets = area_budgets(*load_game())       # retail free space: the starting budget
    areas = area_of(budgets)
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
                w.writerow([e["id"], windows.classify(e), limit_text(e, budgets, areas),
                            windows.ja_for_sheet(e["ja"]), en, note])
    export_images(tr)
    print(f"wrote {len(groups) + 1} sheets to {SHEETS}")


def export_images(tr):
    """img.csv: one row per text image. ja points at a PNG of the original; translated
    rows also get a preview PNG of the English as it will look in game."""
    res = (EXTRACTED / "files" / "RES.R").read_bytes()
    folder = SHEETS / "images"
    folder.mkdir(exist_ok=True)
    with open(SHEETS / "img.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for sid, kind, t in images.text_images(res):
            name = sid.replace("@", "_")
            images.export_png(t, folder / f"{name}.png")
            en, note = tr.get(sid, ("", ""))
            if en:
                try:
                    t.pixels = images.render(t, en)
                    images.export_png(t, folder / f"{name}.en.png")
                except ValueError as err:
                    note = f"{note} [does not fit: {err}]".strip()
            w.writerow([sid, kind, images.limit_text(kind), f"images/{name}.png", en, note])


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


def free_space_report(bufs, tr):
    """Print free bytes per script area that holds text: now (with translations) and retail."""
    retail = area_budgets(*load_game())
    now = area_budgets(bytes(bufs["SCE.S"]), bytes(bufs["SLPS_021.07"]))
    areas = area_of(retail)
    text, done = Counter(), Counter()
    for group, e in entries():
        if e["cmd"] is not None and e["offset"] in areas:
            text[areas[e["offset"]]] += 1
            done[areas[e["offset"]]] += e["id"] in tr
    print("Free space per script area (bytes; growth past 0 needs a sector the disc doesn't have)")
    print("  sheet   area   free now   retail   strings translated")
    tight = 0
    for key in sorted(text):
        si, ai = key
        free_now, free_retail = now[key][0], retail[key][0]
        flag = "OVER" if free_now < 0 else "tight" if free_now < TIGHT else ""
        tight += bool(flag)
        print(f"  sce_{si:02d}  {ai:4}  {free_now:9}  {free_retail:7}   {done[key]:4}/{text[key]:<4}  {flag}")
    print(f"{len(text)} areas with text; {tight} under {TIGHT} bytes free")


def check():
    tr = insert_script.load_translations([TRANSLATIONS]) if TRANSLATIONS.exists() else {}
    bufs, problems = insert_script.apply(EXTRACTED, tr)
    free_space_report(bufs, tr)
    total, done = Counter(), Counter()
    for group, e in entries():
        total[group] += 1
        done[group] += e["id"] in tr
    for sid, kind, _ in images.text_images(bytes(bufs["RES.R"])):
        total["img"] += 1
        done["img"] += sid in tr
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
