"""Fail-closed banned-surface checks for Direct State write-body recovery.

Rejects Shoulder Check class mistakes:
- Hex.bcxo / cfqf labeled as Unit occupancy commit ownership
- edb.* treated as movement commit publish
- Phase-5 milestone notes that still call bcxo occupancy without erratum
- Promoted movement.commit cards that leave helper+_cfqf dual-write as the production path
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from olden_cs_recovery.paths import PACKAGE_ROOT, REPO_ROOT, SCHEMAS_DIR
from olden_cs_recovery.schema_validate import load_json, validate_file, validate_instance

CARDS_DIR = PACKAGE_ROOT / "direct_state_cards"
MILESTONES_DIR = PACKAGE_ROOT / "proof_ledger" / "milestones"
PHASE5_BATTLE = MILESTONES_DIR / "phase5_battle_unit_mechanics.json"
PHASE5_ERRATUM = MILESTONES_DIR / "phase5_battle_unit_mechanics.occupancy_erratum.md"

# Patterns that claim bcxo/cfqf is occupancy ownership (not mere mention).
_OCCUPANCY_CLAIM = re.compile(
    r"(?is)(bcxo|cfqf|_cfqf).{0,80}(occupancy|occupant(?!\s*/\s*corpse)|Unit occupant)",
)
_EDB_PUBLISH_CLAIM = re.compile(
    r"(?is)\bedb\b.{0,60}(commit\s+publish|movement\s+publish|OnUnitEndedMovement|OnUnitChangedHex\s*=)",
)


def fail(message: str) -> None:
    print(f"direct-state-banned-surfaces: {message}", file=sys.stderr)
    raise SystemExit(1)


def _text(path: Path) -> str:
    if not path.is_file():
        fail(f"missing required file: {path}")
    return path.read_text(encoding="utf-8-sig")


def _load_card(path: Path) -> dict[str, Any]:
    validate_file("direct_state_card.schema.json", path)
    data = load_json(path)
    if not isinstance(data, dict):
        fail(f"card root must be object: {path}")
    return data


def validate_card_banned_list(card: dict[str, Any], *, path: Path) -> None:
    surfaces = " ".join(
        f"{row.get('surface', '')} {row.get('reason', '')}" for row in card.get("banned_surfaces") or []
    ).lower()
    required_tokens = (
        ("bcxo", "card must ban Hex.bcxo-as-occupancy"),
        ("edb", "card must ban edb-as-publish for movement"),
    )
    for token, message in required_tokens:
        if token not in surfaces:
            fail(f"{path.name}: {message}")


def validate_card_promotion_rules(card: dict[str, Any], *, path: Path) -> None:
    methods = card.get("live_methods") or []
    proof = card.get("proof_status")
    if proof == "equivalence-proven":
        # Plan / card schema: every live_methods entry is equivalence-proven OR
        # explicitly blocked with reason; at least one proven surface required.
        proven = [m for m in methods if m.get("status") == "equivalence-proven"]
        if not proven:
            fail(f"{path.name}: proof_status=equivalence-proven requires at least one proven method")
        for m in methods:
            status = str(m.get("status") or "")
            if status == "equivalence-proven":
                continue
            if status == "blocked":
                reason = m.get("blocked_reason")
                if not isinstance(reason, str) or not reason.strip():
                    fail(
                        f"{path.name}: blocked method missing blocked_reason: "
                        + str(m.get("method_id"))
                    )
                continue
            fail(
                f"{path.name}: proof_status=equivalence-proven but method not proven|blocked: "
                + str(m.get("method_id"))
                + f" (status={status!r})"
            )
    if "focused_live_positive" not in (card.get("ungate_requires") or []):
        fail(f"{path.name}: ungate_requires must include focused_live_positive")
    binding = card.get("adapter_binding") or {}
    if binding.get("gameplay_gated") is not True and proof != "equivalence-proven":
        fail(f"{path.name}: incomplete cards must keep gameplay_gated=true")
    export = card.get("gamesymbols_export") or {}
    if export.get("exported") is True and proof != "equivalence-proven":
        fail(f"{path.name}: GameSymbols export forbidden until card equivalence-proven")
    # Dest-recipe cards must not claim commit ownership.
    if card.get("role") == "dest_recipe" and card.get("card_id"):
        if "commit" in str(card.get("card_id")).lower() and "dest" not in str(card.get("card_id")).lower():
            fail(f"{path.name}: dest_recipe card_id must not look like commit ownership")
        notes = str(card.get("notes") or "").lower()
        if "commit ownership stays" not in notes and "dest_recipe only" not in notes and "role=dest_recipe" not in notes:
            # Soft requirement via adapter notes when present.
            adapter_notes = str((binding.get("notes") or "")).lower()
            if "dest-recipe" not in adapter_notes and "dest_recipe" not in adapter_notes:
                fail(f"{path.name}: dest_recipe card must document non-commit role")


def validate_phase5_erratum() -> None:
    """Phase 5 CompGen promotion of bcxo remains valid; occupancy ownership claim must be corrected."""
    declaration = _text(PHASE5_BATTLE)
    if "Hex.Session.Battle.Hex::bcxo(Unit)" not in declaration:
        fail("phase5_battle_unit_mechanics.json no longer lists bcxo — update validator")
    # Notes historically said "Hex Unit occupancy". Require erratum file that retracts that claim.
    if not PHASE5_ERRATUM.is_file():
        fail(
            "missing phase5_battle_unit_mechanics.occupancy_erratum.md — "
            "bcxo CompGen proven ≠ occupancy ownership"
        )
    erratum = _text(PHASE5_ERRATUM).lower()
    for token in ("bcxo", "lastcorpse", "not", "occupancy", "fieldobjects"):
        if token not in erratum:
            fail(f"occupancy erratum missing required token {token!r}")
    # Fail if declaration notes still assert occupancy without pointing at erratum.
    notes = ""
    try:
        notes = str(json.loads(declaration).get("notes") or "")
    except json.JSONDecodeError:
        fail("phase5_battle_unit_mechanics.json is not valid JSON")
    if _OCCUPANCY_CLAIM.search(notes) and "occupancy_erratum" not in notes.lower():
        fail(
            "phase5_battle_unit_mechanics notes still label bcxo as occupancy without "
            "occupancy_erratum reference"
        )


def validate_cards() -> list[dict[str, Any]]:
    if not CARDS_DIR.is_dir():
        fail(f"missing cards directory: {CARDS_DIR}")
    cards: list[dict[str, Any]] = []
    for path in sorted(CARDS_DIR.glob("*.json")):
        card = _load_card(path)
        validate_card_banned_list(card, path=path)
        validate_card_promotion_rules(card, path=path)
        # Cards themselves must not teach banned mappings as positive recipe.
        body = json.dumps(card)
        if re.search(r'(?is)"role"\s*:\s*"occupancy_mutator".{0,200}bcxo', body):
            fail(f"{path.name}: must not assign occupancy_mutator role to bcxo")
        cards.append(card)
    return cards


def validate_offline_unlock_mod(cards: list[dict[str, Any]], *, plugin: Path) -> None:
    adapters = _text(plugin / "Homm3DirectStateAdapters.cs")
    symbols = _text(plugin / "GameSymbols.cs")
    unit_hex = _text(plugin / "Homm3DirectStateUnitHexNative.cs")
    gateway = _text(plugin / "NativeCombatWriteGateway.cs")

    # MovementPush must stay gated until M3 live-positive (never overnight-ungate).
    # After focused CapLog dual-readback agree, MovementPushLivePositiveProven=true may
    # allow MovementPush. MovementTeleport ungates only after M6 live-positive (or
    # diagnostic flag); both share the same failReason gate string when blocked.
    adapters_has_gate = (
        "movement occupancy mutation gated until native push_unit/walk is live-positive"
        in adapters
    )
    if not adapters_has_gate:
        fail("Homm3DirectStateAdapters.TryMove must keep MovementPush gameplay gate (M3)")
    if "MovementTeleport" not in adapters:
        fail("TryMove must still reference MovementTeleport (M6 relocate/teleport family)")
    if "Homm3DirectStateM6BfdiTeleportDiagnostic" not in adapters:
        fail("TryMove must route MovementTeleport through Homm3DirectStateM6BfdiTeleportDiagnostic")

    diagnostic_cs = plugin / "Homm3DirectStateM3BfdiShoveDiagnostic.cs"
    if diagnostic_cs.is_file():
        diagnostic = _text(diagnostic_cs)
        if "MovementPushLivePositiveProven = true" in diagnostic:
            proof = PACKAGE_ROOT / "proof_ledger" / "entries" / "ds_m3_movement_push_live_positive.json"
            if not proof.is_file():
                fail(
                    "MovementPushLivePositiveProven=true requires proof_ledger entry "
                    "ds_m3_movement_push_live_positive.json"
                )
            proof_body = _text(proof)
            if '"live_positive": true' not in proof_body and '"live_positive":true' not in proof_body:
                fail("ds_m3_movement_push_live_positive.json must set live_positive=true")
            if "M3_BFDI_DUAL_READBACK" not in proof_body and "dualAgree" not in proof_body:
                fail("ds_m3_movement_push_live_positive.json must cite CapLog dual-readback evidence")

    teleport_cs = plugin / "Homm3DirectStateM6BfdiTeleportDiagnostic.cs"
    if not teleport_cs.is_file():
        fail("missing Homm3DirectStateM6BfdiTeleportDiagnostic.cs (M6 relocate diagnostic)")
    teleport_diag = _text(teleport_cs)
    if "movement.relocate.bfdi_v1" not in teleport_diag and "RelocateCardId" not in teleport_diag:
        fail("M6 diagnostic must cite movement.relocate.bfdi_v1")
    if "TryCommitUnitHexMove" not in gateway and "bfdi" not in gateway:
        fail("NativeCombatWriteGateway must keep journaled bfdi TryCommitUnitHexMove for M6 relocate")
    if "MovementTeleportLivePositiveProven = true" in teleport_diag:
        proof = PACKAGE_ROOT / "proof_ledger" / "entries" / "ds_m6_movement_teleport_live_positive.json"
        if not proof.is_file():
            fail(
                "MovementTeleportLivePositiveProven=true requires proof_ledger entry "
                "ds_m6_movement_teleport_live_positive.json"
            )
        proof_body = _text(proof)
        if '"live_positive": true' not in proof_body and '"live_positive":true' not in proof_body:
            fail("ds_m6_movement_teleport_live_positive.json must set live_positive=true")
        if "M6_BFDI_TELEPORT_DUAL_READBACK" not in proof_body and "dualAgree" not in proof_body:
            fail("ds_m6_movement_teleport_live_positive.json must cite CapLog dual-readback evidence")
        if '"MovementTeleport_ungated": true' not in proof_body and '"MovementTeleport_ungated":true' not in proof_body:
            fail("ds_m6_movement_teleport_live_positive.json must set MovementTeleport_ungated=true")
    else:
        # Still gated: adapter must consult IsMovementTeleportAllowed (not always-open).
        if "IsMovementTeleportAllowed" not in adapters:
            fail("TryMove must call IsMovementTeleportAllowed while MovementTeleport is gated")

    relocate_cards = [
        c
        for c in cards
        if c.get("card_id") == "movement.relocate.bfdi_v1"
    ]
    if not relocate_cards:
        fail("missing promoted/declared card movement.relocate.bfdi_v1 (M6)")
    relocate = relocate_cards[0]
    relocate_notes = (
        str(relocate.get("notes") or "")
        + " "
        + str((relocate.get("adapter_binding") or {}).get("notes") or "")
    ).lower()
    if "movement.commit.bfdi_v1" not in relocate_notes and "reuses" not in relocate_notes:
        fail("movement.relocate.bfdi_v1 must document reuse of movement.commit.bfdi_v1")
    if "MovementTeleport" not in (relocate.get("adapter_binding") or {}).get("operations", []):
        fail("movement.relocate.bfdi_v1 adapter_binding.operations must include MovementTeleport")
    if "TryCommitUnitHexMove" not in (relocate.get("adapter_binding") or {}).get("gateway_methods", []):
        fail("movement.relocate.bfdi_v1 must bind TryCommitUnitHexMove (shared bfdi path)")
    # HexOccupantWriteMembers must be annotated as NOT occupancy for movement.
    if "lastCorpse" not in symbols and "NOT occupancy" not in symbols:
        # Prefer explicit lastCorpse / not-occupancy commentary near HexOccupantWriteMembers.
        block = re.search(
            r"HexOccupantWriteMembers\s*=\s*\{(?P<body>.*?)\};",
            symbols,
            re.S,
        )
        if block is None:
            fail("GameSymbols.DirectStateLaws.HexOccupantWriteMembers missing")
        # Require nearby comment above the member.
        idx = symbols.find("HexOccupantWriteMembers")
        window = symbols[max(0, idx - 400) : idx]
        if "lastCorpse" not in window and "not occupancy" not in window.lower() and "NOT occupancy" not in window:
            fail(
                "HexOccupantWriteMembers must be documented as lastCorpse / NOT movement occupancy "
                "(Direct State M1)"
            )

    promoted = [
        c
        for c in cards
        if c.get("card_id") == "movement.commit.bfdi_v1" and c.get("proof_status") == "equivalence-proven"
    ]
    if promoted:
        # Once M1 card is bar-C proven, production must not remain on helper+_cfqf dual-write.
        if "HexOccupantWriteMembers" in unit_hex and "bfdi" not in gateway:
            fail(
                "movement.commit.bfdi_v1 is equivalence-proven but TryCommitUnitHexMove/UnitHexNative "
                "still relies on HexOccupantWriteMembers dual-write without bfdi binding"
            )
        export = promoted[0].get("gamesymbols_export") or {}
        if not export.get("exported"):
            fail("proven movement.commit.bfdi_v1 must export GameSymbols.DirectStateLaws surfaces")


def validate_docs_against_banned() -> None:
    """Reject new teaching that bcxo is occupancy or edb is commit publish in DS card notes."""
    # Pin table + dossiers already corrected; ensure cards dir README does not regress.
    readme = PACKAGE_ROOT / "DIRECT_STATE_WRITE_BODY.md"
    if readme.is_file():
        text = _text(readme)
        if _OCCUPANCY_CLAIM.search(text) and "lastCorpse" not in text:
            fail("DIRECT_STATE_WRITE_BODY.md occupancy claim missing lastCorpse correction")
        if _EDB_PUBLISH_CLAIM.search(text) and "eda.cfia" not in text:
            fail("DIRECT_STATE_WRITE_BODY.md edb publish claim missing eda.cfia correction")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Direct State banned surfaces (fail-closed).")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    plugin = root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"

    # Ensure schema loads.
    if not (SCHEMAS_DIR / "direct_state_card.schema.json").is_file():
        fail("missing direct_state_card.schema.json")

    validate_phase5_erratum()
    cards = validate_cards()
    validate_offline_unlock_mod(cards, plugin=plugin)
    validate_docs_against_banned()
    print(
        json.dumps(
            {
                "ok": True,
                "cards_validated": len(cards),
                "phase5_erratum": str(PHASE5_ERRATUM.relative_to(PACKAGE_ROOT)).replace("\\", "/"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
