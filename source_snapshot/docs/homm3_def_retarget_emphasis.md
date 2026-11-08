# HoMM3 DEF-retarget animation emphasis pass

Status: **delivered roster-wide as a generated artifact.** The pass rewrites the canonical
DEF-retarget build (`artifacts/homm3_def_retarget/<unit>/<unit>_def_retarget.{blend,glb}`) in place,
stamps the GLB, and is pinned by `tools/validate_homm3_def_retarget_emphasis_contract.py`, which is
wired into the OfflineUnlockMod build. No bundle builder consumes these GLBs yet, so nothing here is
installed or seen in game.

Tool: `tools/homm3_def_retarget_emphasis/`
- `emphasis.py`: detection, plan and invariants (numpy; PIL and the unit-look masks load lazily).
- `bl_keys.py`: Blender side. Dumps the rotation keys, writes emphasised keys back.
- `bl_deliver.py`: the one Blender run per unit (plan, write keys, re-bake corrective smooth,
  render the changed clips, stretch, export).
- `deliver.py`: the per-unit orchestrator and roster batch (`--roster`, `--summary`).
- `look_queue.py`: re-applies the unit look to every emphasised GLB (`look.py <unit> --force`). It
  re-checks that each unit is still due just before running it, so two queues, or a pass list gone
  stale, never redo a unit another run already finished.
- `review_sheet.py`: before/after key sheets per unit and the roster contact sheet.
- `hires_review.py`: high-res stretch renders (shared `review.py`) of emphasised clips, before/after.
- `units/<unit>.json`: per-unit knobs merged over `DEFAULTS` (unknown keys are errors).
- `exceptions.json`: units the pass does not touch, each with a kind and a reason.

## Chain position

`retarget build (run_unit.sh)` → **emphasis** → `idle retime (rollout_idle.py)` → `unit look (look.py --force)`.

Emphasis rewrites the canonical `.blend` and `.glb`, so every later lane must re-read them:
- The idle-cadence lane resolves its input by animation hash; a retimed idle made before emphasis is
  stale and its validator says so.
- The unit look treats the new GLB as a fresh source; `look_queue.py` re-runs `look.py --force` on
  every emphasised unit whose look stamp was not made from the emphasised GLB.

The stamp says the order explicitly: `W/stamp.json` `chain` and `downstream`, and the GLB's
`asset.extras.homm3DefRetargetEmphasis.chain`.

## Why a post-pass, not an `ext/` hook

Detection compares the DEF with the build's own sprite-camera renders, which exist only after a
build. A `before_keys` hook would need those renders before they exist, would need an entry in
~250 unit configs owned by other agents, and would force a rebuild of every unit. The post-pass
runs on any finished build, touches only the canonical `.blend`/`.glb` plus refreshed renders and
metrics, and is re-run (automatically detected as stale) after a rebuild.

## Rule

**Detection** works in silhouette space, the only space the DEF and the fit share. Each action clip
(regex `clips`, default `attack|shoot|hitted|defence|death|cast`; never a loop clip) uses its first
frame `a` as neutral. For the DEF body mask and for the fit's sprite-camera render alpha:
- `area(t) = |M_t xor M_a| / |M_a|`
- `reach(t)`: the outward shift of each bbox edge since `a`, as a fraction of the neutral height.

The **DEF body mask is the unit-look lane's own segmentation** (`bodyNoFx` in
`tools/homm3_unit_look/look.py build_ctx`): `masks.body_mask` minus every `defFlipbook` layer's
`effectMask` for the DEF (group, frame) that layer lists. Baked lightning, breath and bolts are not
body reach. `detect.json` records `fxMasked` and `defFxPixels` per clip.

Keys are the DEF's own extremes (local maxima of `area` ≥ `minDefExcursion` and of each edge's
`reach` ≥ `minDefReach`, merged within one frame, at most `maxKeysPerClip`). At a key,
`r = reach_fit / reach_DEF` on the edge the DEF reaches out furthest:
- `minRatio < r < flagRatio`: **underEmphasised**, exaggerated.
- `r <= minRatio`: **missed**, a retarget fault; reported, never scaled.
- Hips scale < 0.9 at the key: **hidden** (shatter or shrink deaths); never changed.

**Exaggeration** is per selected bone in armature space: the swing since neutral,
`log(M(t) M(a)^-1)`, is scaled by `1 + (G(t) - 1) * boneWeight`, `g = min(maxGain, 1 + strength
(1/r - 1))`, `G` rising by raised cosine to the key and falling back at the clip's last frame (Death
holds it). Around each key: anticipation (`anticipation` × the reversed swing, peaking
`anticipationFrames` before) and follow-through toward `(1 + overshoot)` × the key pose. Caps:
`maxExtraDeg` extra per bone per frame, 170° total; bones with less than `minKeyDeg` swing at the
key are left alone. Results are converted back to local keys against the parent's new rotation.

**Never changed**: Hips and legs; every ancestor of a leg bone (rigs whose legs hang below a spine
bone); an arm chain whose hand comes within `contactBand` of the ground in the clip (a quadruped's
front leg) and every ancestor of it; each clip's first frame; a non-Death clip's last frame; hidden
frames; Idle, Move and every other clip without an underEmphasised key.

## Knobs

Defaults (`emphasis.py DEFAULTS`): `strength 0.5`, `maxGain 1.35`, `maxExtraDeg 18`, `flagRatio 0.8`,
`minRatio 0.15`, `anticipation 0.12`, `anticipationFrames 2`, `followThrough 0.3`, `overshoot 0.05`,
`followFrames 2`, `minDefExcursion 0.06`, `minDefReach 0.03`, `maxKeysPerClip 3`, `contactBand
0.12`, `boneWeights` (spine 0.5–0.7, neck/head 0.6, shoulders 0.8, limbs 1.0), `bones` (regex).
Per unit also: `onlyClips`, `skipClips`. The GLB stamp carries `paramsSha256` = sha256 of
`{version, merged config}`.

The three approved pilots keep their own stronger configs (`strength 0.6`, `maxGain 1.5`,
`maxExtraDeg 22–25`; swordsman `anticipation 0.35` and sword hand/forearm weights `0.3/0.6`).

## Delivery (`deliver.py`)

Per unit, `W = artifacts/homm3_def_retarget_emphasis/<unit>/`:
1. An `exceptions.json` entry skips the unit (reported). A unit another process has open (a
   rebuild, a `look.py`, another agent's `deliver.py`) is deferred and retried once at the batch end.
2. Source: the canonical `.blend` sha vs `W/stamp.json`. Equal to `emphasisedBlendSha256` → the
   pre-emphasis snapshot `W/source/` is the source (same `paramsSha256` → up to date, skipped).
   Anything else is a fresh build and is itself the source.
3. Detection. Nothing underEmphasised → `unchanged`, canonical untouched (restored from
   `W/source/` if it was emphasised under older parameters).
4. Snapshot the build into `W/source/` (`snapshot.json` written last), work copy in `W/work/`,
   one Blender run of `bl_deliver.py`.
5. Checks, all required before install:
   - shared `verify_glb.py` on the work `.blend` vs `work.glb` prints `VERIFY OK`;
   - `check_invariants` on the key dumps: no key change outside emphasised clips or on a first
     frame, non-Death last frames unchanged, hidden frames unchanged, Hips/leg drift 0, contact
     chains planted within their clip, extra rotation ≤ `maxExtraDeg`;
   - `actions.json`: only `Unit_` actions inside emphasised clips were rewritten, never Idle/Move;
   - Idle and Move close their loops in the new round trip;
   - **stretch gate** per emphasised clip: worst frame edges>2x after ≤ max(1.6 × before,
     before + 40). A failure installs nothing (`stretchGateFailed`); the unit then gets an explicit
     per-unit config or an exception.
6. Install: GLB `asset.extras.homm3DefRetargetEmphasis` (schema, version, paramsSha256, source and
   emphasised blend sha, clips, chain); atomic replace of the canonical `.blend` and `.glb` after
   re-checking the canonical `.blend` is still the source; renders, `stretch.json`, `metrics.json`,
   compare gif/mp4 and `glb_verify.json` refreshed; `W/stamp.json` written; `W/work/` removed.

`W/` keeps `stamp.json`, `detect.json`, `plan.json`, `actions.json`, `keys_before.npz`,
`keys_after.npz`, `report.json`, `renders_after/` and `source/` (the pre-emphasis build; the only
way back). A superseded emphasis never stays installed: a new config or version makes the stamp
stale and the next run rebuilds from `W/source/`.

## Validator

`tools/validate_homm3_def_retarget_emphasis_contract.py` (target
`ValidateHomm3DefRetargetEmphasisContract`, skip property `SkipHomm3DefRetargetEmphasisContract`):
- static: `exceptions.json` schema, kinds and reasons; every per-unit config loads and names a
  retarget unit; no unit has both a config and an exception;
- every roster unit has a stamp or an exception (note; error with `--require-complete`);
- stamp version and `paramsSha256` equal the current code and config (error);
- the canonical `.blend` is the stamped one (a later rebuild is a note; error with
  `--require-current`);
- for emphasised units: the GLB is the emphasised export or look's delivery of it through the stamped delivery stages (deyaw, stride match, move low-pass, densify, prop floor, ground: each stage's sourceGlbSha256 links back to the emphasised export, recorded stage outputs must meet the next input; every stage writes `<glb>.<stage>.json` with its source and output sha (deyaw, stride_match, move_lowpass, densify since 2026-09-27; prop_floor, ground before), so a chain built after that is linked end to end; `delivery_chain_errors`, tested by `tools/homm3_def_retarget_emphasis/test_delivery_chain.py`; `fleet_rebuild.py` runs the same check scoped to the unit as its last step, pass or fail, tested by `tools/homm3_def_retarget_delivery/test_fleet_rebuild_chain.py`; a unit that fails there or at any stage gets its pre-run delivered state back byte for byte - GLB, stage sidecars, glb_verify, emphasis and look stamps and look outputs, not the .blend or renders - recorded as `restore` in its rebuild record, tested by `tools/homm3_def_retarget_delivery/test_fleet_rebuild_txn.py`), its extras stamp
  matches, the stored key dumps pass `check_invariants`, `actions.json` rewrote only emphasised
  clips, `glb_verify.json` passes with Idle/Move closing, every emphasised clip passed the stretch
  gate.
Stat fast path: files keeping the size/mtime recorded next to their hash are not re-hashed.

## Roster results

Roster run 2026-09-25, plus `h3_ice_elemental` on 2026-09-26 once no other process had it open (256 folders with a canonical GLB; `roster_summary.json` has every unit):

| decision | units |
|---|---|
| emphasised (installed, stamped) | 244 |
| unchanged (no underEmphasised key, or all flagged keys hidden) | 3: `h3_phoenix`, `h3_fire_elemental`, `h3_automaton_upg_alt` |
| exception (`exceptions.json`) | 9 |

Exceptions:
- `h3_red_dragon_before`: a backup folder with no `.blend`, not a roster unit.
- `h3_air_elemental`, `h3_astral_elemental`, `h3_hurricane_elemental`, `h3_psychic_elemental`,
  `h3_storm_elemental` (`pendingRebuild`): the current build fails its **own** `verify_glb.py`
  round trip before emphasis (mesh error up to 0.04 on every clip, Idle included; re-checked on
  the canonical `.blend`/`.glb`), so no emphasised export can pass. Re-run after the elemental
  rebuilds verify.
- `h3_battle_griffin`, `h3_shadow_dragon`, `h3_efreet_sultan` (`stretchCost`): the stretch gate
  failed and the pass lowered every flagged key's ratio; the deficit is wing (or flame-tail) reach,
  which the pass does not move.

Per-unit reductions after the stretch gate: `h3_vampire` and `h3_wood_elf` (`strength 0.3`,
`maxExtraDeg 11`), both then passed.

Across the 667 emphasised clips (906 flagged keys): the fit/DEF ratio at the flagged keys moves by a
median of +0.00 and a mean of +0.035; 303 keys gain ≥ +0.05, 243 lose some. The worst frame's
edges>2x rises by a median of 4 (×1.10), p90 +23. The largest increases (`h3_wraith` hitted
382 → 488, `h3_banshee` death 321 → 405, `h3_priest` death 275 → 358, `h3_battle_dwarf` defence
462 → 536, `h3_wight` hitted 292 → 352) were reviewed at high resolution: the added tint sits on
cloth that was already stretched and no new tear is visible, so they were kept.

Titan (`h3_giant_upg`) with the effect mask: attack 50 (the bolt, formerly a false key) now reads
`ok` at 1.57; defence 40 0.64 → 0.92; shoot's key moved to 59 (0.65 → 0.72); hitted 30 and death
64 barely move.

The phoenix (`h3_phoenix`, hand-keyed motion 7e95a01be2) has no underEmphasised key (its attack keys
already reach 1.03–1.05 of the DEF; its defence keys are missed wing reach) and is untouched, so the
pass cannot fight its hand keys. `h3_sacred_phoenix` (also hand-keyed) gets at most 2.6–4.1° on
hitted and death.

### Downstream re-run (2026-09-26)

- **Idle retime.** `rollout_idle.py` on the whole roster gives `{"up-to-date": 256}`.
  `validate_homm3_idle_cadence_contract.py` is **OK**: 256 GLB pairs, 0 stale, 34 look VFX idle
  layers on 27 units in step with the retimed idle (see `docs/homm3_idle_cadence.md`).
- **Unit look.** `look_queue.py` re-applied the look to every emphasised unit with a look spec.
  - 244 emphasised units: 5 have no look spec, so the emphasised export is the delivery
    (`h3_dreadnought_upg_alt`, `h3_sacred_phoenix`, `hota_factory_dreadnought`,
    `hota_factory_juggernaut`, `hota_factory_sandworm_larva`).
  - Every emphasised unit's canonical GLB is either the emphasised export or a look delivery made
    from it. None is a look made from pre-emphasis clips.
  - `validate_homm3_unit_look_contract.py`: 250 specs, 221 applied, 29 not applied yet, 1 violation.
- **Look-lane refusals: 26 units, still delivered as the plain emphasised export.** None of these
  had a look stamp before emphasis, so they are not emphasis regressions; the look spec owners need
  to retune them.
  - **exit 5**, "the look is further from the DEF than the raw base colour":
    `h3_arch_devil`, `h3_archer`, `h3_battle_mage`, `h3_boar_rider`, `h3_demon`, `h3_dreadtaur`,
    `h3_energy_elemental`, `h3_glaivier`, `h3_gnoll_shaman`, `h3_griffin`, `h3_horned_demon`,
    `h3_lizardman`, `h3_mage_upg`, `h3_marksman`, `h3_royal_griffin`,
    `hota_bulwark_kobold_foreman`, `hota_bulwark_mountain_ram`, `hota_cove_halcyon`,
    `hota_cove_nix_warrior`, `hota_cove_sea_witch`, `hota_cove_sorceress`,
    `hota_cove_swashbuckler`.
  - **exit 3**, spec needs an explicit `lighting.front`: `h3_snow_elf_upg_alt`,
    `hota_bulwark_jotunn_warlord`, `hota_bulwark_snow_elf`, `hota_factory_bounty_hunter`.
- **The one look violation.** `h3_orc_chieftain`'s look applied to the emphasised GLB, but its
  `lighting.metal` (added in look commit 93343d27d6) no longer improves the DEF metal region
  (L-hist 6.07 → 6.09). The metric probably moved with the emphasised poses. The fix is a
  look-lane retune or removing `lighting.metal`; emphasis is unchanged.
- **Note on `h3_plasma_elemental`.** Before this run its look had last passed at 21:12. The GLB then
  changed twice: the elemental agent's `element_motion` rebuild, then emphasis at 22:41 (defence and
  attack only). The first look re-run was refused on the raw-colour gate; the unit is not due now.

## Findings

- **The silhouette ratio is the trigger, not the proof of effect.** Most of the added swing is in
  depth (the side views change clearly where the sprite silhouette barely does), so the ratio at
  the key stays flat for most clips. The approved pilots were judged on the side view too.
- **Rotation scaling cannot add reach that comes from extension or from bones the pass does not
  move** (wings, tails, arm straightening). Dragons and griffins show that as flat or lower ratios.
- **Large ratio gains are mostly props**: a gun, whip or bow raised further (`hota_factory_gunslinger`
  shoot 0.45 → 2.42, `h3_medusa_queen` defence 0.69 → 2.42). Spot-check the roster contact sheet.
- **Missed keys stay missed**, as intended; they are retarget faults.
- The roster defaults are milder than the approved pilots (`strength 0.5`/`maxGain 1.35`/18° vs
  0.6/1.5/22–25°); a per-unit config raises a unit to pilot strength.

## Review media

- `artifacts/homm3_def_retarget_emphasis/roster_contact_sheet_<n>.png`: the keys with the largest
  ratio gains across the roster; rows DEF | fit before | fit after (DEF outline over both fits) |
  side before | side after.
- `W/keys_sheet.png`: the same for one unit's exaggerated keys (`review_sheet.py <unit>`).
- `W/hires/pair_<frame>.png`: high-res textured before/after with stretched faces tinted, at each
  emphasised clip's worst-stretch frame (`hires_review.py <unit>`).
- `artifacts/homm3_def_retarget_emphasis/roster_summary.json`: per unit decision, flagged keys,
  before → after ratios, worst-frame edges>2x and max stretch before → after, max extra degrees.
