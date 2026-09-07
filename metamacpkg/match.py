"""Tiered cross-manager matching.

Only curated or strongly evidenced relationships become `confident`.
A same-program version family resolves two more cases: an identical-or-older
same-major port is a confident `version` fill (python-variant affinity
additionally needs the same upstream homepage, where C libraries otherwise
collide with their bindings), and the nearest remaining same-program port
is a `near-hit` migration suggestion (offered, never auto-installed).
Everything else is a `suggestion` (needs-review) or `missing`. Character
similarity alone is never evidence: fuzzy scores only populate the
alternatives column for human review.
"""
import difflib
import re
from collections import defaultdict

from .normalize import (GENERIC_HOSTS, desc_overlap, homepage_domain,
                        homepage_key, norm, tokens)

# Tiers that may produce a confident mapping, in order.
CONFIDENT_METHODS = ("curated", "exact", "normalized", "alias", "replaced-by",
                     "homepage", "version")
HOMEPAGE_MIN_OVERLAP = 0.15  # homepage tier additionally needs desc overlap
FUZZY_CUTOFF = 0.80          # suggestions only, never confident
FUZZY_TOP = 3
# A near-hit must be this close in app-major versions. ansible@9 -> the
# 11-line (distance 2) is the farthest plausible "same program, move me".
NEAR_HIT_MAX_DIST = 2


def bigrams(s):
    return {s[i:i + 2] for i in range(max(len(s) - 1, 0))} or {s}


def build_target_indexes(targets):
    by_name, by_norm, by_home, by_base = {}, defaultdict(list), \
        defaultdict(list), defaultdict(list)
    prescan = []
    for t in targets:
        tn = norm(t["name"])
        by_name[t["name"]] = t
        by_norm[tn].append(t)
        hk = homepage_key(t.get("homepage"))
        if hk:
            by_home[hk].append(t)
        by_base[base_name(t["name"])].append(t)
        prescan.append((t, tn, bigrams(tn)))
    return by_name, by_norm, by_home, prescan, by_base


def alias_names(pkg):
    out = set()
    for key in ("aliases", "oldnames"):
        for a in pkg.get(key) or []:
            out.add(a)
            out.add(norm(a))
    return out


def major_version(version):
    """Leading numeric component ('3.14.2' -> 3), or None when unknown."""
    m = re.match(r"\D*(\d+)", str(version or ""))
    return int(m.group(1)) if m else None


def desc_containment(a, b):
    """Shared tokens over the smaller token set (terse-vs-verbose safe)."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def descs_agree(source, target, cutoff=0.15):
    """False only on positive evidence of different programs.

    A known alias pointing at a same-named but unrelated target (brew's
    `sphinx` alias for the doc generator vs MacPorts' `sphinx` search
    engine) must not auto-map. Different homepage domains plus disjoint
    descriptions is that evidence; anything less keeps the tier.
    """
    ds = homepage_domain(source.get("homepage"))
    dt = homepage_domain(target.get("homepage"))
    if not (ds and dt and ds != dt):
        return True
    if len(source.get("desc") or "") < 20 or len(target.get("desc") or "") < 20:
        return True
    return desc_containment(source.get("desc"), target.get("desc")) >= cutoff


def versions_compatible(a, b):
    """False only when both versions are known and majors disagree.

    A migration across a major-version boundary (Python 2 vs 3, Qt 3 vs 6)
    deserves human review even when the homepage matches, so the homepage
    tier must not claim it confidently.
    """
    ma, mb = major_version(a), major_version(b)
    return not (ma is not None and mb is not None and ma != mb)


def _strip_py(n):
    n = re.sub(r"^py\d+[-_]?", "", n)  # py39-ansible, py310_foo
    return re.sub(r"^py[-_]", "", n)   # py-ansible stub


def _strip_version(n):
    return re.sub(r"v?\d[\d.]*$", "", n)  # trailing version bits


def base_name(name):
    """Program skeleton: strip python-variant prefixes and version suffixes.

    ansible@9 -> ansible; py39-ansible -> ansible; py-ansible -> ansible;
    python@3.14 -> python; openssl@3 -> openssl.
    """
    return _strip_version(norm(_strip_py((name or "").lower())))


def affinity(source_name, target_name):
    """Name-affinity class, or None when unrelated.

    'A': equal after version-suffix stripping only (bind ~ bind9,
    redis@6.2 ~ redis7). 'B': equality additionally needs a python
    variant prefix stripped (ansible@9 ~ py39-ansible, six ~ py39-six).
    The B class is where C libraries collide with their Python bindings
    (faiss, build2, base16384), so it carries stricter evidence rules.
    """
    s, t = (source_name or "").lower(), (target_name or "").lower()
    if _strip_version(norm(s)) == _strip_version(norm(t)):
        return "A"
    if base_name(s) == base_name(t):
        return "B"
    return None


def _symmetric_strip(source_name, target_name):
    """Affinity class A with version digits stripped on both sides.

    nip4 ~ nip2, redis@6.2 ~ redis7. Scoped to class A so a python
    prefix around a digit-stem (py314-h2) cannot fake it.
    """
    if affinity(source_name, target_name) != "A":
        return False
    s, t = norm(source_name or ""), norm(target_name or "")
    return _strip_version(s) != s and _strip_version(t) != t


def _stem_direction(source_name, target_name):
    """Where the version digits sat: even, digit-source, digit-target.

    A bare source against a digit-suffixed target (nghttp ~ nghttp3,
    mysql++ ~ mysql4, base16384 ~ base58) is the dangerous direction:
    the target's digits may be semantic (HTTP/3, MySQL 4, base-58) rather
    than a version, so these pairs need extra evidence.
    """
    s, t = norm(source_name or ""), norm(target_name or "")
    ss, tt = _strip_version(s) != s, _strip_version(t) != t
    if ss == tt:
        return "even"
    return "digit-source" if ss else "digit-target"


def _domain_agree(source, target):
    """Same non-forge homepage domain (github.com never counts: two
    different repos share the host but not the program)."""
    ds, dt = homepage_domain(source.get("homepage")), \
        homepage_domain(target.get("homepage"))
    return bool(ds) and ds == dt and ds not in GENERIC_HOSTS


def _same_minor(sv, tv):
    return _minor(sv) == _minor(tv)


def _homepage_key_agree(source, target):
    ks, kt = homepage_key(source.get("homepage")), \
        homepage_key(target.get("homepage"))
    return ks is not None and ks == kt


def _dead_python(name):
    """Python-2 variants are uninstallable fossils, never migration targets."""
    return re.match(r"^py2\d", (name or "").lower()) is not None


def version_tuple(version):
    """Numeric release tuple ('13.8.0' -> (13, 8, 0)), None when unknown."""
    parts = re.findall(r"\d+", str(version or ""))
    return tuple(int(p) for p in parts[:4]) or None


def _version_le(a, b):
    """a <= b with zero-padding ('8.0' <= '8.0.43')."""
    n = max(len(a), len(b))
    return (a + (0,) * (n - len(a))) <= (b + (0,) * (n - len(b)))


def _minor(tup):
    """Minor component, 0 when the version is major-only."""
    return tup[1] if len(tup) > 1 else 0


def family_candidates(source, targets, idx):
    """Same-program ports: name affinity + agreeing descriptions.

    Affinity class A (version-suffixed names: bind ~ bind9) or B
    (python variants: ansible@9 ~ py39-ansible); descs_agree is the
    identity check. Obsolete (replaced_by) and Python-2 ports are
    excluded: a fill must never point at a dead port.
    """
    base = base_name(source["name"])
    if not base or major_version(source.get("version")) is None:
        return []
    by_base = idx[4] if len(idx) > 4 else {}
    pool = []
    for t in by_base.get(base, []):
        if (t.get("replaced_by") or "").strip():
            continue
        if _dead_python(t["name"]):
            continue
        if major_version(t.get("version")) is None:
            continue
        if t["name"] == source["name"]:
            continue
        if affinity(source["name"], t["name"]) is None:
            continue
        if descs_agree(source, t):
            pool.append(t)
    return pool


def fuzzy_suggestions(source, targets, idx=None, top=FUZZY_TOP,
                      cutoff=FUZZY_CUTOFF):
    """Lookalikes for human review only. Never confident.

    Two cheap prefilters (length ratio, bigram overlap) prune the target
    list before the quadratic SequenceMatcher runs, so 50k-port catalogs
    stay tractable.
    """
    snorm = norm(source["name"])
    sb, slen = bigrams(snorm), len(snorm)
    prescan = idx[3] if idx else [(t, norm(t["name"]), None) for t in targets]
    scored = []
    for t, tn, tb in prescan:
        if slen and abs(len(tn) - slen) / max(len(tn), slen) > 0.5:
            continue
        if tb is not None and slen > 2:
            inter = len(sb & tb)
            if inter / max(min(len(sb), len(tb)), 1) < 0.4:
                continue
        s = difflib.SequenceMatcher(None, snorm, tn).ratio()
        if s >= cutoff:
            scored.append((s, t))
    scored.sort(key=lambda x: -x[0])
    return [{"port": t["name"], "confidence": round(s, 3), "reason": "fuzzy",
             "overlap": round(desc_overlap(source.get("desc"), t.get("desc")), 3)}
            for s, t in scored[:top]]


def match_one(source, targets, idx, curated=None, no_equiv=None):
    """Return a mapping row for one source package.

    Row: {source, target|None, confidence, method, status, evidence,
          alternatives:[...]}. status is confident | needs-review | missing
    (match_all can upgrade 'none' rows to confident `version` fills or
    `near-hit` suggestions via the version-family tier).
    """
    curated = curated or {}
    no_equiv = no_equiv or set()
    sname = source["name"]
    by_name, by_norm, by_home, _prescan = idx[:4]
    aliases = alias_names(source)

    def row(target, confidence, method, evidence, status="confident"):
        return {"source": sname, "target": target, "confidence": confidence,
                "method": method, "status": status, "evidence": evidence,
                "alternatives": []}

    # Tier 0: curated decision (equivalence or explicit no-equivalent).
    if sname in no_equiv:
        r = row(None, 1.0, "curated",
                no_equiv[sname] if isinstance(no_equiv, dict)
                else "curated no-equivalent",
                status="missing")
        r["alternatives"] = fuzzy_suggestions(source, targets, idx)
        return r
    if sname in curated:
        c = curated[sname]
        return row(c["target"], 1.0, "curated", c.get("comment", "curated"))

    def followed(t, confidence, method, evidence):
        """Follow a MacPorts replaced_by pointer to the live port."""
        repl = (t.get("replaced_by") or "").strip()
        if repl and repl in by_name:
            return row(repl, 0.95, "replaced-by",
                       f"{t['name']!r} is marked replaced_by {repl!r}")
        return row(t["name"], confidence, method, evidence)

    # Tier 1: exact name.
    if sname in by_name:
        t = by_name[sname]
        return followed(t, 1.0, "exact",
                        f"name identical in both managers; homepages "
                        f"{source.get('homepage')!r} vs {t.get('homepage')!r}")

    # Tier 2: normalized name, only when it is unambiguous (1:1).
    hits = by_norm.get(norm(sname), [])
    if len(hits) == 1:
        t = hits[0]
        return followed(t, 0.96, "normalized",
                        f"{sname!r} ~ {t['name']!r} after case/punctuation folding")
    if len(hits) > 1:
        return _ambiguous(source, targets, idx,
                          f"normalized name matches {len(hits)} targets",
                          [h["name"] for h in hits])

    # Tier 3: official aliases / old names (index lookups, not a scan).
    # Guarded: an alias that names an unrelated target (sphinx-doc's
    # `sphinx` alias vs the Sphinx search engine port) goes to review.
    alias_hits, _seen = [], set()
    for a in aliases:
        for t in by_norm.get(norm(a), []):
            if id(t) not in _seen:
                _seen.add(id(t))
                alias_hits.append(t)
    if len(alias_hits) == 1:
        t = alias_hits[0]
        if descs_agree(source, t):
            return row(t["name"], 0.95, "alias",
                       f"listed as alias/oldname of {sname!r}")
        return _ambiguous(source, targets, idx,
                          f"alias {t['name']!r} looks like a different program "
                          f"(homepages {source.get('homepage')!r} vs "
                          f"{t.get('homepage')!r})",
                          [t["name"]])
    if len(alias_hits) > 1:
        return _ambiguous(source, targets, idx,
                          f"alias matches {len(alias_hits)} targets",
                          [h["name"] for h in alias_hits])

    # (replaced_by pointers are followed inside tiers 1-2 via `followed`.)

    # Tier 4: identical upstream homepage + overlapping description +
    # compatible major versions. The version gate stops e.g. Python 3
    # matching Python 2 on the shared python.org homepage.
    near_miss = ""
    hk = homepage_key(source.get("homepage"))
    if hk:
        cands = [t for t in by_home.get(hk, []) if t["name"] != sname]
        scored = [(desc_overlap(source.get("desc"), t.get("desc")), t)
                  for t in cands]
        good = [(o, t) for o, t in scored
                if o >= HOMEPAGE_MIN_OVERLAP
                and versions_compatible(source.get("version"),
                                        t.get("version"))]
        if cands and not good:
            scored.sort(key=lambda x: -x[0])
            o0, t0 = scored[0]
            why = []
            if o0 < HOMEPAGE_MIN_OVERLAP:
                why.append(f"desc overlap only {o0:.2f}")
            if not versions_compatible(source.get("version"),
                                       t0.get("version")):
                why.append(f"versions {source.get('version')!r} vs "
                           f"{t0.get('version')!r}")
            near_miss = (f"same homepage {source.get('homepage')!r} as "
                         f"{t0['name']!r} but {'; '.join(why)}")
        if len(good) == 1:
            o, t = good[0]
            return row(t["name"], 0.90, "homepage",
                       f"same upstream {source.get('homepage')!r} "
                       f"(desc overlap {o:.2f})")
        if len(good) > 1:
            return _ambiguous(source, targets, idx,
                              "homepage shared by several targets",
                              [t["name"] for _, t in good])

    # Nothing strong: suggestions or missing.
    alts = fuzzy_suggestions(source, targets, idx)
    evidence = "no exact/normalized/alias/homepage evidence"
    if near_miss:
        evidence += "; " + near_miss
    evidence += ("; fuzzy suggestions listed for review" if alts
                 else "; no lookalikes either")
    r = row(None, 0.0, "none", evidence,
            status="missing" if not alts and not near_miss else "needs-review")
    r["alternatives"] = alts
    return r


def _ambiguous(source, targets, idx, evidence, names):
    alts = ([{"port": n, "confidence": 0.0, "reason": "ambiguous",
              "overlap": 0.0} for n in names]
            + fuzzy_suggestions(source, targets, idx))
    seen, uniq = set(), []
    for a in alts:
        if a["port"] not in seen:
            seen.add(a["port"])
            uniq.append(a)
    return {"source": source["name"], "target": None, "confidence": 0.0,
            "method": "ambiguous", "status": "needs-review",
            "evidence": evidence, "alternatives": uniq[:FUZZY_TOP + 2]}


def _sibling_alts(pick, others, confidence):
    return [{"port": t["name"], "confidence": confidence,
             "reason": "version-sibling",
             "overlap": round(desc_overlap(pick.get("desc"),
                                           t.get("desc")), 3)}
            for t in others[:5]]


def _parsed(source, cands):
    ma = major_version(source.get("version"))
    sv = version_tuple(source.get("version"))
    if ma is None or sv is None:
        return None, None
    parsed = [(t, major_version(t.get("version")),
               version_tuple(t.get("version"))) for t in cands]
    parsed = [(t, mb, tv) for t, mb, tv in parsed
              if mb is not None and tv is not None]
    return (ma, sv), parsed


def _py_num(name):
    """Embedded python-variant number (py314 -> 314), else -1.

    Newest-variant tie-breaks must compare these numerically: as strings
    'py39' sorts after 'py314', pointing migrations at older interpreters.
    """
    m = re.search(r"py(\d+)", (name or "").lower())
    return int(m.group(1)) if m else -1


def _fill_affinity_ok(source, t, tv, sv):
    """Is the stem evidence strong enough to auto-install?

    Class B (python variants) needs the identical upstream homepage.
    Class A is structural except in the digit-target direction (bare
    source, suffixed target: nghttp ~ nghttp3), where the digits may be
    semantic -- there it needs the same page, the same non-forge domain,
    a majority-shared description, or a shared release line.
    """
    if affinity(source["name"], t["name"]) == "B":
        return _homepage_key_agree(source, t)
    if _stem_direction(source["name"], t["name"]) != "digit-target":
        return True
    if _homepage_key_agree(source, t) or _domain_agree(source, t):
        return True
    if desc_containment(source.get("desc"), t.get("desc")) > 0.5:
        return True
    return _same_minor(sv, tv)


def family_fill(source, cands):
    """Confident fill: same app-major and the port is identical-or-older.

    A migration onto the line the other manager carries (mysql@8.4 ->
    mysql8). Newer ports never fill: the other manager ahead of Homebrew
    means the lines have diverged and a human should look. The stem must
    also be fill-grade (see _fill_affinity_ok). A 0.x major carries no
    line semantics, so 0.x fills additionally need a symmetric version
    stem or equal minors. Ties go to the newest port version, then the
    newest variant.
    """
    ms, parsed = _parsed(source, cands)
    if ms is None:
        return None
    ma, sv = ms
    fills = [(t, tv) for t, mb, tv in parsed
             if mb == ma and _version_le(tv, sv)
             and _fill_affinity_ok(source, t, tv, sv)
             and (ma != 0 or _symmetric_strip(source["name"], t["name"])
                  or _same_minor(sv, tv))]
    if not fills:
        return None
    fills.sort(key=lambda ft: (ft[1], _py_num(ft[0]["name"]),
                               ft[0]["name"]))
    best = fills[-1][0]
    sibs = [t for t, _ in fills if t["name"] != best["name"]]
    return {"source": source["name"], "target": best["name"],
            "confidence": 0.90, "method": "version",
            "status": "confident",
            "evidence": (
                f"same program line: {source.get('version')} vs "
                f"{best['name']} {best.get('version')} (major {ma}, "
                f"port identical-or-older)"
                + (f"; {len(sibs)} identical sibling(s): "
                     f"{', '.join(t['name'] for t in sibs)}" if sibs else "")),
            "alternatives": _sibling_alts(best, sibs, 0.90)}


def _nearhit_evidence(source, t):
    """A symmetric version stem, the same upstream page, or a description
    that is mostly shared vocabulary.

    Without one of these the "nearest" port is a different program
    wearing a similar stem (h2 the Java database vs py-h2 the HTTP/2
    library, kraken2 vs kraken OCR), and offering it would misinform.
    """
    if _symmetric_strip(source["name"], t["name"]):
        return True
    if _homepage_key_agree(source, t):
        return True
    return desc_containment(source.get("desc"), t.get("desc")) > 0.5


def family_nearhit(source, cands, claimed):
    """Nearest remaining same-program port, for migration tools to offer.

    Nearest by app-major distance (newer preferred, at most
    NEAR_HIT_MAX_DIST away); ties go to the newest variant. Never
    auto-installed -- confidence caps at 0.78. Targets already claimed
    by a confident row or an earlier near-hit are skipped, so one port
    is never offered twice. Candidates without near-hit evidence
    (symmetric stem, same upstream, or majority-shared description)
    are refused rather than offered wrong.
    """
    ms, parsed = _parsed(source, cands)
    if ms is None:
        return None
    ma, sv = ms
    scored = []
    for t, mb, tv in parsed:
        if t["name"] in claimed:
            continue
        # Note: same-major identical-or-older candidates are NOT skipped
        # here. match_all runs fills first, so anything reaching this
        # function failed the fill's affinity bar (e.g. ansible@13 vs the
        # 13.0.0 line on a divergent homepage) and is still the nearest
        # version worth offering.
        dist = abs(mb - ma)
        if dist > NEAR_HIT_MAX_DIST:
            continue
        if not _nearhit_evidence(source, t):
            continue
        width = max(len(tv), len(sv))
        newer = (tv + (0,) * (width - len(tv)) >
                 sv + (0,) * (width - len(sv)))
        scored.append((dist, 0 if newer else 1, tv, t["name"], t))
    if not scored:
        return None
    scored.sort(key=lambda s: (s[0], s[1]))
    dist, newerrank = scored[0][0], scored[0][1]
    tied = sorted([s for s in scored if s[0] == dist and s[1] == newerrank],
                  key=lambda s: (s[2], _py_num(s[4]["name"]), s[3]))
    best = tied[-1][4]
    sibs = [s[4] for s in reversed(tied[:-1])]
    direction = "newer" if newerrank == 0 else "older"
    gap = (f"same major, port {direction}" if dist == 0
           else f"{dist} major{'s' if dist != 1 else ''} {direction}")
    conf = round(max(0.55, 0.78 - 0.05 * dist), 3)
    return {"source": source["name"], "target": best["name"],
            "confidence": conf, "method": "near-hit", "status": "near-hit",
            "evidence": (
                f"nearest same-program port: {source.get('version')} vs "
                f"{best['name']} {best.get('version')} ({gap})"
                + (f"; siblings: "
                     f"{', '.join(t['name'] for t in sibs)}" if sibs else "")),
            "alternatives": _sibling_alts(best, sibs, conf)}


def _bestdist(source, cands):
    """Closest app-major distance among evidenced candidates (claims blind).

    Rows are considered for near-hits closest-first, so the nearest line
    claims a shared port before farther rows (ansible@13 before @12).
    """
    ms, parsed = _parsed(source, cands)
    if ms is None:
        return float("inf")
    ma, _sv = ms
    dists = [abs(mb - ma) for t, mb, _tv in parsed
             if abs(mb - ma) <= NEAR_HIT_MAX_DIST
             and _nearhit_evidence(source, t)]
    return min(dists) if dists else float("inf")


def family_row(source, cands, claimed):
    """Fill, else near-hit. Thin wrapper so both paths stay consistent."""
    return (family_fill(source, cands)
            or family_nearhit(source, cands, claimed))


def match_all(sources, targets, curated=None, no_equiv=None):
    idx = build_target_indexes(targets)
    rows = [match_one(s, targets, idx, curated, no_equiv) for s in sources]
    # Second pass: the version-family tier only touches rows no earlier
    # tier claimed (method 'none'), in source order so near-hit claims
    # are deterministic. Higher-tier confident targets are pre-claimed.
    # Fills land first so near-hits never offer a port a fill just took
    # (ansible@13 fills py314-ansible before ansible@12 near-hits).
    claimed = {r["target"] for r in rows
               if r["status"] == "confident" and r["target"]}
    order = sorted(range(len(sources)), key=lambda i: sources[i]["name"])
    cands_by_row = {}
    for i in order:
        if rows[i]["method"] != "none":
            continue
        cands = family_candidates(sources[i], targets, idx)
        if not cands:
            continue
        cands_by_row[i] = cands
        fill = family_fill(sources[i], cands)
        if fill is None:
            continue
        rows[i] = fill
        claimed.add(fill["target"])
    near_order = sorted(cands_by_row,
                        key=lambda i: (_bestdist(sources[i],
                                                 cands_by_row[i]),
                                       sources[i]["name"]))
    for i in near_order:
        if rows[i]["method"] != "none":
            continue
        hit = family_nearhit(sources[i], cands_by_row[i], claimed)
        if hit is None:
            continue
        rows[i] = hit
        claimed.add(hit["target"])
    return rows
