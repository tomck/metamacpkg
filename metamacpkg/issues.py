"""Import crowdsourced mapping proposals from GitHub issues.

The review site submits each verdict as a `mapping-review` issue whose
body carries a machine-readable block:

    <!-- metamacpkg-proposal {"pair": "...", "source": "...",
         "decision": "confirm|no-equivalent|propose", "target": "...",
         "comment": "..."} -->

Proposals land in curated/pending.yaml, which the build NEVER reads:
a maintainer promotes reviewed entries into curated/relations.yaml or
curated/no_equivalent.yaml by hand. Untrusted input stays untrusted.
"""
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PENDING = ROOT / "curated" / "pending.yaml"

BLOCK = re.compile(r"<!--\s*metamacpkg-proposal\s*(\{.*?\})\s*-->",
                   re.DOTALL)
DECISIONS = {"confirm", "no-equivalent", "propose"}


def parse_body(body):
    """Return the proposal dict, or None when absent/invalid."""
    m = BLOCK.search(body or "")
    if not m:
        return None
    try:
        p = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(p, dict):
        return None
    if p.get("decision") not in DECISIONS:
        return None
    if not p.get("pair") or not p.get("source"):
        return None
    if p["decision"] in ("confirm", "propose") and not p.get("target"):
        return None
    return {"pair": str(p["pair"]), "source": str(p["source"]),
            "decision": p["decision"],
            "target": str(p.get("target") or ""),
            "comment": str(p.get("comment") or "")}


def _gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True,
                          text=True).stdout


def already_imported():
    if not PENDING.exists():
        return set()
    return set(int(n) for n in re.findall(r"^- issue: (\d+)",
                                          PENDING.read_text(),
                                          flags=re.MULTILINE))


def _q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def append_pending(entries):
    lines = []
    if not PENDING.exists():
        lines.append("# Crowdsourced proposals from mapping-review issues.\n"
                     "# NOT read by the build. Maintainer promotes reviewed\n"
                     "# entries into curated/relations.yaml / no_equivalent.yaml.\n")
    with open(PENDING, "a") as f:
        if lines:
            f.write("".join(lines))
        for e in entries:
            f.write(f"- issue: {e['issue']}\n"
                    f"  imported_at: {_q(e['imported_at'])}\n"
                    f"  author: {_q(e['author'])}\n"
                    f"  pair: {_q(e['pair'])}\n"
                    f"  source: {_q(e['source'])}\n"
                    f"  decision: {_q(e['decision'])}\n"
                    f"  target: {_q(e['target'])}\n"
                    f"  comment: {_q(e['comment'])}\n")


def import_issues(close=False, limit=100):
    raw = _gh("issue", "list", "--label", "mapping-review", "--state",
              "open", "--limit", str(limit), "--json",
              "number,title,author,body")
    issues = json.loads(raw)
    seen = already_imported()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fresh, skipped, invalid = [], 0, []
    for issue in issues:
        n = issue["number"]
        if n in seen:
            skipped += 1
            continue
        p = parse_body(issue.get("body"))
        if not p:
            invalid.append(n)
            continue
        fresh.append({"issue": n, "imported_at": now,
                      "author": ((issue.get("author") or {}).get("login")
                                 or ""),
                      **p})
    if fresh:
        append_pending(fresh)
    print(f"imported={len(fresh)} already-seen={skipped} "
          f"invalid={invalid} -> {PENDING.name}")
    if close and fresh:
        for e in fresh:
            _gh("issue", "comment", str(e["issue"]), "--body",
                "Imported into curated/pending.yaml for maintainer review. "
                "Thank you!")
            _gh("issue", "close", str(e["issue"]))
        print(f"closed {len(fresh)} issues")
    return fresh
