Create a new public GitHub repository named `macpkg-catalog`.

This must be an independent project, not a fork of `brew2port`. Its purpose is to build and publish a neutral catalog of package identities and relationships among Homebrew, MacPorts, and Fink.

For reference, `brew2port` may be found at https://github.com/tomck/homebrew-brew2port/

Project goals:

1. Import package metadata from:

   - Homebrew formula JSON API:
     `https://formulae.brew.sh/api/formula.json`
   - Homebrew cask JSON API:
     `https://formulae.brew.sh/api/cask.json`
   - MacPorts port index/API
   - Fink package indexes and package description metadata

2. Normalize each package into a common record containing:

   - package manager
   - package type
   - native package name
   - aliases and historical names
   - description
   - homepage
   - upstream source URL or repository
   - version and revision
   - provides, conflicts, replaces, and renamed-by metadata
   - source URL and source revision
   - last-seen timestamp

3. Store cross-manager relationships separately from package records.

Supported relationship types:

   - `equivalent`
   - `renamed-to`
   - `replaced-by`
   - `split-from`
   - `split-into`
   - `provides`
   - `conflicts`
   - `no-equivalent`

Every relationship must contain:

   - source package
   - target package
   - confidence
   - matching method
   - evidence
   - review status
   - source catalog versions

Do not treat character similarity as proof of equivalence. For example, never map `macs-fan-control` to `qmail-spamcontrol` merely because the names share text.

4. Use a tiered mapping pipeline:

   - manually curated relationships
   - exact package-name matches
   - normalized-name matches
   - official aliases and old names
   - upstream homepage/repository identity
   - provides/replaces metadata
   - description similarity
   - conservative fuzzy suggestions only

Only curated or strongly evidenced relationships should be marked `automatic`. Ambiguous or spelling-only matches must be marked `needs-review` or omitted from the automatic catalog.

5. Publish these artifacts:

   - `catalog.json` — complete portable catalog
   - `catalog.sqlite` — queryable local database
   - `packages.json` — package records
   - `relations.json` — cross-manager relationships
   - `v1/lookup/...` — static exact-lookup API files
   - `checksums.txt`
   - a human-readable mapping report

Suggested static API layout:

   `v1/package/homebrew/formula/wget.json`
   `v1/package/homebrew/cask/docker-desktop.json`
   `v1/package/macports/port/wget.json`
   `v1/package/fink/package/wget.json`
   `v1/relations/homebrew/formula/wget.json`

6. Add a command-line query tool:

   `macpkg-catalog lookup homebrew formula wget`
   `macpkg-catalog relations homebrew formula wget`
   `macpkg-catalog search "video editor"`
   `macpkg-catalog export --format sqlite`

The query tool must work entirely offline against the downloaded SQLite or JSON snapshot.

7. Add curated data files:

   - `curated/relations.yaml`
   - `curated/aliases.yaml`
   - `curated/no-equivalent.yaml`
   - `curated/sources.yaml`

Curated entries must support comments explaining why a relationship is valid or invalid.

8. Add automated validation:

   - reject duplicate package identities
   - reject relationships pointing to nonexistent packages
   - reject automatic mappings with weak evidence
   - detect conflicting curated relationships
   - ensure package names are valid for their manager
   - test known negative examples, including:
     `macs-fan-control` versus `qmail-spamcontrol`

9. Add GitHub Actions workflows using only standard public runners:

   - test on every pull request
   - refresh source catalogs weekly
   - allow manual refresh with `workflow_dispatch`
   - generate the artifacts
   - validate them
   - commit or publish changed artifacts
   - deploy the static API to GitHub Pages

Do not use larger paid runners.

10. Add documentation covering:

   - catalog schema
   - source formats
   - mapping confidence policy
   - how to add a curated relationship
   - how to run the generator locally
   - how to query the SQLite database
   - how `brew2port` and future Fink migration tools consume the catalog
   - limitations of static GitHub Pages hosting

11. After the catalog project is working, update `brew2port` to:

   - download the published catalog snapshot
   - query it before performing local matching
   - validate that the target MacPorts port still exists locally
   - use heuristic matching only for packages absent from the catalog
   - show the relationship evidence and catalog version in migration plans
   - never install or remove anything solely because of a weak heuristic
