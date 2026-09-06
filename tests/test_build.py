"""Integration: curated decisions must reach the mapping CSVs.

Regression test for the pair-key bug where db.build looked up curated
entries under a tuple key while load_curated stores "a-to-b" strings,
silently dropping every curated row.
"""
import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from metamacpkg.curated import Curated
from metamacpkg.db import build


def rec(manager, type_, name, **kw):
    r = {"manager": manager, "type": type_, "name": name, "aliases": [],
         "oldnames": [], "desc": "d", "homepage": "", "version": "",
         "replaced_by": None, "categories": [], "active": True}
    r.update(kw)
    return r


class TestBuildCurated(unittest.TestCase):
    def test_curated_reaches_csv_and_sqlite(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        raw = root / "raw"
        raw.mkdir()
        (raw / "brew.json").write_text(json.dumps([
            rec("homebrew", "formula", "gtk+3"),
            rec("homebrew", "formula", "anubis",
                desc="scraper shield", homepage="https://x.example/"),
        ]) + "\n")
        (raw / "mp.json").write_text(json.dumps([
            rec("macports", "port", "gtk3"),
            rec("macports", "port", "anubis",
                desc="mail processor", homepage="https://y.example/"),
        ]) + "\n")
        (raw / "fink.json").write_text(json.dumps([
            rec("fink", "package", "anubis"),
        ]) + "\n")
        cur = Curated()
        cur.no_equiv = {"brew-formula-to-macports":
                        {"anubis": "different program"}}
        maps = root / "mappings"
        dbp = root / "catalog.sqlite"
        build(rawdir=raw, mapdir=maps, db_path=dbp,
              catalog_path=root / "catalog.json", curated=cur)
        rows = {r["source"]: r for r in
                csv.DictReader(open(maps / "brew-formula-to-macports.csv"))}
        self.assertEqual(rows["gtk+3"]["target"], "gtk3")
        self.assertEqual(rows["gtk+3"]["status"], "confident")
        self.assertEqual(rows["anubis"]["status"], "missing")
        self.assertEqual(rows["anubis"]["method"], "curated")
        con = sqlite3.connect(dbp)
        got = con.execute(
            "SELECT status FROM relations WHERE from_name='anubis'"
            " AND to_manager='macports'").fetchone()
        con.close()
        self.assertEqual(got[0], "missing")
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
