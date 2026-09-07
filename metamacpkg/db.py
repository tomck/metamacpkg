"""Build the portable catalog: SQLite + JSON + reviewable mapping CSVs."""
import csv
import hashlib
import json
import sqlite3
from pathlib import Path

from . import match as m
from .curated import load_curated

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
MAPDIR = ROOT / "mappings"

SCHEMA = """
CREATE TABLE packages (
  manager TEXT NOT NULL, type TEXT NOT NULL, name TEXT NOT NULL,
  description TEXT, homepage TEXT, version TEXT,
  PRIMARY KEY (manager, type, name));
CREATE TABLE relations (
  from_manager TEXT NOT NULL, from_type TEXT NOT NULL, from_name TEXT NOT NULL,
  to_manager TEXT NOT NULL, to_type TEXT NOT NULL, to_name TEXT,
  confidence REAL NOT NULL, method TEXT NOT NULL, status TEXT NOT NULL,
  evidence TEXT, alternatives TEXT, catalog_version TEXT NOT NULL,
  PRIMARY KEY (from_manager, from_type, from_name, to_manager, to_type));
"""

STRONG_METHODS = ("curated", "exact", "normalized", "alias", "replaced-by",
                  "homepage", "version")


def validate_rows(rows):
    """Every automatic relationship needs a strong method and evidence."""
    errors = []
    for r in rows:
        if r["status"] == "confident":
            if r["method"] not in STRONG_METHODS:
                errors.append(f"{r['source']}: weak method {r['method']!r}")
            if not (r["evidence"] or "").strip():
                errors.append(f"{r['source']}: empty evidence")
        elif r["status"] == "near-hit":
            if r["method"] != "near-hit":
                errors.append(f"{r['source']}: near-hit with method "
                              f"{r['method']!r}")
            if not r["target"]:
                errors.append(f"{r['source']}: near-hit without a target")
            if not (r["evidence"] or "").strip():
                errors.append(f"{r['source']}: empty evidence")
    return errors

# Collapse guards: a source below its floor means a failed fetch, not a
# smaller ecosystem. Fail before writing anything.
COUNT_FLOORS = {("homebrew", "formula"): 7000, ("homebrew", "cask"): 5000,
                ("macports", "port"): 40000, ("fink", "package"): 8000}


def catalog_version(rawdir=RAW):
    """Deterministic version from snapshot provenance + curated inputs."""
    h = hashlib.sha1()
    prov = rawdir / "provenance.json"
    h.update(prov.read_bytes() if prov.exists() else b"")
    for name in ("relations.yaml", "no_equivalent.yaml", "aliases.yaml"):
        p = ROOT / "curated" / name
        h.update(p.read_bytes() if p.exists() else b"")
    date = "unknown"
    try:
        date = json.loads(prov.read_text())["fetched_at"][:10].replace("-", "")
    except Exception:
        pass
    return f"v{date}+{h.hexdigest()[:8]}"


# Directed pairs that get mapping tables. (from-tag, to-tag)
PAIRS = [
    (("homebrew", "formula"), ("macports", "port")),
    (("homebrew", "cask"), ("macports", "port")),
    (("homebrew", "formula"), ("fink", "package")),
    (("homebrew", "cask"), ("fink", "package")),
    (("macports", "port"), ("fink", "package")),
    (("fink", "package"), ("macports", "port")),
]


def load_raw(rawdir=RAW):
    groups = {}
    for path in sorted(rawdir.glob("*.json")):
        if path.name == "provenance.json":
            continue
        for rec in json.loads(path.read_text()):
            groups.setdefault((rec["manager"], rec["type"]), []).append(rec)
    return groups


def slug(manager, type_):
    return {"homebrew": {"formula": "brew-formula", "cask": "brew-cask"},
            "macports": {"port": "macports"},
            "fink": {"package": "fink"}}[manager][type_]


def build(rawdir=RAW, mapdir=MAPDIR, db_path=None, catalog_path=None,
          curated=None, check_sources=True):
    groups = load_raw(rawdir)
    curated = curated or load_curated()
    if check_sources:
        for key, floor in COUNT_FLOORS.items():
            n = len(groups.get(key, []))
            if n < floor:
                raise ValueError(
                    f"source {key} collapsed: {n} < floor {floor}")
    for key, pkgs in groups.items():
        names = [p["name"] for p in pkgs]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate identities in {key}")
    version = catalog_version(rawdir)
    all_pkgs = [p for ps in groups.values() for p in ps]

    relations = []
    tables = {}
    extra_aliases = {}
    for key, als in curated.aliases.items():
        try:
            mgr, typ, nm = key.split("/", 2)
        except ValueError:
            continue
        extra_aliases.setdefault((mgr, typ), {}).setdefault(nm, []).extend(
            als or [])
    for frm, to in PAIRS:
        sources = groups.get(frm, [])
        targets = groups.get(to, [])
        extra = extra_aliases.get(frm, {})
        if extra:
            sources = [dict(s, aliases=[*(s.get("aliases") or []),
                                        *extra.get(s["name"], [])])
                       for s in sources]
        ckey = f"{slug(*frm)}-to-{slug(*to)}"
        rows = m.match_all(sources, targets,
                           curated.relations.get(ckey, {}),
                           curated.no_equiv.get(ckey, {}))
        errors = validate_rows(rows)
        if errors:
            raise ValueError(f"weak automatic rows in {ckey}:\n" +
                             "\n".join(errors[:10]))
        tables[ckey] = rows
        for r in rows:
            relations.append({
                "from_manager": frm[0], "from_type": frm[1],
                "from_name": r["source"],
                "to_manager": to[0], "to_type": to[1],
                "to_name": r["target"], "confidence": r["confidence"],
                "method": r["method"], "status": r["status"],
                "evidence": r["evidence"], "alternatives": r["alternatives"],
                "catalog_version": version,
            })

    mapdir.mkdir(parents=True, exist_ok=True)
    for ckey, rows in tables.items():
        with open(mapdir / f"{ckey}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["source", "target", "confidence", "method",
                        "status", "evidence", "alternatives",
                        "catalog_version"])
            for r in rows:
                w.writerow([r["source"], r["target"] or "",
                            r["confidence"], r["method"], r["status"],
                            r["evidence"],
                            "; ".join(a["port"] for a in r["alternatives"]),
                            version])

    db_path = db_path or (ROOT / "data" / "catalog.sqlite")
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO packages VALUES (?,?,?,?,?,?)",
        [(p["manager"], p["type"], p["name"], p.get("desc", ""),
          p.get("homepage", ""), p.get("version", "")) for p in all_pkgs])
    con.executemany(
        "INSERT INTO relations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r["from_manager"], r["from_type"], r["from_name"],
          r["to_manager"], r["to_type"], r["to_name"], r["confidence"],
          r["method"], r["status"], r["evidence"],
          json.dumps(r["alternatives"]), r["catalog_version"])
         for r in relations])
    con.commit()
    con.close()

    catalog = {"catalog_version": version,
               "packages": len(all_pkgs),
               "relations": len(relations),
               "pairs": {ckey: _stats(rows)
                         for ckey, rows in tables.items()}}
    catalog_path = catalog_path or (ROOT / "data" / "catalog.json")
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n")
    print(f"version={version} packages={len(all_pkgs)} "
          f"relations={len(relations)} db={db_path.name}")
    for key, st in catalog["pairs"].items():
        print(f"  {key}: " + " ".join(f"{k}={v}" for k, v in st.items()))

    sums = []
    for name in sorted(p.name for p in mapdir.glob("*.csv")):
        digest = hashlib.sha256((mapdir / name).read_bytes()).hexdigest()
        sums.append(f"{digest}  {name}")
    (mapdir / "checksums.txt").write_text("\n".join(sums) + "\n")
    print(f"checksums -> {mapdir / 'checksums.txt'}")
    return catalog


def _stats(rows):
    out = {"total": len(rows)}
    for r in rows:
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out
