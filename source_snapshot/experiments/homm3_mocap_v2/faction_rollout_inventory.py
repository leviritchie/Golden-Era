"""Read-only roster and source availability inventory; never a readiness gate."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _index(rows: list[dict], key: str) -> dict:
    result = defaultdict(list)
    for row in rows:
        result[row.get(key)].append(row)
    return result


def build_inventory(factions: list[tuple[str, dict]], imports: dict, manifest: dict,
                    selection: dict, mesh_inventory: dict, *, root: Path) -> dict:
    """Keep every defined roster slot, including missing and ambiguous joins."""
    import_index = defaultdict(list)
    for entry in imports["entries"]:
        for sid in entry.get("gameUnitSids", []):
            import_index[sid].append(entry)
    bundle_index = _index(manifest["units"], "bundleName")
    mesh_index = _index(mesh_inventory.get("units", []), "labSid")
    selected_index = _index(selection.get("units", []), "gameSid")
    excluded_index = _index(selection.get("excluded", []), "gameSid")
    rows, faction_rows = [], []
    for filename, faction in factions:
        faction_sid = faction["identity"]["factionSid"]
        variants, lines = faction["unitVariants"], faction["unitLines"]
        faction_rows.append({"factionSid": faction_sid, "source": filename,
                             "lineCount": len(lines), "variantCount": len(variants),
                             "slotCount": len(lines) * len(variants)})
        for line_index, line in enumerate(lines):
            for variant_index, variant in enumerate(variants):
                sid = line.get("variantSids", {}).get(variant, line["baseSid"] + variant)
                names = line.get("names", [])
                issues = []
                name = names[variant_index] if variant_index < len(names) else None
                if not name:
                    issues.append("missing_display_name")
                row = {"factionSid": faction_sid, "tier": line.get("tier"),
                       "lineIndex": line_index, "variant": variant, "gameSid": sid,
                       "name": name, "definition": filename, "issues": issues,
                       "proofTier": "source-and-filesystem-inventory-only",
                       "animationCompletion": "unproven", "lightingCompletion": "unproven",
                       "installedCompletion": "unproven"}
                matches = import_index.get(sid, [])
                row["importMatches"] = [{k: entry.get(k) for k in
                    ("bundleName", "battleResPath", "battlePrefabAssetPath", "mapPrefabAssetPath")} for entry in matches]
                row["labSid"], row["bundleName"] = None, None
                if len(matches) != 1:
                    issues.append("missing_import_mapping" if not matches else "ambiguous_import_mapping")
                else:
                    entry = matches[0]
                    bundle = entry.get("bundleName")
                    row["bundleName"] = bundle
                    bundle_matches = bundle_index.get(bundle, []) if bundle else []
                    row["unitManifestMatches"] = bundle_matches
                    if len(bundle_matches) != 1:
                        issues.append("missing_bundle_mapping" if not bundle_matches else "ambiguous_bundle_mapping")
                    else:
                        unit = bundle_matches[0]
                        row["labSid"] = unit.get("unitSid")
                        for imported, built in (("battlePrefabAssetPath", "battlePrefabAsset"),
                                                ("mapPrefabAssetPath", "mapPrefabAsset")):
                            if entry.get(imported) != unit.get(built):
                                issues.append(imported + "_mismatch")
                selected = selected_index.get(sid, [])
                row["currentSelection"] = selected
                row["explicitExclusions"] = excluded_index.get(sid, [])
                row["currentSelectionCoverage"] = "absent" if not selected else "selected-candidate" if len(selected) == 1 else "ambiguous"
                if len(selected) > 1:
                    issues.append("ambiguous_current_selection")
                if selected and row["explicitExclusions"]:
                    issues.append("selection_and_exclusion_conflict")
                for item in selected:
                    if item.get("labSid") != row["labSid"] or item.get("bundleName") != row["bundleName"]:
                        issues.append("current_selection_mapping_mismatch")
                mesh_matches = mesh_index.get(row["labSid"], []) if row["labSid"] else []
                if len(mesh_matches) > 1:
                    issues.append("ambiguous_mesh_inventory_mapping")
                mesh_inputs = []
                for item in mesh_matches:
                    value = item.get("glb")
                    path = Path(value) if value else None
                    if path is not None and not path.is_absolute():
                        path = root / path
                    mesh_inputs.append({"path": str(path) if path else None,
                                        "exists": path.is_file() if path else False,
                                        "declaredRole": item.get("meshRole"),
                                        "placeholderFrom": item.get("placeholderFrom"),
                                        "authority": "legacy-mesh-location-only; not motion or acceptance"})
                row["meshInputs"] = mesh_inputs
                row["meshAvailability"] = "unmapped" if not mesh_inputs else "available" if any(x["exists"] for x in mesh_inputs) else "missing-file"
                rows.append(row)
    counts = Counter(row["gameSid"] for row in rows)
    for row in rows:
        if counts[row["gameSid"]] > 1:
            row["issues"].append("duplicate_roster_game_sid")
    return {"schema": "current-mocap-faction-rollout-inventory-v1", "inventoryOnly": True,
            "completionClaim": "none; source availability and candidate selection are not completion",
            "factions": faction_rows, "units": rows,
            "counts": {"factions": len(faction_rows), "rosterSlots": len(rows),
                       "expectedSlotsFromDefinitions": sum(x["slotCount"] for x in faction_rows),
                       "uniqueGameSids": len(counts),
                       "selectedCandidateSlots": sum(x["currentSelectionCoverage"] == "selected-candidate" for x in rows),
                       "meshAvailableSlots": sum(x["meshAvailability"] == "available" for x in rows),
                       "legacyDeclaredOwnMeshSlots": sum(any(m["exists"] and m["declaredRole"] == "own_glb" for m in x["meshInputs"]) for x in rows),
                       "legacyDeclaredPlaceholderSlots": sum(any(m["exists"] and m["declaredRole"] == "family_placeholder" for m in x["meshInputs"]) for x in rows),
                       "slotsWithIssues": sum(bool(x["issues"]) for x in rows)}}


def run(root: Path, output: Path) -> dict:
    paths = sorted((root / "custom_factions").glob("homm3_*.json"))
    import_path = root / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_import.json"
    manifest_path = root / "tools/homm3_import/homm3_units_manifest.json"
    selection_path = root / "experiments/homm3_mocap_v2/stronghold_ingame_test.json"
    mesh_path = root / "artifacts/homm3_smartrig_skinned_rollout/status.json"
    def read(path: Path):
        return json.loads(path.read_text(encoding="utf-8-sig"))
    factions = [(str(path.relative_to(root)), read(path)) for path in paths]
    result = build_inventory(factions, read(import_path), read(manifest_path), read(selection_path), read(mesh_path), root=root)
    result["sources"] = [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                         for path in [*paths, import_path, manifest_path, selection_path, mesh_path]]
    if output.resolve() in {Path(item["path"]).resolve() for item in result["sources"]}:
        raise ValueError("inventory output must not overwrite an input")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/homm3_mocap_v2/faction_rollout_v1/inventory.json")
    args = parser.parse_args()
    print(json.dumps(run(args.root.resolve(), args.output.resolve())["counts"], indent=2))
