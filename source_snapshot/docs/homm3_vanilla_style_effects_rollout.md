# HoMM3 unit effects: vanilla-style rollout

Status: active operational doc for the unit-effect redesign lane. Last revalidated 2026-09-27 against the committed
unit-look specs, the def_retarget delivery selections, and the vanilla-style specs/drafts.

## Decision

User, 2026-09-27: "All homm3 effects look bad in actual in engine runtime and need replacements that follow olden
era's vfx contract." Every `defFlipbook` layer (HoMM3 DEF pixels on a camera quad) is replaced. HoMM3 still decides
**what** an effect depicts and **when** it fires (DEF group, key window, anchor bone). It never supplies the pixels.
The replacement is the established vanilla-style lane (`docs/olden_era_vanilla_vfx_style.md`, spec schema
`homm3_vanilla_style_fx.v1`, compiler `tools/homm3_vfx/vanilla_style_fx.py`, runtime `Homm3MeshFx.cs`):

- a **vanillaParticles** layer clones a bare Shuriken subtree of a vanilla prefab under a bone of our rig. Idle effects
  are `always` and attach in battle, the hire/town UI preview and on the map (`TryAttachForSkinnedPresentation`).
  Attack, hit and death effects are DEF-key `window`s mapped through the delivery's time map onto the stock animator
  states that play the clip;
- one **emissionMap** per unit is the only steady glow. A unit with no glow ships a black map. The DEF
  `effectLight` flash layers are superseded by the vanilla subtree's own glow particles, never by a dynamic light;
- a Light in a cloned subtree must be an inactive GameObject. The runtime activates only kept nodes and their
  ancestors, so it stays dark. `check_spec` now enforces this; every vanilla FlashLight/*Light probed so far passes.

## Lane mechanics (what changed on 2026-09-27)

- **Drafts.** `tools/homm3_vfx/vanilla_style/drafts/<unit>.json` holds a redesign for a unit whose active delivery row
  still ships the unit-look layers. Drafts use the same schema. They are never compiled into the catalog and never
  need a selection flip, so the build stays green while a faction is redesigned.
  - `vanilla_style_fx.py check` (the build validator's core) also runs `check_drafts`: every draft is valid
    against the probed sources and never shadows a shipped spec.
  - `vanilla_style_fx.py plan --unit U` dry-runs a draft against the frozen `unit_look` selection row. It resolves
    bones, clips, key windows and stock states, and writes nothing.
  - Promotion happens at freeze: move the draft to `units/`, flip the selection row to `vfxAuthority: vanilla_style` +
    `vanillaStyleSpec` + `albedo: basecolor`, then run `compile`.
- **`sources`** probes the resPaths of shipped specs and drafts together.
- **Per-unit `sourcesSha256`.** A compiled record now hashes only the probed prefabs its own spec reads, so adding a
  source for another unit no longer stales every record. The three compiled records (fire elemental,
  storm elemental, mechanic_upg_alt) were migrated in place after checking that their stored whole-dict hash still
  matched the current sources, meaning nothing they read had changed.
- **`source.firstOfDuplicates`.** Vanilla prefabs have same-named siblings (e.g. `griffin_upg_ability_root/Feathers`
  twice). `Transform.Find` takes the first one, so a spec may keep a duplicated path only by naming it here. Then it
  is the first sibling in serialized order.
- **Lab.** `tools/homm3_vfx/vanilla_style_lab.py` is spec-driven for every unit except the hand-built fire/storm pages.
  - The NEW panel is built from the same spec file the compiler reads. The VANILLA panel comes from `LAB_REFS`: a
    vanilla unit with its own effects on their own authored transforms.
  - `--prune-renders` drops the raw half-float frames (about 1 GB per unit) after compose.
  - A lab replica of the vanilla dissolve feathers (`magic/test/Disappearance_01/02/03`,
    `tools/homm3_vfx/unity/Homm3VfxDisappearanceReplica.shader`) was read from their DXBC. It is approximate: the
    dissolve input is assumed to be the particle Custom1.x, which every vanilla feather drives with a lifetime curve.
  - `magic/Fresnel` has a lab replica (`tools/homm3_vfx/unity/Homm3VfxFresnelReplica.shader`): alpha multiplies the
    vertex colour alpha, and a mesh without colours reads as white. bodyOverlay layers render on NEW and on the
    VANILLA panel (LAB_REFS `overlays`). `magic/test/DepthTexture` still draws nothing (logged per run).
  - Everything the lab shows is **lab-render tier**: a Unity editor replica with a Python bloom. Only an in-game look
    promotes a unit.
- **`alignToReach` (vanillaParticles).** A source-root-local axis is turned onto the one bone's skinned reach: the
  mean of the farthest 20% of vertices weighted > 0.6 to that bone, in its bind-local frame (x negated for glTFast).
  It compiles to `vanillaStyle.boneLocalRot` [x, y, z, w], applied as the clone root's local rotation. It needs
  `orient: bone` or `emitUp` and exactly one bone. Used by the angel line: a HoMM3 sword has no bone, so RightHand's
  reach is the blade (angel [-0.42, 0.74, -0.53]).
- **`bodyDisplacement` (row `battle_body_displacement`).** Hex/Lit FLAG vertex displacement:
  `posWS += _FlagPower.xyz * sin(dot(posWS, _FlagDirection.xyz) + _Time.y * _FlagSpeed) * COLOR.r`
  (`_VertexDisplacementType` 1, keyword `HEX_VERTEX_DISPLACEMENT_FLAG`, TREE off). Every FLAG vertex program reads
  COLOR.x only, so the mask is baked into the delivered GLB's COLOR_0.r by `tools/homm3_vfx/displacement_mask_bake.py`
  (rules boneWeights / heightBand / region; stamp `homm3_displacement_mask_bake.v1`) into
  `artifacts/vanilla_vfx_style/displacement/<unit>/`. The plugin (`Homm3MeshFx.TryApplyBodyDisplacement`, called
  right after the emission apply in the Hex/Lit rebind) refuses a mesh without a colour stream and reads the keyword,
  type and power back. At most one per unit, power <= 0.25. **Shipped since 2026-09-30**: the ship step's
  `displacementMaskGlb` bakes the mask at prepare, builds the lab from it, reads COLOR.r back out of the built bundle
  (`ProbeDisplacementMaskBundles.cs`) and requires the compiled record to pin the same sha at bundles and deploy.
  Candidate proof: `tools/homm3_vfx/vanilla_style/displacement_ship_proof.json` (h3_ice_elemental in
  `conflux_slice_v1`, 15903 vertices, mask mean 0.327, installed). Installed payload proven; the wave in game is not.
- **`bodyOverlay` (row `battle_body_overlay`).** A vanilla renderer's material (probed `meshMaterials` of the source
  prefab; never a Hex/Lit material) is loaded in LateUpdate, copied, and appended to the unit's body SMRs, always or
  on one animator window, with a sharedMaterials readback re-checked every 60 ticks. The vanilla idiom is
  `BhBattleTimelineHelper.AppendMaterial` (griffin_upg fresnel, phoenix rise fire).
- Both new lanes compiled in the OfficialDeobf build with `ValidatePluginLiveInteropRefs` new=0 (build target
  proven, 2026-09-27); not deployed, no runtime proof.

## Findings that change the plan

1. **`Unit_ShootFront` did not play in the 2026-09-27 morning delivery; fd25e047ca fixes that for new ships.** None
   of the 79 delivered `lab_report.json` stock maps then had a state that plays `Unit_ShootFront` (`14.Attack` played
   `Unit_AttackFront` for melee and ranged alike). Since fd25e047ca the owned StockMap plays `Unit_ShootFront` on
   `15.Skill_1` and ranged views shoot on slot 1.
   - Shooters' shoot-clip layers are therefore kept in the drafts again (the monk line's `cast_bolt` windows).
     The monk line's delivery now carries the new StockMap: the 2026-09-27 16:45 promotion dry run plans its
     `cast_gather`/`cast_release` windows on `15.Skill_1`.
   - Melee-only units (the angel line) keep their shoot-clip DEF layers dropped: their views never use the shot slot.
   - Conflux, checked 2026-09-27 against the GLBs (all four have `Unit_ShootFront`) and the Core views:
     - `h3_ice_elemental` (`h3_water_elemental_upg`) and `h3_frost_elemental` (`h3_water_elemental_upg_alt`) have a
       projectile attack. Their `head_frost` moved from `Unit_AttackFront` key 3 to `Unit_ShootFront` key 3, which is
       the DEF shot window. The look is unchanged.
     - `h3_hurricane_elemental` (`h3_air_elemental_upg_alt`) is melee-only in its view, so the DEF shot is not played
       and `attack_bolt` stays on `Unit_AttackFront`.
     - **Storm (shipped).** `h3_storm_elemental` (`h3_air_elemental_upg`) shoots on slot 1, and its delivered stockMap
       maps `15.Skill_1` to `Unit_ShootFront`. Its spec said `shoot_bolt -> none`, so the shot had no bolt effect.
       - Fixed 2026-09-28 (9a4be17219, user-approved): `attack_bolt` has a second window, `Unit_ShootFront` key 1
         (the DEF `shoot_bolt` keys 1-4), compiled to row `vs_h3_storm_elemental_attack_bolt_t1` on `15.Skill_1`.
         Generated artifact only; the in-combat look is unproven until the next Core/plugin install.
2. **Why `freeze_slice.py` refuses vanilla-style units.** Lines 69-70 raise "has a vanilla-style spec; ship it through
   a vanilla_style slice with meshFx pins". The freezer writes rows with no `vfxAuthority`/`vanillaStyleSpec` and
   derives `albedo` from uvAtlas presence alone, so it cannot write a vanilla row. The refusal is correct for the old
   world but should become the reverse; see "Fleet-owned changes".
3. The angel hit-impact (`Angel_hit_impact_root`) is a *target* impact. On a caster's hand it swamps the whole body
   (monk lab, first pass), so hand casts use the vanilla Lightweaver hand-cast pair instead.

## Gate (proposed; wiring is fleet-owned)

`tools/homm3_vfx/validate_no_def_flipbook.py` + `tools/homm3_vfx/vanilla_style/def_flipbook_debt.json`:

- Every row of an active def_retarget selection whose unit-look spec has a defFlipbook layer must be
  `vfxAuthority: vanilla_style`, or its unit must be on the debt list.
- Debt entries that are no longer debt fail.
- The list is capped by `DEBT_CEILING` (18 on 2026-09-27: 8 castle, 7 rampart, 1 stronghold, 2 cove). The cap is
  lowered with every removal and never raised to pass.
- It passes on the current tree (`debt=18/18 selectedUnitsWithFlipbooks=21`; the other 3 are already vanilla_style).
- Proposed wiring: next to `tools/validate_homm3_vanilla_style_fx_contract.py` in the OfflineUnlockMod build.

## Fleet-owned changes (sent to the lead, not made here)

1. `freeze_slice.py`: replace the refusal with the reverse.
   - When `tools/homm3_vfx/vanilla_style/units/<unit>.json` exists, emit `vfxAuthority: "vanilla_style"`,
     `vanillaStyleSpec: <that path>` and `albedo: "basecolor"`, plus the meshFx pins `ship_def_retarget_slice.py`
     already requires for vanilla rows.
   - When the unit's unit-look spec has defFlipbook layers and neither a shipped spec nor a debt entry exists,
     refuse.
2. Promotion of the castle drafts needs a castle vanilla_style selection. Either flip the 8 castle rows in
   `castle_slice_v1.json`, or add `castle_vanilla_style_slice_v1.json` and supersede those rows. Then run
   `vanilla_style_fx.py compile` per unit. The motion is untouched: no re-run of anyone's retarget is needed. Only the
   look layers change, and the vanilla plan must carry no uvAtlas/quads/lights, so the units' delivery `vfx_plan.json`
   is regenerated by the ship stage.
3. Wire `tools/homm3_vfx/validate_no_def_flipbook.py` into the build/deploy path.
4. `ship_def_retarget_slice.py`: deliver the displacement bake. When the unit's compiled vanilla-style record has
   `displacementBake`, ship `artifacts/vanilla_vfx_style/displacement/<unit>/delivered_idle_retimed.color0.glb`
   under a new `displacementMaskGlb` key in place of the idle-retimed GLB, pinning its sha and refusing unless the
   stamp's `sourceGlbSha256` equals the row's `idleRetimedGlbSha256` (`displacement_mask_bake.verify`). Until then
   `vanilla_style_fx.py` refuses every `bodyDisplacement` layer (`RUNTIME_LANES`). **Done 2026-09-30** (the bake is written into the slice's own unit
   directory at prepare rather than read from `artifacts/vanilla_vfx_style/displacement/`; compile bakes the same
   bytes there and the ship stages require the two shas to agree).

## Castle batch (first batch; lab tier)

| unit | NEW (vanilla-style draft) | fires on (stock state, normalized) |
|---|---|---|
| monk / priest / zealot | `cast_gather` Lightweaver (upg) hand energy (Energy_up_01/02) on LeftHand, recoloured to the DEF tint (monk [0.75,0.85,1], priest [0.8,0.7,1], zealot [0.55,0.8,1]); `cast_release` Lightweaver (upg) hand burst (Smoke, Energy_up) at the fitted flash peak | 14.Attack / 03.Walk_ability_Attack and 25.Stance / 27.Victory (Unit_Defence) |
| angel | `blade_flare` Angel hit-impact holy burst on RightHand (scale 0.35) at key 3; `blade_trail` the vanilla Angel's own close-hit spear strike (`Angel_close_hit_Spear`: flash, `Fire_conus/Fire_trail` cone, energy wisps) at key 2, laid along the blade by `alignToReach` (scale 0.5); both recoloured holy gold-white [1, 0.86, 0.58]; Morality feathers (zeroed to the hips) on hit and death | 14.Attack, 20.Damage, 21.Death |
| archangel / seraph | `blade_fire` the angel's close-hit strike on RightHand at key 2, laid along the blade by `alignToReach`, recoloured to the DEF's orange-gold [1, 0.62, 0.2]; `blade_flare` Angel (upg) spine-impact flash at key 3; Morality feathers | 14.Attack, 20.Damage, 21.Death |
| griffin / royal / battle griffin | Griffin (upg) ability feathers (first `Feathers` sibling, Disappearance_01) on Hips for hit and death | 20.Damage, 21.Death |

Every castle draft has a black emissionMap (no steady glow). `h3_griffin` has no delivery row, so it has a draft but
no `plan`.

### Castle lab results (2026-09-27; lab-render tier, not in game)

Sheets are `artifacts/vanilla_vfx_style/lab/<unit>/`: `sheet_<clip>.png` (OLD | NEW | VANILLA rows), `hero.png`,
`idle.png` and `compare.mp4`. Each is rendered next to a vanilla unit under the Hex/Lit replica with the PPv2-like
bloom. Raw frames were pruned.

| unit | verdict from the sheets | open tuning |
|---|---|---|
| monk | Paragon-glow hand cast gathers and releases at LeftHand on attack and on stance/victory; it reads as a vanilla cast. The first pass, with the Angel hit-impact, swamped the whole body and was replaced | none blocking; recolour tint is the DEF light colour |
| priest, zealot | same design, recoloured; peak linear 50 / 107 against the vanilla Lightweaver's 91-93 | none blocking |
| angel | v3: the close-hit cone and wisps run along the sword from the raise (0.21 s) through the downswing, gold-white, with the holy flare at key 3; they match the DEF's golden blade glow. v2 had two faults the coordinator caught: the vanilla cone's own orange-red read as fire, and the strike ran down RightHand's -Y (the vanilla spear axis) instead of the blade, so it streaked off the body. Feathers now shed from the body on hit and death | none blocking |
| archangel, seraph | fire colour is kept: the DEF sweep is a flaming sword (orange flecks along the blade in the OLD row). Phoenix wing fire (v2, and v3 with the emitter line aligned to the blade, recoloured, rate 0.8) bloomed into a red column beside the body and never followed the blade, so v4 uses the angel's strike in the DEF's orange-gold | none blocking: v4 (lab 2026-09-27 16:41) streaks orange-gold along the sword from the raise through the downswing on both units, holy flash at key 3 |
| griffin, royal griffin, battle griffin | vanilla griffin feather meshes burst from the hips on hit and death and dissolve (Disappearance_01 replica). Closest match to the DEF depiction in the batch | scale (0.5 hit / 0.7 death) not yet judged against the DEF |

Lab caveats:

- The vanilla Angel reference body extracts in a broken pose (`extract_native.py` idle t=0 on `humans/1prefabs/angel`),
  so judge the angel page by its effects, not its body.
- `magic/Fresnel` renders through the lab replica since 2026-09-27; `magic/test/DepthTexture` still draws nothing.
  The griffin's Fresnel shell submesh is left out of the static reference.

Ready to freeze: **castle griffins (royal, battle)**, **the angel line** and **the monk line**, as lab-tier drafts
that need the promotion step listed under "Fleet-owned changes". Promotion dry run 2026-09-27: 9 ok, 0 failed
(`h3_griffin` has no delivery row yet; the freeze adds it).

## Inventory (2026-09-27)

Source: every `tools/homm3_unit_look/units/*.json` with a `defFlipbook` layer, mapped to its faction and its
delivery selection rows. **102 units, 188 defFlipbook layers.** Order: installed factions first (castle, rampart,
stronghold, cove, conflux, neutral), then the unfrozen ones. Status values:

- `shipped spec` means a compiled vanilla-style spec with a vanilla_style row;
- `draft spec, lab render` means a draft plus a lab sheet;
- `todo` means no redesign yet.

### castle (installed): 9 units, 27 defFlipbook layers

| unit | status | delivery row | layer | clip (DEF group, frames) | bone | depicts |
|---|---|---|---|---|---|---|
| `h3_angel` | draft spec, lab render | castle_slice_v1, unit_look | sword_glow | Unit_AttackFront (g12, f1-4) | RightHand | DEF g12 frames 1-4 fire+electric Golden blade glow and white sweep arc; the mesh sword arm... |
|  |  |  | sword_glow_shoot | Unit_ShootFront (g15, f1-4) | RightHand | DEF g15 frames 1-4 fire+electric Golden blade glow and white sweep arc; the mesh sword arm... |
|  |  |  | hit_feathers | Unit_Hitted (g03, f0-4) | Hips | DEF g03 frames 0-4 electric Loose feathers; defOrigin = DEF body centroid per frame pinned... |
|  |  |  | death_feathers | Unit_Death (g05, f0-6) | Hips | DEF g05 frames 0-6 electric Loose feathers; defOrigin = DEF body centroid per frame. |
| `h3_archangel` | draft spec, lab render | castle_slice_v1, unit_look | sword_trail | Unit_AttackFront (g12, f2-4) | RightHand | DEF g12 frames 2-4 fire Flaming sword sweep trail (the on-body orange of f0-1 is lighting:... |
|  |  |  | sword_trail_shoot | Unit_ShootFront (g15, f2-4) | RightHand | DEF g15 frames 2-4 fire Flaming sword sweep trail (the on-body orange of f0-1 is lighting:... |
|  |  |  | hit_feathers | Unit_Hitted (g03, f0-4) | Hips | DEF g03 frames 0-4 electric Loose feathers; defOrigin = DEF body centroid per frame pinned... |
|  |  |  | death_feathers | Unit_Death (g05, f0-5) | Hips | DEF g05 frames 0-5 electric Loose feathers; defOrigin = DEF body centroid per frame. |
| `h3_battle_griffin` | draft spec, lab render | castle_slice_v1, unit_look | hit_feathers | Unit_Hitted (g03, f1-6) | Hips | DEF g03 frames 1-6 smoke Loose feathers; defOrigin = DEF body centroid per frame pinned to... |
|  |  |  | death_feathers | Unit_Death (g05, f1-8) | Hips | DEF g05 frames 1-8 smoke Loose feathers; defOrigin = DEF body centroid per frame. |
| `h3_griffin` | draft spec, lab render | none | hit_feathers | Unit_Hitted (g03, f1-6) | Hips | DEF g03 frames 1-6 smoke Loose feathers; defOrigin = DEF body centroid per frame pinned to... |
|  |  |  | death_feathers | Unit_Death (g05, f1-8) | Hips | DEF g05 frames 1-8 smoke Loose feathers; defOrigin = DEF body centroid per frame. |
| `h3_monk` | draft spec, lab render | castle_slice_v1, unit_look | cast_defence | Unit_Defence (g04, f1-5) | LeftHand | DEF g04 frames 1-5 electric Mesh arms stay crossed (retarget issue logged); defOrigin auto... |
|  |  |  | cast_melee | Unit_AttackFront (g12, f1-4) | LeftHand | DEF g12 frames 1-4 electric Mesh arms stay crossed (retarget issue logged); defOrigin auto... |
|  |  |  | cast_bolt | Unit_ShootFront (g15, f1-6) | LeftHand | DEF g15 frames 1-6 electric Mesh arms stay crossed (retarget issue logged); defOrigin auto... |
| `h3_priest` | draft spec, lab render | castle_slice_v1, unit_look | cast_defence | Unit_Defence (g04, f1-5) | LeftHand | DEF g04 frames 1-5 electric+magic Mesh arms stay crossed (retarget issue logged); defOrigi... |
|  |  |  | cast_melee | Unit_AttackFront (g12, f1-4) | LeftHand | DEF g12 frames 1-4 electric+magic Mesh arms stay crossed (retarget issue logged); defOrigi... |
|  |  |  | cast_bolt | Unit_ShootFront (g15, f1-4) | LeftHand | DEF g15 frames 1-4 electric+magic Mesh arms stay crossed (retarget issue logged); defOrigi... |
| `h3_royal_griffin` | draft spec, lab render | castle_slice_v1, unit_look | hit_feathers | Unit_Hitted (g03, f1-6) | Hips | DEF g03 frames 1-6 smoke Loose feathers; defOrigin = DEF body centroid per frame pinned to... |
|  |  |  | death_feathers | Unit_Death (g05, f1-8) | Hips | DEF g05 frames 1-8 smoke Loose feathers; defOrigin = DEF body centroid per frame. |
| `h3_seraph` | draft spec, lab render | castle_slice_v1, unit_look | sword_trail | Unit_AttackFront (g12, f2-4) | RightHand | DEF g12 frames 2-4 fire Flaming sword sweep trail (the on-body orange of f0-1 is lighting:... |
|  |  |  | sword_trail_shoot | Unit_ShootFront (g15, f2-4) | RightHand | DEF g15 frames 2-4 fire Flaming sword sweep trail (the on-body orange of f0-1 is lighting:... |
|  |  |  | hit_feathers | Unit_Hitted (g03, f0-4) | Hips | DEF g03 frames 0-4 electric Loose feathers; defOrigin = DEF body centroid per frame pinned... |
|  |  |  | death_feathers | Unit_Death (g05, f0-5) | Hips | DEF g05 frames 0-5 electric Loose feathers; defOrigin = DEF body centroid per frame. |
| `h3_zealot` | draft spec, lab render | castle_slice_v1, unit_look | cast_defence | Unit_Defence (g04, f1-5) | LeftHand | DEF g04 frames 1-5 electric+water Mesh arms stay crossed (retarget issue logged); defOrigi... |
|  |  |  | cast_melee | Unit_AttackFront (g12, f1-4) | LeftHand | DEF g12 frames 1-4 electric+water; delivery: billboard (the def_retarget lane cannot build... |
|  |  |  | cast_bolt | Unit_ShootFront (g15, f1-4) | LeftHand | DEF g15 frames 1-4 electric+water Mesh arms stay crossed (retarget issue logged); defOrigi... |

### rampart (installed): 7 units, 8 defFlipbook layers

| unit | status | delivery row | layer | clip (DEF group, frames) | bone | depicts |
|---|---|---|---|---|---|---|
| `h3_dendroid_shaman` | todo | rampart_slice_v1, unit_look | lightning | Unit_ShootFront (g15, f2-4) | LeftHand | g15 shoot_front lightning/bolt (white-blue) f2-4 |
| `h3_diamond_dragon` | todo | rampart_slice_v1, unit_look | breath | Unit_AttackFront (g12, f3-6) | Head | g12 attack_front f3-6 (breath); mask by tools/homm3_unit_look/units/masks/rampart_effect_m... |
| `h3_gold_dragon` | todo | rampart_slice_v1, unit_look | breath | Unit_AttackFront (g12, f3-6) | Head | g12 attack_front f3-6 (breath); mask by tools/homm3_unit_look/units/masks/rampart_effect_m... |
| `h3_green_dragon` | todo | rampart_slice_v1, unit_look | breath | Unit_AttackFront (g12, f3-6) | Head | g12 attack_front f3-6 (breath); mask by tools/homm3_unit_look/units/masks/rampart_effect_m... |
|  |  |  | death_gas | Unit_Death (g05, f2-6) | Head | g05 death detached particles f2-6 (green gas over the thrown-back head, drifting up); mask... |
| `h3_pristine_unicorn` | todo | rampart_slice_v1, unit_look | horn_sparkle | Unit_AttackFront (g12, f1-7) | Head | g12 attack_front thrown lightning/bolt (white-blue) - the horn's twinkle trail |
| `h3_unicorn` | todo | rampart_slice_v1, unit_look | horn_sparkle | Unit_AttackFront (g12, f1-7) | Head | g12 attack_front thrown lightning/bolt (white-blue) - the horn's twinkle trail |
| `h3_war_unicorn` | todo | rampart_slice_v1, unit_look | horn_sparkle | Unit_AttackFront (g12, f1-7) | Head | g12 attack_front thrown lightning/bolt (white-blue) - the horn's twinkle trail |

### stronghold (installed): 3 units, 8 defFlipbook layers

| unit | status | delivery row | layer | clip (DEF group, frames) | bone | depicts |
|---|---|---|---|---|---|---|
| `h3_roc` | todo | stronghold_slice_v1, unit_look | hit_feathers | Unit_Hitted (g03, f3-6) | Spine1 | g03 hitted detached particles f3-6 (feathers) Feathers shed as detached DEF particles. def... |
|  |  |  | death_feathers | Unit_Death (g05, f1-6) | Spine1 | g05 death detached particles f1-6 (feathers) Feathers shed as detached DEF particles. defO... |
| `h3_thunderbird` | todo | none | beak_bolt | Unit_AttackFront (g12, f2-5) | Head | g12 attack_front (thrown fire f3-5; the drawn bolt spans f2-5); mask: tools/homm3_unit_loo... |
|  |  |  | hit_feathers | Unit_Hitted (g03, f3-6) | Spine1 | g03 hitted detached particles f3-6 (feathers) Feathers shed as detached DEF particles. Pin... |
|  |  |  | death_feathers | Unit_Death (g05, f1-6) | Spine1 | g05 death detached particles f1-6 (feathers) Feathers shed as detached DEF particles. Pinn... |
| `toa_shahrokh` | todo | none | attack_crackle | Unit_AttackFront (g12, f4-8) | Spine1 | g12 attack_front water/ice f4-8 (the blue lightning fringe over wings and body) Pinned at ... |
|  |  |  | hit_feathers | Unit_Hitted (g03, f3-4) | Spine1 | g03 hitted smoke/dust f3-4 (white feathers) Feathers shed as detached DEF particles. defOr... |
|  |  |  | death_feathers | Unit_Death (g05, f2-6) | Spine1 | g05 death smoke/dust f2-6 (white feathers) Feathers shed as detached DEF particles. defOri... |

### cove (installed): 9 units, 23 defFlipbook layers

| unit | status | delivery row | layer | clip (DEF group, frames) | bone | depicts |
|---|---|---|---|---|---|---|
| `hota_cove_corsair` | todo | none | muzzle | Unit_ShootFront (g15, f4-4) | LeftHand | g15 shoot_front fire/flame f4 (ripper candidate LeftHand) |
| `hota_cove_nereid` | todo | none | water_gather | Unit_AttackFront (g12, f3-4) | LeftHand | DEF g12 attack_front f3-4: the ball gathered in the hands (body-paint water colours; cove_... |
|  |  |  | hit_splash | Unit_Hitted (g03, f2-3) | RightForeArm | def_effect_ripper: detached particles (g3 frames 2-3) |
|  |  |  | death_splash | Unit_Death (g05, f2-3) | Spine | def_effect_ripper: detached particles (g5 frames 2-3) |
|  |  |  | water_ball | Unit_AttackFront (g12, f5-6) | LeftHand | def_effect_ripper: detached particles (g12 frames 5-6) |
| `hota_cove_nymph` | todo | none | water_gather | Unit_AttackFront (g12, f3-4) | LeftHand | DEF g12 attack_front f3-4: the ball gathered in the hands (body-paint water colours; cove_... |
|  |  |  | hit_splash | Unit_Hitted (g03, f2-3) | RightForeArm | def_effect_ripper: detached particles (g3 frames 2-3) |
|  |  |  | death_splash | Unit_Death (g05, f2-3) | Spine | def_effect_ripper: detached particles (g5 frames 2-3) |
|  |  |  | water_ball | Unit_AttackFront (g12, f5-6) | LeftHand | def_effect_ripper: detached particles (g12 frames 5-6) |
| `hota_cove_oceanid` | todo | cove_slice_v1, unit_look | hit_spray | Unit_Hitted (g03, f2-3) | Root | DEF group 03 frames 2-3: spray thrown left on being hit defOrigin = the Root pixel (Sprite... |
|  |  |  | attack_blob | Unit_AttackFront (g12, f4-6) | Root | DEF group 12 frames 4-6: water blob thrown right defOrigin = the Root pixel (SpriteCam ori... |
|  |  |  | death_spray | Unit_Death (g05, f1-3) | Root | DEF group 05 frames 1-3: spray as the column collapses defOrigin = the Root pixel (SpriteC... |
|  |  |  | death_puddle | Unit_Death (g05, f0-8) | Root | DEF group 05: the puddle the column collapses into (ground band -16..+14 px around the Roo... |
|  |  |  | move_puddle | Unit_MoveStart (g20, f0-12); Unit_MoveEnd (g21, f0-12) | Root | DEF groups 20/21: sink into a puddle on MoveStart and rise out of it on MoveEnd ground ban... |
| `hota_cove_pirate` | todo | none | muzzle | Unit_ShootFront (g15, f4-4) | LeftHand | g15 shoot_front fire/flame f4 (ripper candidate LeftHand) |
| `hota_cove_sea_dog` | todo | none | muzzle | Unit_ShootFront (g15, f4-4) | LeftHand | g15 shoot_front fire/flame f4 (ripper candidate LeftHand) |
| `hota_cove_sea_witch` | todo | none | orb | Unit_Move (g00, f0-7); Unit_Mouseover (g01, f0-10); Unit_Idle (g02, f0-6); Unit_Hitted (g03, f0-5); Unit_Defence (g04, f0-14); Unit_Death (g05, f0-6); Unit_AttackFront (g12, f0-9); Unit_ShootFront (g15, f0-8); Unit_MoveStart (g20, f0-1); Unit_MoveEnd (g21, f0-1) | LeftHand | recurring ~5% water event in every group (the held orb); body paint to defEffects (calm-gr... |
|  |  |  | charge | Unit_ShootFront (g15, f2-5) | RightHand | DEF g15 shoot_front f2-5: pale-blue water swirl over the head and raised hand before the b... |
|  |  |  | bolt | Unit_ShootFront (g15, f6-7) | RightHand | def_effect_ripper: explicit (g15 frames 6-7; f5 was a speck, now in charge) |
| `hota_cove_sorceress` | todo | none | orb | Unit_Move (g00, f0-7); Unit_Mouseover (g01, f0-10); Unit_Idle (g02, f0-6); Unit_Hitted (g03, f0-5); Unit_Defence (g04, f0-14); Unit_Death (g05, f0-6); Unit_AttackFront (g12, f0-9); Unit_ShootFront (g15, f0-8); Unit_MoveStart (g20, f0-1); Unit_MoveEnd (g21, f0-1) | LeftHand | recurring ~4% event in every group (the held blue orb); body paint to defEffects (calm-gro... |
|  |  |  | charge | Unit_ShootFront (g15, f2-6) | RightHand | DEF g15 shoot_front f2-6: the swirl gathered over the head and thrown off the raised hand ... |
| `hota_cove_tidecaller` | todo | cove_slice_v1, unit_look | orb | Unit_Move (g00, f0-7); Unit_Mouseover (g01, f0-10); Unit_Idle (g02, f0-6); Unit_Hitted (g03, f0-5); Unit_Defence (g04, f0-14); Unit_Death (g05, f0-6); Unit_AttackFront (g12, f0-9); Unit_ShootFront (g15, f0-8); Unit_MoveStart (g20, f0-1); Unit_MoveEnd (g21, f0-1) | LeftHand | recurring ~4% event in every group (the held red orb); body paint to defEffects (calm-grou... |
|  |  |  | charge | Unit_ShootFront (g15, f2-6) | RightHand | DEF g15 shoot_front f2-6: the swirl gathered over the head and thrown off the raised hand ... |

### conflux (installed): 14 units, 23 defFlipbook layers

| unit | status | delivery row | layer | clip (DEF group, frames) | bone | depicts |
|---|---|---|---|---|---|---|
| `h3_air_elemental` | todo | none | attack_bolt | Unit_AttackFront (g12, f3-5) | LeftHand | g12 attack_front lightning/bolt (white-blue) f2-6; cut by thin-structure mask |
| `h3_energy_elemental` | todo | none | idle_arcs | Unit_Idle (g02, f0-6) | Hips | idle self-electric (flicker); thin-structure mask |
|  |  |  | attack_arcs | Unit_AttackFront (g12, f0-7) | Spine2 | g12 attack_front arcs + burst f3-7; thin-structure mask |
| `h3_faerie` | todo | none | attack_burst | Unit_AttackFront (g12, f3-6) | LeftHand | g12 attack_front magic ball f3-6 (+spray); burst mask |
| `h3_fire_elemental` | shipped spec (vanilla_style row) | conflux_vanilla_style_slice_v1, vanilla_style | punch_fire | Unit_AttackFront (g12, f3-11) | RightHand | DEF group 12 (attack): the flame jet thrown from the outstretched fist f3-11, cut with a c... |
| `h3_firebird` | todo | none | breath | Unit_AttackFront (g12, f4-11) | Head | phoenix_fire_masks.py (phoenix_fire_lab.breath_mask): everything opaque in front of the be... |
|  |  |  | death_burn | Unit_Death (g05, f1-4) | Spine1 | phoenix_fire_masks.py: DEF g5 frames 1-3 flame+ember (the flared feather fringe), frame 4 ... |
|  |  |  | death_ash | Unit_Death (g05, f5-6) | Root | phoenix_fire_masks.py: DEF g5 frames 5-6, the whole frame (the ash pile); origin = the Spr... |
| `h3_frost_elemental` | todo | none | shoot_sparkle | Unit_ShootFront (g15, f3-7) | Head | g15 shoot_front breath/spit (water/ice) f3-6 |
| `h3_hurricane_elemental` | todo | none | attack_bolt | Unit_AttackFront (g12, f2-4) | LeftHand | g12 attack_front bolt; thin-structure mask |
|  |  |  | shoot_bolt | Unit_ShootFront (g15, f1-4) | Spine2 | g15 shoot_front bolt above the hands; thin-structure mask |
| `h3_ice_elemental` | todo | none | shoot_sparkle | Unit_ShootFront (g15, f3-7) | Head | g15 shoot_front breath/spit (water/ice) f3-6 |
| `h3_phoenix` | todo | none | breath | Unit_AttackFront (g12, f3-11) | Head | phoenix_fire_masks.py (phoenix_fire_lab.breath_mask): frame 3 flame+ember in front of 62% ... |
|  |  |  | hit_sparks | Unit_Hitted (g03, f2-5) | Spine2 | phoenix_fire_masks.py: DEF g3 detached embers (229 -> 835 px, flung outward); origin = the... |
|  |  |  | death_burn | Unit_Death (g05, f0-4) | Spine1 | phoenix_fire_masks.py: DEF g5 frames 0-3 crest tips + flame + embers (white-hot flare, win... |
|  |  |  | death_ash | Unit_Death (g05, f5-6) | Root | phoenix_fire_masks.py: DEF g5 frames 5-6, the whole frame (the ash pile); origin = the Spr... |
| `h3_pixie` | todo | none | attack_burst | Unit_AttackFront (g12, f3-6) | LeftHand | g12 attack_front magic ball f3-6 (+spray); burst mask |
| `h3_plasma_elemental` | todo | none | idle_arcs | Unit_Idle (g02, f0-6) | Hips | idle self-electric (flicker); thin-structure mask |
|  |  |  | attack_arcs | Unit_AttackFront (g12, f0-7) | Spine2 | g12 attack_front arcs + burst f3-7; thin-structure mask |
| `h3_sprite` | todo | none | attack_burst | Unit_AttackFront (g12, f3-6) | LeftHand | g12 attack_front magic ball f3-6 (+spray); burst mask |
| `h3_storm_elemental` | shipped spec (vanilla_style row) | conflux_vanilla_style_slice_v1, vanilla_style | attack_bolt | Unit_AttackFront (g12, f2-4) | LeftHand | g12 attack_front bolt; thin-structure mask |
|  |  |  | shoot_bolt | Unit_ShootFront (g15, f1-4) | Spine2 | g15 shoot_front bolt above the hands; thin-structure mask |
| `h3_water_elemental` | todo | none | attack_splash | Unit_AttackFront (g12, f5-7) | Spine1 | g12 attack_front water/ice f5-7 |

### neutral (installed): 0 units

No unit-look spec in this faction has a defFlipbook layer.

### tower (unfrozen): 10 units, 23 defFlipbook layers

| unit | status | delivery row | layer | clip (DEF group, frames) | bone | depicts |
|---|---|---|---|---|---|---|
| `h3_battle_mage` | todo | none | attack_fire | Unit_AttackFront (g12, f3-7) | RightHand | roster g12 attack_front fire f3-7 (hand fireball f3, then the staff head burns f4-7); towe... |
|  |  |  | death_orb_sparks | Unit_Death (g05, f1-6) | Root | roster g05 death: the staff orb flies up (f1-2), then magenta sparks rise (f4-6); tower_fx... |
| `h3_colossus` | todo | none | strike_arc | Unit_AttackFront (g12, f1-6) | RightHand | roster g12 attack_front sword lightning f1-6; tower_fx_masks.colossus_lightning (warm pink... |
|  |  |  | defence_arc | Unit_Defence (g04, f2-6) | RightHand | roster g04 defence crackle f2-6; tower_fx_masks.colossus_lightning |
|  |  |  | shoot_arc | Unit_ShootFront (g15, f1-6) | RightHand | roster g15 shoot_front sword crackle f1-6; tower_fx_masks.colossus_lightning |
| `h3_elemental_gargoyle` | todo | none | death_melt | Unit_Death (g05, f14-16) | Root | roster g05 death f13-16 fire: the gargoyle melts to a molten ember heap (f14-16); tower_fx... |
| `h3_genie` | todo | none | attack_sparkle | Unit_AttackFront (g12, f2-5) | Spine2 | roster g12 attack_front sparkle cloud f2-5; tower_fx_masks.genie_star_sparkle (cream star ... |
|  |  |  | defence_sparkle | Unit_Defence (g04, f1-5) | Spine2 | roster g04 defence blue-white sparkle f1-5; tower_fx_masks.genie_blue_sparkle above the Sp... |
|  |  |  | death_sparkle | Unit_Death (g05, f2-4) | Root | roster g05 death dissolve sparkle f2-4; tower_fx_masks.genie_blue_sparkle |
|  |  |  | death_remains | Unit_Death (g05, f5-7) | Root | DEF g05 f5-7 whole frame (last sparkle + the lamp); the mesh is hidden from f5 Root is sta... |
| `h3_genie_upg` | todo | none | attack_sparkle | Unit_AttackFront (g12, f2-5) | Spine2 | roster g12 attack_front sparkle cloud f2-5; tower_fx_masks.genie_star_sparkle (cream star ... |
|  |  |  | defence_sparkle | Unit_Defence (g04, f1-5) | Spine2 | roster g04 defence blue-white sparkle f1-5; tower_fx_masks.genie_blue_sparkle above the Sp... |
|  |  |  | death_sparkle | Unit_Death (g05, f2-4) | Root | roster g05 death dissolve sparkle f2-4; tower_fx_masks.genie_blue_sparkle |
|  |  |  | death_remains | Unit_Death (g05, f5-7) | Root | DEF g05 f5-7 whole frame (last sparkle + the lamp); the mesh is hidden from f5 Root is sta... |
| `h3_genie_vizier` | todo | none | death_flash | Unit_Death (g05, f2-7) | Root | DEF g05 f2-7 whole frame: the vizier bursts into a white-cyan star flash and leaves a pool... |
| `h3_giant` | todo | none | strike_arc | Unit_AttackFront (g12, f1-6) | RightHand | roster g12 attack_front lightning sword swing arc f1-6; the Titan recipe (lumaSparse 170, ... |
|  |  |  | defence_arc | Unit_Defence (g04, f2-6) | RightHand | roster g04 defence blade crackle f2-6 (lumaSparse, Titan recipe) |
| `h3_giant_upg` | todo | none | strike_arc | Unit_AttackFront (g12, f1-6) | RightHand | titan_vfx_textures.py approach A (attack) |
|  |  |  | throw_bolt | Unit_ShootFront (g15, f1-5) | LeftHand | titan_vfx_textures.py approach A (shoot) |
| `h3_mage` | todo | none | shoot_glow | Unit_ShootFront (g15, f2-10) | LeftHand | roster g15 shoot_front magic glow f2-10; tower_fx_masks.orb_blobs green (defEffects calls ... |
|  |  |  | death_sparks | Unit_Death (g05, f4-6) | Root | roster g05 death detached magenta sparks f4-6; tower_fx_masks.detached |
| `h3_mage_upg` | todo | none | attack_fire | Unit_AttackFront (g12, f3-7) | RightHand | roster g12 attack_front fire f3-7 (hand fireball f3, then the staff head burns f4-7); towe... |
|  |  |  | death_orb_sparks | Unit_Death (g05, f1-6) | Root | roster g05 death: the staff orb flies up (f1-2), then magenta sparks rise (f4-6); tower_fx... |

### inferno (unfrozen): 12 units, 25 defFlipbook layers

| unit | status | delivery row | layer | clip (DEF group, frames) | bone | depicts |
|---|---|---|---|---|---|---|
| `h3_amalek` | todo | none | hand_flame | Unit_Idle (g02, f0-5); Unit_Move (g00, f0-7); Unit_Mouseover (g01, f0-9); Unit_Hitted (g03, f0-4); Unit_Defence (g04, f0-5); Unit_Death (g05, f0-4) | LeftHand | inferno_fx_masks.py hot_blob: the hand flame on every frame (idle/move/mouseover), knocked... |
|  |  |  | fireball | Unit_AttackFront (g12, f2-6); Unit_ShootFront (g15, f2-4) | RightHand | inferno_fx_masks.py hot_blob: g12 attack fireball conjured f2-3, thrown f4, bursting f5-6 ... |
| `h3_arch_demon` | todo | none | scythe_arc | Unit_AttackFront (g12, f1-6) | RightHand | g12 attack_front detached f2-6 (the burning scythe sweep) |
|  |  |  | teleport | Unit_MoveStart (g20, f4-13); Unit_MoveEnd (g21, f0-7) | Hips | inferno_fx_masks.py opaque_all: g20 move_start f4-13 + g21 move_end f0-7, the fire cloud d... |
| `h3_arch_devil` | todo | none | scythe_arc | Unit_AttackFront (g12, f1-6) | RightHand | g12 attack_front held fire f1-7 (the burning scythe sweep) |
|  |  |  | teleport | Unit_MoveStart (g20, f4-13); Unit_MoveEnd (g21, f0-7) | Hips | inferno_fx_masks.py opaque_all: g20 move_start f4-13 + g21 move_end f0-7, the fire cloud (... |
|  |  |  | death_burn | Unit_Death (g05, f0-6) | Spine | g05 death fire (flames licking the body as it collapses) |
| `h3_cerberus` | todo | none | breath | Unit_AttackFront (g12, f1-6) | HeadRight | g12 attack_front breath/spit fire f1-6 (bone HeadRight) render unitPlane: directional piec... |
|  |  |  | death_burn | Unit_Death (g05, f2-5) | Spine1 | inferno_fx_masks.py opaque_all: g5 death f2-5, the body goes up in flames and bursts into ... |
| `h3_devil` | todo | none | teleport | Unit_MoveStart (g20, f4-13); Unit_MoveEnd (g21, f0-7) | Hips | inferno_fx_masks.py opaque_all: g20 move_start f4-13 + g21 move_end f0-7, the fire cloud (... |
|  |  |  | death_burn | Unit_Death (g05, f0-6) | Spine | g05 death fire (flames licking the body as it collapses) |
| `h3_efreet_sufi` | todo | none | sparkle | Unit_AttackFront (g12, f0-5) | RightHand | inferno_fx_masks.py white_sparkle: g12 attack f0-5 neutral white four-point stars |
|  |  |  | death_lamp | Unit_Death (g05, f3-5) | Hips | inferno_fx_masks.py opaque_all: g5 death f3-5, the flame wisps and the lamp the efreet ret... |
| `h3_efreet_sultan` | todo | none | fireball | Unit_AttackFront (g12, f4-7) | RightHand | inferno_fx_masks.py hot_blob: g12 attack f4-7, the fireball held out in the hand |
|  |  |  | death_flash | Unit_Death (g05, f2-6) | Hips | inferno_fx_masks.py opaque_all: g5 death f2-6, the body bursts into a white star flash (th... |
| `h3_efreeti` | todo | none | fireball | Unit_AttackFront (g12, f4-7) | RightHand | inferno_fx_masks.py hot_blob: g12 attack f4-7, the fireball held out in the hand |
|  |  |  | death_flash | Unit_Death (g05, f2-6) | Hips | inferno_fx_masks.py opaque_all: g5 death f2-6, the body bursts into a white star flash (th... |
| `h3_fire_hound` | todo | none | breath | Unit_AttackFront (g12, f1-6) | HeadRight | g12 attack_front breath fire f1-6 render unitPlane: directional pieces (thrown/jetting for... |
|  |  |  | death_burn | Unit_Death (g05, f2-5) | Spine1 | inferno_fx_masks.py opaque_all: g5 death f2-5, the body goes up in flames and bursts into ... |
| `h3_gog` | todo | none | hand_flame | Unit_Idle (g02, f0-5); Unit_Move (g00, f0-7); Unit_Mouseover (g01, f0-9); Unit_Hitted (g03, f0-4); Unit_Defence (g04, f0-5); Unit_Death (g05, f0-4) | LeftHand | inferno_fx_masks.py hot_blob: the hand flame on every frame (idle/move/mouseover), knocked... |
|  |  |  | fireball | Unit_AttackFront (g12, f2-6); Unit_ShootFront (g15, f2-4) | RightHand | inferno_fx_masks.py hot_blob: g12 attack fireball conjured f2-3, thrown f4, bursting f5-6 ... |
| `h3_hell_hound` | todo | none | breath | Unit_AttackFront (g12, f1-6) | Head | g12 attack_front breath fire f1-6 render unitPlane: directional pieces (thrown/jetting for... |
|  |  |  | death_burn | Unit_Death (g05, f2-5) | Spine1 | inferno_fx_masks.py opaque_all: g5 death f2-5, the body goes up in flames and bursts into ... |
| `h3_magog` | todo | none | hand_flame | Unit_Idle (g02, f0-5); Unit_Move (g00, f0-7); Unit_Mouseover (g01, f0-9); Unit_Hitted (g03, f0-4); Unit_Defence (g04, f0-5); Unit_Death (g05, f0-4) | LeftHand | inferno_fx_masks.py hot_blob: the hand flame on every frame (idle/move/mouseover), knocked... |
|  |  |  | fireball | Unit_AttackFront (g12, f2-6); Unit_ShootFront (g15, f2-4) | RightHand | inferno_fx_masks.py hot_blob: g12 attack fireball conjured f2-3, thrown f4, bursting f5-6 ... |

### necropolis (unfrozen): 8 units, 11 defFlipbook layers

| unit | status | delivery row | layer | clip (DEF group, frames) | bone | depicts |
|---|---|---|---|---|---|---|
| `h3_lich` | todo | none | staff_orb | Unit_ShootFront (g15, f2-8) | LeftHand | g15 shoot_front on-body tint (fire); the staff-tip orb turns red f2-8. mask: tools/homm3_u... |
| `h3_lich_master` | todo | none | staff_burst | Unit_AttackFront (g12, f4-8); Unit_ShootFront (g15, f4-8) | LeftHand | g12/g15 on-body tint (fire) f4-7; the red-white starburst at the staff tip f4-8 (defEffect... |
| `h3_power_lich` | todo | none | staff_orb | Unit_ShootFront (g15, f2-8) | LeftHand | g15 shoot_front on-body tint (fire); the staff-tip orb turns red f2-8. mask: tools/homm3_u... |
| `h3_vampire` | todo | none | bat_cloud | Unit_MoveStart (g20, f0-4); Unit_MoveEnd (g21, f0-4) | Hips | DEF g20 move_start / g21 move_end: the white smoke column the vampire sinks into and the b... |
|  |  |  | death_dust | Unit_Death (g05, f4-6) | Spine1 | g05 death: the dust/sparkle the body dissolves into, frames 4-6 specks rise off the whole ... |
| `h3_vampire_lord` | todo | none | bat_cloud | Unit_MoveStart (g20, f0-4); Unit_MoveEnd (g21, f0-4) | Hips | DEF g20 move_start / g21 move_end: the white smoke column the vampire sinks into and the b... |
|  |  |  | death_dust | Unit_Death (g05, f3-6) | Spine1 | g05 death: the dust/sparkle the body dissolves into, frames 3-6 specks rise off the whole ... |
| `h3_vampire_prince` | todo | none | bat_cloud | Unit_MoveStart (g20, f0-4); Unit_MoveEnd (g21, f0-4) | Hips | DEF g20 move_start / g21 move_end: the white smoke column the vampire sinks into and the b... |
|  |  |  | death_dust | Unit_Death (g05, f3-6) | Spine1 | g05 death: the dust/sparkle the body dissolves into, frames 3-6 specks rise off the whole ... |
| `h3_wight` | todo | none | claw_slash | Unit_AttackFront (g12, f2-4); Unit_ShootFront (g15, f2-4) | Spine1 | necropolis rollout: DEF g12/g15 (attack) f2-4, the white swipe trail of the claw (luma >= ... |
| `h3_wraith` | todo | none | claw_slash | Unit_AttackFront (g12, f0-4); Unit_ShootFront (g15, f0-4) | Spine1 | necropolis rollout: DEF g12/g15 (attack) f0-4, the glowing hand (f0-1) and its white swipe... |

### dungeon (unfrozen): 7 units, 7 defFlipbook layers

| unit | status | delivery row | layer | clip (DEF group, frames) | bone | depicts |
|---|---|---|---|---|---|---|
| `h3_beholder` | todo | none | attack_bolt | Unit_AttackFront (g12, f0-6) | Spine2 | DEF CBEHOL-family g12 attack_front: white forked discharge around the tentacles, f0-6 defO... |
| `h3_black_dragon` | todo | none | breath | Unit_AttackFront (g12, f3-6) | Head | g12 attack_front fire f3-6; file mask because defEffects keeps nothing on f3 and 12 px on ... |
| `h3_evil_eye` | todo | none | attack_bolt | Unit_AttackFront (g12, f0-6) | Spine1 | DEF CBEHOL-family g12 attack_front: white forked discharge around the tentacles, f0-6 defO... |
| `h3_fargazer` | todo | none | attack_bolt | Unit_AttackFront (g12, f0-6) | Spine1 | DEF CBEHOL-family g12 attack_front: white forked discharge around the tentacles, f0-6 defO... |
| `h3_minotaur_taskmaster` | todo | none | whip_crack | Unit_ShootFront (g15, f3-7) | Head | g15 shoot_front lightning/bolt (white-blue) f5-6 (measured wider: f3-7) |
| `h3_red_dragon` | todo | none | breath | Unit_AttackFront (g12, f3-5) | Head | g12 attack_front breath/spit fire f3-5 defOrigin auto pins the flame's body contact (the D... |
| `h3_shadow_dragon` | todo | none | breath | Unit_AttackFront (g12, f3-6) | Head | g12 attack_front fire f3-6; file mask because defEffects keeps nothing on f3 and 12 px on ... |

### fortress (unfrozen): 5 units, 8 defFlipbook layers

| unit | status | delivery row | layer | clip (DEF group, frames) | bone | depicts |
|---|---|---|---|---|---|---|
| `h3_corrosive_gorgon` | todo | none | snort | Unit_Mouseover (g01, f1-3) | Head | g01 mouseover detached particles f1-3 |
|  |  |  | breath | Unit_AttackFront (g12, f3-6) | Head | g12 attack_front thrown fire/flame f3-6 |
| `h3_damsel_fly` | todo | none | frost_spit | Unit_AttackFront (g12, f2-6) | Head | g12 attack_front water/ice sparks f3-6 (+f2 onset) blue spark spray from the mouth; the in... |
| `h3_dragon_fly` | todo | none | fire_spit | Unit_AttackFront (g12, f2-6) | Head | g12 attack_front detached fire sparks f3-6 (+f2 onset) HoMM3 dragon fly fire sparks spraye... |
| `h3_gorgon` | todo | none | snort | Unit_Mouseover (g01, f1-3) | Head | g01 mouseover magic glow f1-3 (green snort) |
|  |  |  | gaze_breath | Unit_AttackFront (g12, f2-5) | Head | g12 attack_front magic glow f2-5 (green breath cloud) |
| `h3_mighty_gorgon` | todo | none | snort | Unit_Mouseover (g01, f1-3) | Head | g01 mouseover detached particles f1-3 |
|  |  |  | breath | Unit_AttackFront (g12, f3-6) | Head | g12 attack_front thrown fire/flame f3-6 |

### factory (unfrozen): 12 units, 17 defFlipbook layers

| unit | status | delivery row | layer | clip (DEF group, frames) | bone | depicts |
|---|---|---|---|---|---|---|
| `h3_automaton_upg_alt` | todo | none | death_explosion | Unit_Death (g05, f2-10) | Hips | g05 death detached particles f2-10 (auto rip saw specks; the whole fireball is the effect)... |
|  |  |  | vent_steam | Unit_Mouseover (g01, f4-8) | LeftUpLeg | g01 mouseover smoke/dust f7-8 (steam rule adds the attached puffs f4-6) |
| `h3_couatl_upg_alt` | todo | none | hit_feathers | Unit_Hitted (g03, f1-5) | Spine1 | g03 hitted detached particles f2-4 (feathers) |
|  |  |  | death_feathers | Unit_Death (g05, f3-23) | Spine1 | g05 death detached particles f3-22 (feathers) |
| `h3_gunslinger_upg_alt` | todo | none | muzzle_flash | Unit_ShootFront (g15, f5-5) | RightHand | g15 shoot_front fire/flame (def_effect_ripper) |
| `h3_mechanic_upg_alt` | shipped spec (vanilla_style row) | factory_mechanic_slice_v1, vanilla_style | flame_jet | Unit_AttackFront (g12, f1-6) | RightHand | g12 attack_front fire/flame f1-8 (extends) |
| `hota_factory_automaton` | todo | none | death_explosion | Unit_Death (g05, f2-10) | Hips | g05 death detached particles f2-10 (auto rip saw specks; the whole fireball is the effect)... |
|  |  |  | vent_steam | Unit_Mouseover (g01, f4-8) | RightUpLeg | g01 mouseover smoke/dust f7-8 (steam rule adds the attached puffs f4-6) |
| `hota_factory_bounty_hunter` | todo | none | muzzle_flash | Unit_ShootFront (g15, f5-5) | LeftHand | g15 shoot_front fire/flame (def_effect_ripper) |
| `hota_factory_couatl` | todo | none | hit_feathers | Unit_Hitted (g03, f1-5) | Spine1 | g03 hitted detached particles f2-4 (feathers) |
| `hota_factory_crimson_couatl` | todo | none | hit_feathers | Unit_Hitted (g03, f1-5) | Spine1 | g03 hitted detached particles f2-4 (feathers) |
|  |  |  | death_feathers | Unit_Death (g05, f3-23) | Spine1 | g05 death detached particles f3-22 (feathers) |
| `hota_factory_engineer` | todo | none | flame_jet | Unit_AttackFront (g12, f1-6) | RightHand | g12 attack_front fire/flame f1-8 (extends) |
| `hota_factory_gunslinger` | todo | none | muzzle_flash | Unit_ShootFront (g15, f4-4) | RightHand | g15 shoot_front fire/flame (def_effect_ripper) |
| `hota_factory_mechanic` | todo | none | flame_jet | Unit_AttackFront (g12, f1-6) | RightHand | g12 attack_front fire/flame f1-8 (extends) |
| `hota_factory_sentinel_automaton` | todo | none | death_explosion | Unit_Death (g05, f2-10) | Hips | g05 death detached particles f2-10 (auto rip saw specks; the whole fireball is the effect)... |
|  |  |  | vent_steam | Unit_Mouseover (g01, f4-8) | RightUpLeg | g01 mouseover smoke/dust f7-8 (steam rule adds the attached puffs f4-6) |

### bulwark (unfrozen): 6 units, 8 defFlipbook layers

| unit | status | delivery row | layer | clip (DEF group, frames) | bone | depicts |
|---|---|---|---|---|---|---|
| `h3_jotunn_upg_alt` | todo | none | frost_breath | Unit_Mouseover (g01, f4-8) | Head | g01 mouseover lightning/bolt (white-blue) f4 + f6-8 (frost breath from the mouth); def_eff... |
|  |  |  | death_frost | Unit_Death (g05, f5-8) | Head | g05 death lightning/bolt (white-blue) f5-8 (frost spark rising off the head); def_effect_r... |
| `h3_shaman_upg_alt` | todo | none | staff_bolt | Unit_ShootFront (g15, f0-4) | LeftHand | g15 shoot_front held lightning/bolt (white-blue) f0-6 (CGSHMN); def_effect_ripper explicit |
| `hota_bulwark_great_shaman` | todo | none | staff_bolt | Unit_ShootFront (g15, f0-4) | LeftHand | g15 shoot_front held lightning/bolt (white-blue) f0-6 (CGSHMN); def_effect_ripper explicit |
| `hota_bulwark_jotunn` | todo | none | death_frost | Unit_Death (g05, f5-8) | Head | g05 death lightning/bolt (white-blue) f5-8 (frost spark rising off the head); def_effect_r... |
| `hota_bulwark_jotunn_warlord` | todo | none | frost_breath | Unit_Mouseover (g01, f4-8) | Head | g01 mouseover lightning/bolt (white-blue) f4 + f6-8 (frost breath from the mouth); def_eff... |
|  |  |  | death_frost | Unit_Death (g05, f5-8) | Head | g05 death lightning/bolt (white-blue) f5-8 (frost spark rising off the head); def_effect_r... |
| `hota_bulwark_shaman` | todo | none | staff_bolt | Unit_ShootFront (g15, f0-4) | LeftHand | g15 shoot_front lightning/bolt (white-blue) f0-4; def_effect_ripper explicit |

## Donor map (2026-09-27; static-asset evidence only)

`tools/homm3_vfx/vanilla_style/donor_map.json` (schema `homm3_vanilla_style_donor_map.v1`) proposes ranked vanilla donors for
**156 layers**: every inventory defFlipbook layer except Castle, `h3_water_elemental` and the three shipped specs
(fire/storm elemental, mechanic_upg_alt). Every `resPath`/`childPath` was resolved against a read-only probe of the installed
bundles (`vanilla_vfx_probe.py`; dumps under `artifacts/claude_takeover_20260927/vfx_donor_map/probes/`). Each row carries its
DEF windows, attach bone, colour intent, overlay verdict, and per candidate: PS count, Lights, duplicate names, Shape-scaled
nodes, Animator nodes and lab-unrenderable nodes. **Nothing here is a lab, visual or runtime verdict.**

Rules applied: the same-kind vanilla unit's own bone-attached effect (idle or attack) first; target impacts and spell hexes only as
flagged fallbacks, or where a shipped spec already uses them (the storm family). Donors the runtime would refuse are kept out of
the primary slot: `Phoenix_upd_idle_spine` and `skeleton_upg_hit_root` have an Animator on the root, and the aqualotl caster
starts (`Naiad_alt_hit_start_root`, `Naiad_upg_distant_hit_root`) sit under an Animator'd Transform. Shape-scaled nodes (Sentinel
`Angel_hit_Sword_R/Transform/Energy_02`, World Watcher `hit_Eye/Wind_circle`) must be left out of keepNodes.

| recipe | layers | primary | alternates | colour | notes |
|---|---|---|---|---|---|
| staff_lightning | lightning, staff_bolt: bulwark_great_shaman, bulwark_shaman, dendroid_shaman, shaman_upg_alt | `qilin_upg` `Qilin_upg_idle_head` | `mech_guard` `World_watcher_idle_Ring2`; `druid_upg` `Druid_upg_on_Staf` | white-blue (dendroid: white-blue; druid alternative is green) |  |
| cold_breath | breath: diamond_dragon | `dragon` `Dragon_hit_02_Head/Transform` | `lich_dragon` `Dragon_lich_hit_Jaw` | per DEF (diamond: white-cyan; verify against DEF before tinting) | needs recolour; lab-check it does not read as fire |
| gold_breath | breath: gold_dragon | `dragon_upg` `Dragon_upg_hit_02_Head` | `dragon` `Dragon_hit_02_Head/Transform` | gold-orange fire |  |
| dragon_breath | breath: green_dragon, red_dragon | `dragon` `Dragon_hit_02_Head/Transform` | `phoenix` `Phoenix_upg_hit_fire_Root/Transform` keep FlashLight,Fire_spark_01,Fire_spark_02,Fire_spark_03,Fire_stretch_01,Fire_stretch_02,Fire_stretch_03; `dragon_upg` `Dragon_upg_hit_02_Head` | orange-red fire | Breath_of_fire (Stylized_lerp_upd) and Wave_distortion (Distortion) cannot render in the lab: judge the VfxUber Breath_of_fire_01..04 subset; Fire_spark_03 exists twice: firstOfDuplicates |
| death_gas | death_gas: green_dragon | `coatl` `Coatl_hit_03_Head` | `magic_fatal_decay_unit` `Transform ` | green gas | fatal decay is a spell-on-target: reads as a debuff |
| horn | horn_sparkle: pristine_unicorn, unicorn, war_unicorn | `unicorn` `unicorn_hit_Def_head` | `unicorn` `unicorn_ability_Def.head`; `star_child` `Star_child_idle_sparks_Hand_L` | white-blue | unicorn_hit_Def_head carries Distortion_01 (lab cannot render) |
| feathers | death_feathers, hit_feathers: roc, thunderbird | `griffin_upg` `griffin_upg_ability_root` keep Feathers | `cavalry_upg_kn_w-c.feather.l.003` `Feathers`; `angel` `Angel_ability_buff_01_root/Transform` keep Feathers | brown/tan (roc, thunderbird) - recolour | Feathers is duplicated under griffin_upg_ability_root: firstOfDuplicates; Disappearance shaders have only a lab replica |
| beak_bolt | beak_bolt: thunderbird | `qilin_upg` `Qilin_upg_idle_head` | `mech_guard` `World_watcher_hit_Eye`; `magic_lightning_strike_hex` `Transform_lightning/Impact` | white-blue |  |
| body_crackle | attack_crackle: toa_shahrokh | `qilin_upg` `Qilin_upg_idle_Spine` | `mech_guard` `World_watcher_hit_Ring2` | blue-white | overlay yes, candidate |
| white_feathers | death_feathers, hit_feathers: toa_shahrokh | `cavalry_upg_kn_w-c.feather.l.003` `Feathers` | `griffin_upg` `griffin_upg_ability_root` keep Feathers | white |  |
| muzzle | muzzle, muzzle_flash: cove_corsair, cove_pirate, cove_sea_dog, factory_bounty_hunter, factory_gunslinger, gunslinger_upg_alt | `elite_upg_bullet_projectile` `Bullet/flash_flick` | `crossbowman_upg` `Crossbowman_ability_start_Crossbow`; `emissary_fire_hit_root` `Transform` | yellow-orange flash | no gun unit in the probed set: nothing same-kind; projectile prefab class |
| water_gather | water_gather: cove_nereid, cove_nymph | `aqualotl_upg` `Naiad_upg_ability_water_ball_root` keep Ball | `aqualotl_upg` `Naiad_upg_idle_root`; `aqualotl_upg_alt` `Naiad_alt_ability_vortex_Hand_L` | blue water | the caster-side starts (Naiad_alt_hit_start_root, Naiad_upg_distant_hit_root) hold every system under an Animator'd Transform: runtime refuses them |
| water_splash | death_splash, death_spray, hit_splash, hit_spray: cove_nereid, cove_nymph, cove_oceanid | `aqualotl_upg` `Naiad_upg_hit_root/Water_01` keep <root>,Water_02,Water_03 | `aqualotl_upg` `Naiad_upg_moove_end_root` | blue water |  |
| water_ball | water_ball: cove_nereid, cove_nymph | `aqualotl_upg` `Naiad_upg_ability_water_ball_root` | `aqualotl_upg` `Naiad_upg_hit_root/Water_01` keep <root>,Water_02,Water_03 | blue water | water_ball root has a Light; Distortion_start/WaveDistortion nodes cannot render in the lab |
| water_bolt | attack_blob, bolt: cove_oceanid, cove_sea_witch | `aqualotl_upg` `Naiad_upg_ability_water_ball_root` keep Ball | `aqualotl_upg` `Naiad_upg_hit_root/Water_01` keep <root>,Water_02,Water_03 | pale blue | the obvious caster-side donors (Naiad_upg_distant_hit_root, Naiad_alt_hit_start_root) are Animator-blocked |
| water_puddle | death_puddle, move_puddle: cove_oceanid | `aqualotl_upg` `Naiad_upg_moove_start_root` | `aqualotl_upg` `Naiad_upg_moove_end_root` | blue water | Distortion_01 in both (lab cannot render) |
| water_orb | orb: cove_sea_witch, cove_sorceress | `aqualotl_upg` `Naiad_upg_idle_root` | `succubus_upg` `Succubus_upg_idle_sphere` | blue water | succubus sphere is purple: recolour |
| water_swirl | charge: cove_sea_witch, cove_sorceress, cove_tidecaller | `aqualotl_upg_alt` `Naiad_alt_ability_vortex_Hand_L` | `naiad_alt_ability_vortex_unit` `Wind_start_small_01` keep <root>,Wind_01,Wind_02,Wind_03,Wind_04 | pale blue |  |
| red_orb | orb: cove_tidecaller | `vampire_upg_alt` `Vampire_alt_idle_Heart` | `aqualotl_upg` `Naiad_upg_idle_root` | red |  |
| storm_bolt | attack_bolt, shoot_bolt: air_elemental, hurricane_elemental | `magic_lightning_strike_hex` `Transform_lightning/Impact` keep Lightning_sparks,Lightning_trails,Lightning_sphere,Flash_01,Energy,Sparks_01,Sparks_02,Sparks_03 | `qilin_upg` `Qilin_upg_idle_head`; `mech_guard` `World_watcher_hit_Ring1` | white-blue | primary is a target spell impact reused on the caster; it is already shipped on storm, so keep one family, but lab-check that it does not read as being struck |
| elec_idle | idle_arcs: energy_elemental, plasma_elemental | `qilin_upg` `Qilin_upg_idle_Spine` | `mech_guard` `World_watcher_idle_Ring2`; `qilin_upg` `Qilin_upg_idle_Tail3` | white-blue (energy) / violet-white (plasma: recolour) | overlay maybe |
| elec_burst | attack_arcs: energy_elemental, plasma_elemental | `mech_guard` `World_watcher_hit_Ring2` | `qilin_upg` `Qilin_upg_idle_ability_buff_01_root (1)`; `magic_chain_lightning_hex` `Transform_lightning/Lightning_start` | white-blue | the Qilin buff root carries Dragon_crack_01 ground cracks: keepNodes must drop them; ability roots carry Lights: keep inactive |
| magic_burst | attack_burst: faerie, pixie, sprite | `pixie` `Pixie_hit_start_root` | `fairy_dragon` `Fairy_Dragon_hit_Head`; `star_child` `Star_child_hit_Chest` | pink-violet / gold pollen | draft uses Pixie_hit_impact_root (target impact, 64 PS): impact class, prefer the start root; Pixie_hit_start_root has a Light |
| phoenix_breath | breath: firebird, phoenix | `phoenix` `Phoenix_upg_hit_fire_Root/Transform` keep FlashLight,Fire_spark_01,Fire_spark_02,Fire_spark_03,Fire_stretch_01,Fire_stretch_02,Fire_stretch_03 | `dragon` `Dragon_hit_02_Head/Transform` | orange-gold fire (firebird: redder) | the full Phoenix_upg_hit_fire_Root has Crack_grounde (Stylized_lerp_upd) ground cracks: keep the jet subset only |
| phoenix_death_burn | death_burn: firebird, phoenix | `phoenix` `Phoenix_ability_rise_spine` | `phoenix_upg` `Phoenix_upd_idle_Elbow_L` | white-hot to orange | rise_spine carries a Light: keep inactive; overlay maybe |
| ash | death_ash: firebird, phoenix | `phoenix` `Phoenix_ability_smoke_rise_root` keep smoke,smoke_dust_01,smoke_dust_02,Flame_sparks_01 | `griffin_upg` `griffin_upg_ability_dust_root` | grey ash with ember sparks | Feathers node uses Disappearance_03 (lab replica only) |
| frost_breath | frost_breath, shoot_sparkle: bulwark_jotunn_warlord, frost_elemental, ice_elemental, jotunn_upg_alt | `frostworm_rider_upg` `FrostWorm_upg_hit_WormBottomJaw` | `aqualotl_upg_alt` `Naiad_ability_ice_root`; `magic_snowball_idle_root` `Transform` | ice blue-white | Naiad_ability_ice_root has a Light |
| embers | hit_sparks: phoenix | `phoenix` `Phoenix_ability_rise_spine` keep Fire_sparks | `phoenix_upg` `Phoenix_upd_idle_Elbow_L` keep Sparks_02,Sparks_03 | orange embers |  |
| staff_fire | attack_fire: battle_mage, mage_upg | `unfrozen_cultist_upg` `Cultist_upg_idle_Hand_R` | `phoenix` `Phoenix_upg_ability_fire_01` keep Fire_01,Fire_02 | orange fire |  |
| magenta_sparks | death_orb_sparks, death_sparks: battle_mage, mage, mage_upg | `star_child` `Star_child_teleport_out_Root` | `star_child` `Star_child_idle_sparks_Hand_L` | magenta (recolour) |  |
| sword_arc | shoot_arc, strike_arc: colossus, giant, giant_upg | `sentinel` `Angel_hit_Sword_R` | `qilin_upg` `Qilin_upg_idle_Tail3`; `mech_guard` `World_watcher_hit_Ring5` | white-blue (giant/titan) / warm pink-white (colossus: recolour) | Sentinel sword effect is energy, not lightning: pair with a Qilin crackle subset if the lab reads it as plain glow |
| sword_crackle | defence_arc: colossus, giant | `qilin_upg` `Qilin_upg_idle_Tail3` | `sentinel` `Angel_space_idle_Sword_L` | white-blue / colossus pink-white |  |
| molten_heap | death_melt: elemental_gargoyle | `olgoi_upg` `Olgoi_upg_lava_end_root` | `phoenix` `Phoenix_ability_smoke_rise_root` | molten orange | lava roots carry Lights and lava_volcano meshes: subset |
| star_sparkle | attack_sparkle: genie, genie_upg | `star_child` `Star_child_hit_Chest` | `halfling` `Halfling_ability_ring_Hand_R`; `star_child` `Star_child_idle_sparks_Hand_L` | cream-gold stars | hit_Chest has a Light |
| blue_sparkle | defence_sparkle, sparkle: efreet_sufi, genie, genie_upg | `star_child` `Star_child_idle_sparks_Hand_L` | `star_child` `Star_child_idle_sparks_Toe_L` | blue-white stars |  |
| dissolve_flash | death_flash, death_sparkle: efreet_sultan, efreeti, genie, genie_upg, genie_vizier | `star_child` `Star_child_teleport_out_Root` | `magic_blink_unit` `Transform_start`; `star_child` `Star_child_idle_sparks_Hand_L` | white-cyan | Transform/Flash_start exists twice: firstOfDuplicates |
| lamp_remains | death_remains: genie, genie_upg | `star_child` `Star_child_idle_sparks_Hand_L` |  | blue-white | the lamp is a mesh/prop, not a particle job |
| throw_bolt | throw_bolt: giant_upg | `magic_chain_lightning_hex` `Transform_lightning/Lightning_start` | `mech_guard` `World_watcher_hit_Eye`; `magic_lightning_strike_hex` `Transform_lightning/Impact` | white-blue | spell-start roots can carry long trails aimed down the hex; orient by alignToReach |
| staff_glow_green | shoot_glow: mage | `druid_upg` `Druid_upg_on_Staf` | `lich_upg` `Lich_upg_emission_Staff` | green |  |
| hand_flame | hand_flame: amalek, gog, magog | `unfrozen_cultist_upg` `Cultist_upg_idle_Hand_L` | `jaw_upg` `Jaw_upg_idle_Jand_L`; `phoenix` `Phoenix_upg_ability_fire_01` keep Fire_01,Fire_02 | orange fire | cultist hand root is heavy and carries a Light: subset + inactive light |
| hand_fireball | fireball: amalek, efreet_sultan, efreeti, gog, magog | `unfrozen_cultist_upg` `Cultist_upg_idle_Hand_R` | `emissary_fire_hit_root` `Transform`; `scorpion_upg` `Scorpion_upg_ability_power_Finger_L` | orange fire |  |
| scythe_fire | scythe_arc: arch_demon, arch_devil | `trick_demon_upg` `Trick_demon_upg_slash_hit_02_root` | `godslayer_upg` `GodSlayer_upg_hit_slash_root` | orange-red | root-level slash: position via bone + alignToReach; slash arcs are authored for a different weapon length |
| fire_teleport | teleport: arch_demon, arch_devil, devil | `locust_upg` `Locust_ability_Hips` | `assassin_upg` `Assassin_move_smoke_disappearance_root`; `unspeakable_upg` `Unspeakable_upg_teleport_out_root` | orange fire cloud | Locust ability has a Light; assassin smoke is dark by default |
| body_burn | death_burn: arch_devil, cerberus, devil, fire_hound, hell_hound | `phoenix` `Phoenix_ability_rise_spine` | `olgoi_upg` `Olgoi_upg_idle_Head` | orange fire | overlay maybe |
| hound_breath | breath: cerberus, fire_hound, hell_hound | `phoenix` `Phoenix_upg_hit_fire_Root/Transform` keep FlashLight,Fire_spark_01,Fire_spark_02,Fire_spark_03,Fire_stretch_01,Fire_stretch_02,Fire_stretch_03 | `emissary_fire_hit_root` `Transform`; `dragon` `Dragon_hit_01_Head` | orange fire | cerberus fires from HeadRight: bone exists only on the triple-head rig |
| lamp_wisps | death_lamp: efreet_sufi | `phoenix` `Phoenix_ability_smoke_rise_root` keep smoke,Flame_sparks_01,Flame_sparks_02 | `star_child` `Star_child_teleport_out_Root` | orange wisps | the lamp is a mesh/prop |
| staff_red | staff_orb: lich, power_lich | `lich_upg_alt` `Lich_alt_upg_hit_Staff` | `lich_upg` `Lich_upg_emission_Staff`; `vampire_upg_alt` `Vampire_alt_idle_Heart` | red | lich staff donors are pale/teal by default; red needs recolour or the blood family |
| staff_burst | staff_burst: lich_master | `lich_upg` `Lich_upg_burst_Staff` | `lich_upg_alt` `Lich_alt_upg_ray_flick_Staff` | red-white | burst has a Light |
| bat_cloud | bat_cloud: vampire, vampire_lord, vampire_prince | `assassin_upg` `Assassin_move_smoke_disappearance_root` | `assassin_upg` `Assassin_upg_ability_smoke_uppear_root`; `magic_blink_unit` `Transform_start` | white smoke (recolour from dark) | no bat particles in any probed donor; bats stay a DEF-only detail; assassin roots carry Lights |
| undead_dust | death_dust: vampire, vampire_lord, vampire_prince | `vampire_upg_alt` `Vampire_alt_hit_root` | `star_child` `Star_child_teleport_out_Root` | pale dust |  |
| claw_slash | claw_slash: wight, wraith | `flicker_upg` `Flicker_upg_hit_root` | `flicker_upg` `Flicker_alt_hit_DEF.hand.L`; `griffin_upg` `griffin_upg_hit_close_root` | white | root-level slashes: orient via alignToReach |
| eye_bolt | attack_bolt: beholder, evil_eye, fargazer | `mech_guard` `World_watcher_hit_Eye` | `lesser_eldritch_upg` `lesser_eldritch_upg_idle_FrontTentacle2_L`; `mech_guard` `World_watcher_hit_Ring1` | white | hit_Eye contains a Light: keep inactive |
| black_breath | breath: black_dragon, shadow_dragon | `black_dragon` `Black_dragon_hit_02_jaw_fire_Head` | `black_dragon_upg` `Black_dragon_upg_hit_01_fire_Head`; `obsidian_dragon` `ObsidianDragon_fire_hit_Jaw ` | dark red / orange fire | black_dragon_upg fire root has a Light; trailing-space node name on the obsidian alternative |
| whip_crack | whip_crack: minotaur_taskmaster | `mech_guard` `World_watcher_hit_Ring5` | `qilin_upg` `Qilin_upg_idle_Tail3`; `minos_upg` `Minos_upg_hit_ability_Head` | white-blue | Minos alternative is orange fire: colour mismatch with the DEF's white-blue |
| snort | snort: corrosive_gorgon, gorgon, mighty_gorgon | `medusa_upg` `Medusa_upg_idle_head (1)` | `coatl` `Coatl_hit_03_Head` | grey-green |  |
| gas_breath | breath, gaze_breath: corrosive_gorgon, gorgon, mighty_gorgon | `coatl` `Coatl_hit_02_Head` | `coatl` `Coatl_hit_01_Head`; `giant_frog` `Giant_frog_ability_language_start` | acid green | Coatl_hit_02_Head has a Light |
| insect_frost | frost_spit: damsel_fly | `frostworm_rider_upg` `FrostWorm_upg_hit_WormBottomJaw` | `locust_upg` `Locust_upg_hit_BottomJaw` | blue sparks |  |
| insect_fire | fire_spit: dragon_fly | `locust_upg` `Locust_upg_hit_BottomJaw` | `dragon` `Dragon_hit_01_Head` | orange sparks |  |
| explosion | death_explosion: automaton_upg_alt, factory_automaton, factory_sentinel_automaton | `siege_explosion` `Transform` | `elite_upg_bullet_projectile` `Transform/Impact`; `minos_upg` `Minos_upg_hit_impact` | orange fireball + smoke | impact-type: may overwhelm the body; scale down; stones use OpaqueEmissive meshes |
| steam | vent_steam: automaton_upg_alt, factory_automaton, factory_sentinel_automaton | `qilin_upg` `Qilin_upg_idle_Foot_L` | `frostworm_rider_upg` `FrostWorm_upg_idle_root`; `hydra_upg` `Hydra_upd_hit_wind_root` | white steam |  |
| red_feathers | death_feathers, hit_feathers: couatl_upg_alt, factory_couatl, factory_crimson_couatl | `griffin_upg` `griffin_upg_ability_root` keep Feathers | `phoenix` `Phoenix_ability_smoke_rise_root` keep Feathers | green/crimson per unit (recolour) |  |
| flame_jet | flame_jet: factory_engineer, factory_mechanic | `phoenix` `Phoenix_upg_hit_fire_Root/Transform` keep FlashLight,Fire_spark_01,Fire_spark_02,Fire_spark_03,Fire_stretch_01,Fire_stretch_02,Fire_stretch_03 |  | orange fire |  |
| frost_rise | death_frost: bulwark_jotunn, bulwark_jotunn_warlord, jotunn_upg_alt | `aqualotl_upg_alt` `Naiad_alt_hit_01_root` | `frostworm_rider_upg` `FrostWorm_upg_idle_root` | ice white | Naiad_alt_hit_01_root has a Light |

No candidate's body displacement is proposed: FLAG displacement stays refused until it ships. A bodyOverlay is marked as a
candidate only where the DEF shows the body itself flashing (the shahrokh fringe) and as a maybe for the idle arcs and body burns.
No probed prefab has bats (vampire bat_cloud), a gun muzzle of the same kind (cove/factory muzzles), or a lamp prop (genie/efreet
remains). Those rows say so.

Lab feedback from the main effects agent (lab-render tier, not in game; recorded in the rows' `labFindings`):
- The lightning_strike Impact subset (`storm_bolt`) renders as blue orbs rather than branches.
- The v2 drafts adopt the pixie start root (`Ground_pollen` subset only; `Butterfly_01` is inactive and Opaque_fresnel), Qilin idle
  spine and World Watcher `hit_Ring2` for energy/plasma, and a separate smoke-rise death_ash.
- The only vanilla Fresnel body overlay, `Flicker_fresnel_01`, is green, which is off-palette on the red-robed psychic and magic elementals.

## Conflux lab set (2026-09-27, lab-render tier only)

Every Conflux draft now has an OLD | NEW | VANILLA lab page beside its native donor, stacked into
`artifacts/vanilla_vfx_style/lab/conflux_comparison.png`, which has a per-unit index in `conflux_comparison.json` (hero,
clip sheets and `compare.mp4`). The lab outputs are not tracked. Body warp is only visible in `compare.mp4`. It is
also held: the FLAG `bodyDisplacement` layers (air/hurricane Col_00-05, ice/frost Tail_06-13, energy/plasma
Spine1-Head, psychic/magic Col_00-04, firebird/phoenix WingL/R_02-03) stay pending until the fleet ship step lands
the prepare-time bake and `displacementMaskGlb`.

| Unit(s) | Donor | Lab reading |
|---|---|---|
| pixie, sprite, faerie | `pixie` wing_2 pollen + `Pixie_hit_start_root/Ground_pollen` (scale 0.4, recoloured) | A caster-side flare centred on the unit. It may still be strong. The target-side impact from v1 read as a detached splash |
| air, hurricane | `aqualotl_upg` idle water, vortex wind, lightning `Impact` | The emission was dimmed in v2. The bolt still reads as blue orbs; retry `qilin_upg` head or `World_watcher_hit_Ring1` |
| ice, frost | `frostworm_rider_upg` idle root + `hit_WormBottomJaw` | Good |
| energy, plasma | `qilin_upg` idle spine lightning + `mech_guard` `World_watcher_hit_Ring2` | Good crackle. An amber Star_01 sits on the chest |
| earth | none (vanilla titan body) | Black emission only; no particles |
| magma | `phoenix` rise Fire_sparks | The lava cracks and embers are visible |
| psychic, magic | `flicker_upg` Fresnel bodyOverlay (+ `star_child` sparks on magic) | The rim renders. `Flicker_fresnel_01` is green, which is off-palette on red robes, so the bodyOverlay `colors` tint (plugin `ApplyOverlayTint`, 5540ed146f) retints it: magenta-rose on psychic, violet on magic, luminance-matched to the vanilla green. It is compile-checked (live interop new=0) and lab rendered; in game it is unproven |
| firebird, phoenix | `phoenix` hit fire, rise and smoke-rise (+ wing fire on phoenix) | The breath, the death burn and the ash all read. The phoenix wing fire is small at scale 0.2 |

The alias siblings (faerie, frost, hurricane, plasma) share their sibling's donors and were not rendered separately. The
next proof tier is the user's in-game look. No draft is promoted, frozen or deployed.
