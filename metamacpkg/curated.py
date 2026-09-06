"""Curated decisions: hand-confirmed mappings and confirmed gaps.

Files (YAML, comments welcome):
  curated/relations.yaml     from -> to equivalences the pipeline can't prove
  curated/no_equivalent.yaml confirmed-missing packages with reasons
  curated/aliases.yaml       extra known aliases for a package

Keys name a directed pair, e.g. `brew-formula-to-macports`.
Package refs use the native name (`gtk+3`, `python@3.14`, `HandBrake`).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURATED = ROOT / "curated"


class Curated:
    def __init__(self):
        self.relations = {}   # pair-key -> {source: {target, comment}}
        self.no_equiv = {}    # pair-key -> {source: comment}
        self.aliases = {}     # (manager, type, name) -> [aliases]


def _parse_simple_yaml(text):
    """Parse the small YAML subset our curated files use.

    Supports: top-level `key:` maps, lists of `key: value` dicts, scalar
    strings (single/double/unquoted), and `#` comments. Anything fancier
    raises ValueError telling the author to simplify.
    """
    root, stack = {}, []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0] if _hash_starts_comment(raw) else raw
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if "\t" in line[:indent]:
            raise ValueError(f"line {lineno}: tabs not allowed")
        line = line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if line.startswith("- "):
            item = line[2:].strip()
            parent = stack[-1][1] if stack else None
            if not isinstance(parent, list):
                raise ValueError(f"line {lineno}: '-' without a list parent")
            if ": " in item or item.endswith(":"):
                d = {}
                parent.append(d)
                stack.append((indent, d))
                _put_kv(d, item, lineno)
            else:
                parent.append(_scalar(item))
        elif line.endswith(":") and ": " not in line:
            key = _scalar(line[:-1])
            if not stack and key in root:
                raise ValueError(
                    f"line {lineno}: duplicate top-level key {key!r}; "
                    f"use one list per pair")
            parent = stack[-1][1] if stack else None
            new = {} if _next_is_map(text, lineno) else []
            if isinstance(parent, dict):
                parent[key] = new
            elif parent is None:
                root[key] = new
                stack.append((indent, new))
                continue
            else:
                raise ValueError(f"line {lineno}: can't nest under a list")
            stack.append((indent, new))
        elif ": " in line:
            parent = stack[-1][1] if stack else root
            if not isinstance(parent, dict):
                raise ValueError(f"line {lineno}: key/value outside a map")
            _put_kv(parent, line, lineno)
        else:
            raise ValueError(f"line {lineno}: cannot parse {line!r}")
    return root


def _hash_starts_comment(raw):
    # A '#' starts a comment unless inside quotes (good enough for our files).
    in_s = in_d = False
    for ch in raw:
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif ch == "#" and not in_s and not in_d:
            return True
    return False


def _next_is_map(text, lineno):
    lines = text.splitlines()
    for nxt in lines[lineno:]:
        s = nxt.strip()
        if not s or s.startswith("#"):
            continue
        return not s.startswith("- ")
    return True


def _put_kv(d, item, lineno):
    k, _, v = item.partition(":")
    k, v = k.strip(), v.strip()
    if not k or not v:
        raise ValueError(f"line {lineno}: bad key/value {item!r}")
    d[_scalar(k)] = _scalar(v)


def _scalar(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    if s in ("null", "Null", "~"):
        return None
    return s


def _duplicate_sources(text, field):
    """Sources listed twice under one pair block (dicts would hide these)."""
    dupes = []
    pair, seen = None, set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        mkey = re.match(r"^([A-Za-z0-9_-]+):$", raw)
        if mkey:
            pair, seen = mkey.group(1), set()
            continue
        m = re.match(r"^- " + field + r":\s*(.+)$", line)
        if m and pair:
            val = m.group(1).strip().strip("\"'")
            if val in seen:
                dupes.append(f"{pair}: duplicate {field} {val!r}")
            seen.add(val)
    return dupes


def validate_curated(cur, texts=()):
    """Reject duplicate decisions and relation/no-equivalent conflicts.

    texts are (label, raw YAML) pairs for duplicate-source scanning;
    parsed dicts cannot show those since duplicate keys collapse.
    """
    errors = []
    for label, text in texts:
        field = "from" if "relations" in label else "name"
        errors.extend(f"{label} {d}" for d in _duplicate_sources(text, field))
    for pair in set(cur.relations) & set(cur.no_equiv):
        for source in set(cur.relations[pair]) & set(cur.no_equiv[pair]):
            errors.append(f"{pair}: {source!r} has both a relation "
                          f"and a no-equivalent")
    if errors:
        raise ValueError("curated validation failed:\n" + "\n".join(errors))
    return True


def load_curated(curdir=CURATED):
    cur = Curated()
    rel = curdir / "relations.yaml"
    if rel.exists():
        for pair, entries in _parse_simple_yaml(rel.read_text()).items():
            for e in entries or []:
                cur.relations.setdefault(pair, {})[e["from"]] = {
                    "target": e["to"], "comment": e.get("comment", "")}
    noeq = curdir / "no_equivalent.yaml"
    if noeq.exists():
        for pair, entries in _parse_simple_yaml(noeq.read_text()).items():
            for e in entries or []:
                cur.no_equiv.setdefault(pair, {})[e["name"]] = e.get(
                    "comment", "curated no-equivalent")
    ali = curdir / "aliases.yaml"
    if ali.exists():
        for key, entries in _parse_simple_yaml(ali.read_text()).items():
            cur.aliases[key] = entries or []
    return cur
