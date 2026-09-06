"""Export review-site data: per-pair needs-review queues + name index.

Reads data/raw/ snapshots and mappings/*.csv, writes docs/data/.
Queue files are committed so GitHub Pages serves them with zero build.
"""
import csv
import json
import re
from pathlib import Path

from .db import PAIRS, load_raw, slug

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "data"


def target_key(pair_from, pair_to):
    return pair_to


def export_web(pairs=None, outdir=DOCS, limit_per_pair=0):
    groups = load_raw()
    by_key = {(r["manager"], r["type"], r["name"]): r
              for ps in groups.values() for r in ps}
    names = [{"n": r["name"], "m": r["manager"], "t": r["type"]}
             for ps in groups.values() for r in ps]
    names.sort(key=lambda x: (x["n"].lower(), x["m"], x["t"]))
    outdir.mkdir(parents=True, exist_ok=True)
    shards: dict = {}
    for e in names:
        ch = (re.sub(r"[^a-z0-9]", "", e["n"].lower())[:1] or "other")
        if ch.isdigit():
            ch = "0-9"
        shards.setdefault(ch, []).append(e)
    idxdir = outdir / "names"
    idxdir.mkdir(exist_ok=True)
    for ch, entries in shards.items():
        (idxdir / f"{ch}.json").write_text(json.dumps(entries) + "\n")
    print(f"names: {len(names)} in {len(shards)} shards")

    wanted = set(pairs or [])
    made = {}
    for frm, to in PAIRS:
        key = f"{slug(*frm)}-to-{slug(*to)}"
        if wanted and key not in wanted:
            continue
        cards = []
        with open(ROOT / "mappings" / f"{key}.csv") as f:
            for r in csv.DictReader(f):
                if r["status"] != "needs-review":
                    continue
                src = by_key.get((frm[0], frm[1], r["source"]), {})
                likes = []
                for alt in (a.strip() for a in r["alternatives"].split(";")
                            if a.strip()):
                    t = by_key.get((to[0], to[1], alt), {})
                    likes.append({
                        "target": alt,
                        "desc": (t.get("desc") or "")[:400],
                        "homepage": t.get("homepage") or "",
                        "version": t.get("version") or "",
                    })
                cards.append({
                    "pair": key,
                    "source": r["source"],
                    "from": {"manager": frm[0], "type": frm[1]},
                    "to": {"manager": to[0], "type": to[1]},
                    "desc": (src.get("desc") or "")[:600],
                    "homepage": src.get("homepage") or "",
                    "version": src.get("version") or "",
                    "evidence": r["evidence"],
                    "lookalikes": likes[:8],
                })
                if limit_per_pair and len(cards) >= limit_per_pair:
                    break
        path = outdir / f"queue-{key}.json"
        path.write_text(json.dumps({"pair": key, "count": len(cards),
                                    "cards": cards}) + "\n")
        made[key] = len(cards)
        print(f"{key}: {len(cards)} cards -> {path.name}")
    return made
