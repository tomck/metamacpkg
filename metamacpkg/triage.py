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


def plus_one_voters(issue_number):
    out = _gh("api", f"repos/{REPO}/issues/{issue_number}/reactions",
              "--paginate", "--jq", ".[] | select(.content == \"+1\") | .user.login")
    return {l for l in out.splitlines() if l.strip()}


def open_review_issues(limit=100):
    raw = _gh("issue", "list", "--repo", REPO, "--label", "mapping-review",
              "--state", "open", "--limit", str(limit), "--json",
              "number,title,author,body,labels")
    return json.loads(raw)


def append_relation(pair, source, target, comment):
    path = ROOT / "curated" / "relations.yaml"
    with open(path, "a") as f:
        f.write(f"{pair}:\n  - from: {_q(source)}\n    to: {_q(target)}\n"
                f"    comment: {_q(comment)}\n")
    load_curated()  # fail loudly if the YAML no longer parses


def append_no_equivalent(pair, source, comment):
    path = ROOT / "curated" / "no_equivalent.yaml"
    with open(path, "a") as f:
        f.write(f"{pair}:\n  - name: {_q(source)}\n"
                f"    comment: {_q(comment)}\n")
    load_curated()


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
