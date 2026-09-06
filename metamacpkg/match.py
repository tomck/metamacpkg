"""Tiered cross-manager matching.

Only curated or strongly evidenced relationships become `confident`.
Everything else is a `suggestion` (needs-review) or `missing`. Character
similarity alone is never evidence: fuzzy scores only populate the
alternatives column for human review.
"""
import difflib
import re
from collections import defaultdict

from .normalize import (desc_overlap, homepage_domain, homepage_key, norm,
                        tokens)

# Tiers that may produce a confident mapping, in order.
CONFIDENT_METHODS = ("curated", "exact", "normalized", "alias", "replaced-by")
HOMEPAGE_MIN_OVERLAP = 0.15  # homepage tier additionally needs desc overlap
FUZZY_CUTOFF = 0.80          # suggestions only, never confident
FUZZY_TOP = 3


def bigrams(s):
    return {s[i:i + 2] for i in range(max(len(s) - 1, 0))} or {s}


def build_target_indexes(targets):
    by_name, by_norm, by_home = {}, defaultdict(list), defaultdict(list)
    prescan = []
    for t in targets:
        tn = norm(t["name"])
        by_name[t["name"]] = t
        by_norm[tn].append(t)
        hk = homepage_key(t.get("homepage"))
        if hk:
            by_home[hk].append(t)
        prescan.append((t, tn, bigrams(tn)))
    return by_name, by_norm, by_home, prescan


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
          alternatives:[...]}. status is confident | needs-review | missing.
    """
    curated = curated or {}
    no_equiv = no_equiv or set()
    sname = source["name"]
    by_name, by_norm, by_home, _prescan = idx
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


def match_all(sources, targets, curated=None, no_equiv=None):
    idx = build_target_indexes(targets)
    return [match_one(s, targets, idx, curated, no_equiv) for s in sources]
