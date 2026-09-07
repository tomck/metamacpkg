"""Human-readable migration reports: stats, gaps, and the review queue."""
import csv
import sqlite3
from pathlib import Path

from .normalize import homepage_domain

ROOT = Path(__file__).resolve().parent.parent

PAIR_TITLES = {
    ("brew-formula", "macports"): "Homebrew formulae -> MacPorts ports",
    ("brew-cask", "macports"): "Homebrew casks -> MacPorts ports",
    ("brew-formula", "fink"): "Homebrew formulae -> Fink packages",
    ("brew-cask", "fink"): "Homebrew casks -> Fink packages",
    ("macports", "fink"): "MacPorts ports -> Fink packages",
    ("fink", "macports"): "Fink packages -> MacPorts ports",
}


def generate(db_path=None, out_path=None):
    from .db import PAIRS, slug
    db_path = db_path or (ROOT / "data" / "catalog.sqlite")
    con = sqlite3.connect(db_path)
    lines = ["# metamacpkg migration report", ""]
    for frm, to in PAIRS:
        a, b = slug(*frm), slug(*to)
        title = PAIR_TITLES[(a, b)]
        rows = con.execute(
            "SELECT from_name,to_name,confidence,method,status,evidence,"
            "alternatives FROM relations WHERE from_manager=? AND from_type=?"
            " AND to_manager=? AND to_type=? ORDER BY from_name",
            (frm[0], frm[1], to[0], to[1])).fetchall()
        n_conf = sum(1 for r in rows if r[4] == "confident")
        n_hit = sum(1 for r in rows if r[4] == "near-hit")
        n_rev = sum(1 for r in rows if r[4] == "needs-review")
        n_mis = sum(1 for r in rows if r[4] == "missing")
        lines += [f"## {title}",
                  f"{len(rows)} source packages: "
                  f"{n_conf} confident, {n_hit} near-hit, "
                  f"{n_rev} need review, {n_mis} missing.",
                  ""]
        near = [r for r in rows if r[4] == "near-hit"]
        if near:
            lines.append("<details><summary>"
                         f"Near-hit suggestions ({len(near)})</summary>")
            lines.append("")
            for r in near[:200]:
                lines.append(f"- `{r[0]}` -> `{r[1]}` ({r[5]})")
            if len(near) > 200:
                lines.append(f"- ... and {len(near) - 200} more "
                             f"(see mappings/{a}-to-{b}.csv)")
            lines += ["", "</details>", ""]
        missing = [r for r in rows if r[4] == "missing"]
        if missing:
            lines.append("<details><summary>"
                         f"Missing in {b} ({len(missing)})</summary>")
            lines.append("")
            for r in missing[:200]:
                lines.append(f"- `{r[0]}`")
            if len(missing) > 200:
                lines.append(f"- ... and {len(missing) - 200} more "
                             f"(see mappings/{a}-to-{b}.csv)")
            lines += ["", "</details>", ""]
    lines += ["## Same name, different homepage (churn queue)",
              "",
              "Confident `exact`/`normalized`/`version` rows whose homepages live on "
              "different domains. Most are benign (project site vs GitHub "
              "repo), but this list is where same-name collisions hide "
              "(e.g. `anubis`, `dash`, `dune`). Work it with:",
              "",
              "    python3 -m metamacpkg.cli lookup <manager> <type> <name>",
              "",
              "and record verdicts in `curated/no_equivalent.yaml`.",
              ""]
    flag = con.execute(
        "SELECT r.from_manager, r.from_type, r.from_name, r.to_name,"
        " s.homepage, t.homepage FROM relations r"
        " JOIN packages s ON s.manager=r.from_manager AND s.type=r.from_type"
        "  AND s.name=r.from_name"
        " JOIN packages t ON t.manager=r.to_manager AND t.type=r.to_type"
        "  AND t.name=r.to_name"
        " WHERE r.status='confident'"
        " AND r.method IN ('exact','normalized','version')"
        " ORDER BY r.from_name").fetchall()
    n = 0
    for fm, ft, fn, tn, sh, th in flag:
        ds, dt = homepage_domain(sh), homepage_domain(th)
        if ds and dt and ds != dt:
            lines.append(f"- `{fn}` ({fm}/{ft} -> {tn}): {ds} vs {dt}")
            n += 1
    lines += ["", f"{n} rows to review.", ""]
    con.close()
    out_path = out_path or (ROOT / "mappings" / "REPORT.md")
    out_path.write_text("\n".join(lines))
    print(f"report -> {out_path}")
    return out_path


def review_queue(map_csv, limit=30):
    """Print the top needs-review rows with evidence (the churn list)."""
    with open(map_csv) as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "needs-review"]
    print(f"{len(rows)} needs-review rows in {map_csv}")
    for r in rows[:limit]:
        print(f"\n### {r['source']}  [{r['method']}]")
        print(f"    evidence: {r['evidence']}")
        if r["alternatives"]:
            print(f"    lookalikes: {r['alternatives']}")
    if len(rows) > limit:
        print(f"\n... and {len(rows) - limit} more")
    return rows
