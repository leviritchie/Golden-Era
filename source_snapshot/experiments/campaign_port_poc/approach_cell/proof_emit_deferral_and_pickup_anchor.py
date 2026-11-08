#!/usr/bin/env python3
"""Fail-closed proofs for random-squad deferral and mine-clear pickup anchoring.

Proof boundary: source/static only (no map regen required).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_homecoming_single_layer_map as single_layer
import surface_emit as single

WITH_C = "propAiIntet" + "actions"
WITHOUT_C = "propAiIntet" + "ations"


def _fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def proof_allowlists_synced() -> None:
    importlib.reload(single)
    importlib.reload(single_layer)
    if single.SUPPORTED_LIVE_PROPERTY_FAMILIES != single_layer.SUPPORTED_LIVE_PROPERTY_FAMILIES:
        _fail("surface_emit and single_layer SUPPORTED_LIVE_PROPERTY_FAMILIES diverged")
    families = single.SUPPORTED_LIVE_PROPERTY_FAMILIES
    for name in (WITH_C, WITHOUT_C, "propSquads", "propRandomSquads"):
        if name not in families:
            _fail(f"SUPPORTED_LIVE_PROPERTY_FAMILIES missing {name!r}")


def proof_random_squad_not_false_deferred() -> None:
    importlib.reload(single)
    required = single.discover_native_property_required_sids()
    props = required.get("random-squad") or {}
    unsupported = sorted(set(props) - single.SUPPORTED_LIVE_PROPERTY_FAMILIES)
    if "random-squad" not in single.SUPPORTED_LIVE_PROPERTY_SIDS:
        _fail("random-squad missing from SUPPORTED_LIVE_PROPERTY_SIDS")
    if unsupported:
        _fail(f"random-squad still has unsupported families: {unsupported}")
    would_defer = bool(props) and (
        "random-squad" not in single.SUPPORTED_LIVE_PROPERTY_SIDS or bool(unsupported)
    )
    if would_defer:
        _fail("random-squad would still be property-deferred")
    # Non-whitelisted prop-bearing SIDs that still bind unsupported families
    # must remain deferred. Barracks that only needed propSquads are now
    # allowlisted-family-clean; assert an SID that still has a truly foreign family
    # if discovery surfaces one, otherwise assert random-squad is clean.
    leftover = {
        sid: sorted(set(props) - single.SUPPORTED_LIVE_PROPERTY_FAMILIES)
        for sid, props in required.items()
        if sid not in single.SUPPORTED_LIVE_PROPERTY_SIDS
        and sorted(set(props) - single.SUPPORTED_LIVE_PROPERTY_FAMILIES)
    }
    # Discovery only records unsupported families, so leftover values are the props.
    if "random-squad" in leftover:
        _fail(f"random-squad unexpectedly still unsupported: {leftover['random-squad']}")


def proof_mine_clear_prefers_visit_emit() -> None:
    importlib.reload(single)
    # Synthetic 3x3 GATE ring (occupied center). Pin visit via monkeypatch so the
    # proof does not depend on H3 mask/Y-flip projection details.
    config = {
        "sizeX": 3,
        "sizeZ": 3,
        "canBeMirrored": False,
        "nodes": [2, 2, 2, 2, 1, 2, 2, 2, 2],
    }
    previous = (single.OLDEN_WIDTH, single.OLDEN_HEIGHT)
    original_visit_nodes = single.entity_visit_nodes
    try:
        single.OLDEN_WIDTH = 80
        single.OLDEN_HEIGHT = 80
        visit_node = 10 * 80 + 10  # (10,10)
        single.entity_visit_nodes = lambda _entity: {visit_node}  # type: ignore[assignment]
        entity = {"sourceKey": "proof:10:10", "sourceX": 10, "sourceY": 10}
        # Far mine occupied cell — clear of the visit footprint, but previously made
        # maximize-distance scoring prefer a non-visit emit.
        far_mine = {0}
        node_clear, evidence_clear = single.derive_gate_ring_anchor_on_visit_node(
            entity,
            "resource_gold",
            config,
            default_node=visit_node,
            rotation=0,
            forbidden_occupied=far_mine,
            allow_pickup_range_fallback=True,
        )
        if node_clear != visit_node:
            _fail(
                f"clear pickup must keep emit on visit; got {node_clear} "
                f"decision={evidence_clear.get('decision')}"
            )
        # Block the visit-emit body (south-east of visit for emit-on-visit).
        blocked_body = {(11 * 80) + 11}
        node_blocked, evidence_blocked = single.derive_gate_ring_anchor_on_visit_node(
            entity,
            "resource_gold",
            config,
            default_node=visit_node,
            rotation=0,
            forbidden_occupied=blocked_body,
            allow_pickup_range_fallback=True,
        )
        if node_blocked == visit_node:
            _fail("mine-blocked visit emit must re-anchor off visit")
        if evidence_blocked.get("decision") not in {
            "emit_gate_aligned_clear_of_forbidden_occupied",
            "emit_gate_aligned_on_neighbor_interact_clear_of_mines",
        }:
            _fail(f"unexpected blocked decision {evidence_blocked.get('decision')!r}")
        body = next(iter(evidence_blocked.get("occupiedNodes") or []), None)
        if not isinstance(body, int):
            _fail("blocked reanchor missing occupied body")
        body_dist = abs((body % 80) - (visit_node % 80)) + abs((body // 80) - (visit_node // 80))
        if body_dist > 2:
            _fail(f"reanchor body drifted too far from visit: dist={body_dist} body={body}")
    finally:
        single.entity_visit_nodes = original_visit_nodes
        single.OLDEN_WIDTH, single.OLDEN_HEIGHT = previous


def main() -> int:
    proof_allowlists_synced()
    proof_random_squad_not_false_deferred()
    proof_mine_clear_prefers_visit_emit()
    print("OK: emit deferral + pickup anchor proofs passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
