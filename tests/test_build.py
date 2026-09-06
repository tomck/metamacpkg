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
              catalog_path=root / "catalog.json", curated=cur,
              check_sources=False)
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


class TestRoundTripAndValidation(unittest.TestCase):
    def test_csv_sqlite_agree_and_strong(self):
        import csv as _csv
        from metamacpkg.db import build as _build, catalog_version, validate_rows
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        raw = root / "raw"
        raw.mkdir()
        (raw / "brew.json").write_text(json.dumps([
            rec("homebrew", "formula", "wget"),
            rec("homebrew", "formula", "zzz-missing"),
        ]) + "\n")
        (raw / "mp.json").write_text(json.dumps([
            rec("macports", "port", "wget"),
        ]) + "\n")
        (raw / "fink.json").write_text(json.dumps([]) + "\n")
        maps = root / "mappings"
        dbp = root / "catalog.sqlite"
        _build(rawdir=raw, mapdir=maps, db_path=dbp,
               catalog_path=root / "catalog.json", curated=Curated(),
               check_sources=False)
        csv_rows = list(_csv.DictReader(
            open(maps / "brew-formula-to-macports.csv")))
        con = sqlite3.connect(dbp)
        db_rows = con.execute(
            "SELECT from_name, COALESCE(to_name,''), status, method,"
            " catalog_version FROM relations"
            " WHERE from_manager='homebrew' AND to_manager='macports'").fetchall()
        con.close()
        self.assertEqual(
            {(r["source"], r["target"], r["status"], r["method"],
              r["catalog_version"]) for r in csv_rows},
            {(n, t, s, m, v) for n, t, s, m, v in db_rows})
        versions = {r[4] for r in db_rows}
        self.assertEqual(len(versions), 1)
        self.assertEqual(validate_rows(csv_rows), [])
        weak = [dict(csv_rows[0], method="fuzzy")]
        self.assertEqual(len(validate_rows(weak)), 1)
        noev = [dict(csv_rows[0], evidence="  ")]
        self.assertEqual(len(validate_rows(noev)), 1)
        v1, v2 = catalog_version(raw), catalog_version(raw)
        self.assertEqual(v1, v2)
        self.assertRegex(v1, r"^v[0-9a-z+]+$")
        self.assertTrue((maps / "checksums.txt").exists())
        tmp.cleanup()

    def test_two_accepts_per_file_survive_reload_and_build(self):
        """Luna's regression test: two accepted decisions for the same pair
        must both survive reload and the next build — for relations and
        no-equivalents. This is the exact curated-loss failure mode."""
        import tempfile as _tf
        from metamacpkg.curated import load_curated
        from metamacpkg.db import build as _build
        from metamacpkg.triage import append_no_equivalent, append_relation
        tmp = _tf.TemporaryDirectory()
        root = Path(tmp.name)
        curdir = root / "curated"
        curdir.mkdir()
        pair = "brew-formula-to-macports"
        append_relation(pair, "s1", "t1", "first", curdir=curdir)
        append_relation(pair, "s1b", "t1b", "second", curdir=curdir)
        append_no_equivalent(pair, "s3", "gone1", curdir=curdir)
        append_no_equivalent(pair, "s3b", "gone2", curdir=curdir)
        cur = load_curated(curdir)
        self.assertEqual(set(cur.relations[pair]), {"s1", "s1b"})
        self.assertEqual(set(cur.no_equiv[pair]), {"s3", "s3b"})
        raw = root / "raw"
        raw.mkdir()
        (raw / "brew.json").write_text(json.dumps([
            rec("homebrew", "formula", "s1"),
            rec("homebrew", "formula", "s1b"),
            rec("homebrew", "formula", "s3"),
            rec("homebrew", "formula", "s3b"),
        ]) + "\n")
        (raw / "mp.json").write_text(json.dumps([
            rec("macports", "port", "t1"),
            rec("macports", "port", "t1b"),
        ]) + "\n")
        (raw / "fink.json").write_text(json.dumps([]) + "\n")
        maps = root / "mappings"
        _build(rawdir=raw, mapdir=maps, db_path=root / "c.sqlite",
               catalog_path=root / "c.json", curated=cur,
               check_sources=False)
        import csv as _csv
        rows = {r["source"]: r for r in _csv.DictReader(
            open(maps / "brew-formula-to-macports.csv"))}
        for s, t in (("s1", "t1"), ("s1b", "t1b")):
            self.assertEqual((rows[s]["target"], rows[s]["method"],
                              rows[s]["status"]), (t, "curated", "confident"))
        for s in ("s3", "s3b"):
            self.assertEqual((rows[s]["method"], rows[s]["status"]),
                             ("curated", "missing"))
        tmp.cleanup()

    def test_collapsed_source_fails(self):
        import tempfile as _tf
        from metamacpkg.db import build as _build
        tmp = _tf.TemporaryDirectory()
        root = Path(tmp.name)
        raw = root / "raw"
        raw.mkdir()
        (raw / "brew.json").write_text(json.dumps([
            rec("homebrew", "formula", "wget")]) + "\n")
        with self.assertRaises(ValueError):
            _build(rawdir=raw, mapdir=root / "m",
                   db_path=root / "c.sqlite",
                   catalog_path=root / "c.json", curated=Curated())
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
