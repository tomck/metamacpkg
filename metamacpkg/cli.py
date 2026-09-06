"""metamacpkg: confident 3-way package maps for Homebrew/MacPorts/Fink."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def cmd_build(_):
    from .db import build
    build()


def cmd_lookup(args):
    con = sqlite3.connect(ROOT / "data" / "catalog.sqlite")
    con.row_factory = sqlite3.Row
    pkg = con.execute(
        "SELECT * FROM packages WHERE manager=? AND type=? AND name=?",
        (args.manager, args.type, args.name)).fetchone()
    if not pkg:
        print(f"no such package: {args.manager}/{args.type}/{args.name}",
              file=sys.stderr)
        return 1
    print(json.dumps(dict(pkg), indent=2))
    for r in con.execute(
            "SELECT * FROM relations WHERE from_manager=? AND from_type=?"
            " AND from_name=?", (args.manager, args.type, args.name)):
        print(json.dumps(dict(r), indent=2))


def cmd_search(args):
    con = sqlite3.connect(ROOT / "data" / "catalog.sqlite")
    like = f"%{args.text}%"
    for m, t, n, d in con.execute(
            "SELECT manager,type,name,description FROM packages "
            "WHERE name LIKE ? OR description LIKE ? LIMIT ?",
            (like, like, args.limit)):
        print(f"{m}/{t}/{n}: {(d or '')[:100]}")


def cmd_review(args):
    from .report import review_queue
    review_queue(ROOT / "mappings" / f"{args.pair}.csv", limit=args.limit)


def cmd_report(_):
    from .report import generate
    generate()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="metamacpkg")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="build sqlite + json + mapping CSVs")
    p = sub.add_parser("lookup", help="show a package and its relations")
    p.add_argument("manager", choices=["homebrew", "macports", "fink"])
    p.add_argument("type")
    p.add_argument("name")
    p = sub.add_parser("search", help="full-text search over names+descriptions")
    p.add_argument("text")
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("review", help="show the needs-review queue for a pair")
    p.add_argument("pair", help="e.g. brew-formula-to-macports")
    p.add_argument("--limit", type=int, default=30)
    sub.add_parser("report", help="regenerate mappings/REPORT.md")
    args = ap.parse_args(argv)
    return {"build": cmd_build, "lookup": cmd_lookup, "search": cmd_search,
            "review": cmd_review, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
