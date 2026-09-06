"""Triage mapping-review issues (driven by GitHub Actions, runnable locally).

Rules:
  * author is the maintainer -> accept immediately.
  * maintainer thumbs-ups anyone's issue -> accept immediately.
  * >= REQUIRED_VOTES (default 2) thumbs-ups from other users -> accept.
  * proposal already in curated/ identically -> comment + close as duplicate.
  * proposal contradicts curated/ -> `conflict` label, stays open.
  * unparseable body -> `invalid` label + comment, stays open.
  * otherwise -> wait (votes accrue; a scheduled run rechecks).

Accepting writes to curated/relations.yaml or no_equivalent.yaml,
drops the card from docs/data/queue-<pair>.json, commits, pushes,
comments, and closes the issue.
"""
import json
import os
import re
import subprocess
from pathlib import Path

from .curated import load_curated
from .issues import parse_body

ROOT = Path(__file__).resolve().parent.parent

REPO = os.environ.get("TRIAGE_REPO", "tomck/metamacpkg")
MAINTAINER = os.environ.get("TRIAGE_MAINTAINER", "tomck")
REQUIRED_VOTES = int(os.environ.get("TRIAGE_REQUIRED_VOTES", "2"))

# Test hook: triage_all/triage_issue pass None; tests inject a fake.
_opener = None

PAIR_TO = {"brew-formula": ("homebrew", "formula"),
           "brew-cask": ("homebrew", "cask"),
           "macports": ("macports", "port"),
           "fink": ("fink", "package")}


def _pair_to(pair):
    try:
        _, to = pair.split("-to-", 1)
        return PAIR_TO[to]
    except (ValueError, KeyError):
        return None


def _gh(*args, input_text=None):
    return subprocess.run(["gh", *args], check=True, capture_output=True,
                          text=True, input=input_text).stdout


def _q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def evaluate(*, author, maintainer, voters, proposal_exists):
    """Pure verdict: (verdict, reason). proposal_exists is None,
    ("relation", target), or ("no-equivalent", None)."""
    if proposal_exists is not None:
        return ("duplicate", f"already recorded as {proposal_exists[0]}")
    if proposal_exists is not None:
        return ("duplicate", f"already recorded as {proposal_exists[0]}")
    voters = set(voters or []) - {author}
    if author == maintainer or maintainer in voters:
        return ("accept", "maintainer approval")
    if len(voters) >= REQUIRED_VOTES:
        return ("accept", f"{len(voters)} community approvals")
    return ("wait", f"{len(voters)}/{REQUIRED_VOTES} approvals")


def curated_existing(pair, source, decision, target):
    """None, or ("relation", target) / ("no-equivalent", None) describing
    what curated/ already says. A contradicting entry is returned as
    ("conflict", description)."""
    cur = load_curated()
    rel = (cur.relations.get(pair) or {}).get(source)
    noeq = (cur.no_equiv.get(pair) or {}).get(source)
    if decision == "no-equivalent":
        if noeq:
            return ("duplicate", "no-equivalent")
        if rel:
            return ("conflict", f"curated maps to {rel['target']}")
        return None
    if rel:
        if rel["target"] == target:
            return ("duplicate", f"relation to {target}")
        return ("conflict", f"curated maps to {rel['target']}")
    if noeq:
        return ("conflict", "curated says no equivalent")
    return None


def target_exists(to_manager, to_type, name, opener=None):
    """Live existence check for a proposed target. Unknown managers or
    network failures fail open (True) with a log line; a confirmed 404
    fails closed (False)."""
    import urllib.request
    from urllib.parse import quote
    urls = {
        ("macports", "port"): "https://ports.macports.org/api/v1/ports/{}/",
        ("homebrew", "formula"): "https://formulae.brew.sh/api/formula/{}.json",
        ("homebrew", "cask"): "https://formulae.brew.sh/api/cask/{}.json",
    }
    url = urls.get((to_manager, to_type))
    if url is None:
        print(f"no existence check for {to_manager}/{to_type}; skipping")
        return True
    req = urllib.request.Request(
        url.format(quote(name, safe="")),
        headers={"User-Agent": "metamacpkg-triage/0.1"})
    import urllib.error
    try:
        if opener:
            return bool(opener(req))
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        print(f"existence check for {name} failed open: HTTP {e.code}")
        return True
    except Exception as e:
        print(f"existence check for {name} failed open: {e}")
        return True


def plus_one_voters(issue_number):
    out = _gh("api", f"repos/{REPO}/issues/{issue_number}/reactions",
              "--paginate", "--jq", ".[] | select(.content == \"+1\") | .user.login")
    return {l for l in out.splitlines() if l.strip()}


def open_review_issues(limit=100):
    raw = _gh("issue", "list", "--repo", REPO, "--label", "mapping-review",
              "--state", "open", "--limit", str(limit), "--json",
              "number,title,author,body,labels")
    return json.loads(raw)


def insert_entry(text, pair, entry_lines):
    """Append list items into the pair's existing list (one list per pair),
    creating the block when absent. Pure text edit preserving comments."""
    if not text:
        return f"{pair}:\n" + "".join(entry_lines)
    lines = text.splitlines(keepends=True)
    if not text.endswith("\n"):
        lines[-1] = lines[-1] + "\n"
    try:
        start = next(i for i, l in enumerate(lines)
                     if re.match(rf"^{re.escape(pair)}:$", l.rstrip("\n")))
    except StopIteration:
        return text + ("\n" if not text.endswith("\n\n") else "") + \
            f"{pair}:\n" + "".join(entry_lines)
    end = start + 1
    while end < len(lines) and (lines[end].strip() == "" or
                                lines[end][0] in " \t"):
        end += 1
    return "".join(lines[:end] + entry_lines + lines[end:])


def _texts():
    d = ROOT / "curated"
    out = []
    for name in ("relations.yaml", "no_equivalent.yaml"):
        p = d / name
        out.append((name, p.read_text() if p.exists() else ""))
    return out


def _write_validated(path, pair, entry_lines):
    text = path.read_text() if path.exists() else ""
    path.write_text(insert_entry(text, pair, entry_lines))
    from .curated import load_curated, validate_curated
    cur = load_curated()  # raises on duplicate pair keys
    validate_curated(cur, _texts())  # raises on dup sources/conflicts
    return cur


def append_relation(pair, source, target, comment):
    _write_validated(
        ROOT / "curated" / "relations.yaml", pair,
        [f"  - from: {_q(source)}\n", f"    to: {_q(target)}\n",
         f"    comment: {_q(comment)}\n"])


def append_no_equivalent(pair, source, comment):
    _write_validated(
        ROOT / "curated" / "no_equivalent.yaml", pair,
        [f"  - name: {_q(source)}\n", f"    comment: {_q(comment)}\n"])


def drop_queue_card(pair, source):
    path = ROOT / "docs" / "data" / f"queue-{pair}.json"
    if not path.exists():
        return False
    data = json.loads(path.read_text())
    before = len(data["cards"])
    data["cards"] = [c for c in data["cards"] if c["source"] != source]
    data["count"] = len(data["cards"])
    if len(data["cards"]) == before:
        return False
    path.write_text(json.dumps(data) + "\n")
    return True


def git_commit_push(message):
    subprocess.run(["git", "add", "curated/relations.yaml",
                    "curated/no_equivalent.yaml", "docs/data/queue-*.json"],
                   check=True, cwd=ROOT)
    subprocess.run(["git", "-c", "user.name=github-actions[bot]",
                    "-c", "user.email=github-actions[bot]@users.noreply.github.com",
                    "commit", "-m", message], check=True, cwd=ROOT)
    try:
        subprocess.run(["git", "push"], check=True, capture_output=True,
                       cwd=ROOT)
    except subprocess.CalledProcessError:
        subprocess.run(["git", "pull", "--rebase"], check=True, cwd=ROOT)
        subprocess.run(["git", "push"], check=True, capture_output=True,
                       cwd=ROOT)


def comment(issue_number, text):
    _gh("issue", "comment", str(issue_number), "--repo", REPO, "--body", text)


def close(issue_number):
    _gh("issue", "close", str(issue_number), "--repo", REPO)


def label(issue_number, *labels):
    _gh("issue", "edit", str(issue_number), "--repo", REPO,
        "--add-label", ",".join(labels))


def triage_issue(issue, dry_run=False):
    n = issue["number"]
    author = ((issue.get("author") or {}).get("login")) or ""
    labels = {l["name"] for l in issue.get("labels", [])}
    proposal = parse_body(issue.get("body"))
    if not proposal:
        if "invalid" not in labels and not dry_run:
            label(n, "invalid")
            comment(n, "I couldn't find a valid proposal block in this issue. "
                       "Please submit via the review site so the machine-readable "
                       "block is included.")
        return ("invalid", n)
    existing = curated_existing(proposal["pair"], proposal["source"],
                                proposal["decision"], proposal["target"])
    if existing and existing[0] == "conflict":
        if "conflict" not in labels and not dry_run:
            label(n, "conflict")
            comment(n, f"This conflicts with the current database ({existing[1]}). "
                       "Leaving open for a human to sort out.")
        return ("conflict", n)
    if existing and existing[0] == "duplicate":
        if not dry_run:
            comment(n, f"Already in the database ({existing[1]}), closing as duplicate.")
            close(n)
        return ("duplicate", n)
    voters = plus_one_voters(n)
    verdict, reason = evaluate(author=author, maintainer=MAINTAINER,
                               voters=voters, proposal_exists=None)
    if verdict == "wait":
        return ("wait", n)
    assert verdict == "accept", verdict
    # accept
    target = proposal["target"] or "∅ (no equivalent)"
    if proposal["decision"] != "no-equivalent" and not dry_run:
        to = _pair_to(proposal["pair"])
        if (to and not target_exists(to[0], to[1], proposal["target"],
                                     opener=_opener)):
            comment(n, f"Target {proposal['target']!r} is not in the current "
                       f"{to[0]} catalog, so this needs a human look. Leaving open.")
            return ("stale-target", n)
    credit = (f"Accepted from #{n} by @{author or 'unknown'} "
              f"({reason})" + (f": {proposal['comment'][:200]}"
                               if proposal.get("comment") else ""))
    if not dry_run:
        if proposal["decision"] == "no-equivalent":
            append_no_equivalent(proposal["pair"], proposal["source"], credit)
        else:
            append_relation(proposal["pair"], proposal["source"],
                            proposal["target"], credit)
        drop_queue_card(proposal["pair"], proposal["source"])
        git_commit_push(f"Accept mapping proposal #{n}: "
                        f"{proposal['source']} -> {target}")
        comment(n, f"Accepted and committed ({reason}).")
        close(n)
    return (f"accept ({reason})", n)


def triage_all(dry_run=False, limit=100):
    results = []
    for issue in open_review_issues(limit):
        try:
            results.append(triage_issue(issue, dry_run=dry_run))
        except subprocess.CalledProcessError as e:
            results.append((f"error: {e}", issue["number"]))
    for verdict, n in results:
        print(f"#{n}: {verdict}")
    return results
