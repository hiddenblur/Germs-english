"""Live review page: filter, search, edit the English in the browser and check it as you type.

    python -I tools/qc_server.py [--port 8765] [--open]

Serves the qc_table page on http://127.0.0.1:<port> (this machine only: it holds the game's
Japanese script). The sheets stay the source of truth:

    - typing checks the string with the real inserter code (word-wrap, widths, bytes, font)
    - "Save to sheet" writes that one cell of sheets/<sheet>.csv (the `en` column) and nothing else
    - "Re-check all" runs the whole inserter, so shared area budgets are counted
    - "Import to translations/" is `sheets.py import`; the server never writes translations/ otherwise

Run `sheets.py export` first if sheets/ is missing. A cell that changed on disk since the page
loaded (Excel, another editor) is refused at save instead of overwritten.
"""
import argparse
import contextlib
import csv
import io
import json
import math
import os
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops the script dir
import images
import insert_script
import layout
import qc_table
import sheets
import tim
import windows

MAX_BODY = 1 << 20


class Conflict(Exception):
    """The cell on disk is not what the page thinks it is."""


def norm(text):
    return (text or "").replace("\r\n", "\n")


def save_cell(path, sid, en, base):
    """Write `en` into the row `sid` of a sheet CSV, keeping every other byte of the layout
    (UTF-8 with BOM, csv defaults, as sheets.py writes them). Raises Conflict if the cell
    no longer holds `base`, KeyError if the id is not in the sheet."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    col = rows[0].index("en")
    for row in rows[1:]:
        if row and row[0] == sid:
            if norm(row[col]) != norm(base):
                raise Conflict(norm(row[col]))
            row[col] = norm(en)
            break
    else:
        raise KeyError(sid)
    tmp = Path(path).with_name(Path(path).name + ".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)
    os.replace(tmp, path)               # PermissionError if the sheet is open in Excel


class Review:
    """Everything the handlers need: the dumps, the sheets' ids, the area map."""

    def __init__(self, sheets_dir=None):
        self.dir = Path(sheets_dir or sheets.SHEETS)
        self.dumps = insert_script.load_dumps(sheets.EXTRACTED)
        self.json_tr = insert_script.load_translations([sheets.TRANSLATIONS])
        self.res = (sheets.EXTRACTED / "files" / "RES.R").read_bytes()
        self.meta = {}                      # id -> (group, ja, limit, window)
        for group in qc_table.ORDER:
            path = self.dir / f"{group}.csv"
            if not path.exists():
                raise SystemExit(f"{path} is missing: run `python -I tools/sheets.py export` first")
            with open(path, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    self.meta[r["id"]] = (group, qc_table.readable(r["ja"]), r["limit"], r["window"])
        retail = sheets.area_budgets(*sheets.load_game())
        areas = sheets.area_of(retail)
        self.area_of = {e["id"]: areas[e["offset"]] for _, e in sheets.entries()
                        if e["cmd"] is not None and e["offset"] in areas}

    def csv_translations(self):
        """{id: (text, half)} as the sheets say (en column), screens and widths from translations/."""
        tr = dict(self.json_tr)
        en_of = {g: self.sheet_en(g) for g in qc_table.ORDER}
        for sid, (group, *_) in self.meta.items():
            en = en_of[group][sid]
            if en:
                tr[sid] = (en, tr.get(sid, (None, True))[1])
            elif not isinstance(tr.get(sid, ("",))[0], dict):
                tr.pop(sid, None)
        return tr

    def sheet_en(self, group):
        with open(self.dir / f"{group}.csv", encoding="utf-8-sig", newline="") as f:
            return {r["id"]: norm(r["en"]) for r in csv.DictReader(f)}

    def differing(self, tr):
        """Ids whose English differs between the sheets and translations/*.json."""
        text = lambda v: v[0] if isinstance(v[0], str) else None
        ids = {i for i in set(tr) | set(self.json_tr) if i in self.meta}
        return sorted(i for i in ids if text(tr.get(i, ("", 1))) != text(self.json_tr.get(i, ("", 1))))

    # ---- one string -------------------------------------------------------------------
    def preview(self, entry, text, half):
        """The text as the inserter lays it out (label marker added, word-wrapped)."""
        kind = windows.classify(entry)
        column = windows.marker_column(entry)
        if half and column is not None and "○" not in text:
            text = "{20}" + text + "{col %d}{3}○" % column
        measure = lambda t: layout.line_widths(insert_script.encode(t, half))[0]
        if kind == "profile text":
            return windows.wrap(text, width=windows.PROFILE_ROW, measure=measure)
        if windows.WINDOWS[kind].wrap:
            return windows.wrap(text, measure=measure)
        return text

    def check_one(self, sid, en):
        en = norm(en)
        if sid not in self.meta:
            return {"error": f"unknown id {sid}"}
        group, ja, limit, _ = self.meta[sid]
        if group == "img":
            return self.check_image(sid, en)
        entry = self.dumps[sid]
        out = {"en_empty": not en, "problem": None, "flags": [],
               "status": qc_table.status_of(ja, en)}
        if not en:
            return out
        half = self.json_tr.get(sid, (None, True))[1]
        raw = None
        try:
            raw = insert_script.prepare(entry, en, half)
            if entry["cmd"] is None:
                if len(raw) + 1 > entry["capacity"]:
                    raise ValueError(f"{len(raw) + 1} bytes, but only {entry['capacity']} fit in place")
        except ValueError as err:
            out["problem"] = str(err)
        try:
            out["preview"] = self.preview(entry, en, half)
        except ValueError:
            pass
        if raw is not None:
            out["widths"] = layout.line_widths(raw)
            out["bytes"] = len(raw) + (1 if entry["cmd"] is None else 0)
            if entry["cmd"] is None:
                out["capacity"] = entry["capacity"]
            if windows.classify(entry) == "dialogue":
                out["pages"] = math.ceil(len(out["widths"]) / layout.ROWS_PER_PAGE)
        out["flags"] = qc_table.text_flags(ja, en, out["problem"], limit.startswith("label only"))
        return out

    def check_image(self, sid, en):
        name, off = images.parse_id(sid)
        out = {"en_empty": not en, "problem": None, "flags": [], "status": "translated" if en else "untranslated"}
        if not en:
            return out
        t = tim.parse(self.res, off)
        try:
            t.pixels = images.render(t, en)
            out["image"] = qc_table.data_uri(tim.to_png(t, 1))
            out["fit"] = "fits"
        except (ValueError, KeyError, IndexError) as err:
            out["problem"] = out["fit"] = str(err)
            out["flags"] = [("IMG-FIT", str(err))]
        if qc_table.JAPANESE.search(en):
            out["flags"].append(("JA-LEFT", ""))
        return out

    # ---- everything -------------------------------------------------------------------
    def apply_all(self):
        tr = self.csv_translations()
        return tr, insert_script.apply(sheets.EXTRACTED, tr)

    def area_labels(self, applied):
        bufs, _ = applied
        now = sheets.area_budgets(bytes(bufs["SCE.S"]), bytes(bufs["SLPS_021.07"]))
        labels = {}
        for sid, key in self.area_of.items():
            free = now[key][0]
            flag = " (OVER)" if free < 0 else " (tight)" if free < sheets.TIGHT else ""
            labels[sid] = f"area {key[1]}: {free} bytes free{flag}"
        return labels

    def rows(self):
        tr, applied = self.apply_all()
        rows = qc_table.build(tr, applied)
        labels = self.area_labels(applied)
        for r in rows:
            r["area"] = labels.get(r["id"], "")
        return rows, tr

    def check_all(self):
        tr, applied = self.apply_all()
        rows = qc_table.build(tr, applied)
        labels = self.area_labels(applied)
        return {"rows": {r["id"]: {"flags": r["flags"], "status": r["status"], "area": labels.get(r["id"], ""),
                                   "fit": r.get("fit", "")} for r in rows},
                "problems": len(applied[1])}

    def save(self, sid, en, base):
        if sid not in self.meta:
            raise KeyError(sid)
        save_cell(self.dir / f"{self.meta[sid][0]}.csv", sid, en, base)
        return self.check_one(sid, en)

    def do_import(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sheets.import_()
        self.json_tr = insert_script.load_translations([sheets.TRANSLATIONS])
        return buf.getvalue().strip()


def make_handler(review, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def reply(self, code, obj):
            self.send(code, json.dumps(obj, ensure_ascii=False))

        def host_ok(self):
            return self.headers.get("Host", "").rsplit(":", 1)[0] in ("127.0.0.1", "localhost")

        def do_GET(self):
            if not self.host_ok():
                return self.send(403, "forbidden", "text/plain")
            if self.path != "/":
                return self.send(404, "not found", "text/plain")
            rows, tr = review.rows()
            diff = review.differing(tr)
            page = qc_table.render_page(rows, {"token": token, "differing": len(diff)})
            self.send(200, page, "text/html; charset=utf-8")

        def do_POST(self):
            if not self.host_ok() or self.headers.get("X-Token") != token:
                return self.reply(403, {"error": "forbidden"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self.reply(413, {"error": "too large"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                sid = body.get("id")
                if self.path == "/api/check":
                    return self.reply(200, review.check_one(sid, body.get("en", "")))
                if self.path == "/api/save":
                    return self.reply(200, review.save(sid, body.get("en", ""), body.get("base", "")))
                if self.path == "/api/checkall":
                    return self.reply(200, review.check_all())
                if self.path == "/api/import":
                    return self.reply(200, {"output": review.do_import()})
                self.reply(404, {"error": "not found"})
            except Conflict as err:
                self.reply(409, {"error": "this cell changed on disk since the page loaded; "
                                          "reload the page. On disk: " + json.dumps(str(err), ensure_ascii=False)})
            except KeyError as err:
                self.reply(404, {"error": f"id not in a sheet: {err}"})
            except PermissionError:
                self.reply(423, {"error": "the sheet is locked (open in Excel?); close it and save again"})
            except Exception as err:        # keep the page alive; show what broke
                self.reply(500, {"error": f"{type(err).__name__}: {err}"})

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="open the page in the default browser")
    args = ap.parse_args()
    review = Review()
    token = secrets.token_urlsafe(16)
    server = HTTPServer(("127.0.0.1", args.port), make_handler(review, token))
    url = f"http://127.0.0.1:{args.port}/"
    print(f"review page: {url}   (Ctrl+C to stop; edits are written to sheets/*.csv)")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
