"""One Psy-Q object per function of decomp/src, made from the compiled C, to put into the PSYLINK link.

Usage: python -I tools/cobjs.py        (lists the functions and the symbols they need)

Each C file is compiled (cc_check.compile_c: CPPPSX -> gcc 2.8.1 -> ASPSX). Its `.text` is cut at the
function symbols, and every function becomes an object of its own (lnk.write_object) because the functions
of one file sit at different places of the EXE. The patch records are rewritten to refer to symbols by name:
calls inside the file (`.text + offset`) name the callee, the other references already name an extern or a
common symbol (the `gp` variables of the C, in .sbss).
Addresses of those names: functions are named after their address (or listed in decomp/functions.txt), the
rest is read back from the retail words (datamap.symbol_values), since the game's data is not linked from C yet.
"""
import glob
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cc_check
import datamap
import lnk

ROOT = cc_check.ROOT
EXE_BASE = cc_check.EXE_BASE


def sources():
    return sorted(glob.glob(str(ROOT / "decomp" / "src" / "*.c")))


def flags_of(src):
    m = re.search(r"cc-flags:[ \t]*(.+?)[ \t]*(\*/|$)", Path(src).read_text()[:400], re.M)
    return m.group(1) if m else cc_check.DEFAULT_FLAGS


def symbol_name(o, sid):
    name = o["xrefs"].get(sid) or o["sym_ids"].get(sid) or next((x[4] for x in o["xbss"] if x[1] == sid), None)
    if name is None:
        raise ValueError(f"patch refers to symbol id {sid}, which is not declared")
    return name


def rewrite(tree, o, tid, owner):
    """Patch expression with names instead of ids; `.text + n` becomes the function that contains n."""
    kind = tree[0]
    if kind == "const":
        return tree
    if kind == "sym":
        return ("sym", symbol_name(o, tree[1]))
    if kind == "sec":
        if o["sections"][tree[2]][0] != ".text":
            raise ValueError(f"patch refers to {o['sections'][tree[2]][0]}, which the C objects do not provide yet")
        return owner(0)
    if kind == 0x2C:
        a, b = tree[1], tree[2]
        if a[0] == "const" and b[0] == "sec" and o["sections"][b[2]][0] == ".text":
            return owner(a[1])
        if b[0] == "const" and a[0] == "sec" and o["sections"][a[2]][0] == ".text":
            return owner(b[1])
    return (kind, rewrite(tree[1], o, tid, owner), rewrite(tree[2], o, tid, owner))


def names_in(tree):
    if tree[0] == "sym":
        return {tree[1]}
    if tree[0] in ("const", "sec"):
        return set()
    return names_in(tree[1]) | names_in(tree[2])


def build(cc1="2.8.1"):
    """Return (functions, values): functions = [{name, addr, size, obj, source}], values = {name: set of addresses}
    read from the retail words for the names that are not functions."""
    cc_check.COMPILER = cc1
    exe = cc_check.EXE.read_bytes()
    table = cc_check.functions_table()
    funcs, values = [], {}
    for src in sources():
        o = cc_check.compile_c(Path(src), flags_of(src))
        tid = next(i for i, s in o["sections"].items() if s[0] == ".text")
        code = bytes(o["sections"][tid][1])
        starts = sorted((off, name) for name, (sec, off) in o["xdefs"].items() if sec == tid)
        spans = {name: (st, starts[i + 1][0] if i + 1 < len(starts) else len(code)) for i, (st, name) in enumerate(starts)}

        def owner(off):
            name, (st, _) = next((n, s) for n, s in spans.items() if s[0] <= off < s[1])
            return ("sym", name) if off == st else (0x2C, ("const", off - st), ("sym", name))

        def exe_offset(off):
            name, (st, _) = next((n, s) for n, s in spans.items() if s[0] <= off < s[1])
            return table[name] - EXE_BASE + off - st

        known = {n for n in spans if n in table}
        section_at = {tid: exe_offset}
        # patch_values reads every text patch, so only offer it the functions that have an address
        sub = dict(o, patch_exprs=[p for p in o["patch_exprs"] if any(spans[n][0] <= p[1] < spans[n][1] for n in known)])
        for name, vals in datamap.symbol_values(sub, 0x80000000, exe, section_at).items():
            values.setdefault(name, set()).update(vals)
        for name, (st, en) in spans.items():
            if name not in table:
                continue
            patches = []
            for sec, off, tag, tree in o["patch_exprs"]:
                if sec == tid and st <= off < en:
                    patches.append((off - st, tag, rewrite(tree, o, tid, owner)))
            refs = sorted(set().union(*(names_in(t) for _, _, t in patches)) if patches else set())
            obj = lnk.write_object({".text": code[st:en]}, symbols={name: (".text", 0)}, xrefs=refs, patches=patches)
            funcs.append(dict(name=name, addr=table[name], size=en - st, obj=obj, source=Path(src).name, refs=refs))
    return funcs, values


def address_of(name, values, table):
    """RAM address of a name the C refers to, or None."""
    if name in table:
        return table[name]
    m = re.fullmatch(r"fn_([0-9A-F]{8})", name)
    if m:
        return int(m.group(1), 16)
    if name in values:
        return min(values[name])
    return None


if __name__ == "__main__":
    funcs, values = build()
    table = cc_check.functions_table()
    names = {r for f in funcs for r in f["refs"]} - {f["name"] for f in funcs}
    print(f"{len(funcs)} function objects, {len(names)} external names")
    missing = sorted(n for n in names if address_of(n, values, table) is None)
    print("no address from the retail words yet:", missing)
