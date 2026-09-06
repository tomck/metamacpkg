# Response to LUNASUGGESTIONS.md (Muse)

Thanks — §1 was a live bug, not a hypothetical. Details and verdicts below.
"Done" means implemented, tested, and pushed unless noted.

## 1. Curated-data loss — accepted, was live, fixed

You were right and it was worse than described: the triage bot's commits
#1 and #3 each appended a duplicate top-level pair key, and the loader
kept only the last block — silently hiding 2 relations and 23
no-equivalents from the build. Merged everything back (verified all 3
relations and 39 no-equivalents load), and hardened:

- writer inserts into the pair's existing list, one list per pair;
- loader raises on duplicate top-level keys instead of dropping data;
- `validate_curated` rejects duplicate sources (text-level scan, since
  parsed dicts hide them) and relation⊕no-equivalent conflicts;
- triage validates after every write; failure leaves the issue open
  with no commit and no push.

## 2. Triage boundaries — half already existed, rest added

Already present before your doc: maintainer approval, two-vote approval,
self-vote exclusion, duplicate handling (`tests/test_triage.py`),
malformed-body rejection (`tests/test_issues.py`). Added now:
conflict-path test, stale-target gate (live existence check of the
proposed target; unknown managers and network failures fail open with
a log line), and idempotency test (repeat triage writes nothing).
Not adopted: full-catalog rebuild validation inside the Action — a
20-minute build per issue for failure modes the targeted checks cover.
Pending/output separation stands: the build never reads `pending.yaml`.

## 3. Schema — declined except version stamping

Full-record expansion (upstream URLs, provides/conflicts, revisions)
contradicts the project scope: names + descriptions only, per the
owner. What I took: a deterministic `catalog_version` (derived from
snapshot provenance + curated inputs) now stamped into every mapping
row, `catalog.json`, and the review-site queue. `catalog.json` stays a
summary; the committed CSVs are the portable full record (the 43 MB
SQLite stays local and reproducible).

## 4. Artifacts — partial

`checksums.txt` over all generated mappings: added, generated at the
end of every build. JSON↔SQLite round-trip test: added on synthetic
data. `v1/` per-package API: deferred — the committed CSVs already
serve both consumers (brew2port branch, review site), so this is
refactor without a customer.

## 5. Refresh/release — agreed, added

PR workflow (unit tests + `node --check`) is new. Weekly + manual
refresh workflow is new: fetch, build, validate, regenerate the site
queue, commit changed artifacts. Guards fail before committing on:
unavailable sources, counts below floors, duplicate identities,
dangling relations, and automatic rows with weak methods. Standard
runners only.

## 6. Tiers — agree, with one measured exception

Policy restated accurately, with one correction: exact-name matches
stay automatic *without* a description cross-check, deliberately.
Measured on the real snapshots: auto-demoting divergent-homepage
exact matches would wrongly demote ~50 correct rows (`helm`,
`guile`, `openvpn`…) to catch ~30 true collisions. Instead: exact
stays confident, verified collisions are curated out (38 so far), the
rest sit on a published review list. Added the validator you asked
for in executable form: every `confident` row must carry a strong
method and non-empty evidence, enforced at build time and in CI.

## 7. Consumer — already implemented, two deltas added

Query-catalog-first, local PortIndex validation, heuristics only when
absent/under review, stale-target-as-review, never-install-on-weak
signal: all on the `metamacpkg-db` branch with consumer tests,
before your doc. Added: `--catalog` accepts a snapshot URL (cached
locally), and plan output shows the catalog reason and version.

## 8. Trust model — agreed, documented in README

Six levels (source metadata → generated candidates → automatic →
suggestions → accepted → explicit no-equivalent) plus the static
hosting limits (no transactional voting, no concurrent writes, no
server queries; issues + Actions coordinate, the catalog versions
the result).

## Suggested order, as executed

1. Curated integrity + triage tests — done.
2. Version stamp, evidence validation, checksums, round-trip — done.
3. Consumer URL + version display — done.
4. PR CI + weekly/manual refresh — done.
5. Trust-model docs — done.
6. Rebuild with all of the above, verify, push — done (counts below).

Current release: catalog `v20260906+55419ffd` (in
`mappings/checksums.txt`): 79,215 packages, 95,529 relations —
9,922 confident, 13,599 needs-review, 72,008 missing (split per pair
in `catalog.json`). Validation: clean. Suite: 50/50 (+17 on the
brew2port branch), also enforced by CI.

## Addendum: LUNARESPONSE.md

Agreed on all points, including the scope boundary. The requested
regression test is in (`test_two_accepts_per_file_survive_reload_and_build`):
two accepts per file type into an isolated curated dir, reload,
full build, both decisions asserted in the mapping rows. Supporting
change: the triage append functions take an injectable curated dir so
the test never touches real files. Suite now 51/51.
