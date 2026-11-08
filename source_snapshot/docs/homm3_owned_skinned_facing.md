# Owned-skinned unit facing

Status: active contract. Proof tier: source, lab prefab and installed-bundle validated, and Unity-editor rig
renders (generated artifact). The in-game map and preview facing are **not** runtime-proven until the plugin is
installed and someone looks at it.

## Native convention (installed `resources.assets`, UnityPy census)

- A native unit prefab is a root whose first child is `scale_roll` / `Scale_roll` / `Scale_roll_pos`. The mesh
  faces that child's +Z (inside it, the rest forward is 0 on 115 of 170 map prefabs), and the child carries the
  presentation yaw. Native code only rescales that child: `UiModelsSpawner` / `BhUnitPreviews.SpawnModel` set
  `child(0).localScale`.
- Battle prefabs have first-child yaw +90 on 165 of 176.
- `<unit>_map` prefabs have an authored per-unit yaw toward the camera, about 120 to 240 degrees, and some carry an
  X-mirror scale. An X-mirror does not change a +Z forward. `troglodyte_upg_alt_map` (the map shell of nearly
  every owned unit) has root yaw -20 and `Scale_roll_pos` yaw 145.
- `SquadDrawer.Init` instantiates the map prefab under an unrotated holder, so the map facing is entirely the
  prefab's own. `BhUnitPreviews.TryGetModel` sets the model root to world yaw 22, and the preview camera sits at -Z.

## Our prefab and the plugin rule (fleet convention)

- Every owned skinned prefab has an `Orientation` child of the root. Inside it, the idle-0 mesh of the fleet
  (capture / idle-0 mocap lanes, 230+ units) faces **`OwnedSkinnedBindFacingYaw` = -60**, one hex side clockwise
  of +Z. The measured limb-line median is about -55 (bipeds about -50, Bip01 quadrupeds -60 to -100). The battle
  side heading was tuned on this offset: left 150 and right -30 are native +90 / -90 minus -60. The attack-facing
  hook uses the lane marker (yaw 90) as the mesh forward, which is also consistent with -60.
- **Rule.** Every lane sets `Orientation` to the native presentation yaw minus -60 (`OwnedSkinnedOrientationYawFor`):
  - Battle, left and right: native +90 / -90, giving 150 / -30 (these values are unchanged).
  - Adventure map (`FinishOwnedSkinnedAdventureMapPresentation`, `TryApplyOwnedSkinnedNativeModelFacing`): the
    donor map shell's `scale_roll` yaw, +60.
  - Vanilla-model preview (`Homm3OwnedSkinnedPreviewFraming.TryFrame` -> `TryApplyOwnedSkinnedNativeModelFacing`; the
    retired `PlaceOwnedSkinnedPreviewAtVanillaMeshPose` applied the same yaw): the vanilla model's `scale_roll` yaw, +60.
  - Synthetic preview with no donor (`TryApplyOwnedSkinnedBattlePrefabFacing`): the battle prefab's +90, giving 150.
- Every path fails closed with a `LogError` when a node is missing. No yaw is substituted.
- The baked `Orientation` yaw (+90) no longer matters at runtime, because every lane sets it. No bundle needs a
  rebuild for facing.
- **Phase-1 history (2026-09-26).** The first map and preview fix copied the native yaw with no offset. Units with a
  -60 bind then stood side-on on the map, about 60 degrees off native. The offset rule replaces it.

## Deviations (allowlist)

`tools/homm3_owned_skinned_facing_allowlist.json` records each lane or unit whose idle-0 forward is not within 45 of
-60, with a reason. A row that no longer applies fails the gate, so the list only shrinks.

- **Lane `def_retarget` conforms (2026-09-26, user-approved).** It used to face +Z (0) inside `Orientation`,
  60 degrees off the fleet in every lane (battle world 150, attack aim 60 off). The lab builder
  (`Homm3OwnedSkinnedLabBuild.DefRetarget.cs`, `DefRetargetBindFacingYaw`) now turns every top-level GLB node -60
  about `Orientation`'s Y, after the VFX nodes are built and before the prefab is saved. It refuses any clip that
  animates a top-level GLB node's position or rotation. The delivery GLBs themselves still face glTF +Z. The lane
  row was removed from the allowlist, so the gate enforces -60 on this lane too.
- **Body frame for effects.** Because the body is no longer `Orientation`'s own frame, the effects that
  read a body direction use `Homm3ImportVisuals.OwnedSkinnedBodyRotation` (`Orientation` turned by -60):
  - `Homm3MeshFx` `orient: body` rows;
  - the `Homm3UnitLookVfxRuntime` billboard mirror.

  Their authored values (`bodyYawDeg`) keep their body-relative meaning.
- **Units** in the allowlist:
  - native-donor riders (f about 0);
  - five mixamo units measured at about 0;
  - units whose limb labels are mirrored or non-anatomical (elementals, automaton, worms);
  - units with no left/right limb pair (hydra, chthonian, abyss serpent, boar rider).

  The riders and the units at about 0 are also 60 degrees off in battle today. Fixing any of them is an asset
  re-fit, not a runtime rule.

## Gate

`tools/validate_homm3_owned_skinned_facing_contract.py` runs in three places:

- **OfflineUnlockMod BeforeBuild.** It checks three things:
  - the source rule, including its constants and its use in all four lanes;
  - every lab prefab: `Orientation` at yaw 90 with no tilt and no mirror, and an idle-0 limb-line forward within
    45 of -60 (or the allowlisted value);
  - every built DEF-retarget delivery GLB: idle-0 forward within 45 of +Z.
- **`ship_def_retarget_slice.py` payload gate**, in `--bundle-dir` mode.
- **Mocap `payload_gate`** (`experiments/homm3_mocap_v2/ship_ingame_candidates.py`, also used by
  `ship_remaining_idle0.py`), in `--bundle-dir` mode.

Bundle mode reads every owned skinned prefab in the bundle, found by its lane marker. For each it checks
`Orientation`, the marker, and the bind facing measured on that prefab's own bone copies.

Against the installed `homm3_bundles` with `--name-prefix custom_units_` (2026-09-26), every bundle that
`homm3_import.json` references passes. Nine unreferenced leftovers fail and are not delivered:

- `custom_units_h3_battle_dwarf` and the seven un-prefixed `custom_units_h3_*_upg_alt` bundles have no lane marker;
- `custom_units_temple_griffon` has no `Orientation`.

## Evidence

`python tools/homm3_import/owned_skinned_facing_proof.py --rules before|after|fleet --tag <tag>` renders the native
troglodyte and lab prefabs through the lane compositions (Unity editor, unitylock, memgate first). It writes
`artifacts/homm3_owned_skinned_facing_proof/<tag>/facing_sheet_<rules>.png` and `facing_report.json`. The rig
measures the forward from the validator's limb pairs.

DEF lane conform: `def60_before` (fleet rule on the old +Z DEF prefabs) against `def60_after` (rebuilt lab
prefabs). Each tile reports `attackAimErrorDeg`, the signed angle from the lane marker's forward (which the attack
hook aims at the target) to the body forward.

World forward yaw before -> after, with the attack-aim error in brackets:

| lane | oceanid | tidecaller | storm elemental | pegasus |
|---|---|---|---|---|
| map | -175 -> 125 | -160 -> 140 | -175 -> 125 | -167 -> 133 |
| preview | 172 -> 112 | -173 -> 127 | 172 -> 112 | 180 -> 120 |
| battle L | 150 -> 90 (aim 60 -> 0) | 165 -> 105 (75 -> 15) | 150 -> 90 (60 -> 0) | 158 -> 98 (68 -> 8) |

For comparison, the native troglodyte faces 165 on the map and 152 in the preview.

**Open finding: right-side attack aim (fleet-wide, predates this change).** `TryApplySkinnedBattleTargetFacing` turns
the root so that the lane marker (local yaw 90) points at the target, and it leaves `Orientation` alone. On the
right side `Orientation` is -30, so the body sits at -90 in the root frame, antiparallel to the marker, whatever the
parent mirror is. The DEF lane was 120 off there before and is now 180 off, like every mocap unit. A right-side
attack is therefore expected to face away from its target, and this needs a runtime record. A candidate fix is for
the hook to set `Orientation` to the left-side value (150) while it owns the root yaw. That fix is not done here.

World forward yaw from `phase2_after` (the phase-1 rule, HEAD before this change) and `phase2_fleet`. The camera
direction is 180, and a unit faces the camera when it is within 90 of 180.

| lane | native troglodyte | h3_dwarf | h3_goblin | h3_black_dragon | hota_cove_oceanid (def_retarget, pre-conform) |
|---|---|---|---|---|---|
| map, phase 1 | 165 | 60 (side-on) | 75 (side-on) | 34 (away) | 125 |
| map, fleet | 165 | 120 | 135 | 94 | -175 |
| preview (synthetic and vanilla), phase 1 | 152 | 47 | 62 | 21 | 112 |
| preview, fleet | 152 | 107 | 122 | 81 | 172 |
| battle L / R, phase 1 and fleet (identical) | 130 / 50 | 85 / 85 | 100 / 100 | 59 / 59 | 150 / 150 |

The dragon's -91 thigh line is a quadruped hip reading. Its sheet tile faces the camera.

## Open findings

- **Battle, native reference.** The rig's native battle-right composition comes from the mono demo
  (`rightStayAngle` 180 plus the `SideSettings` X-mirror). It puts the native troglodyte facing away, so that tile
  is not a trustworthy Golden Era reference. For the same reason, the rig's owned battleR tile shows the same world
  yaw as battleL. That is a rig assumption, `ApplySideFacing` sits after the root copy, and the side values are
  unchanged by this change. Battle facing is a runtime-record question, not a regression.
- **Proof tiers.**
  - Source, lab prefab, and installed-bundle validated.
  - Unity-editor rig renders (generated artifact).
  - In-game map and preview facing are not runtime-proven.
