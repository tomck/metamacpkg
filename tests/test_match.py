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


class TestVersionFamily(unittest.TestCase):
    ANS_S = dict(desc="Automate deployment, configuration, and upgrading",
                 homepage="https://www.ansible.com/")
    ANS_T = dict(desc="Configuration management and deployment",
                 homepage="https://github.com/ansible/ansible")
    HON = dict(desc="Python clone of Foreman, for managing applications",
               homepage="https://github.com/nickstenning/honcho")

    def run_all(self, sources, targets, **kw):
        return m.match_all(sources, targets, **kw)

    def test_base_name(self):
        self.assertEqual(m.base_name("ansible@9"), "ansible")
        self.assertEqual(m.base_name("py39-ansible"), "ansible")
        self.assertEqual(m.base_name("py-ansible"), "ansible")
        self.assertEqual(m.base_name("python@3.14"), "python")
        self.assertEqual(m.base_name("awscli"), "awscli")
        self.assertEqual(m.base_name("py-awscli2"), "awscli")

    def test_affinity_classes(self):
        self.assertEqual(m.affinity("bind", "bind9"), "A")
        self.assertEqual(m.affinity("redis@6.2", "redis7"), "A")
        self.assertEqual(m.affinity("ansible@9", "py39-ansible"), "B")
        self.assertEqual(m.affinity("six", "py39-six"), "B")
        self.assertIsNone(m.affinity("node", "ode"))

    def test_fill_class_a_needs_no_homepage(self):
        # inchi-style: divergent homepages, same program line.
        r = m.family_fill(
            P("inchi", desc="IUPAC chemical identifier",
              homepage="https://example.com/inchi", version="1.07.5"),
            [T("inchi-1", desc="IUPAC chemical identifier",
               homepage="https://example.org/inchi", version="1.03")])
        self.assertEqual((r["target"], r["status"], r["method"]),
                         ("inchi-1", "confident", "version"))

    def test_fill_class_b_needs_same_homepage(self):
        # faiss-style: a C library and its Python binding share a stem
        # but live upstream in different places. No fill without the
        # same homepage...
        r = m.family_fill(
            P("ansible@13", version="13.8.0", **self.ANS_S),
            [T("py314-ansible", version="13.0.0", **self.ANS_T)])
        self.assertIsNone(r)
        # ...while honcho-style (same repo both sides) still fills.
        r = m.family_fill(
            P("honcho", version="1.1.0", **self.HON),
            [T("py314-honcho", version="1.0.0", **self.HON)])
        self.assertEqual((r["target"], r["status"], r["method"]),
                         ("py314-honcho", "confident", "version"))

    def test_fill_refuses_newer_port(self):
        r = m.family_fill(
            P("ansible@9", version="9.13.0", **self.ANS_S),
            [T("py39-ansible", version="11.1.0", **self.ANS_T)])
        self.assertIsNone(r)

    def test_fill_tie_prefers_newest_variant(self):
        cands = [T("py310-honcho", version="1.0.0", **self.HON),
                 T("py314-honcho", version="1.0.0", **self.HON)]
        r = m.family_fill(P("honcho", version="1.1.0", **self.HON), cands)
        self.assertEqual(r["target"], "py314-honcho")
        self.assertEqual(len(r["alternatives"]), 1)

    def test_nearhit_prefers_newer_within_bound(self):
        r = m.family_nearhit(
            P("ansible@9", version="9.13.0", **self.ANS_S),
            [T("py39-ansible", version="11.1.0", **self.ANS_T),
             T("py38-ansible", version="6.0.0", **self.ANS_T)],
            set())
        self.assertEqual((r["target"], r["status"]), ("py39-ansible",
                                                      "near-hit"))
        self.assertLess(r["confidence"], 0.8)
        self.assertIn("2 majors newer", r["evidence"])

    def test_nearhit_downgrade_only_option(self):
        r = m.family_nearhit(
            P("conan@2", desc="C/C++ package manager",
              homepage="https://conan.io/", version="2.9.0"),
            [T("conan", desc="C/C++ package manager",
               homepage="https://conan.io/", version="1.66.0")],
            set())
        self.assertEqual(r["target"], "conan")
        self.assertIn("older", r["evidence"])

    def test_nearhit_bound_refuses_far_jump(self):
        r = m.family_nearhit(
            P("tomcat@9", desc="Java servlet container",
              homepage="https://tomcat.apache.org/", version="9.0.0"),
            [T("tomcat", desc="Java servlet container",
               homepage="https://tomcat.apache.org/", version="5.5.0")],
            set())
        self.assertIsNone(r)

    def test_nearhit_skips_claimed_targets(self):
        cands = [T("py314-ansible", version="13.0.0", **self.ANS_T),
                 T("py313-ansible", version="13.0.0", **self.ANS_T)]
        r = m.family_nearhit(P("ansible@12", version="12.3.0",
                               **self.ANS_S),
                             cands, {"py314-ansible"})
        self.assertEqual(r["target"], "py313-ansible")

    def test_nearhit_skips_obsolete_ports(self):
        cands = [T("py38-ansible-base", version="2.10.11", **self.ANS_T,
                   replaced_by="py39-ansible-core")]
        s = P("tool@2", desc="SSH-based configuration management",
              homepage="https://github.com/ansible/ansible",
              version="2.5.0")
        idx = m.build_target_indexes(cands)
        self.assertEqual(m.family_candidates(s, cands, idx), [])

    def test_nearhit_skips_dead_python(self):
        self.assertTrue(m._dead_python("py27-FlexGet"))
        self.assertFalse(m._dead_python("py314-ansible"))
        cands = [T("py27-roundup", desc="Issue tracking system",
                   homepage="https://example.com/roundup",
                   version="1.6.1")]
        s = P("roundup", desc="Issue tracking system",
              homepage="https://example.com/roundup", version="0.0.6")
        idx = m.build_target_indexes(cands)
        self.assertEqual(m.family_candidates(s, cands, idx), [])

    def test_nearhit_refuses_different_program(self):
        # h2 the Java database vs py-h2 the HTTP/2 library: same stem,
        # disjoint descriptions, different upstreams. Offering it would
        # misinform, so there is no near-hit at all.
        r = m.family_nearhit(
            P("h2", desc="Java SQL database",
              homepage="https://www.h2database.com/", version="2.5.250"),
            [T("py314-h2", desc="HTTP/2 protocol stack for Python",
               homepage="https://python-hyper.org/projects/h2/",
               version="4.4.1")],
            set())
        self.assertIsNone(r)

    def test_nearhit_symmetric_stem_passes_thin_descs(self):
        # nip4 ~ nip2: both sides version-suffixed, so the stem match is
        # structural even when the blurbs barely overlap.
        r = m.family_nearhit(
            P("nip4", desc="Image processing spreadsheet",
              homepage="https://github.com/libvips/nip4", version="9.1.5"),
            [T("nip2", desc="Image workshop tool",
               homepage="https://libvips.github.io/libvips/",
               version="8.9.1")],
            set())
        self.assertEqual((r["target"], r["status"]),
                         ("nip2", "near-hit"))

    def test_sphinx_collision_not_family(self):
        # Same stem, but different-homepage + disjoint-desc evidence wins.
        s = P("sphinx-doc",
              desc="Tool to create intelligent and beautiful documentation",
              homepage="https://www.sphinx-doc.org/", version="8.0.0",
              aliases=["sphinx"])
        t = [T("sphinx", desc="Sphinx is a full-text search engine",
               homepage="http://sphinxsearch.com/", version="2.3.0")]
        rows = self.run_all([s], t)
        self.assertNotEqual(rows[0]["status"], "confident")

    def test_match_all_ansible_end_to_end(self):
        # Divergent homepages keep the 13-line out of confident fills, so
        # every row near-hits; closest lines claim first (@13 takes py314
        # before @12 is considered).
        src = [P("ansible@9", version="9.13.0", **self.ANS_S),
               P("ansible@12", version="12.3.0", **self.ANS_S),
               P("ansible@13", version="13.8.0", **self.ANS_S)]
        tgt = [T("py-ansible", version="13.0.0", **self.ANS_T),
               T("py313-ansible", version="13.0.0", **self.ANS_T),
               T("py314-ansible", version="13.0.0", **self.ANS_T),
               T("py39-ansible", version="11.1.0", **self.ANS_T)]
        got = {r["source"]: (r["target"], r["status"], r["method"])
               for r in self.run_all(src, tgt)}
        self.assertEqual(got["ansible@13"],
                         ("py314-ansible", "near-hit", "near-hit"))
        self.assertIn("same major", self.run_all(src, tgt)[2]["evidence"])
        self.assertEqual(got["ansible@12"],
                         ("py313-ansible", "near-hit", "near-hit"))
        self.assertEqual(got["ansible@9"],
                         ("py39-ansible", "near-hit", "near-hit"))

    def test_zero_major_needs_symmetric_or_same_minor(self):
        # build2 0.18 vs build 0.3: a 0.x "major" is no program line.
        r = m.family_fill(
            P("build2", desc="C/C++ Build Toolchain",
              homepage="https://build2.org", version="0.18.1"),
            [T("build", desc="Massively-parallel build system",
               homepage="http://www.codesynthesis.com/projects/build",
               version="0.3.10")])
        self.assertIsNone(r)
        # ...while imposm 0.14.2 -> 0.14.2 (same minor) still fills.
        r = m.family_fill(
            P("imposm3", desc="Import OSM data",
              homepage="https://example.com/imposm", version="0.14.2"),
            [T("imposm", desc="Import OSM data",
               homepage="https://example.com/imposm", version="0.14.2")])
        self.assertEqual(r["target"], "imposm")

    def test_digit_target_needs_extra_evidence(self):
        # fink nghttp (nghttp2 1.58) vs mp nghttp3 (HTTP/3 lib 1.18):
        # the target's digit is semantic, not a version. Refused.
        r = m.family_fill(
            P("nghttp", desc="HTTP/2 client, server and proxy",
              homepage="https://tatsuhiro-t.github.io/nghttp2/",
              version="1.58.0"),
            [T("nghttp3", desc="HTTP/3 protocol implementation in C",
               homepage="https://nghttp2.org/nghttp3/", version="1.18.0")])
        self.assertIsNone(r)
        # ...while libmpc shares its domain, and textmate/glib share
        # their release line, so those still fill.
        r = m.family_fill(
            P("libmpc", desc="Complex number library",
              homepage="https://www.multiprecision.org/", version="1.4.1"),
            [T("libmpc3", desc="Complex number C library",
               homepage="https://www.multiprecision.org/", version="1.3.1")])
        self.assertEqual(r["target"], "libmpc3")
        r = m.family_fill(
            P("textmate", desc="Text editor for macOS",
              homepage="https://macromates.com/", version="2.0.23"),
            [T("textmate2", desc="TextMate editor",
               homepage="https://github.com/textmate/textmate",
               version="2.0.23")])
        self.assertEqual(r["target"], "textmate2")

    def test_tie_break_compares_python_numerically(self):
        # Equal versions: py314 must beat py39 (strings compare wrong).
        cands = [T("py39-chardet", desc="Encoding detector",
                   homepage="https://example.com/chardet", version="5.2.0"),
                 T("py314-chardet", desc="Encoding detector",
                   homepage="https://example.com/chardet", version="5.2.0")]
        r = m.family_nearhit(
            P("chardet", desc="Encoding detector",
              homepage="https://example.com/chardet", version="7.6.0"),
            cands, set())
        self.assertEqual(r["target"], "py314-chardet")

    def test_match_all_leaves_confident_rows_alone(self):
        src = [P("wget", version="1.2.0")]
        rows = self.run_all(src, [T("wget", version="1.2.0")])
        self.assertEqual((rows[0]["target"], rows[0]["method"]),
                         ("wget", "exact"))


class TestNorm(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(norm("python@3.14"), "python314")
        self.assertEqual(norm("gtk+3"), "gtk3")
        self.assertEqual(norm("HandBrake"), "handbrake")


if __name__ == "__main__":
    unittest.main()
