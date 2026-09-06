# Response to Meta’s hardening update

This is a good resolution. The most serious issue was the curated-data loss, and you confirmed that it had already occurred in real triage commits. Fixing the writer, rejecting duplicate keys, validating after writes, and adding idempotency coverage directly addresses the trust problem.

The new review safeguards are also appropriate. Maintainer approval, community voting, malformed issue handling, conflict detection, stale-target checks, pending-data separation, and repeated-run safety give the human review process a clear boundary. Keeping the review Actions and strengthening their tests is the right design.

The refresh workflow, source-count floors, identity checks, dangling-relation checks, evidence validation, checksums, catalog version, PR CI, and Pages deployment complete the operational side of the mapping project. The reported release counts and clean validation result make the current state measurable and reproducible.

I accept the scope decision for this repository: `metamacpkg` is a mapping database for migration support, based on names, descriptions, homepages, versions, and curated review. It does not need to become a full package metadata archive if that is outside the owner’s goal.

For clarity, the following remain future work only if the project later becomes the broader neutral package catalog originally described:

- complete package records with upstream repositories, aliases, historical names, provides, conflicts, replaces, source revisions, and last-seen timestamps;
- typed relationship records with structured source and target identities;
- complete `catalog.json`, `packages.json`, and `relations.json` snapshots;
- static `v1/package`, `v1/lookup`, and `v1/relations` endpoints;
- a consumer contract independent of the six migration CSVs.

One final regression test would be valuable: simulate two accepted review decisions for the same pair, reload the curated files, and confirm that both decisions survive the next build. This test should cover both relation entries and `no-equivalent` entries because it is the exact failure mode that prompted this review.

With that test in place, I consider the current `metamacpkg` mapping system a credible base for `brew2port` migration planning. The full neutral catalog remains a separate product decision rather than an outstanding defect in this mapping-focused implementation.
