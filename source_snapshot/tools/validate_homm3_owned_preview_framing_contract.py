#!/usr/bin/env python3
"""Owned skinned UI preview framing contract (detail window, hire screen, BhUnitPreviews pool).

Rule: every preview lane frames an owned skinned unit by its OWN battle size -
world height = battleHeightHexes * battleWorldHeightPerHex through Homm3ImportVisuals.FitSkinnedBattleMesh,
lowest idle-0 vertex planted on the model root by moving the Orientation / MocapDeliveryRoot wrap. Never the
donor's height or bounds: the retired PlaceOwnedSkinnedPreviewAtVanillaMeshPose sized the detail window to the
donor prefab (0.53x-2.26x battle size) and the pool/hire lane to raw bundle size x the donor-copied view scale
(0.13x-87x). Native framing has one fixed camera and no bounds fit, so size must be right before it renders.

Checks:
  * source: the framing class uses the battle fit and plants on the wrap, refuses without battleHeightHexes, and
    every preview caller goes through Homm3OwnedSkinnedPreviewFraming.TryFrame; the retired donor rule is not
    called from any preview hook.
  * generated artifact tools/homm3_import/owned_preview_framing.json (measure_owned_preview_framing.py): covers
    every owned skinned SID of homm3_import.json, agrees with the table's battleHeightHexes / perHex (staleness),
    after-height = hexes * perHex, and no unit's structure defeats the wrap plant.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_homm3_owned_skinned_preview_contract import owned_skinned_sids  # noqa: E402

PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
FRAMING = PLUGIN / "Homm3OwnedSkinnedPreviewFraming.cs"
IMPORT_TABLE = PLUGIN / "homm3_import.json"
ARTIFACT = ROOT / "tools" / "homm3_import" / "owned_preview_framing.json"
SCHEMA = "owned_preview_framing.v1"

PREVIEW_CALLERS = {
    "Homm3ImportUnitPreviewModelHook.cs": "Homm3OwnedSkinnedPreviewFraming.TryFrame(instance, entry, vanilla, keepPose, 0f, source, Plugin.LogSource);",
    "Homm3ImportPreviewSyntheticMeshHook.cs": 'Homm3OwnedSkinnedPreviewFraming.TryFrame(instance, entry, null, keepPose: false, c, "preview-synthetic", Plugin.LogSource);',
    "Homm3ImportPreviewWindowHook.cs": 'Homm3OwnedSkinnedPreviewFraming.TryFrame(instance, skinnedEntry, vanilla, keepPose: false, 0f, "preview-window", Plugin.LogSource);',
}
RETIRED = ("PlaceOwnedSkinnedPreviewAtVanillaMeshPose", "AlignOwnedSkinnedPreviewToDonorCenter",
           "AlignOwnedSkinnedPreviewToParentSlot", "FitSkinnedMeshToDonorWorldHeight", "FitSkinnedMeshToPreviewBackground")

FRAMING_REQUIRED = (
    ("Homm3ImportVisuals.FitSkinnedBattleMesh(null, skinned, entry, log);", "preview size must be the battle fit, with no donor"),
    ("!entry.BattleHeightHexes.HasValue", "a unit without battleHeightHexes must be refused, not donor-sized"),
    ("wrap.position += Vector3.up * plant;", "feet must be planted by moving the wrap (native zeroes the root position)"),
    ("var plant = root.position.y - bounds.min.y;", "plant = lowest rendered point onto the model root"),
    ("first.localScale = new Vector3(Mathf.Sign(s.x), Mathf.Sign(s.y), Mathf.Sign(s.z)) * nativeFirstChildScale;",
     "the native first-child view-scale write must be applied before the fit so its repeat is idempotent"),
)
FRAMING_FORBIDDEN = RETIRED + ("TryGetPreviewDonorSid", "donorBounds")


def main() -> int:
    errors: list[str] = []
    framing = FRAMING.read_text(encoding="utf-8", errors="replace") if FRAMING.is_file() else ""
    if not framing:
        errors.append(f"missing {FRAMING}")
    for text, why in FRAMING_REQUIRED:
        if text not in framing:
            errors.append(f"{FRAMING.name}: missing {text!r} ({why})")
    for text in FRAMING_FORBIDDEN:
        if text in framing:
            errors.append(f"{FRAMING.name}: forbidden {text!r} (preview size must not follow a donor)")
    fit_at = framing.find("FitSkinnedBattleMesh(")
    plant_at = framing.find("wrap.position += Vector3.up * plant;")
    if fit_at >= 0 and plant_at >= 0 and plant_at < fit_at:
        errors.append(f"{FRAMING.name}: the plant must follow the battle fit")

    for name, call in PREVIEW_CALLERS.items():
        src = (PLUGIN / name).read_text(encoding="utf-8", errors="replace")
        if call not in src:
            errors.append(f"{name}: missing {call!r} (owned skinned preview must use the battle-size framing rule)")
        for text in RETIRED:
            if text in src:
                errors.append(f"{name}: forbidden {text!r} (retired donor-sized preview rule)")

    # Generated artifact.
    table = json.loads(IMPORT_TABLE.read_text(encoding="utf-8-sig"))
    per_hex = table.get("battleWorldHeightPerHex")
    if not isinstance(per_hex, (int, float)) or per_hex <= 0:
        errors.append(f"{IMPORT_TABLE.name}: battleWorldHeightPerHex missing; the preview rule has no scale")
    if not ARTIFACT.is_file():
        errors.append(f"missing {ARTIFACT} (run tools/homm3_import/measure_owned_preview_framing.py)")
    else:
        art = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        rows = art.get("rows") or {}
        if art.get("schema") != SCHEMA:
            errors.append(f"{ARTIFACT.name}: schema {art.get('schema')!r} != {SCHEMA!r}")
        if art.get("battleWorldHeightPerHex") != per_hex:
            errors.append(f"{ARTIFACT.name}: perHex {art.get('battleWorldHeightPerHex')} != table {per_hex} (stale; re-measure)")
        hexes_by_sid: dict[str, float] = {}
        for entry in table.get("entries") or []:
            for sid in entry.get("gameUnitSids") or []:
                if sid:
                    hexes_by_sid[sid] = entry.get("battleHeightHexes")
        owned, _ = owned_skinned_sids(IMPORT_TABLE, None, {}, [])
        missing = sorted(owned - set(rows))
        extra = sorted(set(rows) - owned)
        if missing:
            errors.append(f"{ARTIFACT.name}: {len(missing)} owned skinned SID(s) unmeasured (stale): {missing[:8]}")
        if extra:
            errors.append(f"{ARTIFACT.name}: {len(extra)} row(s) no longer owned skinned (stale): {extra[:8]}")
        for sid in sorted(owned & set(rows)):
            row = rows[sid]
            hexes = hexes_by_sid.get(sid)
            if hexes is None:
                errors.append(f"{sid}: owned skinned unit has no battleHeightHexes; its preview would be refused")
                continue
            if "error" in row:
                errors.append(f"{sid}: measurement failed: {row['error']}")
                continue
            if row.get("battleHeightHexes") != hexes:
                errors.append(f"{sid}: artifact hexes {row.get('battleHeightHexes')} != table {hexes} (stale; re-measure)")
            after = (row.get("after") or {}).get("height")
            if not isinstance(after, (int, float)) or abs(after - hexes * per_hex) > 1e-3:
                errors.append(f"{sid}: after height {after} != hexes*perHex {hexes * per_hex:.4f}")
            if not row.get("plantNode"):
                errors.append(f"{sid}: no Orientation/MocapDeliveryRoot wrap to plant on")
            elif not row.get("placedUnderPlantNode"):
                errors.append(f"{sid}: rendered geometry outside the wrap; the plant would not move it")
            if row.get("plantNodeAnimated"):
                errors.append(f"{sid}: an animation clip drives the wrap position and would undo the plant")
            if row.get("firstChildScaleAnimated"):
                errors.append(f"{sid}: an animation clip drives the first child's scale and would undo the fit")

    if errors:
        print("FAIL: owned skinned preview framing contract")
        for e in errors:
            print("  - " + e)
        return 1
    print(f"OK: owned skinned preview framing contract ({len(PREVIEW_CALLERS)} preview callers on the battle-size rule)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
