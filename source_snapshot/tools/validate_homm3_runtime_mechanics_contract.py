#!/usr/bin/env python3
"""Validate the executable HoMM3 direct-state runtime-mechanics contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


UNIT_FLAG = "homm3_runtime_mechanic_unit_pilot.flag"
LAW_FLAG = "homm3_runtime_mechanic_law_pilot.flag"
CAPS = {
    "maxRootWork": 64,
    "maxDepth": 8,
    "maxJournalEntries": 64,
    "maxFanout": 16,
    "maxDirtyIdentities": 32,
    "maxQueueSpan": 32,
}
ADAPTERS = {
    "damage": (1, "damage", ["DamageFlatDelta"]),
    "cast": (2, "cast", ["CastChain"]),
    "focus": (3, "resource", ["FocusGrant", "FocusSpend", "FocusSet"]),
    "cooldown": (
        4,
        "resource",
        [
            "CooldownSet",
            "CooldownReduce",
            "CooldownIncrease",
            "CooldownCharges",
            "CooldownCastCounter",
        ],
    ),
    "status": (
        5,
        "status",
        ["StatusApply", "StatusRefresh", "StatusTick", "StatusExpire", "StatusRemove"],
    ),
    "movement": (
        6,
        "movement",
        ["MovementPush", "MovementPull", "MovementTeleport", "MovementSetImmobile"],
    ),
    "summon": (7, "lifecycle", ["SummonCreate"]),
    "trap": (8, "lifecycle", ["TrapSpawn", "TrapTrigger", "TrapDespawn"]),
    "corpse": (9, "lifecycle", ["CorpseCreate", "CorpseConsume"]),
    "nestedDamage": (
        10,
        "nestedDamage",
        ["NestedReflection", "NestedRedirection", "NestedSplash"],
    ),
    "kill": (11, "kill", ["KillConfirm"]),
    "allyDeath": (12, "kill", ["AllyDeathObserve"]),
    "actionQueue": (13, "action", ["ActionQueueInsert", "ActionQueueRemove"]),
    "turnOrder": (14, "turnOrder", ["TurnOrderReorder"]),
    "aura": (15, "aura", ["AuraDefine", "AuraRefresh", "AuraRemove"]),
}
TRIGGERS = {
    "damage": {"damageApplying"},
    "cast": {"castCommitted"},
    "focus": {"castCommitted"},
    "cooldown": {"castCommitted"},
    "status": {"castCommitted", "roundStart", "roundEnd"},
    "movement": {"damageApplied", "movementCommitted"},
    "summon": {"castCommitted"},
    "trap": {"castCommitted", "movementCommitted", "roundEnd"},
    "corpse": {"objectDestroyed", "castCommitted"},
    "nestedDamage": {"damageApplying", "damageApplied"},
    "kill": {"objectDestroyed"},
    "allyDeath": {"objectDestroyed"},
    "actionQueue": {"actionEnd"},
    "turnOrder": {"roundStart"},
    "aura": {"unitInit", "movementCommitted", "objectDestroyed", "roundStart"},
}
RECONCILIATION_POLICIES = {
    "damage": "preCommitScalar",
    "cast": "committedEventAndDeferredChildren",
    "focus": "directStorageAndEnergyView",
    "cooldown": "directStorageAndAbilityView",
    "status": "managerAuthoritativeNoNativeInventory",
    "movement": "atomicOccupancyAndView",
    "summon": "battleSideOccupancyAndView",
    "trap": "managerObjectAndOccupancy",
    "corpse": "managerAuthoritativeCorpse",
    "nestedDamage": "preCommitRedirectAndPostCommitChildren",
    "kill": "committedDestructionAtMostOnce",
    "allyDeath": "committedDestructionAtMostOnce",
    "actionQueue": "authoritativeQueueAndDerivedView",
    "turnOrder": "authoritativeStableSplice",
    "aura": "dirtyIdentityMembership",
}


def fail(message: str) -> None:
    print(f"homm3-runtime-mechanics-contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load_json(path: Path) -> object:
    if not path.is_file():
        fail(f"missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        fail(f"{path}: JSON parse failed: {exc}")


def required_keys(owner: dict, keys: set[str], context: str) -> None:
    missing = sorted(keys.difference(owner))
    require(not missing, f"{context}: missing keys {missing}")


def expected_flag(adapter_id: str) -> str:
    return f"homm3_runtime_{adapter_id}_pilot.flag"


def validate_manifest(path: Path, document: object) -> None:
    require(isinstance(document, dict), f"{path}: manifest root must be an object")
    required_keys(document, {"schemaVersion", "kind", "adapters"}, str(path))
    require(document["schemaVersion"] == 2, f"{path}: schemaVersion must be 2")
    require(document["kind"] == "adapterManifest", f"{path}: kind must be adapterManifest")
    wave_map = document.get("ingressWaveMap")
    require(isinstance(wave_map, dict) and wave_map, f"{path}: ingressWaveMap is required")
    routed = set()
    for surface, ids in wave_map.items():
        require(isinstance(surface, str) and surface, f"{path}: ingressWaveMap surface keys must be non-empty")
        require(isinstance(ids, list) and ids, f"{path}: ingressWaveMap[{surface}] must list adapters")
        routed.update(ids)
    require(routed == set(ADAPTERS), f"{path}: ingressWaveMap must route all adapters")
    rows = document["adapters"]
    require(isinstance(rows, list), f"{path}: adapters must be an array")
    require(len(rows) == len(ADAPTERS), f"{path}: adapters must exhaust stable IDs")
    seen_ids: set[int] = set()
    seen_contract_ids: set[str] = set()
    seen_operations: set[str] = set()
    for index, row in enumerate(rows):
        context = f"{path}:adapters[{index}]"
        require(isinstance(row, dict), f"{context}: row must be an object")
        required_keys(
            row,
            {
                "stableId",
                "adapterId",
                "family",
                "operations",
                "fixtureFlag",
                "proofLabel",
                "reconciliationPolicy",
                "caps",
            },
            context,
        )
        adapter_id = row["adapterId"]
        require(adapter_id in ADAPTERS, f"{context}: unknown adapterId {adapter_id!r}")
        stable_id, family, operations = ADAPTERS[adapter_id]
        require(row["stableId"] == stable_id, f"{context}: stableId mismatch")
        require(row["family"] == family, f"{context}: family mismatch")
        require(row["operations"] == operations, f"{context}: operations mismatch")
        require(
            row["fixtureFlag"] == expected_flag(adapter_id),
            f"{context}: fixtureFlag mismatch",
        )
        require(
            row["proofLabel"] == f"{family}.runtime-unvalidated",
            f"{context}: proofLabel must preserve proof boundary",
        )
        require(
            row["reconciliationPolicy"] == RECONCILIATION_POLICIES[adapter_id],
            f"{context}: reconciliationPolicy mismatch",
        )
        require(row["caps"] == CAPS, f"{context}: caps must match hard code caps")
        require(stable_id not in seen_ids, f"{context}: duplicate stableId")
        require(adapter_id not in seen_contract_ids, f"{context}: duplicate adapterId")
        seen_ids.add(stable_id)
        seen_contract_ids.add(adapter_id)
        for operation in operations:
            require(operation not in seen_operations, f"{context}: operation has two owners")
            seen_operations.add(operation)
    require(seen_ids == set(range(1, 16)), f"{path}: stable IDs must be append-only 1..15")


def validate_definition(definition: object, context: str) -> tuple[str, str, str]:
    require(isinstance(definition, dict), f"{context}: definition must be an object")
    required_keys(
        definition,
        {
            "mechanicId",
            "enabled",
            "diagnosticFlag",
            "adapterId",
            "activation",
            "trigger",
            "operation",
        },
        context,
    )
    mechanic_id = definition["mechanicId"]
    require(
        isinstance(mechanic_id, str) and mechanic_id.startswith("diagnostic."),
        f"{context}: mechanicId must be a diagnostic ID",
    )
    require(
        isinstance(definition["enabled"], bool),
        f"{context}: enabled must be a boolean",
    )
    # Product Shoulder Check uses native push_unit; this pilot stays off (store bfdi ≠ view).
    if mechanic_id == "diagnostic.bellwether_shoulder_check":
        require(
            definition["enabled"] is False,
            f"{context}: Bellwether DS MovementPush pilot must stay disabled",
        )
    else:
        require(
            definition["enabled"] is True,
            f"{context}: pilot definition must be enabled",
        )
    adapter_id = definition["adapterId"]
    require(adapter_id in ADAPTERS, f"{context}: unknown adapterId {adapter_id!r}")
    operation = definition["operation"]
    require(isinstance(operation, dict), f"{context}: operation must be an object")
    operation_kind = operation.get("kind")
    require(
        operation_kind in ADAPTERS[adapter_id][2],
        f"{context}: operation {operation_kind!r} is not owned by {adapter_id}",
    )
    trigger = definition["trigger"]
    require(
        isinstance(trigger, str) and trigger in TRIGGERS[adapter_id],
        f"{context}: trigger {trigger!r} is not allow-listed for {adapter_id}",
    )

    flag = definition["diagnosticFlag"]
    allowed_flags = {expected_flag(adapter_id)}
    if adapter_id == "damage":
        allowed_flags.update({UNIT_FLAG, LAW_FLAG})
    require(flag in allowed_flags, f"{context}: diagnostic flag mismatch")

    activation = definition["activation"]
    require(isinstance(activation, dict), f"{context}: activation must be an object")
    kind = activation.get("kind")
    if kind == "unit":
        require(
            set(activation) == {"kind", "unitSid"}
            and isinstance(activation["unitSid"], str)
            and activation["unitSid"],
            f"{context}: unit activation shape is invalid",
        )
    elif kind == "law":
        require(adapter_id == "damage", f"{context}: only damage law fixture is supported")
        require(
            activation
            == {"kind": "law", "factionSid": "homm3_castle", "lawIndex": 6},
            f"{context}: law pilot must target homm3_castle law index 6",
        )
        require(flag == LAW_FLAG, f"{context}: law pilot flag mismatch")
    else:
        fail(f"{context}: activation.kind must be unit or law")

    serialized = json.dumps(definition, sort_keys=True)
    for forbidden in ("effectPayload", "effectKey", "donor", "spellSid"):
        require(
            forbidden not in serialized,
            f"{context}: executable mechanics must not use donor/native payload key {forbidden!r}",
        )
    return mechanic_id, adapter_id, kind


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--contract-dir",
        type=Path,
        help="Optional deployed runtime_mechanics directory to validate.",
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()
    plugin = root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
    contract_dir = (
        args.contract_dir.resolve()
        if args.contract_dir
        else root / "custom_factions" / "runtime_mechanics"
    )

    manifest_path = contract_dir / "homm3_adapter_manifest.json"
    validate_manifest(manifest_path, load_json(manifest_path))
    paths = sorted(
        path for path in contract_dir.glob("homm3_*.json") if path != manifest_path
    )
    require(bool(paths), f"no mechanic contracts under {contract_dir}")

    ids: set[str] = set()
    adapter_fixtures: set[str] = set()
    kinds: set[str] = set()
    for path in paths:
        root_doc = load_json(path)
        require(isinstance(root_doc, dict), f"{path}: root must be an object")
        required_keys(root_doc, {"schemaVersion", "enabled", "definitions"}, str(path))
        require(root_doc["schemaVersion"] == 2, f"{path}: schemaVersion must be 2")
        if root_doc["enabled"] is False:
            continue
        require(root_doc["enabled"] is True, f"{path}: enabled must be Boolean")
        definitions = root_doc["definitions"]
        require(isinstance(definitions, list), f"{path}: definitions must be an array")
        for index, definition in enumerate(definitions):
            mechanic_id, adapter_id, kind = validate_definition(
                definition, f"{path}:definitions[{index}]"
            )
            require(mechanic_id not in ids, f"duplicate mechanicId {mechanic_id!r}")
            ids.add(mechanic_id)
            adapter_fixtures.add(adapter_id)
            kinds.add(kind)

    require(
        adapter_fixtures == set(ADAPTERS),
        f"fixture coverage mismatch: missing {sorted(set(ADAPTERS) - adapter_fixtures)}",
    )
    require(kinds == {"unit", "law"}, "contract must contain unit and law fixtures")

    pilots = load_json(contract_dir / "homm3_state_pilots.json")
    serialized_pilots = json.dumps(pilots, sort_keys=True)
    require(
        "MovementPush" in serialized_pilots
        and "homm3_runtime_movement_pilot.flag" in serialized_pilots,
        "movement fixture coverage must retain a gated MovementPush pilot",
    )
    require(
        "diagnostic.bellwether_shoulder_check" in serialized_pilots
        and "h3_bellwether_armadillo" in serialized_pilots
        and "Shoulder Check" in serialized_pilots,
        "Bellwether Shoulder Check MovementPush pilot must be present for DS shove",
    )

    castle_manifest = load_json(root / "custom_factions" / "homm3_castle.json")
    require(
        "h3_pikeman" in json.dumps(castle_manifest),
        "h3_pikeman must remain present in the Castle runtime manifest",
    )
    factory_manifest = load_json(root / "custom_factions" / "homm3_factory.json")
    require(
        "h3_bellwether_armadillo" in json.dumps(factory_manifest),
        "Bellwether must remain present in the Factory runtime manifest",
    )
    factory_abilities = load_json(
        root / "custom_factions" / "ability_overrides" / "homm3_factory.json"
    )
    bellwether = factory_abilities.get("unitOverrides", {}).get(
        "h3_bellwether_armadillo"
    )
    require(isinstance(bellwether, dict), "Bellwether ability override is missing")
    shoulder_check = next(
        (
            row
            for row in (
                bellwether.get("abilities", [])
                + bellwether.get("existingSpecials", [])
            )
            if isinstance(row, dict) and row.get("nameText") == "Shoulder Check"
        ),
        None,
    )
    require(isinstance(shoulder_check, dict), "Shoulder Check override is missing")
    shoulder_shell = shoulder_check.get("directStateNativeShell")
    require(
        isinstance(shoulder_shell, dict)
        and shoulder_shell.get("mode") == "restoreNativeMechanic",
        "Shoulder Check must keep native teleport (mode=restoreNativeMechanic) from Schism Command: Fear",
    )
    require(
        shoulder_check.get("effectKey") == "arbitrator:abilities:1",
        "Shoulder Check donor must be arbitrator:abilities:1 (Schism T6 Command: Fear)",
    )
    reshape = shoulder_shell.get("reshape") if isinstance(shoulder_shell, dict) else None
    dealer = reshape.get("damageDealer") if isinstance(reshape, dict) else None
    mechanics = dealer.get("targetMechanics") if isinstance(dealer, dict) else None
    ordered = dealer.get("orderedCastParams") if isinstance(dealer, dict) else None
    require(
        isinstance(reshape, dict)
        and reshape.get("attackType_") == "cast"
        and isinstance(dealer, dict)
        and dealer.get("attackPatternSid") == "attack_single_buff"
        and dealer.get("damageTarget_") == "none"
        and dealer.get("shootRange") == 1
        and dealer.get("multitargetType") == "ordered"
        and dealer.get("numTargets") == 2
        and isinstance(ordered, list)
        and len(ordered) == 1
        and isinstance(ordered[0], dict)
        and ordered[0].get("selection") == "hex"
        and ordered[0].get("distanceFromFirst") == 1
        and isinstance(mechanics, list)
        and len(mechanics) == 1
        and isinstance(mechanics[0], dict)
        and mechanics[0].get("mech") == "teleport"
        and mechanics[0].get("values") == [],
        "Shoulder Check reshape must be Command: Fear teleport with shootRange 1 and distanceFromFirst 1",
    )
    pilots = load_json(
        root / "custom_factions" / "runtime_mechanics" / "homm3_state_pilots.json"
    )
    bell_pilots = [
        row
        for row in (pilots.get("definitions") or [])
        if isinstance(row, dict)
        and (
            row.get("mechanicId") == "diagnostic.bellwether_shoulder_check"
            or (
                isinstance(row.get("activation"), dict)
                and row["activation"].get("unitSid") == "h3_bellwether_armadillo"
                and isinstance(row.get("operation"), dict)
                and row["operation"].get("kind") == "MovementPush"
            )
        )
    ]
    require(
        len(bell_pilots) == 1
        and bell_pilots[0].get("mechanicId") == "diagnostic.bellwether_shoulder_check"
        and bell_pilots[0].get("enabled") is False,
        "Bellwether Shoulder Check DS MovementPush pilot must exist and stay disabled (native push_unit owns product)",
    )
    require(
        shoulder_check.get("attackType") == "cast",
        "Shoulder Check envelope attackType must be cast for adjacent-only strike",
    )

    project = (plugin / "OfflineUnlockMod.csproj").read_text(encoding="utf-8-sig")
    require(
        "ValidateHomm3RuntimeMechanicsContract" in project
        and "validate_homm3_runtime_mechanics_contract.py" in project,
        "OfflineUnlockMod.csproj must wire runtime-mechanics validation",
    )
    require(
        r"custom_factions\**\homm3_*.json" in project,
        "plugin deploy must recursively include runtime_mechanics/homm3_*.json",
    )

    registry = (plugin / "Homm3RuntimeMechanicRegistry.cs").read_text(
        encoding="utf-8-sig"
    )
    for token in (
        "ValidateAdapterManifest",
        "IsAdapterActive",
        "GetPreparedHookSurfaces",
        "TryGetActiveMechanicsForUnitSid",
        "PublishPreparedSnapshot",
        "DisablePreparedSnapshot",
    ):
        require(token in registry, f"runtime registry missing {token!r}")

    print("validated HoMM3 direct-state runtime-mechanics contract")


if __name__ == "__main__":
    main()
