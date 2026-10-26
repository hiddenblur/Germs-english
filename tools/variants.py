"""Search source variants of a function until one compiles to the retail bytes (gcc 2.8.1 -O2 -G8).

Used from small driver scripts: build a list of candidate C sources (often a product of choices:
statement order, loop form, pointer or global access, ...) and call `search`.

    import variants
    hits = variants.search("fn_801A0690", 0x801A0690, header, candidates)   # candidates: {label: source}

Runs candidates in parallel; returns the labels that match (exact), and prints near misses (registers only).
"""
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cc_check

cc_check.COMPILER = "2.8.1"


def check(name, addr, source, flags="-O2"):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v.c"
        path.write_text(source)
        cc_check.functions_table = lambda: {name: addr}
        try:
            rows = cc_check.compare(path, flags)
        except SystemExit:
            return False                           # compile error
    for n, a, words, ok, mine, theirs in rows:
        if n == name:
            return ok
    return False


def search(name, addr, header, candidates, workers=8, flags="-O2", verbose=True):
    labels = list(candidates)

    def one(label):
        return label, check(name, addr, header + candidates[label], flags)

    hits, near = [], []
    with ThreadPoolExecutor(workers) as ex:
        for label, ok in ex.map(one, labels):
            if ok is True:
                hits.append(label)
            elif ok == "regs":
                near.append(label)
    if verbose:
        print(f"{name}: {len(labels)} candidates, {len(hits)} exact, {len(near)} registers-only")
        for h in hits[:5]:
            print("  EXACT", h)
        for h in near[:3]:
            print("  regs ", h)
    return hits
