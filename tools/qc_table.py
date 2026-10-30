"""Quality-control review table of the whole script: Japanese and English side by side.

    python -I tools/qc_table.py          write sheets/qc/script_review.html and .csv

Run `sheets.py import` and `export` first so sheets/ is current. Read-only for translations/.
The output holds the game's Japanese script and artwork, so sheets/qc/ is gitignored (it sits
under sheets/): keep it local, never publish or commit it.

Rows: sce_00..sce_23, exe, res (text, from sheets/*.csv), then img (the text images in
sheets/img.csv plus the screens in translations/screens.json). Auto-flags:

    LONG         the inserter reports a line too wide / too many rows / too many bytes
    JA-LEFT      Japanese characters remain in the English
    PLACEHOLDER  %s/%d or {0}-{9} colour codes differ in count or order from the Japanese
    DOUBLE-SPACE two spaces in a row inside a line (leading indent is ignored)
    TRAILING-SPACE  a line ends with a space
    CHECK        any other problem `sheets.py check` reports for the string (area overflow...)
    IMG-FIT      an image's text does not fit in pixels (images only)
"""
import base64
import csv
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops the script dir
import images
import insert_script
import sheets
import tim

ROOT = sheets.ROOT
QC = sheets.SHEETS / "qc"
SCENES = [f"sce_{i:02d}" for i in range(24)]
ORDER = SCENES + ["exe", "res", "img"]
FLAGS = ["LONG", "JA-LEFT", "PLACEHOLDER", "DOUBLE-SPACE", "TRAILING-SPACE", "CHECK", "IMG-FIT"]
JAPANESE = re.compile(r"[぀-ヿ㐀-鿿＀-￯　-〿]")
PLACEHOLDERS = re.compile(r"%[sd]")
COLOURS = re.compile(r"\{(\d)\}")
TOO_BIG = re.compile(r"half-cells|rows|bytes|label is|lines")


def readable(text):
    """Display form: colour codes stay as {n}, no raw control characters, real newlines."""
    text = text.replace("\r\n", "\n")
    return "".join(c for c in text if c == "\n" or c >= " ")


def colours(text, label_only):
    """Colour codes in order. A label-only choice gets its {3}○ marker added by the inserter,
    so the marker is dropped from ja."""
    if label_only:
        text = re.sub(r"\{3\}○.*$", "", text, flags=re.S)
    return COLOURS.findall(text)


def text_flags(ja, en, problem, label_only=False):
    """Auto-flags for a translated text row: [(code, detail)]."""
    flags = []
    if problem:
        flags.append(("LONG", problem) if TOO_BIG.search(problem) and "free space" not in problem
                     else ("CHECK", problem))
    if JAPANESE.search(en):
        flags.append(("JA-LEFT", "".join(sorted(set(JAPANESE.findall(en))))[:20]))
    if PLACEHOLDERS.findall(ja) != PLACEHOLDERS.findall(en):
        flags.append(("PLACEHOLDER", f"ja {PLACEHOLDERS.findall(ja)} en {PLACEHOLDERS.findall(en)}"))
    elif colours(ja, label_only) != colours(en, False):
        flags.append(("PLACEHOLDER", f"colours ja {colours(ja, label_only)} en {colours(en, False)}"))
    lines = en.split("\n")
    if any("  " in ln.lstrip(" ") for ln in lines):
        flags.append(("DOUBLE-SPACE", ""))
    if any(ln.endswith(" ") for ln in lines):
        flags.append(("TRAILING-SPACE", ""))
    return flags


def status_of(ja, en):
    if not en:
        return "untranslated"
    return "identical" if en == ja else "translated"


def text_rows(problems):
    rows = []
    for group in SCENES + ["exe", "res"]:
        with open(sheets.SHEETS / f"{group}.csv", encoding="utf-8-sig", newline="") as f:
            for n, r in enumerate(csv.DictReader(f), 1):
                ja, en = readable(r["ja"]), readable(r["en"])
                status = status_of(ja, en)
                flags = text_flags(ja, en, problems.get(r["id"]), r["limit"].startswith("label only")) if en else []
                rows.append(dict(scene=group, row=n, id=r["id"], window=r["window"], limit=r["limit"],
                                 ja=ja, en=en, status=status, flags=flags, kind="text"))
    return rows


def data_uri(png):
    return "data:image/png;base64," + base64.b64encode(png).decode()


def image_rows(problems, bufs, tr):
    """Rows for img.csv plus the screens; thumbnails are the original and the final image.
    tr is {id: (text or {"regions": ...}, half)} as insert_script.load_translations gives."""
    ids, kinds = [], {}
    res = (sheets.EXTRACTED / "files" / "RES.R").read_bytes()
    for sid, kind, _ in images.text_images(res):
        ids.append(sid)
        kinds[sid] = (kind, images.limit_text(kind))
    for sid, (v, _) in tr.items():
        if isinstance(v, dict) and "regions" in v:
            ids.append(sid)
            kinds[sid] = ("screen", v.get("note", ""))
    rows = []
    for n, sid in enumerate(ids, 1):
        name, off = images.parse_id(sid)
        orig = tim.parse((sheets.EXTRACTED / "files" / name).read_bytes(), off)
        final = tim.parse(bytes(bufs[name]), off)
        v = tr.get(sid, ("", True))[0]
        en = "\n".join(r["text"] for r in v["regions"]) if isinstance(v, dict) else readable(v)
        problem = problems.get(sid)
        flags = [("IMG-FIT", problem)] if problem else []
        if en and JAPANESE.search(en):
            flags.append(("JA-LEFT", ""))
        kind, limit = kinds[sid]
        rows.append(dict(scene="img", row=n, id=sid, window=kind, limit=limit, ja="", en=en,
                         status="translated" if en else "untranslated", flags=flags, kind="image",
                         editable=kind != "screen",
                         fit=problem or ("fits" if en else "-"),
                         orig=data_uri(tim.to_png(orig, 1)),
                         new=data_uri(tim.to_png(final, 1)) if en else ""))
    return rows


def write_csv(rows, path):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scene", "row", "id", "window", "limit", "ja", "en", "status", "flags", "flag_detail", "image_fit"])
        for r in rows:
            ja = r["ja"] if r["kind"] == "text" else f"(image) sheets/images/{r['id'].replace('@', '_')}.png"
            w.writerow([r["scene"], r["row"], r["id"], r["window"], r["limit"], ja, r["en"], r["status"],
                        " ".join(c for c, _ in r["flags"]), "; ".join(d for _, d in r["flags"] if d),
                        r.get("fit", "")])


def summary(rows):
    per_scene = {s: Counter() for s in ORDER}
    per_flag, per_status = Counter(), Counter()
    for r in rows:
        c = per_scene[r["scene"]]
        c["total"] += 1
        c["translated"] += r["status"] != "untranslated"
        c["flagged"] += bool(r["flags"])
        per_status[r["status"]] += 1
        for code, _ in r["flags"]:
            per_flag[code] += 1
    return per_scene, per_flag, per_status


def render_page(rows, live=None):
    """The review page. live=None gives the static file; a dict ({"token": ...}) turns on editing."""
    per_scene, per_flag, per_status = summary(rows)
    payload = {"rows": rows, "scenes": ORDER, "flags": FLAGS,
               "summary": {"scene": {s: dict(c) for s, c in per_scene.items()},
                           "flag": dict(per_flag), "status": dict(per_status)}}
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    mode = json.dumps(live).replace("</", "<\\/")
    return PAGE.replace("/*DATA*/", blob).replace("/*LIVE*/null", mode)


def write_html(rows, path):
    Path(path).write_text(render_page(rows), encoding="utf-8")


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Germs script review</title>
<style>
:root{--bg:#fff;--fg:#1c1c1e;--mut:#6b6b70;--line:#d8d8dc;--head:#f1f1f4;--acc:#2255cc;--bad:#c62828;--ok:#2e7d32;--hl:#fff3b0}
@media (prefers-color-scheme:dark){:root{--bg:#18181b;--fg:#e8e8ea;--mut:#9a9aa2;--line:#3a3a40;--head:#25252a;--acc:#7ea2ff;--bad:#ff7b72;--ok:#6fcf7a;--hl:#5a4d00}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}
header{padding:12px 16px;border-bottom:1px solid var(--line)}
h1{font-size:18px;margin:0 0 6px}
.sum{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
.chip{border:1px solid var(--line);border-radius:12px;padding:1px 8px;cursor:pointer;background:var(--head);font-size:12px}
.chip b{font-weight:600}.chip.on{outline:2px solid var(--acc)}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:8px}
select,input,button,textarea{font:inherit;color:inherit;background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:3px 6px}
table{border-collapse:collapse;width:100%;table-layout:fixed}
thead th{position:sticky;top:0;background:var(--head);z-index:2;text-align:left;border-bottom:2px solid var(--line);padding:6px}
td{vertical-align:top;border-bottom:1px solid var(--line);padding:6px;overflow-wrap:anywhere}
col.c1{width:120px}col.c2{width:130px}col.c3{width:36%}col.c4{width:36%}col.c5{width:150px}
.t{white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;font-size:13px}
.c{color:var(--acc);font-size:10px;vertical-align:super}
.id{font-family:ui-monospace,Consolas,monospace;font-size:12px}
.m{color:var(--mut);font-size:12px}
.flag{display:inline-block;background:var(--bad);color:#fff;border-radius:3px;padding:0 5px;margin:1px 2px 1px 0;font-size:11px}
.st-untranslated{color:var(--bad)}.st-identical{color:#b26a00}
tr.q-ok{background:color-mix(in srgb,var(--ok) 12%,transparent)}
tr.q-issue{background:color-mix(in srgb,var(--bad) 14%,transparent)}
mark{background:var(--hl);color:inherit}
.imgs{display:flex;gap:8px;flex-wrap:wrap}.imgs figure{margin:0}
.imgs img{image-rendering:pixelated;max-width:100%;width:360px;border:1px solid var(--line)}
.imgs figcaption{font-size:11px;color:var(--mut)}
textarea{width:100%;box-sizing:border-box;margin-top:4px;height:3.2em}
textarea.ed{height:auto;min-height:5em;font-family:ui-monospace,Consolas,monospace;font-size:13px;margin-top:0}
textarea.dirty{outline:2px solid #e0a000}
.res{font-size:12px;margin-top:4px}.res .bad{color:var(--bad)}.res .good{color:var(--ok)}
pre.prev{margin:4px 0 0;padding:4px 6px;background:var(--head);border:1px solid var(--line);font-size:12px;white-space:pre-wrap}
pre.prev:empty{display:none}
button.save{margin-top:4px}
#toast{position:fixed;right:16px;bottom:16px;max-width:min(420px,calc(100vw - 32px));padding:10px 14px;border-radius:6px;background:var(--ok);color:#fff;font-size:13px;box-shadow:0 2px 10px rgba(0,0,0,.35);opacity:0;transform:translateY(8px);transition:opacity .2s,transform .2s;pointer-events:none;z-index:10}
#toast.show{opacity:1;transform:none}#toast.err{background:var(--bad)}
@media (max-width:800px){col.c1,col.c2{width:90px}}
</style></head><body>
<header>
<h1>Germs: Nerawareta Machi - script review</h1>
<div class="m">Local file: contains the game's Japanese script. Do not publish. QC marks are saved in this browser.</div>
<div id="sum"></div>
<div class="bar">
<select id="fScene"></select><select id="fStatus"></select><select id="fFlag"></select><select id="fQc"></select>
<input id="q" type="search" placeholder="Search id, Japanese, English, notes" size="34">
<button id="dl">Download notes (CSV)</button><button id="chk" hidden>Re-check all</button><button id="imp" hidden>Import to translations/</button><span id="count" class="m"></span><span id="msg" class="m"></span>
</div></header>
<table><colgroup><col class="c1"><col class="c2"><col class="c3"><col class="c4"><col class="c5"></colgroup>
<thead><tr><th>Scene / id</th><th>Window</th><th>Japanese</th><th>English</th><th>QC</th></tr></thead>
<tbody id="body"></tbody></table>
<div id="toast" role="status" aria-live="polite"></div>
<script>
const D=/*DATA*/;
const LIVE=/*LIVE*/null;
const drafts={},chkT={};
const rowOf=id=>D.rows.find(r=>r.id===id);
let toastT;
function toast(text,err){const t=$("toast");t.textContent=text;t.className="show"+(err?" err":"");
 clearTimeout(toastT);toastT=setTimeout(()=>{t.className=""},err?5000:2500)}
async function api(path,body){
 let r;try{r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-Token":LIVE.token},body:JSON.stringify(body||{})})}
 catch(e){return {error:"cannot reach the server (is qc_server.py still running?)",_status:0}}
 const j=await r.json().catch(()=>({error:"bad response from server"}));j._status=r.status;return j}
const flagsHtml=r=>r.flags.map(f=>`<span class="flag" title="${esc(f[1]||"")}">${f[0]}</span>`).join("");
const editable=r=>LIVE&&(r.kind==="text"||r.editable);
const KEY="germs-qc-v1";
let qc={};try{qc=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(qc))}catch(e){}}
const $=id=>document.getElementById(id);
const esc=s=>s.replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function fmt(s,term){let h=esc(s);if(term)h=h.replace(new RegExp(term.replace(/[.*+?^${}()|[\\]\\\\]/g,"\\\\$&").replace(/&/g,"&amp;"),"gi"),m=>"<mark>"+m+"</mark>");
 return h.replace(/\\{(\\d)\\}/g,'<span class="c">{$1}</span>')}
function opts(el,list){el.innerHTML=list.map(([v,l])=>`<option value="${v}">${l}</option>`).join("")}
opts($("fScene"),[["","All scenes"],...D.scenes.map(s=>[s,s])]);
opts($("fStatus"),[["","Any status"],["translated","translated"],["untranslated","untranslated"],["identical","identical to Japanese"]]);
opts($("fFlag"),[["","Any flag"],["ANY","Any flag set"],["NONE","No flags"],...D.flags.map(f=>[f,f])]);
opts($("fQc"),[["","Any QC mark"],["unmarked","unmarked"],["ok","OK"],["issue","issue"],["note","has note"]]);
function computeSummary(){
 const s={scene:{},flag:{},status:{}};
 for(const r of D.rows){const c=s.scene[r.scene]=s.scene[r.scene]||{total:0,translated:0,flagged:0};
  c.total++;if(r.status!=="untranslated")c.translated++;if(r.flags.length)c.flagged++;
  s.status[r.status]=(s.status[r.status]||0)+1;for(const f of r.flags)s.flag[f[0]]=(s.flag[f[0]]||0)+1}
 return s}
function renderSummary(){
 const s=computeSummary(),t=D.rows.length,tr=t-(s.status.untranslated||0);
 let h=`<div class="m"><b>${t}</b> rows, <b>${tr}</b> translated (${(100*tr/t).toFixed(1)}%), `+
  Object.entries(s.status).map(([k,v])=>`${v} ${k}`).join(", ")+`</div><div class="sum">`;
 h+=D.scenes.map(sc=>{const c=s.scene[sc]||{};return `<span class="chip" data-scene="${sc}"><b>${sc}</b> ${c.translated||0}/${c.total||0}`+(c.flagged?` · ${c.flagged} flagged`:"")+`</span>`}).join("");
 h+=`</div><div class="sum">`+Object.entries(s.flag).map(([f,n])=>`<span class="chip" data-flag="${f}"><b>${f}</b> ${n}</span>`).join("")+`</div>`;
 $("sum").innerHTML=h;
 $("sum").onclick=e=>{const c=e.target.closest(".chip");if(!c)return;
  if(c.dataset.scene)$("fScene").value=c.dataset.scene;if(c.dataset.flag)$("fFlag").value=c.dataset.flag;draw()}}
function editBox(r){
 const v=drafts[r.id]!==undefined?drafts[r.id]:r.en;
 return `<textarea class="ed${v!==r.en?" dirty":""}" data-edit="1" spellcheck="false">${esc(v)}</textarea>`+
  `<button class="save" data-save="1">Save to sheet</button> <span class="res" data-res>${r.area?esc(r.area):""}</span><pre class="prev" data-prev></pre>`}
function cellEn(r,term){
 if(r.kind==="image"){return `<div class="imgs"><figure><img loading="lazy" src="${r.orig}"><figcaption>original</figcaption></figure>`+
  `<figure data-newfig ${r.new?"":"hidden"}><img loading="lazy" src="${r.new||""}"><figcaption>English, as built</figcaption></figure></div>`+
  `<div class="m" data-fit>fit: ${esc(r.fit)}</div>`+(editable(r)?editBox(r):(r.en?`<div class="t">${fmt(r.en,term)}</div>`:""))}
 if(editable(r))return editBox(r);
 return `<div class="t">${r.en?fmt(r.en,term):'<span class="m">(empty)</span>'}</div>`}
function draw(){
 const sc=$("fScene").value,st=$("fStatus").value,fl=$("fFlag").value,qf=$("fQc").value,term=$("q").value.trim().toLowerCase();
 const out=[];let n=0;
 for(const r of D.rows){
  const q=qc[r.id]||{};
  if(sc&&r.scene!==sc)continue;if(st&&r.status!==st)continue;
  if(fl==="ANY"&&!r.flags.length)continue;if(fl==="NONE"&&r.flags.length)continue;
  if(fl&&fl!=="ANY"&&fl!=="NONE"&&!r.flags.some(f=>f[0]===fl))continue;
  if(qf==="unmarked"&&q.s)continue;if((qf==="ok"||qf==="issue")&&q.s!==qf)continue;if(qf==="note"&&!q.n)continue;
  if(term&&!(r.id+" "+r.ja+" "+r.en+" "+(q.n||"")).toLowerCase().includes(term))continue;
  n++;
  out.push(`<tr data-id="${esc(r.id)}" class="${q.s?"q-"+q.s:""}"><td><b>${r.scene}</b> #${r.row}<div class="id">${esc(r.id)}</div>`+
   `<div class="st-${r.status}" data-st>${r.status}</div><div data-fl>${flagsHtml(r)}</div></td>`+
   `<td class="m">${esc(r.window)}<br>${esc(r.limit)}</td>`+
   `<td>${r.kind==="image"?'<span class="m">(image)</span>':`<div class="t">${fmt(r.ja,term)}</div>`}</td>`+
   `<td>${cellEn(r,term)}</td>`+
   `<td><label><input type="radio" name="r${n}" data-s="ok" ${q.s==="ok"?"checked":""}> OK</label> `+
   `<label><input type="radio" name="r${n}" data-s="issue" ${q.s==="issue"?"checked":""}> issue</label> `+
   `<a href="#" data-clear="1" class="m">clear</a><textarea placeholder="note" data-note="1">${esc(q.n||"")}</textarea></td></tr>`);
  if(n>=1500){break}}
 $("body").innerHTML=out.join("");
 $("count").textContent=`${n}${n>=1500?"+ (first 1500 shown; narrow the filter)":""} rows shown`}
$("body").addEventListener("change",e=>{const tr=e.target.closest("tr"),id=tr.dataset.id;const q=qc[id]=qc[id]||{};
 if(e.target.dataset.s){q.s=e.target.dataset.s;tr.className="q-"+q.s}
 if(e.target.dataset.note)q.n=e.target.value.trim();
 if(!q.s&&!q.n)delete qc[id];save()});
$("body").addEventListener("click",e=>{if(!e.target.dataset.clear)return;e.preventDefault();
 const tr=e.target.closest("tr");delete qc[tr.dataset.id];save();draw()});
for(const id of ["fScene","fStatus","fFlag","fQc"])$(id).onchange=draw;
let timer;$("q").oninput=()=>{clearTimeout(timer);timer=setTimeout(draw,200)};
$("dl").onclick=()=>{
 const byId=Object.fromEntries(D.rows.map(r=>[r.id,r]));
 const cell=s=>'"'+String(s).replace(/"/g,'""')+'"';
 const lines=["id,flag,note,auto_flags"];
 for(const [id,q] of Object.entries(qc))lines.push([id,q.s||"",q.n||"",(byId[id]?byId[id].flags.map(f=>f[0]).join(" "):"")].map(cell).join(","));
 const a=document.createElement("a");a.download="germs_qc_notes.csv";
 a.href=URL.createObjectURL(new Blob(["\\ufeff"+lines.join("\\r\\n")],{type:"text/csv"}));a.click()};
function patchRow(tr,r){
 const st=tr.querySelector("[data-st]");st.textContent=r.status;st.className="st-"+r.status;
 tr.querySelector("[data-fl]").innerHTML=flagsHtml(r);
 const fit=tr.querySelector("[data-fit]");if(fit)fit.textContent="fit: "+r.fit}
function showCheck(tr,j){
 const res=tr.querySelector("[data-res]"),prev=tr.querySelector("[data-prev]");
 if(j.error){res.innerHTML=`<span class="bad">${esc(j.error)}</span>`;return}
 let h=j.problem?`<span class="bad">${esc(j.problem)}</span>`:(j.en_empty?`<span class="m">empty: keeps the Japanese</span>`:`<span class="good">fits</span>`);
 h+=j.flags.map(f=>` <span class="flag" title="${esc(f[1]||"")}">${f[0]}</span>`).join("");
 if(j.widths)h+=` · widths ${j.widths.join(", ")}${j.pages?` · ${j.pages} page${j.pages>1?"s":""}`:""}`;
 if(j.bytes!==undefined)h+=` · ${j.bytes}${j.capacity?"/"+j.capacity:""} bytes`;
 const r=rowOf(tr.dataset.id);if(r.area)h+=` · ${esc(r.area)}`;
 res.innerHTML=h;prev.innerHTML=j.preview?fmt(j.preview,""):"";
 const fig=tr.querySelector("[data-newfig]");
 if(fig&&j.image){fig.hidden=false;fig.querySelector("img").src=j.image}}
async function checkRow(tr){
 const id=tr.dataset.id,en=drafts[id]!==undefined?drafts[id]:rowOf(id).en;
 showCheck(tr,await api("/api/check",{id,en}))}
async function saveRow(tr){
 const id=tr.dataset.id,r=rowOf(id),en=drafts[id]!==undefined?drafts[id]:r.en;
 const j=await api("/api/save",{id,en,base:r.en});
 if(j.error){$("msg").textContent="";showCheck(tr,j);toast("Not saved: "+j.error,true);return}
 r.en=en;r.status=j.status;r.flags=j.flags;if(j.fit)r.fit=j.fit;if(j.image)r.new=j.image;
 delete drafts[id];tr.querySelector("textarea.ed").classList.remove("dirty");
 patchRow(tr,r);showCheck(tr,j);renderSummary();
 $("msg").textContent="saved "+id+" to the sheet";
 toast(j.problem?"Saved "+id+" (with a problem: see the check line)":"Saved "+id+" to the sheet");
 clearTimeout(chkT.all);chkT.all=setTimeout(checkAll,600)}
async function checkAll(){
 $("msg").textContent="checking everything...";
 const j=await api("/api/checkall");
 if(j.error){$("msg").textContent=j.error;return}
 for(const r of D.rows){const u=j.rows[r.id];if(!u)continue;
  r.flags=u.flags;r.status=u.status;r.area=u.area||"";if(u.fit)r.fit=u.fit}
 for(const tr of document.querySelectorAll("#body tr")){patchRow(tr,rowOf(tr.dataset.id))}
 renderSummary();
 $("msg").textContent=j.problems?`check: ${j.problems} problem(s) in the sheets`:"check: no problems"}
if(LIVE){
 for(const id of ["chk","imp"])$(id).hidden=false;
 $("chk").onclick=checkAll;
 $("imp").onclick=async()=>{
  if(!confirm("Write translations/*.json from the sheets (same as sheets.py import)?"))return;
  const j=await api("/api/import");$("msg").textContent=j.error||j.output};
 $("body").addEventListener("input",e=>{
  if(!e.target.dataset.edit)return;const tr=e.target.closest("tr"),id=tr.dataset.id;
  drafts[id]=e.target.value;e.target.classList.toggle("dirty",drafts[id]!==rowOf(id).en);
  clearTimeout(chkT[id]);chkT[id]=setTimeout(()=>checkRow(tr),300)});
 $("body").addEventListener("click",e=>{if(e.target.dataset.save)saveRow(e.target.closest("tr"))});
 $("body").addEventListener("keydown",e=>{
  if(e.target.dataset.edit&&(e.ctrlKey||e.metaKey)&&e.key==="s"){e.preventDefault();saveRow(e.target.closest("tr"))}});
 window.addEventListener("beforeunload",e=>{
  if(Object.entries(drafts).some(([id,v])=>v!==rowOf(id).en)){e.preventDefault();e.returnValue=""}})}
renderSummary();draw();
if(LIVE&&LIVE.differing)$("msg").textContent=LIVE.differing+" string(s) differ between the sheets and translations/ (the sheets win here; Import writes translations/)";
</script></body></html>
"""


def build(tr=None, applied=None):
    """All review rows. tr defaults to translations/*.json; the live server passes the sheets' English."""
    if tr is None:
        tr = insert_script.load_translations([sheets.TRANSLATIONS])
    bufs, plist = applied or insert_script.apply(sheets.EXTRACTED, tr)
    problems = {}
    for where, msg in plist:
        problems[where] = f"{problems[where]}; {msg}" if where in problems else msg
    return text_rows(problems) + image_rows(problems, bufs, tr)


def main():
    rows = build()
    QC.mkdir(parents=True, exist_ok=True)
    write_csv(rows, QC / "script_review.csv")
    write_html(rows, QC / "script_review.html")
    per_scene, per_flag, per_status = summary(rows)
    print(f"{len(rows)} rows -> {QC}")
    print("status:", dict(per_status))
    print("flags: ", dict(per_flag))
    for s in ORDER:
        c = per_scene[s]
        print(f"  {s:7} {c['translated']:5}/{c['total']:<5} flagged {c['flagged']}")


if __name__ == "__main__":
    main()
