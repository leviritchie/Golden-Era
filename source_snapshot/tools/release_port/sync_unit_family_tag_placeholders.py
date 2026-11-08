#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))

from validate_unit_family_tags import ALLOWED_FACTS, DEFAULT_TAGS_PATH, load_live_unit_sids  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
from validate_custom_faction_manifests import DEFAULT_MANIFEST_DIR, load_json  # noqa: E402


UNKNOWN_ENTRY = {fact: "unknown" for fact in sorted(ALLOWED_FACTS)}


def sync_placeholders(doc: dict[str, Any], live_sids: set[str], prune_stale: bool) -> tuple[int, int]:
    units = doc.setdefault("units", {})
    if not isinstance(units, dict):
        raise ValueError("unit_family_tags.json units must be an object")

    added = 0
    pruned = 0
    for sid in sorted(live_sids):
        if sid in units:
            continue
        units[sid] = dict(UNKNOWN_ENTRY)
        added += 1

    if prune_stale:
        for sid in sorted(list(units)):
            if sid in live_sids:
                continue
            del units[sid]
            pruned += 1

    return added, pruned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tags", type=Path, default=DEFAULT_TAGS_PATH)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--prune-stale", action="store_true")
    args = parser.parse_args()

    doc = load_json(args.tags)
    if not isinstance(doc, dict):
        print(f"error: {args.tags} root must be an object", file=sys.stderr)
        return 1

    live_sids = load_live_unit_sids(args.manifest_dir)
    added, pruned = sync_placeholders(doc, live_sids, args.prune_stale)
    args.tags.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"unit family tag placeholders synced: added={added} pruned={pruned} total={len(doc.get('units') or {})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
