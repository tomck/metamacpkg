"""Guardrails: the wrong answers this database must never give.

Each case below is a real failure from heuristic (fuzzy-only) matching:
a confident mapping that points at a different program, which would
install the wrong software during a migration.
"""
import unittest

from metamacpkg import match as m
from metamacpkg.normalize import homepage_key, norm


def P(name, **kw):
    rec = {"manager": "homebrew", "type": "formula", "name": name,
           "aliases": [], "oldnames": [], "desc": "", "homepage": "",
           "version": ""}
    rec.update(kw)
    return rec


def T(name, **kw):
    rec = {"manager": "macports", "type": "port", "name": name,
           "aliases": [], "oldnames": [], "desc": "", "homepage": "",
           "version": "", "replaced_by": None, "categories": [],
           "active": True}
    rec.update(kw)
    return rec


def run(source, targets):
    return m.match_one(source, targets, m.build_target_indexes(targets))


class TestNeverConfidentOnSpelling(unittest.TestCase):
    def test_macs_fan_control_not_qmail(self):
        r = run(P("macs-fan-control", desc="Control fans on Macs",
                  homepage="https://github.com/crystalidea/macs-fan-control"),
                [T("qmail-spamcontrol", desc="Qmail spam control",
                   homepage="https://example.com/qmail")])
        self.assertNotEqual(r["target"], "qmail-spamcontrol")
        self.assertNotEqual(r["status"], "confident")

    def test_git_svn_not_gitsign(self):
        r = run(P("git-svn", desc="Git SVN bridge",
                  homepage="https://git-scm.com/"),
                [T("gitsign", desc="Keyless Git signing",
                   homepage="https://github.com/sigstore/gitsign"),
                 T("git", desc="Version control",
                   homepage="https://git-scm.com/")])
        self.assertNotEqual(r["target"], "gitsign")

    def test_muse_code_missing_not_mmencode(self):
        r = run(P("muse-code", desc="Muse Code agent",
                  homepage="https://example.com/muse"),
                [T("mmencode", desc="Encode multimedia",
                   homepage="https://example.com/mmencode")])
        self.assertNotEqual(r["target"], "mmencode")
        self.assertNotEqual(r["status"], "confident")

    def test_node_not_ode(self):
        r = run(P("node", desc="JavaScript runtime",
                  homepage="https://nodejs.org/"),
                [T("ode", desc="ODE solver", homepage="https://example.com/ode")])
        self.assertNotEqual(r["target"], "ode")

    def test_qt_not_qt3(self):
        r = run(P("qt", desc="Qt framework version 6",
                  homepage="https://www.qt.io/"),
                [T("qt3", desc="Qt framework version 3",
                   homepage="https://www.qt.io/archive"),
                 T("qt6", desc="Qt framework version 6",
                   homepage="https://www.qt.io/")])
        self.assertNotEqual(r["target"], "qt3")

    def test_telnet_not_dateline(self):
        r = run(P("telnet", desc="Telnet client",
                  homepage="https://example.com/telnet"),
                [T("DateLine", desc="Calendar widget",
                   homepage="https://example.com/dateline")])
        self.assertNotEqual(r["target"], "DateLine")


class TestConfidentTiers(unittest.TestCase):
    def test_exact(self):
        r = run(P("wget"), [T("wget")])
        self.assertEqual((r["target"], r["status"]), ("wget", "confident"))

    def test_normalized(self):
        r = run(P("gtk+3"), [T("gtk3")])
        self.assertEqual((r["target"], r["method"]), ("gtk3", "normalized"))

    def test_normalized_ambiguous_is_review(self):
        r = run(P("foo-bar"), [T("foobar"), T("foo_bar")])
        self.assertEqual(r["status"], "needs-review")
        self.assertIsNone(r["target"])

    def test_alias(self):
        r = run(P("oldname", oldnames=["newname"]), [T("newname")])
        self.assertEqual((r["target"], r["method"]), ("newname", "alias"))

    def test_alias_collision_goes_to_review(self):
        # brew sphinx-doc aliases `sphinx`, but MacPorts sphinx is the
        # unrelated search engine. Must not map confidently.
        r = run(P("sphinx-doc",
                  desc="Tool to create intelligent and beautiful documentation",
                  homepage="https://www.sphinx-doc.org/", aliases=["sphinx"]),
                [T("sphinx", desc="Sphinx is a full-text search engine",
                   homepage="http://sphinxsearch.com/")])
        self.assertNotEqual(r["status"], "confident")

    def test_alias_agreeing_descs_stays_confident(self):
        r = run(P("qt", desc="Cross-platform application framework",
                  homepage="https://www.qt.io/", aliases=["qt6"]),
                [T("qt6", desc="Cross-platform application framework",
                   homepage="https://www.qt.io/")])
        self.assertEqual((r["target"], r["method"]), ("qt6", "alias"))

    def test_replaced_by_followed(self):
        r = run(P("oldport"), [T("oldport", replaced_by="newport"),
                               T("newport")])
        self.assertEqual((r["target"], r["method"]),
                         ("newport", "replaced-by"))

    def test_homepage(self):
        r = run(P("mytool", desc="awesome video editor tool",
                  homepage="https://example.com/mytool/"),
                [T("mytool2", desc="awesome video editor program",
                   homepage="https://example.com/mytool")])
        self.assertEqual((r["target"], r["method"]), ("mytool2", "homepage"))

    def test_homepage_major_version_mismatch_is_not_confident(self):
        # Same python.org homepage, overlapping blurbs, but Python 3 vs 2.
        r = run(P("python@3.14", desc="Interpreted, interactive, object-oriented",
                  homepage="https://www.python.org/", version="3.14.0"),
                [T("python21", desc="Interpreted, object-oriented language",
                   homepage="http://www.python.org", version="2.1.3")])
        self.assertNotEqual(r["status"], "confident")

    def test_homepage_same_major_stays_confident(self):
        r = run(P("cpython", desc="Interpreted, interactive, object-oriented",
                  homepage="https://www.python.org/", version="3.14.0"),
                [T("python314", desc="Interpreted, interactive, object-oriented",
                   homepage="https://www.python.org/", version="3.14.2")])
        self.assertEqual((r["target"], r["method"]), ("python314", "homepage"))

    def test_homepage_near_miss_is_review_with_evidence(self):
        # Same nodejs.org homepage, different majors: not confident, but
        # the row must name the near-miss instead of claiming nothing.
        r = run(P("node", desc="Open-source, cross-platform JavaScript runtime",
                  homepage="https://nodejs.org/", version="26.0.0"),
                [T("nodejs24", desc="Evented I/O for V8 JavaScript",
                   homepage="https://nodejs.org/", version="24.0.0")])
        self.assertEqual(r["status"], "needs-review")
        self.assertIn("nodejs24", r["evidence"])

    def test_curated_missing_keeps_lookalikes(self):
        targets = [T("muse-codes"), T("mmencode")]
        r = m.match_one(P("muse-code"), targets,
                        m.build_target_indexes(targets),
                        no_equiv={"muse-code": "not packaged"})
        self.assertEqual(r["status"], "missing")
        self.assertEqual([a["port"] for a in r["alternatives"]],
                         ["muse-codes"])

    def test_github_paths_must_match_fully(self):
        r = run(P("tool-a", desc="tool a does x",
                  homepage="https://github.com/org/tool-a"),
                [T("tool-b", desc="tool b does y",
                   homepage="https://github.com/org/tool-b")])
        self.assertNotEqual(r["status"], "confident")
        self.assertEqual(
            homepage_key("https://github.com/org/tool-a"),
            ("github.com", "/org/tool-a"))


class TestNorm(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(norm("python@3.14"), "python314")
        self.assertEqual(norm("gtk+3"), "gtk3")
        self.assertEqual(norm("HandBrake"), "handbrake")


if __name__ == "__main__":
    unittest.main()
