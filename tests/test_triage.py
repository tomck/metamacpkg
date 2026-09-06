"""Triage rules: maintainer auto-accept, community votes, dupes, conflicts."""
import unittest
from unittest import mock

from metamacpkg import triage as T
from metamacpkg.curated import (Curated, _parse_simple_yaml,
                                validate_curated)
from metamacpkg.triage import evaluate


class TestEvaluate(unittest.TestCase):
    def test_maintainer_author_accepts(self):
        v, _ = evaluate(author="tomck", maintainer="tomck", voters=set(),
                        proposal_exists=None)
        self.assertEqual(v, "accept")

    def test_maintainer_vote_accepts(self):
        v, _ = evaluate(author=" stranger ".strip(), maintainer="tomck",
                        voters={"tomck"}, proposal_exists=None)
        self.assertEqual(v, "accept")

    def test_two_community_votes_accept(self):
        v, _ = evaluate(author="a", maintainer="tomck", voters={"b", "c"},
                        proposal_exists=None)
        self.assertEqual(v, "accept")

    def test_one_vote_waits(self):
        v, reason = evaluate(author="a", maintainer="tomck", voters={"b"},
                             proposal_exists=None)
        self.assertEqual(v, "wait")
        self.assertIn("1/2", reason)

    def test_author_self_vote_does_not_count(self):
        v, _ = evaluate(author="a", maintainer="tomck", voters={"a"},
                        proposal_exists=None)
        self.assertEqual(v, "wait")

    def test_existing_proposal_is_duplicate(self):
        v, _ = evaluate(author="tomck", maintainer="tomck", voters=set(),
                        proposal_exists=("relation", "gtk3"))
        self.assertEqual(v, "duplicate")


class TestInsertEntry(unittest.TestCase):
    def test_appends_into_existing_list(self):
        text = ("# comment\npair-a:\n  - from: x\n    to: y\n"
                "pair-b:\n  - from: z\n")
        out = T.insert_entry(text, "pair-a", ["  - from: n\n"])
        self.assertEqual(out.count("pair-a:"), 1)
        self.assertIn("  - from: x\n    to: y\n  - from: n\n", out)
        self.assertIn("pair-b:\n  - from: z\n", out)
        # both entries survive a strict load
        cur = _parse_simple_yaml_for(out)
        self.assertEqual([e["from"] for e in cur["pair-a"]], ["x", "n"])

    def test_creates_missing_block(self):
        out = T.insert_entry("pair-a:\n  - from: x\n", "pair-b",
                             ["  - from: n\n"])
        self.assertIn("pair-b:\n  - from: n\n", out)

    def test_strict_parser_rejects_duplicate_keys(self):
        with self.assertRaises(ValueError):
            _parse_simple_yaml_for("pair-a:\n  - from: x\npair-a:\n  - from: y\n")


def _parse_simple_yaml_for(text):
    from metamacpkg.curated import _parse_simple_yaml
    return _parse_simple_yaml(text)


class TestValidate(unittest.TestCase):
    def test_duplicate_source_rejected(self):
        cur = Curated()
        cur.relations = {"p": {"s": {"target": "t", "comment": ""}}}
        texts = [("relations.yaml", "p:\n  - from: s\n  - from: s\n")]
        with self.assertRaises(ValueError):
            validate_curated(cur, texts)

    def test_cross_conflict_rejected(self):
        cur = Curated()
        cur.relations = {"p": {"s": {"target": "t", "comment": ""}}}
        cur.no_equiv = {"p": {"s": "gone"}}
        with self.assertRaises(ValueError):
            validate_curated(cur, [])

    def test_clean_passes(self):
        cur = Curated()
        cur.relations = {"p": {"s": {"target": "t", "comment": ""}}}
        self.assertTrue(validate_curated(cur, []))


class TestTargetExists(unittest.TestCase):
    def test_true(self):
        self.assertTrue(T.target_exists("macports", "port", "wget",
                                        opener=lambda req: True))

    def test_404_is_false(self):
        import urllib.error
        def gone(req):
            raise urllib.error.HTTPError(req.full_url, 404, "x", {}, None)
        self.assertFalse(T.target_exists("macports", "port", "zzz-gone",
                                         opener=gone))

    def test_unknown_manager_skips(self):
        self.assertTrue(T.target_exists("fink", "package", "whatever"))


class TestIdempotentDuplicate(unittest.TestCase):
    def test_repeat_duplicate_writes_nothing(self):
        from pathlib import Path
        d = Path("curated")
        before = {p.name: (d / p.name).read_text()
                  for p in [Path("relations.yaml"), Path("no_equivalent.yaml")]}
        issue = {"number": 999, "author": {"login": "someone"},
                 "labels": [],
                 "body": '<!-- metamacpkg-proposal {"pair": "brew-formula-to-macports", '
                         '"source": "anubis", "decision": "no-equivalent"} -->'}
        with mock.patch.object(T, "_gh") as gh, \
             mock.patch.object(T, "plus_one_voters", return_value=set()):
            self.assertEqual(T.triage_issue(issue)[0], "duplicate")
            self.assertEqual(T.triage_issue(issue)[0], "duplicate")
            self.assertTrue(gh.called)
        after = {(d / n).read_text() for n in before}
        self.assertEqual(set(before.values()), after)

    def test_stale_target_leaves_open(self):
        issue = {"number": 998, "author": {"login": "tomck"},
                 "labels": [],
                 "body": '<!-- metamacpkg-proposal {"pair": "brew-formula-to-macports", '
                         '"source": "zzz-no-such", "decision": "confirm", '
                         '"target": "zzz-gone"} -->'}
        with mock.patch.object(T, "_gh") as gh, \
             mock.patch.object(T, "_opener", lambda req: False):
            self.assertEqual(T.triage_issue(issue)[0], "stale-target")
            self.assertTrue(gh.called)  # comment posted, no close/push


if __name__ == "__main__":
    unittest.main()
