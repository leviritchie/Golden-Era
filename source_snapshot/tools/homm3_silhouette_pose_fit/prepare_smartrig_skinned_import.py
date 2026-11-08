#!/usr/bin/env python3
"""Write Unity lab specs and import-table paths for SmartRig skinned units.

Only units with a generated delivery_manifest.json (own GLB clips) or a family
peer delivery (placeholder idle) are eligible. Does not invent missing clips.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_TOOL = Path(__file__).resolve().parent
if str(_TOOL) not in sys.path:
    sys.path.insert(0, str(_TOOL))
_TOOLS = _TOOL.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from gpu_cascade_delivery import (  # noqa: E402
    IDLE_GROUP,
    SKIPPED_DEF_GROUPS,
    contract_name_for_group,
)
from deliberate_motion_contract import lifecycle_role_for_clip_name  # noqa: E402

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
DEFAULT_OUT = ROOT / "artifacts/homm3_smartrig_skinned_rollout"
OUT = DEFAULT_OUT
STATUS = OUT / "status.json"
FIT_PLAN = OUT / "fit_plan.json"
IMPORT_TABLE = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_import.json"
)
UNITS_MANIFEST = ROOT / "tools/homm3_import/homm3_units_manifest.json"
SKINNED_MANIFEST = OUT / "homm3_units_manifest_skinned_rollout.json"
LAB_SPEC = OUT / "unity_lab_batch.json"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def delivery_manifest(lab_sid: str) -> dict[str, Any] | None:
    path = OUT / "units" / lab_sid / "delivery_manifest.json"
    if not path.is_file():
        return None
    payload = _load(path)
    if not isinstance(payload, dict) or not payload.get("clips"):
        return None
    return payload


def pbr_path(payload: dict[str, Any], key: str) -> str:
    pbr = payload.get("pbr") or {}
    value = pbr.get(key)
    if isinstance(value, dict):
        value = value.get("output")
    if not value:
        raise RuntimeError(f"{payload.get('labSid')} delivery is missing PBR {key}")
    return str(value)


def master_path(payload: dict[str, Any]) -> str:
    master = payload.get("master") or {}
    value = master.get("master") or master.get("output") or payload.get("masterPath")
    if not value:
        raise RuntimeError(f"{payload.get('labSid')} delivery is missing oriented master GLB")
    return str(value)


def clip_specs(payload: dict[str, Any]) -> list[dict[str, str]]:
    clips = []
    for item in payload.get("clips") or []:
        name = item.get("contractName")
        path = item.get("output")
        if not name or not path:
            raise RuntimeError(f"{payload.get('labSid')} clip row is missing contractName/output")
        clips.append(
            {
                "contractName": str(name),
                "sourcePath": str(path),
                "lifecycleRole": lifecycle_role_for_clip_name(str(name)),
            }
        )
        if item.get("fps") is not None:
            clips[-1]["fps"] = float(item["fps"])
    if not clips:
        raise RuntimeError(f"{payload.get('labSid')} has no exported clips")
    return clips


def idle_only_from_peer(peer: dict[str, Any], lab_sid: str, prefix: str) -> dict[str, Any]:
    idle_name = f"{prefix}_Idle"
    idle = next((item for item in peer.get("clips") or [] if item.get("contractName") == idle_name or str(item.get("contractName") or "").endswith("_Idle")), None)
    if idle is None:
        raise RuntimeError(f"{lab_sid} placeholder peer has no Idle clip")
    return {
        "labSid": lab_sid,
        "clipPrefix": prefix,
        "masterGlb": master_path(peer),
            "albedo": pbr_path(peer, "albedo"),
            "normal": pbr_path(peer, "normal"),
            "metallicGloss": pbr_path(peer, "metallicGloss"),
        "placeholderIdleOnly": True,
        "clips": [
            {
                "contractName": f"{prefix}_Idle",
                "sourcePath": str(idle.get("output")),
                "lifecycleRole": "cycle",
            }
        ],
    }


def planned_contract_names(plan_row: dict[str, Any], prefix: str) -> set[str]:
    names: set[str] = set()
    for choice in plan_row.get("choices") or []:
        groups = [int(group) for group in choice.get("groups") or []]
        motion = [group for group in groups if group != IDLE_GROUP]
        if not motion:
            names.add(f"{prefix}_Idle")
            continue
        for group in motion:
            if group in SKIPPED_DEF_GROUPS:
                continue
            names.add(contract_name_for_group(group, prefix))
    return names


def build_lab_spec(row: dict[str, Any]) -> dict[str, Any] | None:
    sid = row["labSid"]
    prefix = "Crusader" if sid == "h3_crusader" else "Unit"
    own = delivery_manifest(sid)
    if own is not None:
        spec = {
            "labSid": sid,
            "clipPrefix": prefix,
            "masterGlb": master_path(own),
            "albedo": pbr_path(own, "albedo"),
            "normal": pbr_path(own, "normal"),
            "metallicGloss": pbr_path(own, "metallicGloss"),
            "placeholderIdleOnly": bool(own.get("idleOnly") or own.get("placeholderIdleOnly")),
            "clips": clip_specs(own),
        }
        if own.get("provenance", {}).get("motionAuthority"):
            spec["motionAuthority"] = own["provenance"]["motionAuthority"]
        if isinstance(own.get("skinWeights"), dict):
            spec["skinWeights"] = str(own["skinWeights"].get("path") or "")
            spec["skinWeightsSha256"] = str(own["skinWeights"].get("sha256") or "")
        elif own.get("skinWeights"):
            spec["skinWeights"] = str(own["skinWeights"])
            if own.get("skinWeightsSha256"):
                spec["skinWeightsSha256"] = str(own["skinWeightsSha256"])
        if own.get("rawManifest"):
            spec["rawManifest"] = str(own["rawManifest"])
        if own.get("rawManifestSha256"):
            spec["rawManifestSha256"] = str(own["rawManifestSha256"])
        idle_name = f"{prefix}_Idle"
        clip_names = {item.get("contractName") for item in spec["clips"]}
        if clip_names == {idle_name}:
            spec["placeholderIdleOnly"] = True
        return spec
    if row.get("meshRole") == "family_placeholder":
        peer_sid = row.get("placeholderFrom")
        if not peer_sid:
            return None
        peer = delivery_manifest(str(peer_sid))
        if peer is None:
            return None
        spec = idle_only_from_peer(peer, sid, prefix)
        spec["masterGlb"] = master_path(peer)
        return spec
    return None


def owned_prefab(lab_sid: str) -> str:
    # 2026-10-08: the Crusader binds the shared owned-skinned prefab like every other lab unit.
    return f"Assets/CustomUnits/homm3_lab/{lab_sid}/OwnedSkinned/owned_skinned.prefab"


def main() -> int:
    global OUT, STATUS, FIT_PLAN, SKINNED_MANIFEST, LAB_SPEC
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rollout-dir",
        type=Path,
        default=DEFAULT_OUT,
        help="fused_push or smartrig rollout root (units/*/delivery_manifest.json)",
    )
    parser.add_argument("--write-import", action="store_true", help="rewrite homm3_import.json prefab paths for ready units")
    parser.add_argument("--write-units-manifest", action="store_true", help="rewrite homm3_units_manifest.json skinned lanes for ready units")
    parser.add_argument(
        "--lab-sids",
        default="",
        help="comma-separated lab SIDs to include (default: every ready unit)",
    )
    parser.add_argument(
        "--require-chosen-set",
        action="store_true",
        help="own-GLB units are ready only when delivery clips cover the 3D-relevant plan (not idle-only)",
    )
    parser.add_argument(
        "--selection",
        type=Path,
        default=ROOT / "experiments/homm3_mocap_v2/stronghold_ingame_test.json",
        help="current-mocap selection used for the pre-write delivery validator",
    )
    args = parser.parse_args()
    rollout = Path(args.rollout_dir).resolve()
    OUT = rollout
    STATUS = OUT / "status.json"
    FIT_PLAN = OUT / "fit_plan.json"
    SKINNED_MANIFEST = OUT / "homm3_units_manifest_skinned_rollout.json"
    LAB_SPEC = OUT / "unity_lab_batch.json"
    if (args.write_import or args.write_units_manifest) and not args.require_chosen_set:
        raise SystemExit(
            "refusing to write import/manifest without --require-chosen-set "
            "(idle-only Golden Era installs are forbidden)"
        )
    if (args.write_import or args.write_units_manifest) and not str(args.lab_sids).strip():
        raise SystemExit(
            "refusing to write import/manifest without --lab-sids "
            "(a blank list rewrites every ready unit onto OwnedSkinned paths)"
        )
    # fused_push writes delivery under --rollout-dir but inventory status lives
    # beside the smartrig catalog; fall back so prepare can run against either root.
    if not STATUS.is_file():
        from inventory_smartrig_skinned_rollout import STATUS_PATH as _INVENTORY_STATUS

        if not _INVENTORY_STATUS.is_file():
            raise SystemExit(f"missing status.json at {STATUS} and {_INVENTORY_STATUS}")
        STATUS = _INVENTORY_STATUS
        print(f"prepare: using inventory status {STATUS}", flush=True)
    status = _load(STATUS)
    plan_by_sid = {}
    if FIT_PLAN.is_file():
        for item in _load(FIT_PLAN).get("plan") or []:
            plan_by_sid[item.get("labSid")] = item
    specs = []
    skipped = []
    wanted = {part.strip() for part in str(args.lab_sids).split(",") if part.strip()}
    for row in status["units"]:
        if wanted and row.get("labSid") not in wanted:
            continue
        plan_row = plan_by_sid.get(row.get("labSid")) or {}
        if plan_row.get("blocked"):
            skipped.append(
                {
                    "labSid": row["labSid"],
                    "reason": plan_row.get("reason") or "plan blocked",
                    "blocked": True,
                }
            )
            continue
        try:
            spec = build_lab_spec(row)
        except RuntimeError as exc:
            skipped.append({"labSid": row["labSid"], "reason": str(exc)})
            continue
        if spec is None:
            skipped.append(
                {
                    "labSid": row["labSid"],
                    "reason": row.get("unfilledReason") or "clips not generated yet",
                    "meshRole": row.get("meshRole"),
                }
            )
            continue
        if args.require_chosen_set and row.get("meshRole") == "own_glb":
            if plan_row.get("error"):
                skipped.append({"labSid": row["labSid"], "reason": plan_row["error"]})
                continue
            required = planned_contract_names(plan_row, spec["clipPrefix"])
            have = {item.get("contractName") for item in spec.get("clips") or []}
            missing = sorted(required - have)
            if missing:
                skipped.append(
                    {
                        "labSid": row["labSid"],
                        "reason": "chosen clip set incomplete: " + ", ".join(missing),
                    }
                )
                continue
        specs.append(spec)
    # Current mocap delivery is validated before any import-table or batch
    # artifact is written. Legacy fused rollouts do not carry this authority
    # field and retain their existing preparation path.
    if any(spec.get("motionAuthority") == "current_mocap_v2" for spec in specs):
        from validate_homm3_mocap_delivery_contract import validate as _validate_delivery

        selection_path = args.selection.resolve()
        errors = _validate_delivery(rollout_dir=OUT, selection_path=selection_path)
        if errors:
            raise SystemExit("current mocap delivery validation failed:\n" + "\n".join(errors))
    _dump(LAB_SPEC, {"units": specs})
    skinned_units = []
    ready_sids = {spec["labSid"] for spec in specs}
    units_manifest = _load(UNITS_MANIFEST)
    for unit in units_manifest.get("units") or []:
        sid = unit.get("unitSid")
        if sid not in ready_sids:
            continue
        skinned_units.append(
            {
                **unit,
                "battlePrefabAsset": owned_prefab(sid),
                "mapPrefabAsset": owned_prefab(sid),
                "battlePresentationLane": "skinned_mesh",
            }
        )
    _dump(SKINNED_MANIFEST, {"formatVersion": 1, "units": skinned_units})

    if args.write_import:
        table = _load(IMPORT_TABLE)
        changed = 0
        for entry in table.get("entries") or []:
            battle = str(entry.get("battlePrefabAssetPath") or "").replace("\\", "/")
            lab_sid = None
            for spec in specs:
                if f"/homm3_lab/{spec['labSid']}/" in battle or battle.endswith(f"/homm3_lab/{spec['labSid']}/battle.prefab"):
                    lab_sid = spec["labSid"]
                    break
                if f"/homm3_lab/{spec['labSid']}/OwnedSkinned/" in battle:
                    lab_sid = spec["labSid"]
                    break
            if lab_sid is None:
                # also match audio stem / folder from current billboard path
                for spec in specs:
                    token = f"homm3_lab/{spec['labSid']}/"
                    if token in battle or token in str(entry.get("mapPrefabAssetPath") or "").replace("\\", "/"):
                        lab_sid = spec["labSid"]
                        break
            if lab_sid is None:
                continue
            prefab = owned_prefab(lab_sid)
            if entry.get("battlePrefabAssetPath") == prefab and entry.get("mapPrefabAssetPath") == prefab:
                continue
            entry["battlePrefabAssetPath"] = prefab
            entry["mapPrefabAssetPath"] = prefab
            changed += 1
        _dump(IMPORT_TABLE, table)
        print(json.dumps({"importRowsUpdated": changed}, indent=2), flush=True)

    if args.write_units_manifest:
        for unit in units_manifest.get("units") or []:
            sid = unit.get("unitSid")
            if sid not in ready_sids:
                continue
            unit["battlePrefabAsset"] = owned_prefab(sid)
            unit["mapPrefabAsset"] = owned_prefab(sid)
            unit["battlePresentationLane"] = "skinned_mesh"
        _dump(UNITS_MANIFEST, units_manifest)

    print(
        json.dumps(
            {
                "ready": len(specs),
                "skipped": len(skipped),
                "labSpec": str(LAB_SPEC),
                "skinnedManifest": str(SKINNED_MANIFEST),
                "skippedSample": skipped[:12],
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
