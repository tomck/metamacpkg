# metamacpkg — confident 3-way package maps (Homebrew ↔ MacPorts ↔ Fink)

`brew2port`'s fuzzy matcher invents mappings: `git-svn` → `gitsign`,
`node` → `ode`, `telnet` → `DateLine`, `macs-fan-control` →
`qmail-spamcontrol`, `muse-code` → `mmencode`. Every one of those would
install the **wrong program** during a migration.

metamacpkg fixes this at the root: it downloads all three repositories
(names + descriptions only), matches them in tiers, and publishes
**confident one-to-one mappings plus explicit missing lists**. Spelling
similarity alone is never treated as evidence.

## Repository layout

| Path | What it is |
|---|---|
| `metamacpkg/` | Python tool (fetch, match, db, cli, report, curated) |
| `curated/` | Hand-reviewed decisions (YAML with comments) |
| `data/raw/` | Downloaded snapshots, git-ignored, reproducible via `make fetch` |
| `data/catalog.sqlite`, `data/catalog.json` | Built database + summary (git-ignored) |
| `mappings/` | **The deliverable**: confident per-pair CSVs + `REPORT.md` |
| `brew2port/` | Nested checkout of upstream brew2port on branch `metamacpkg-db` (its own git repo, never merged to its `main`) |
| `PLAN.md`, `migration-preview.csv` | Reference material (Codex plan + old heuristic output) |
| `tests/` | Guardrail tests: wrong answers the matcher must never give |

## Quick start

```sh
make fetch    # download Homebrew + MacPorts + Fink snapshots (~5 min)
make build    # match everything, write mappings/*.csv + catalog.sqlite
make report   # mappings/REPORT.md with missing-program lists
make test     # guardrail tests
```

Query the database offline:

```sh
python3 -m metamacpkg.cli lookup homebrew formula wget
python3 -m metamacpkg.cli search "video editor" --limit 10
python3 -m metamacpkg.cli review brew-formula-to-macports --limit 30
sqlite3 data/catalog.sqlite "SELECT * FROM relations WHERE status='missing' LIMIT 5;"
```

## Confidence policy

| Tier | Method | Confident? |
|---|---|---|
| Hand-curated entry | `curated` | yes (1.0) |
| Identical name | `exact` | yes (1.0) |
| Same after case/punctuation folding, unambiguous | `normalized` | yes (0.96) |
| Official alias / old name | `alias` | yes (0.95) |
| MacPorts `replaced_by` pointer | `replaced-by` | yes (0.95) |
| Identical upstream homepage + overlapping description | `homepage` | yes (0.90) |
| Spelling lookalikes (`fuzzy`) | suggestion only | **never** |

`normalized` requires a 1:1 fold: if two targets fold to the same key the
row becomes `needs-review` instead of guessing. `homepage` requires the
full normalized URL (forge hosts like github.com compare owner/repo path,
never bare domain) plus description token overlap ≥ 0.15, so shared
forge or vendor pages can't force a false match.

Every row lands in exactly one state: `confident`, `needs-review`
(human churn queue with evidence + lookalikes), or `missing`
(confirmed absent, e.g. `muse-code` on MacPorts).

## Crowdsourced review site

Uncertain mappings are outsourced to humans at
<https://tomck.github.io/metamacpkg/> (static site, served from `docs/`
via GitHub Pages — no server to run). Each card shows the package, why
the pipeline is unsure, and the lookalikes; a verdict opens a
pre-filled `mapping-review` GitHub issue. Import them with:

```sh
python3 -m metamacpkg.cli import-issues        # -> curated/pending.yaml
python3 -m metamacpkg.cli import-issues --close # also thank + close issues
```

`pending.yaml` is deliberately never read by the build — promote
reviewed entries into `curated/` by hand. Refresh the site data with
`make webdata` (then commit + push).

## Churning through the queue

```sh
python3 -m metamacpkg.cli review brew-cask-to-macports --limit 30
```

Decisions go into `curated/` with a comment explaining the evidence:

```yaml
# curated/no_equivalent.yaml
brew-cask-to-macports:
  - name: muse-code
    comment: no MacPorts port; closest spelling (mmencode) is an unrelated encoder
```

```yaml
# curated/relations.yaml
brew-formula-to-macports:
  - from: handbrake
    to: HandBrake
    comment: same upstream (handbrake.fr), CLI vs GUI split documented upstream
```

Re-run `make build` and the curated rows override the pipeline at
confidence 1.0.

## brew2port branch

`brew2port/` is a clone of
[homebrew-brew2port](https://github.com/tomck/homebrew-brew2port) on the
`metamacpkg-db` branch. That branch adds a catalog backend: it loads
`mappings/brew-*-to-macports.csv`, trusts only `confident` rows, marks
everything else `needs-review`, and validates the target port still
exists locally before planning. See `brew2port/BRANCH.md` there.
It is deliberately never merged back to its `main`.

## Sources & provenance

- Homebrew formulae/casks: `https://formulae.brew.sh/api/{formula,cask}.json`
- MacPorts: `https://ports.macports.org/api/v1/ports/` (paginated, 50/page)
- Fink: `https://github.com/fink/fink-distributions` `.info` files
  (shallow sparse checkout; deduped across per-OS trees)

`data/raw/provenance.json` records URLs, counts, and fetch time.
Only names, descriptions, homepages, and versions are kept — no bottles,
no dependency graphs.

## Limitations

- Exact-name matches assume same-name programs are the same program;
  homepage evidence is recorded on each row so reviewers can spot the
  rare collision.
- Fink trees lag upstream; a package missing from Fink may just be
  outdated rather than truly absent.
- MacPorts has ~52k ports including `pyXY-` version variants; the CSVs
  map to the literal port name, variants included.
- The static CSVs are a snapshot: refresh with `make fetch build`.
