"""Download raw package lists (names + descriptions) for Homebrew, MacPorts, Fink.

Snapshots land in data/raw/ with a provenance record. Re-run any time to
refresh; the build step only reads these files, so fetching is side-effect
free apart from the snapshot files themselves.
"""
import json
import subprocess
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

UA = {"User-Agent": "metamacpkg-fetch/0.1"}

BREW_FORMULA_URL = "https://formulae.brew.sh/api/formula.json"
BREW_CASK_URL = "https://formulae.brew.sh/api/cask.json"
MACPORTS_API = "https://ports.macports.org/api/v1/ports/"
FINK_GIT = "https://github.com/fink/fink-distributions.git"


def _get(url, timeout=90):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_brew(outdir=RAW):
    outdir.mkdir(parents=True, exist_ok=True)
    meta = {}
    for name, url, keep in (
        ("brew_formula", BREW_FORMULA_URL, None),
        ("brew_cask", BREW_CASK_URL, None),
    ):
        raw = _get(url)
        items = json.loads(raw)
        slim = [_slim_brew(i, name) for i in items]
        path = outdir / f"{name}.json"
        path.write_text(json.dumps(slim, indent=1) + "\n")
        meta[name] = {"url": url, "count": len(slim), "path": path.name}
        print(f"{name}: {len(slim)} records -> {path} ({len(raw)//1024} KiB raw)")
    return meta


def _slim_brew(item, kind):
    if kind == "brew_formula":
        return {
            "manager": "homebrew", "type": "formula",
            "name": item.get("name"),
            "aliases": item.get("aliases", []),
            "oldnames": item.get("oldnames", []),
            "desc": item.get("desc", ""),
            "homepage": item.get("homepage", ""),
            "version": (item.get("versions") or {}).get("stable", ""),
            "deprecated": bool(item.get("deprecated")),
            "disabled": bool(item.get("disabled")),
            "tap": item.get("tap", ""),
        }
    return {
        "manager": "homebrew", "type": "cask",
        "name": item.get("token"),
        "aliases": [],
        "oldnames": item.get("old_tokens", []) or [],
        "desc": item.get("desc", ""),
        "homepage": item.get("homepage", ""),
        "version": item.get("version", ""),
        "deprecated": False,
        "disabled": item.get("disabled", False),
        "tap": item.get("tap", ""),
    }


def fetch_macports(outdir=RAW, workers=8):
    outdir.mkdir(parents=True, exist_ok=True)
    first = json.loads(_get(MACPORTS_API + "?page=1"))
    total = first["count"]
    pages = (total + 49) // 50
    print(f"macports: {total} ports over {pages} pages")
    rows = []

    def one(page):
        payload = json.loads(_get(f"{MACPORTS_API}?page={page}"))
        return [_slim_port(p) for p in payload["results"]]

    rows.extend(_slim_port(p) for p in first["results"])
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, page_rows in enumerate(pool.map(one, range(2, pages + 1)), start=2):
            rows.extend(page_rows)
            if i % 100 == 0:
                print(f"  ... page {i}/{pages}")
    seen = {r["name"] for r in rows}
    assert len(seen) == len(rows), "duplicate port names in MacPorts dump"
    path = outdir / "macports.json"
    path.write_text(json.dumps(rows, indent=1) + "\n")
    print(f"macports: {len(rows)} records -> {path}")
    return {"url": MACPORTS_API, "count": len(rows), "path": path.name}


def _slim_port(p):
    return {
        "manager": "macports", "type": "port",
        "name": p.get("name"),
        "aliases": [],
        "oldnames": [],
        "desc": (p.get("description") or "") + (
            ("\n" + p["long_description"]) if p.get("long_description") else ""),
        "homepage": p.get("homepage") or "",
        "version": p.get("version") or "",
        "replaced_by": p.get("replaced_by"),
        "categories": p.get("categories") or [],
        "active": bool(p.get("active", True)),
    }


def fetch_fink(outdir=RAW):
    """Parse Fink .info files from a shallow sparse checkout.

    The same package stanza repeats across per-OS trees, so records are
    deduplicated by package name (keeping the highest version seen and the
    list of trees that carry it).
    """
    outdir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="fink-dist-"))
    run = lambda *a: subprocess.run(a, check=True, capture_output=True, cwd=tmp)
    run("git", "init", "-q")
    run("git", "remote", "add", "origin", FINK_GIT)
    run("git", "config", "extensions.partialClone", "origin")
    subprocess.run(["git", "sparse-checkout", "set", "--no-cone",
                    "*/stable/main/finkinfo/*.info",
                    "*/stable/main/finkinfo/*/*.info",
                    "*/stable/main/finkinfo/*/*/*.info"],
                   check=True, capture_output=True, cwd=tmp)
    subprocess.run(["git", "fetch", "--depth", "1", "--filter=blob:none",
                    "origin", "master"], check=True, cwd=tmp)
    subprocess.run(["git", "checkout", "FETCH_HEAD"], check=True,
                   capture_output=True, cwd=tmp)
    rev = subprocess.run(["git", "rev-parse", "FETCH_HEAD"],
                         check=True, capture_output=True, text=True,
                         cwd=tmp).stdout.strip()
    infos = sorted(tmp.rglob("*.info"))
    print(f"fink: {len(infos)} .info files")
    pkgs = {}
    for info in infos:
        try:
            fields = _parse_info(info.read_text(errors="replace").splitlines())
        except Exception:
            continue
        name = fields.get("Package")
        if not name:
            continue
        rel = info.relative_to(tmp)
        tree = rel.parts[0] if rel.parts else ""
        section = info.parent.name
        rec = pkgs.setdefault(name, {
            "manager": "fink", "type": "package", "name": name,
            "aliases": [], "oldnames": [],
            "desc": "", "homepage": "", "version": "",
            "trees": [], "sections": [],
        })
        desc = _clean_heredoc(fields.get("Description", ""))
        detail = _clean_heredoc(fields.get("DescDetail", "")).replace("\\n", "\n")
        if len(desc) + len(detail) > len(rec["desc"]):
            rec["desc"] = (desc + ("\n" + detail if detail else "")).strip()
        if not rec["homepage"] and fields.get("Homepage"):
            rec["homepage"] = fields["Homepage"]
        ver = fields.get("Version", "")
        if _ver_gt(ver, rec["version"]):
            rec["version"] = ver
        if tree and tree not in rec["trees"]:
            rec["trees"].append(tree)
        if section and section not in rec["sections"]:
            rec["sections"].append(section)
    rows = sorted(pkgs.values(), key=lambda r: r["name"])
    path = outdir / "fink.json"
    path.write_text(json.dumps(rows, indent=1) + "\n")
    print(f"fink: {len(rows)} packages -> {path}")
    return {"url": FINK_GIT, "revision": rev, "count": len(rows),
            "path": path.name}


def _parse_info(lines):
    """Minimal Fink .info parser: 'Key: value', '{...}' blocks kept raw."""
    fields, key, buf = {}, None, []
    for line in lines:
        if line.startswith("#") or not line.strip():
            continue
        if line[0] in " \t" and key:
            buf.append(line.strip())
            continue
        if key:
            fields[key] = " ".join(buf)
        if ":" in line:
            key, _, val = line.partition(":")
            key, buf = key.strip(), [val.strip()]
        else:
            key, buf = None, []
    if key:
        fields[key] = " ".join(buf)
    return fields


def _clean_heredoc(s):
    """Drop Fink `<<` heredoc marker lines from descriptions."""
    return "\n".join(ln for ln in s.splitlines() if ln.strip() != "<<").strip()


def _ver_gt(a, b):
    def parts(s):
        out = []
        for tok in str(s).replace("-", ".").split("."):
            out.append((0, int(tok)) if tok.isdigit() else (1, tok))
        return out
    return parts(a) > parts(b) if b else bool(a)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["brew", "macports", "fink"])
    args = ap.parse_args()
    prov_path = RAW / "provenance.json"
    meta = json.loads(prov_path.read_text()) if prov_path.exists() else {}
    meta["fetched_at"] = datetime.now(timezone.utc).isoformat()
    if args.only in (None, "brew"):
        meta.update(fetch_brew())
    if args.only in (None, "macports"):
        meta.update({"macports_api": fetch_macports()})
    if args.only in (None, "fink"):
        meta.update({"fink_git": fetch_fink()})
    prov_path.write_text(json.dumps(meta, indent=2) + "\n")
    print("provenance written")


if __name__ == "__main__":
    main()
