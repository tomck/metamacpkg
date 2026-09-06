# Suggestions for Meta

Meta already has the important pieces of the project in place: pairwise Homebrew/MacPorts/Fink mappings, conservative matching, negative examples, a static review site, and GitHub Actions for human review. Please preserve that work and use the following as a focused hardening pass.

## 1. Protect curated data from silent loss

`curated/relations.yaml` and `curated/no_equivalent.yaml` must not contain duplicate top-level pair keys. Appending a second block for the same pair can cause a simple YAML parser to replace the earlier block.

Use one list per pair and append new entries to the existing list. Add a validation test that loads a file containing two entries under the same pair and confirms that both entries survive.

Also reject duplicate curated decisions for the same source, and reject a curated relationship that conflicts with a curated `no-equivalent` decision.

## 2. Keep the human-review Actions, but test their boundaries

The new issue and reaction workflow is useful. Do not replace it with a different review system. Add tests for:

- a maintainer approval;
- two independent community approvals;
- self-voting;
- duplicate proposals;
- conflicting proposals;
- malformed or edited issue bodies;
- an issue whose proposed target disappeared from the latest catalog;
- repeated triage runs, which must be idempotent;
- two accepted issues processed close together, which must not lose either curated entry.

The workflow should validate the generated catalog before committing accepted decisions. A failed validation must leave the issue open and must not push a partial change.

Keep imported proposals separate from trusted curated data. A pending proposal should never become an automatic mapping until it has passed the normal validation and promotion path.

## 3. Make the catalog schema complete

The SQLite and JSON catalog should retain the full normalized package record:

- manager;
- package type;
- native package name;
- aliases and historical names;
- description;
- homepage;
- upstream source URL or repository;
- version and revision;
- provides, conflicts, replaces, and renamed-by metadata;
- source URL and source revision;
- last-seen timestamp.

Each relationship should contain:

- relationship type;
- source package identity;
- target package identity, or an explicit representation for `no-equivalent`;
- confidence;
- matching method;
- structured evidence;
- review status;
- source catalog versions.

The complete catalog should be available in `catalog.json`. A summary report can remain separate.

## 4. Generate stable portable artifacts

Add a single deterministic build command that produces:

```text
catalog.json
catalog.sqlite
packages.json
relations.json
v1/package/<manager>/<type>/<name>.json
v1/lookup/<manager>/<type>/<name>.json
v1/relations/<manager>/<type>/<name>.json
checksums.txt
mapping-report.md
```

The build should use a clean output directory, stable ordering, a catalog version derived from the source snapshots and curated inputs, and checksums generated after all artifacts are complete.

Add a round-trip test: generate the JSON and SQLite artifacts, query both, and confirm that they contain the same package and relationship records.

## 5. Add the missing refresh and release path

Use standard GitHub-hosted runners only. Add workflows for:

- pull-request tests and validation;
- weekly source refresh;
- manual `workflow_dispatch` refresh;
- artifact generation;
- catalog validation;
- committing changed generated artifacts;
- GitHub Pages deployment.

The refresh workflow should fail before committing if any source is unavailable, if counts unexpectedly collapse, if identities duplicate, if relationship endpoints are missing, or if an automatic relationship has weak evidence.

Record source URL, fetch time, source revision, and record count in provenance metadata.

## 6. Keep mapping tiers conservative

The current policy is good. Preserve these rules:

- curated decisions are strongest;
- exact names may be automatic only with the documented collision checks;
- normalized names and aliases must be unambiguous;
- upstream identity should compare the actual project identity, not merely a shared host;
- description similarity can suggest a relationship but must not prove equivalence;
- fuzzy spelling must remain review-only;
- `macs-fan-control` and `qmail-spamcontrol` must never become an automatic relationship.

Add a validation rule that every automatic relationship has structured evidence and an allowed strong matching method. Add tests for unrelated shared-name examples such as `git-svn`/`gitsign`, `node`/`ode`, `telnet`/`DateLine`, and `muse-code`/`mmencode`.

## 7. Finish the brew2port consumer contract

The `brew2port` integration should consume `catalog.json` or `catalog.sqlite` from a specified snapshot URL or local snapshot directory. It should:

- query the catalog before local matching;
- verify that a proposed MacPorts target still exists in the local PortIndex;
- use local heuristics only when the source package is absent from the catalog or the catalog marks it for review;
- display relationship type, confidence, evidence, and catalog version in the migration plan;
- never install or remove anything based solely on a weak heuristic;
- treat a stale catalog target as a review condition rather than silently substituting a fuzzy result.

Add consumer tests for a confident catalog match, a `needs-review` match, a `no-equivalent` result, a stale target, and the named negative example.

## 8. Document the trust model

Document the difference between:

- source metadata;
- generated candidate relationships;
- automatic relationships;
- human review suggestions;
- accepted human decisions;
- explicit `no-equivalent` decisions.

Explain that GitHub Pages is static hosting: it can serve snapshots and review queues, but it cannot safely provide transactional voting, authoritative concurrent writes, or arbitrary server-side queries. GitHub issues and Actions are the review coordination layer; the generated catalog remains the versioned result.

## Suggested order

1. Add duplicate-curation and idempotent-triage tests.
2. Fix curated-file writing so existing decisions cannot disappear.
3. Complete the package and relationship schema.
4. Add deterministic artifact generation and validation.
5. Add weekly/manual refresh and release workflows.
6. Update `brew2port` to consume the published snapshot.

Please report the exact catalog version, source revisions, package counts, relationship counts, automatic count, review count, and validation result for each generated release.
