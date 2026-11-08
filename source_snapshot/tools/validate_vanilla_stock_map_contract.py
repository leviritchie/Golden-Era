#!/usr/bin/env python3
"""Validate a vanilla_stock emitted .map against stock Core allowlists.

Fail-closed checks (delegated to ``vanilla_stock.validate_map``):

- SIDs subset of stock Core ObjectConfigs; no ``homm3_`` / ``h3_`` / ``golden_era``
- tilesMap / waterMap subset of Core.zip catalogs (tiles 1..7 / waters 1..7 today)
- no GE-only tile ids (Burrow 15 / Water 18-22 / Void 23)
- ocean-basin climb contract, scenery footprints, gate-face rotation,
  placement ground-truth ↔ map join, zero Core overlay
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POC = REPO / "experiments" / "campaign_port_poc"
if str(POC) not in sys.path:
    sys.path.insert(0, str(POC))

from vanilla_stock.emit_map import DEFAULT_STOCK_CORE  # noqa: E402
from vanilla_stock.validate_map import VanillaStockValidationError, validate_vanilla_stock_map  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--stock-core", type=Path, default=DEFAULT_STOCK_CORE)
    parser.add_argument("--expect-map-sid", type=str, default=None)
    parser.add_argument("--expect-victory-mode", type=str, default=None)
    parser.add_argument("--expect-mine-entity-count", type=int, default=None)
    parser.add_argument("--expect-map-event-count", type=int, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = validate_vanilla_stock_map(
            map_path=args.map,
            stock_core=args.stock_core,
            expect_map_sid=args.expect_map_sid,
            expect_victory_mode=args.expect_victory_mode,
            expect_mine_entity_count=args.expect_mine_entity_count,
            expect_map_event_count=args.expect_map_event_count,
            manifest_path=args.manifest,
        )
    except VanillaStockValidationError as ex:
        print(str(ex), file=sys.stderr)
        return 1
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
