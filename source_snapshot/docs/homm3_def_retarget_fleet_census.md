# HoMM3 DEF-retarget fleet census and rollout

Operational note for getting every finished DEF-retarget unit into the game through the existing
`ship_def_retarget_slice.py` lane (prepare -> lab -> bundles -> probe; the user runs `deploy`).

- Census table (every `homm3_import.json` OwnedSkinned row): `docs/homm3_def_retarget_fleet_census.json`,
  written by `tools/homm3_def_retarget_delivery/fleet_census.py` (read-only over the canonical chain).
- Rebuild driver: `tools/homm3_def_retarget_delivery/fleet_rebuild.py <unit>...` (sequences the existing
  unit tools only; per-unit record `artifacts/homm3_def_retarget_delivery/_fleet_logs/rebuild_<unit>.json`).
- Freeze: `tools/homm3_def_retarget_delivery/freeze_slice.py <slice> <unit>...` writes the selection
  `tools/homm3_def_retarget_delivery/<slice>.json` and its frozen inputs + idle retime.
- Mesh identity (2026-09-28, after the wolf rider/raider swap shipped): `build_unit.py` stamps the smartrigged file it
  rigged (`tools/homm3_def_retarget/source_mesh.py`, GLB `asset.extras.homm3DefRetargetSourceMesh`, carried by every
  later stage). Freeze refuses, and every ship stage re-refuses, a GLB whose source is not the identity review's
  (`defRetargetMesh` when the review has one, else `meshSha256`) or, for an unreviewed unit, not its own current
  `<unit>_smartrigged.glb`, or is under `_superseded_do_not_use/`; rows record `sourceMeshSha256` + `identityReview`.
  Pre-stamp builds pass only through `tools/homm3_def_retarget/source_mesh_legacy.json` (per-unit body UV set,
  attested once; the list only shrinks). Fix for a refusal: a full `run_unit.sh` build on the right mesh, then re-freeze.
  Rule: `tools/homm3_def_retarget_delivery/source_mesh_identity.py`; tests `test_source_mesh_identity.py`.

Proof tier of everything here: generated artifact (and offline Unity bundle probe once a slice probes).
Nothing is installed by these tools; in-game look is unproven until the user deploys and looks.

## Classification

| class | meaning |
| --- | --- |
| `shipped` | already in a `*_slice_v1.json` selection |
| `ship_now` | bake on the Tikhonov solve (or disabled by the unit config), `glb_verify` within tolerance, morph ratio <= 1.5, emphasis settled, look stamp applied on the current canonical GLB |
| `rebuild_then_ship` | fixable by rerunning the existing tools: stale bake, morph over the gate, failed verify, look not on the current GLB, emphasis pending |
| `blocked` | no retarget build or no animation (declared mesh-identity rows are listed as known issues only) |
| `out_of_scope` | neutral rows (a parallel agent owns the neutral slices) |

"Stale bake" = the canonical `.blend` (written only by `build_unit.py`, `bake_cs.py` or the emphasis
install) was saved before c08b4ea145 / a9de7da122, i.e. its corrective-smooth morphs came from the
det > 1e-6 solve. The e5010f6abd -60 conform lives in the lab builder, so every slice built now carries it.

## Pre-rollout census (2026-09-26 19:5x, `_fleet_logs/census_pre_rollout_20260926.json`)

262 rows: 244 `rebuild_then_ship`, 8 `shipped`, 5 `blocked`, 5 `out_of_scope`, 0 `ship_now`.

- Every non-shipped build predates the bake fix (blends saved 2026-09-24/25).
- **75 of 252 measured GLBs exceed the morph gate** (worst offset / rest height > 1.5), i.e. they would ship
  at speck size exactly like the storm elemental did; worst: h3_gremlin 1553, h3_medusa_warrior 1233,
  h3_couatl_upg_alt 891, h3_gremlin_upg 754, h3_harpy_hag 732. Median over the fleet 0.47.
  The installed bundles of these units come from the earlier pipeline, not from these GLBs.
- `glb_verify.json` passes on every built unit; no look stamp is out of date against its canonical GLB.
- Blocked at the pre-rollout census: hota_cove_seaman and h3_cannon (no retarget build or config).
  The census also listed toa_boar_rider, h3_centaur and h3_paokai (h3_wyvern_upg_alt) as blocked on the
  stopgap ledger's declared mesh identity. The Meshy regen agent re-checked the source meshes on 2026-09-26
  and all three are correct (`h3_boar_rider_smartrigged.glb`, `h3_centaur_smartrigged.glb` regenerated
  9/25, `h3_paokai_smartrigged.glb`); their retarget builds (2026-09-25) postdate those meshes, so they are
  `rebuild_then_ship` and ship in their faction slices (the paokai "bear" is the older installed bundle,
  fixed by delivery). toa_boar_rider ships from retarget unit h3_boar_rider (`fleet_census.SOURCE_UNIT`;
  freeze argument `h3_boar_rider:toa_boar_rider`).
- Conflux h3_air / psychic / hurricane / astral elementals carry emphasis `pendingRebuild` owned by the
  elemental-motion work; they are rebuilt last.

## Rebuild route (fleet_rebuild.py)

- Every unit, after the emphasis/bake step and the de-yaw: `stride_match_glb.py apply <u>` (docs/homm3_stride_match.md;
  exit 3 = airborne Move, skipped) before the look, and `freeze_slice.py` gates stride (slip, stride ratio) next to
  facing and articulation.
- Emphasised units: `deliver.py <u> --force` re-plans from the pre-emphasis snapshot and re-bakes through the
  shared `bake_cs.py` (about 30 s), then `look.py <u> --force` (about 2-5 min).
- Other units: `bake_cs.py` on the canonical `.blend`, `RENDER_ONLY=1 run_unit.sh`, `verify_glb.py`,
  `deliver.py <u>` (not for exceptions), then `look.py <u> --force`.
- Measured on the pilot: h3_pikeman morph ratio 0.0617 -> 0.040.

## Slices

Faction slices follow the selection schema of the existing slices and keep the import table's bundle
names, so a deploy replaces in place. Status per slice lives in its selection and output folder;
`tools/validate_homm3_def_retarget_delivery_contract.py` reads them all.

## Quality census (what the game shows now)

`tools/homm3_def_retarget_delivery/quality_census.py` writes `tools/homm3_def_retarget_delivery/census/quality_census.json` (a subfolder: the delivery validator reads every top-level `*.json` there as a slice selection).
It covers every `homm3_import.json` row: custom factions and neutrals, 268 rows. It reads the installed bundles by
sha256 and compares them with each fleet selection's `installed_readback.json`. For each row it records:

- the lane the game shows: `fleet_slice`, `stopgap` or `older_owned_skinned`;
- the mesh identity (repair ledger, declared identity, later regenerations);
- the articulation gate, including jitter, and the facing gate, both measured on the bundled retimed GLB;
- texture binding, quoted from the current `BepInEx/LogOutput.log`;
- the last review date;
- a visibility count: the squads in Core.zip `DB/squads/` that place the unit on custom or campaign maps.

Rows that fail a gate or sit on an older lane are queued. User-reported units come first, then the rest by visibility.
Proof tier: installed-payload and generated-artifact census. Only the texture column is runtime evidence.

First run, 2026-09-26:

- **Lanes.** 29 fleet_slice, 237 older_owned_skinned, 1 stopgap (toa_boar_rider), 1 missing bundle (h3_nomad,
  committed but not deployed). By faction, fleet builds are installed for:
  - castle: 15 of 21;
  - rampart: 3 (the pegasus line);
  - conflux: 2;
  - cove: 2;
  - factory: 1;
  - neutral: 6.

  The held rampart and stronghold slices are not installed. Bulwark, dungeon, fortress, inferno, necropolis and tower
  have no fleet build installed.
- **Articulation.** 4 installed units fail. All four are on the debt list:
  - royal_griffin: wing swing 5.4;
  - battle_griffin: wing swing 9.2, jitter 0.45;
  - angel: wing swing 44.1;
  - seraph: wing swing 55.1.

  The rebuilt angel line passes and is waiting on the castle re-freeze.
- **Facing and texture.** No installed fleet unit fails facing. No albedo or Hex/Lit error appears in the log. 264 rows
  loaded their own bundle texture in the logged sessions.
- **Mesh identity.**
  - 64 verified.
  - 196 unverified: the ledger has no retained generation input. This is not the same as wrong.
  - 4 declared correct at source but stale in the bundle.
  - 2 borrowed.
  - 2 regenerated: the griffins, now with wings spread at rest.
- **Queue.** 245 rows. It starts with royal_griffin, champion, cavalier, battle_griffin and justiciar. Then it runs by
  squads: gog 63, magog 60, water_elemental 52, wolf_raider 51, orc_chieftain 50, hell_hound 45, and so on.
- **Gate additions made with this census:**
  - The articulation gate reads the mount rig's horse legs (`HFL/HFR/HHL/HHR`). Before this, the cavalier line passed
    vacuously.
  - A jitter cap: the 90th-percentile bone's share of rotation energy above 4 Hz on `Unit_Move` must be at most 0.35.
    Vanilla Walk has median 0.071 and p90 0.22. The fleet's worst unit is 0.31.

