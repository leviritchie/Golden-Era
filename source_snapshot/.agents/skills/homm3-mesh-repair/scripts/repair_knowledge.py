"""Small repair rules, not acceptance decisions. Evidence paths are repo-relative.

load defaults to structural checks; validate defaults to evidence existence checks.
verify_evidence=True adds hashes and implies existence checks for both functions.
select defaults to verifying only its returned rules; False is structural-only.
signatures=None selects by body plan/unit without a signature filter.
Tags match exactly; prerequisites remain caller-reviewed. Recipe measurements and
applicability require human evidence review: hashes prove identity, not causality.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys

ROOT = Path(__file__).resolve().parents[4]
INDEX = Path(__file__).resolve().parents[1] / "references/learning_index.json"
PROOFS = {"diagnostic", "source_validated", "generated_artifact_validated"}
REQUIRED = {"id", "bodyPlans", "signatures", "scope", "kind", "action",
            "prerequisites", "proof", "evidence"}


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _text(value, cap=600):
    _require(isinstance(value, str) and 0 < len(value.strip()) <= len(value) <= cap,
             "expected bounded nonempty text")


def _tags(values):
    _require(isinstance(values, list) and 1 <= len(values) <= 16, "expected 1..16 tags")
    for value in values:
        _text(value, 80)
        _require(re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value), "invalid tag")
    _require(len(values) == len(set(values)), "duplicate tag")


def _keys(obj, required, optional=()):
    _require(isinstance(obj, dict) and required <= obj.keys()
             and obj.keys() <= required | set(optional), "missing or unknown fields")


def _evidence_path(value, root, check):
    _text(value, 300)
    path = PurePosixPath(value)
    _require(bool(path.parts) and not path.is_absolute() and not any(x in value for x in ("\\", ":"))
             and ".." not in path.parts and path.as_posix() == value,
             "evidence path must be canonical repo-relative")
    if not check:
        return root / value
    resolved = (root / value).resolve()
    _require(resolved.is_relative_to(root) and resolved.is_file(),
             "missing evidence or path outside root: " + value)
    return resolved


def _recipe(rule):
    _text(rule["applicability"])
    rows = rule["improvements"]
    _require(isinstance(rows, list) and 1 <= len(rows) <= 16, "missing improvements")
    supported = set()
    for row in rows:
        _keys(row, {"unit", "metric", "before", "after", "direction", "evidencePath"})
        _tags([row["unit"]])
        _text(row["metric"], 120)
        _require(row["direction"] in ("lower", "higher"), "invalid improvement direction")
        before, after = row["before"], row["after"]
        _require(all(type(x) in (int, float) and math.isfinite(x) for x in (before, after)),
                 "improvement values must be finite numbers")
        _require(after < before if row["direction"] == "lower" else after > before,
                 "recipe requires positive improvement")
        _require(row["evidencePath"] in [e["path"] for e in rule["evidence"]],
                 "improvement must reference hashed evidence")
        supported.add(row["unit"])
    _require(rule["scope"] != "asset_class" or len(supported) >= 2,
             "asset_class recipe requires improvements on at least two units")
    if "units" in rule:
        _require(set(rule["units"]) <= supported, "recipe units lack improvement evidence")


def validate(index, *, root=ROOT, check_evidence=True, verify_evidence=False):
    """Set check_evidence=False for no evidence IO; verify_evidence overrides it."""
    check_evidence = check_evidence or verify_evidence
    root, seen, hashes = Path(root), set(), {}
    if check_evidence:
        root = root.resolve()
    _keys(index, {"schema", "records"})
    _require(index["schema"] == "repair_learning.v1", "invalid schema")
    _require(isinstance(index["records"], list) and len(index["records"]) <= 256,
             "expected at most 256 records")
    for rule in index["records"]:
        _keys(rule, REQUIRED, {"units", "applicability", "improvements"})
        _tags([rule["id"]])
        _require(rule["id"] not in seen, "duplicate id: " + rule["id"])
        seen.add(rule["id"])
        for field in ("bodyPlans", "signatures"):
            _tags(rule[field])
        for field, allowed in (("scope", ("unit", "asset_class")),
                               ("kind", ("negative", "recipe")), ("proof", tuple(PROOFS))):
            _require(rule[field] in allowed, "invalid " + field)
        _text(rule["action"])
        _require(isinstance(rule["prerequisites"], list)
                 and 1 <= len(rule["prerequisites"]) <= 6, "expected 1..6 prerequisites")
        for item in rule["prerequisites"]:
            _text(item, 240)
        _require(rule["scope"] != "unit" or "units" in rule, "unit scope requires units")
        if "units" in rule:
            _tags(rule["units"])
        evidence = rule["evidence"]
        _require(isinstance(evidence, list) and 1 <= len(evidence) <= 8,
                 "expected 1..8 evidence records")
        paths = set()
        for entry in evidence:
            _keys(entry, {"path", "sha256"})
            path = _evidence_path(entry["path"], root, check_evidence)
            _require(entry["path"] not in paths, "duplicate evidence path")
            paths.add(entry["path"])
            _require(isinstance(entry["sha256"], str)
                     and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]), "invalid sha256")
            if verify_evidence:
                if path not in hashes:
                    digest = hashlib.sha256()
                    with path.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                    hashes[path] = digest.hexdigest()
                _require(hashes[path] == entry["sha256"], "evidence hash mismatch: " + entry["path"])
        if rule["kind"] == "recipe":
            _require({"applicability", "improvements"} <= rule.keys(),
                     "recipe requires applicability and improvements")
            _recipe(rule)
        else:
            _require(not {"applicability", "improvements"} & rule.keys(),
                     "negative must not claim recipe improvements")


def load(path=INDEX, *, root=ROOT, check_evidence=False, verify_evidence=False):
    """Read only the index by default; evidence IO must be explicitly requested."""
    with Path(path).open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    _require(len(raw) <= 1024 * 1024, "index exceeds 1 MiB")
    index = json.loads(raw)
    validate(index, root=root, check_evidence=check_evidence, verify_evidence=verify_evidence)
    return index


def select(index, *, body_plan, signatures=None, unit=None, limit=6, root=ROOT, verify_evidence=True):
    """Rank by unit restriction, overlap, narrower tags, then lexical ID; max six."""
    validate(index, root=root, check_evidence=False)
    if signatures is not None:
        signatures = [signatures] if isinstance(signatures, str) else list(signatures)
        _tags(signatures)
    _tags([body_plan])
    if unit is not None:
        _tags([unit])
    _require(type(limit) is int and limit > 0, "limit must be a positive integer")
    wanted = set(signatures or ())
    rules = [r for r in index["records"] if body_plan in r["bodyPlans"]
             and (signatures is None or wanted.intersection(r["signatures"]))
             and ("units" not in r or unit in r["units"])]
    chosen = sorted(rules, key=lambda r: ("units" not in r,
                  -len(wanted.intersection(r["signatures"])), len(r["bodyPlans"]),
                  len(r["signatures"]), r["id"]))[:min(limit, 6)]
    if verify_evidence:
        validate({"schema": index["schema"], "records": chosen}, root=root, verify_evidence=True)
    return chosen


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=INDEX)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("validate")
    check.add_argument("--verify-evidence", action="store_true")
    query = commands.add_parser("query")
    query.add_argument("--body-plan", required=True)
    query.add_argument("--signature", action="append")
    query.add_argument("--unit")
    query.add_argument("--limit", type=int, default=6)
    args = parser.parse_args(argv)
    try:
        index = load(args.index, check_evidence=args.command == "validate",
                     verify_evidence=getattr(args, "verify_evidence", False))
        result = ({"ok": True, "records": len(index["records"]),
                   "evidenceVerified": args.verify_evidence} if args.command == "validate"
                  else select(index, body_plan=args.body_plan, signatures=args.signature,
                              unit=args.unit, limit=args.limit))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
