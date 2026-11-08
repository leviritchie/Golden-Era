# Agent Surface Guide (Engine / Mod)

Status: **active** cold-start hub for product surfaces. This file does not prove runtime behavior by itself. Prefer current code, validators, installed Golden Era `Core.zip` readback, and labeled decomp evidence over dated prose (`docs/README.md` truth order).

Active install: `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era`.

Companion skills: `.cursor/skills/agent-surface-guide/SKILL.md` (this hub’s required navigation ritual) · `.cursor/skills/decomp-search/SKILL.md` (battle / IL2CPP ownership).

Cheap gate: `python tools/validate_agent_surface_guide_contract.py --repo-root .` (also wired into `tools/validate_documentation_contract.py`). That gate is **navigation-only**; it does not prove these practices were followed at runtime.

Hard-won IL2CPP pitfalls (keyed lookups, managed-proxy≠native identity, enumeration, producer→consumer windows, store≠view): `.cursor/skills/decomp-search/pitfalls.md`.

---



## Silent miss / wrong proof (read before coding)

When a plan, register, or Core row “exists” but battle/UI still fails, check this class first — before inventing a second path or blaming assets:

| Failure class | What it looks like | Durable practice |
| --- | --- | --- |
| **Store key ≠ retrieve key** | Dict/plan map non-empty; Harmony `TryGetValue` still misses | Pin **live hook arg type** against **map key type** (GameSymbols hints). Bridge wrappers before lookup. This is a **wrong-type / need-bridge** miss (example: Unit.Init side wrapper vs `TransferSide`). A silent miss with a non-empty map is a failed check, not “no plan.” |
| **Managed proxy identity ≠ native identity** | Types already match (or are bridged); map still non-empty; `TryGetValue` / `ReferenceEquals` / managed `GetHashCode` still miss | Il2Cpp often re-wraps the same native object into a **new managed proxy**. Do not key caches by `RuntimeHelpers.GetHashCode` / managed reference equality on `Il2CppObjectBase`. Key by native pointer via `Homm3DirectStateIdentity` (or equivalent). That fixes managed re-wrap only: matching `nativeKey`s mean the same native object; **distinct CapLog `nativeKey`s mean different objects / wrong ownership key** — not proof that store and retrieve are the same TransferSide (or other owner). Distinct from **Store key ≠ retrieve key** (type/bridge) and from **Producer→consumer window** (timing). |
| **Wrong collection surface** | Another layer shows items present; managed `foreach` looks empty | Prefer `Count` + indexer on Il2Cpp lists when foreach has lied or thrown; verify the collection API before pattern-copy. |
| **Producer→consumer window** | Planned/registered, then empty at the later apply hook; miss logs stay quiet | Keep producer state alive until **every** consumer has run (or own apply on one shared registration surface). Do not clear in an earlier postfix than apply. Quiet miss logs + emptied map → **timing/ownership**, not key-identity and not “proof bar alone.” `BattleLogic.Init` also runs during adventure-map / session `Loader` — fail-closed throws from optional pilots in an Init prefix can brick map load; soft-skip / log, do not throw out of Init for optional pilots. |
| **Wrong proof bar** | Logs say planned / registered / stored | That is not applied / presented / **user-visible**. Label each claim; do not promote across proof tiers. (If planned≠applied *and* miss logs are quiet because the map was already cleared, diagnose **Producer→consumer window** first.) |
| **QuestScript AND of different event families** | Map chunk-3 trigger has `ObjectInteractionBefore` + `Counter` / `ItemOwnSide` / `CounterEqualityInDays`; visit logs fire but dialog never shows | OE conditions are **event latches**, not state polls. A lone Done deactivates that listener until the whole AND completes. Never AND visit with CounterChanged / QuestTakedItem / SideStartTurn in one trigger — own state with `SubQuestActivate` / `SubQuestDeactivate` and keep each trigger on one event family. `ObjectInteractionBefore` matches `propEntity.sid` (propEntities), not `objects[].sid` / event-bank `sidConfig`. Confirmed Seer shape: four stages in `docs/homm3_seer_hut_questscript.md`. |
| **Town suppressor kills non-town billboard** | Artifact (or other) map billboard logs `applied` but stays invisible; donor already hidden | `Homm3TownBillboardDonorSuppressor` late-scan matches root name == passed sid and force-disables child renderers. Do not pass artifact SIDs as `citySid`; mark `homm3_artifact_billboard` in `RendererIsBillboardMarker`. Copy donor child layer onto the quad (root layer can be 0). |
| **Pattern-copy without identity** | Copied a working hook/map from another feature | Re-check object identity and **one ownership path** (who mutates, which key type, which presentation owner). No silent fallbacks. |
| **Wrong Method_N / DiffableCs index ≠ live raise** | `BuffEventArgs` dispatch throws `InvalidCastException` to `ChangeAbilityEventArgs`, or “succeeds” with empty listeners while has-by-SID still misses | DiffableCs **declaration index** among `void(object, BattleEventArgs)` is **not** the live `Method_Public_Void_Object_BattleEventArgs_N`. Pin raises via ISIL field offset → interop `GetIl2CppField(..., "shortName")` → `field_Private_EventHandler_1_BattleEventArgs_N` → matching raise `Method_…_N`. Live-negative: DiffableCs `bcja` index 39 ≠ `Method_39` (`cfir` / ChangeAbility); buff got-buff raise is `cfin` / `Method_35` (`GameSymbols.BuffDebuffLaws.BuffEventDispatch`). Sender arg is ability/native source (`baqj`'s `a`), never the event hub as both `this` and arg0. |

Pointers: [gamesymbols_obfuscation](surfaces/gamesymbols_obfuscation.md) · [buffs_and_statuses](surfaces/buffs_and_statuses.md) · [decomp-search pitfalls](../.cursor/skills/decomp-search/pitfalls.md)

---



## How to use this guide

1. Skim **Silent miss / wrong proof** above if you are wiring Harmony lookups, Il2Cpp collections, producer→consumer plan windows, native-pointer cache keys, or “why didn’t it apply?”
2. Start from **player intent** in the navigation table below.
3. Open the linked **surface card**. Read Intent → Ownership preference → Can / cannot → Pitfalls before editing.
4. Run the card’s **do-not-miss checklist**.
5. If ownership branches (native Core vs Harmony vs Direct State), follow decomp-search: Core donor first, then maps/pins, then Direct State only for a traced store transaction.
6. Label every claim you add with a proof tier (`source/static`, `generated`, `deployed`, `startup smoke`, `runtime`, `user-visible gameplay`). Do not promote across tiers without evidence.

Archived search dumps (`docs/AGENT_REFERENCE.md`, `docs/OLDEN_ERA_PLAYTEST_AGENTIC_KNOWLEDGE_BASE.md`, `docs/rag_chunks/`, OfflineUnlockMod `AGENT_REBUILD_AND_MAINTENANCE.md`) may contain leads. Treat them as historical until revalidated.

---



## Narrated overview (cold start)

Olden Era modding in this repo has **three layers** that agents often conflate:


| Layer                                | What it is                                                                                       | Typical owners                                                                                              |
| ------------------------------------ | ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| **Core data**                        | JSON / scripts inside installed `Core.zip` (units, hero abilities, laws, buffs, specializations) | `tools/release_port/apply_release_core_overlay.py`, `custom_factions/`*, ability/hero/law overrides         |
| **Plugin runtime**                   | BepInEx / Harmony adapters that mutate live battle or UI when data cannot express the design     | `OfflineUnlockMod/*.cs`, pins in `GameSymbols.cs`                                                           |
| **Direct State / runtime-mechanics** | Opt-in battle transaction lane for journaled native writes                                       | `custom_factions/runtime_mechanics/`, `docs/runtime_mechanics_implementation_handoff.md`, battle-state maps |


**Default product preference:** express the design with a **native Core envelope** (existing ability / buff / law bonus / specialization row) whenever a live donor already exists. Use plugin hooks only when the envelope cannot say the thing. Use Direct State only when you need a traced store transaction with journal/rollback — and still need presentation proof for user-visible combat. CapLog / dual-readback of stores is **not** gameplay proof.

**Obfuscation rule:** live generated names live in `GameSymbols.cs` (or established resolvers). Do not scatter new RVAs or dump-era names through feature code. Dump ≠ live (example: mech factory is live `egd.bdpz`, not dump `egb.bdoh`).

**Build note:** `OfficialDeobfBuild` / `official_deobf` are compile-profile identifiers for Golden Era interop. They are not a second install. Live probe and playtesting target Golden Era.

---



## Navigation: player intent → surface


| Player / designer intent                                                              | Surface card                                                                 | Primary touch points                                                                                              |
| ------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Change Heroic Strike / warrior commander attack damage, Focus cost, CD, VFX           | [heroic_strike_warrior_ability](surfaces/heroic_strike_warrior_ability.md)   | `skill_warrior_ability`, `hero_ability.script`, `battleSubskillBonus` → `specializations_skill_warrior_ability_*` |
| Change mage-class hero battle ability (same Focus attack, different presentation)     | [mage_hero_battle_ability](surfaces/mage_hero_battle_ability.md)             | `skill_mage_ability`, same script family, mage specialization delta SIDs                                          |
| Add a separate hero action (Warcry, Avenger, Gating, Arcane Battery, Elite Strategem) | [separate_hero_battle_actions](surfaces/separate_hero_battle_actions.md)     | `heroBattleAbility` rows, faction ability SIDs, Warcry UI hooks                                                   |
| Change a unit active/passive (Focus, CD, donor special, text/icon)                    | [unit_ability_core_overrides](surfaces/unit_ability_core_overrides.md)       | `custom_factions/ability_overrides/`, Core `units_logics` / `units_views`, catalog                                |
| Scale damage via laws / outDmgMods / hard-law CSV                                     | [damage_mutation_law_runtime](surfaces/damage_mutation_law_runtime.md)       | law `unitStat` modifiers, `Homm3TrainingDamageLawRuntime` (gated), packet proofs                                  |
| Hero specialization that actually works in overlay                                    | [specialization_bonus_row_types](surfaces/specialization_bonus_row_types.md) | `CUSTOM_SPECIALIZATION_BONUS_TYPES`, `hero_overrides`                                                             |
| Buff / status DB tables                                                               | [buffs_and_statuses](surfaces/buffs_and_statuses.md)                         | `sub_skills_battle_hero_ability_buffs`, `buffs_space_magics`, …                                                   |
| Faction laws (native-data vs hook-required)                                           | [faction_laws](surfaces/faction_laws.md)                                     | law overrides, no-compromise validators, packet gate                                                              |
| Battle Direct State / native donors (index only)                                      | [direct_state_index](surfaces/direct_state_index.md)                         | battle_state_logic_map, adapter dossiers, decomp-search                                                           |
| Custom town / city world                                                              | [town_city_scene](surfaces/town_city_scene.md)                               | `docs/custom_town_scene_paradigm.md`                                                                              |
| Live probe / OfficialDeobf compile                                                    | [live_probe_and_build](surfaces/live_probe_and_build.md)                     | live probe MCP README, OfficialDeobfBuild                                                                         |
| Where obfuscated pins live                                                            | [gamesymbols_obfuscation](surfaces/gamesymbols_obfuscation.md)               | `GameSymbols.cs`, pin tables                                                                                      |
| Keyed caches / Harmony args (plan maps, side wrappers, Unit.Init-style lookups)       | [gamesymbols_obfuscation](surfaces/gamesymbols_obfuscation.md)               | GameSymbols type hints; bridge before lookup; key Il2Cpp objects by native pointer (`Homm3DirectStateIdentity`); keep producer→consumer windows open; [decomp-search pitfalls](../.cursor/skills/decomp-search/pitfalls.md) |
| Ship a HoMM3 unit as a **skinned mesh** in battle, preview, and adventure map | [custom_unit_skinned_mesh](surfaces/custom_unit_skinned_mesh.md) | Idle-0 linked-master mocap SmartRig GLBs → `Homm3OwnedSkinnedLabBuild` → `battlePresentationLane: skinned_mesh`; `mesh`/`mapMesh` = `homm3_import/...`; Idle loops; cache-only Init donor |
| HoMM2 shade object outlines / visitable solids on Golden Era | [homm2_shade_object_class](surfaces/homm2_shade_object_class.md) | `Homm2ShadeObjectClassStamp` framebuffer alpha from `ObjectConfig.isInteractable`; ReShade `OutlineMode` Map objects |
| HoMM2 StyleBlit preview on Golden Era (normals from depth) | [homm2_styleblit_preview](surfaces/homm2_styleblit_preview.md) | `HoMM2_StyleBlit` after Shade; depth-reconstructed normals; `preview_styleblit.py` is the sphere identity fixture |


---



## Family checklists (do not miss)



### Hero battle abilities (Heroic Strike / Mage / separate actions)

- [ ] Confirm class maps to `skill_warrior_ability` vs `skill_mage_ability` (overlay `class_type == "magic"`).
- [ ] Read installed `DB/info/info_hero_ability/hero_ability.script` before inventing a damage formula.
- [ ] Remember both stock abilities set `ignoreCasterOffence` / `ignoreEnemyDefence` and use `absolute_damage` — this is **not** classic HoMM Attack–Defense gap combat.
- [ ] Specialization scaling uses `battleSubskillBonus(["hero_ability", "specializations_skill_warrior_ability_*"])` (or mage twin), not inventing new HeroStat fields without Core wiring.
- [ ] Separate actions (Warcry / Gating / Avenger) are **additional** `heroBattleAbility` grants — do not overwrite the warrior/mage slot unless that is the explicit design.
- [ ] Legacy Warcry “normalize before availability” path is quarantined; release-safe path is icon/UI bind via `GameSymbols.WarcryHeroAbility`.



### Unit abilities

- [ ] Edit via `custom_factions/ability_overrides/<faction>.json` (or editor), then overlay — do not hand-edit Steam `Core.zip`.
- [ ] Preserve `branchRole` / `sourceMechanicId` / `decisionTest`.
- [ ] Prefer donor `unit-special` effectKeys from live Core over inventing Direct State mid-damage behavior.
- [ ] Regenerate / browse catalog: `docs/homm3_custom_unit_ability_catalog.md`, `python tools/unit_ability_catalog/server.py`.
- [ ] Ability icons must be runtime sprite keys, not loc tokens (`docs/ability_editor_agent_notes.md`).



### Damage pipeline / law mutation

- [ ] Prefer law-native `unitStat` / `modifierSet` / `outDmgMods` / `inDmgMods` when the design is a passive scalar.
- [ ] Committed-damage Harmony mutation is packet-gated and **must not** share ownership with Direct State damage adapters without an explicit single owner.
- [ ] `Homm3TrainingDamageLawRuntime` is source-prepared and stays inert while the committed-damage packet gate is closed; do not assume it is live product.
- [ ] Damage `__0` is not a ready `Unit` — unwrap before classify (runtime handoff).
- [ ] `DamageApplied` postfix requires a typed prefix that sets `__state`.



### Buffs / statuses

- [ ] Pick the correct buff table for the owner (hero ability vs hero skill vs space magic).
- [ ] Proven-static config identity ≠ apply/query mutation proven (`gameplay_surface_evidence_matrix.md`).
- [ ] Hire / ability-display UI NRE often means a bad or missing buff SID in Core (null BuffConfig), not missing bundles — run `python tools/validate_homm3_unit_buff_sid_contract.py` before blaming art.
- [ ] Custom native buff add/event path: use `GameSymbols.BuffDebuffLaws` only. Buff got-buff dispatch is `BuffEventDispatch` → live `Method_Public_Void_Object_BattleEventArgs_35` (`cfin`). Do **not** treat DiffableCs `bcja` index 39 as `Method_39` (that raise is `cfir` / ChangeAbility — live-negative `BuffEventArgs`→`ChangeAbilityEventArgs` cast).



### Specializations

- [ ] Only emit bonus types in `CUSTOM_SPECIALIZATION_BONUS_TYPES` from overrides (plus generator-owned common `heroBattleAbility` / magic-school rows).
- [ ] Masterful specialists: `heroMagicReplace` owned in `hero_overrides`, not silent post-pass replacement.



### Direct State

- [ ] Native donor + correct envelope → keep native; DS off for product.
- [ ] Static dossier finished ≠ MovementPush/Teleport ungated.
- [ ] Never treat CapLog store agreement as user-visible combat.



### HoMM3 skinned-mesh battle units

- [ ] Open [custom_unit_skinned_mesh](surfaces/custom_unit_skinned_mesh.md) before inventing a second battle-visual path.
- [ ] Lab: skinned mesh required; `RebaseClipPaths`; `applyRootMotion = false`; Etalon shader GUID `78014d7ab89888f49b8c173e150ffc71`; marker `__homm3_skinned_battle_lane__`. Ground speed is the normalized Core view `moveSpeed` (`custom_factions/unit_move_speed_normalization.json`); the Move stride is matched to it offline, never the speed to the stride; do not retime Walk with `Animator.speed`. Do not time-stretch fused-push clips to Esquire 5.33s Idle; flatten quaternion tangents. Cycle clips must close with a sign-aligned copy of frame 0 at `N * frameDuration` (Idle 8 poses → last key 8/12s, not 7/12s). Loop from `lifecycleRole`, not a suffix table. After a cycle exists, wrap velocity/acceleration both forward and backward across last↔first (`circular_temporal_score.py`); do not turn `temporal_loop_wrap_enabled` on inside `CURRENT_CASCADE_KEEP`. Sprite-feasibility leftover search uses those same checks on one shared skeleton, not a new mesh per frame. Physics smoothing is bounded polish after deliberate-motion authority; `physicsSmooth.enabled` alone is not ship readiness. Gate: `validate_deliberate_motion_contract.py`.
- [ ] Bundle: `battlePresentationLane: "skinned_mesh"` — omit battle billboard arrays/materials/anims; keep map, sounds, owned prefab, stock controller, basecolor jpg, normal png, metallic-gloss png. Missing Hex/Lit maps leave `Hidden/InternalErrorShader` (pink); crusader sidecars live in `homm3_skinned_pbr/h3_crusader/` until the bundle lists those PNGs. The lab material is a carrier (albedo + shader GUID only — the Etalon shader has no normal/metallic slots, so build-time binds no-op); the runtime rebind owns the PBR stamp. Clone a **native** Hex/Lit donor sheet (do not assign `Shader.Find` over an Etalon clone — that sheet has no `_BumpMap` and throws). `OwnedSkinnedMaterialNeedsHexLit` must fire for incomplete Hex/Lit **and** any non-Hex/Lit shader including glTF, or fog/lighting stay off the vanilla contract. Map presentation finds the shell donor **before** rebind. After clone, `SanitizeMapMaterialForOpaqueMesh` keeps `HEX_*` fog keywords. Register `Homm3MapArraySliceHexLitBridge` in Il2Cpp before collecting native-shell components. Remaining-idle0 live import rows must carry `approved-oe-v1` baked albedo from `prepare_remaining_idle0_lighting.py` (idle DEF plates → COMBINED bake on Cycles CUDA, not CPU) before Unity lab; do not ship Meshy bind extract as the battle albedo. After stamp, drop engine/matte/source-albedo copies; resume completeness is stamped-master hash + baked PNG hash. The 8 GiB floor is checked after sprite-frame selection and before wrapping the delivery master.
- [ ] Do not copy unshipped skinned-only packs over billboard `custom_units_*` in `build_out` or the Golden Era `homm3_bundles` folder. Those packs have no `battle.prefab`; combat Init then null-derefs.
- [ ] Unit detail preview keeps the Idle mesh for owned-skinned SIDs only. Do not cover those with the 2D portrait overlay (`homm3PreviewUseStaticPortraits=false` is not enough by itself). Town recruitment for owned-skinned SIDs must also keep the Idle mesh (`BhUnitPreviews.hqv`); `Start`/`Init` stay on the empty placeholder. `BhCityHireIncrementItemView` sprite prefix must not stamp `homm3_static_portrait_*` over owned-skinned hire cards. `Show.bewc` is passed `UnitViewConfig.id`, not `mesh` — rewrite that id to the dungeon **catalog id** (`trogl`, not `troglodyte`). Copy the vanilla 3D mesh pose in preview; do not copy leftover billboard `localPosition`/`localScale`, and do not AABB-fit owned meshes to the preview background. `Homm3PreviewFineTuneRegistry` must not stamp `Sprites/Default` / overlay render state on owned skinned meshes.
- [ ] Adventure-map owned-skinned presentation must copy donor map renderer flags and hide donor shell drivers (`FinishOwnedSkinnedAdventureMapPresentation`). Skipping billboard finish alone leaves the dungeon map shell visible.
- [ ] Release `ecd.Init` uses `TryGetCachedBattlePresentationTemplate` only — never `TryGetBattlePresentationTemplate` on that path.
- [ ] `ApplySideFacing` for owned-skinned writes left +150° / right −30° (native ±90 minus the fleet bind facing −60, `OwnedSkinnedOrientationYawFor`) onto the `Orientation`/`MocapDeliveryRoot` child after wrap yaw is zeroed. Map and preview use the same rule (native `scale_roll` yaw + 60). Do not copy the native yaw without the offset. Per-unit deviations live in `tools/homm3_owned_skinned_facing_allowlist.json` (`docs/homm3_owned_skinned_facing.md`). Native ecz writes identity onto the visual root, so a constant extra +90 wrap made every unit 90° counterclockwise, skipping side yaw left everyone northwest, 0°/180° faced a different wrong way per side, and +90/−90 left every unit one hex side counterclockwise. Do not put +90 on both sides. Adventure-map FoW follows the map-squad visibility flag on owned skins; native donor stays `forceRenderingOff`. The fog probe must not force owned meshes visible. Do not copy native `enabled` onto owned skins and do not `initRestoreDraw=owned-skinned`. Map size uses the same hex fit as battle, not dungeon donor height. `h3_pegasus` is refused off owned-skinned onto authentic CPEGAS lab frames; Silver/Gold stay skinned. Plant skinned feet on hex-container Y, not unit_cutout bounds. Preview centers visual mass on the vanilla 3D donor / slot — do not plant preview feet on parent Y. Never `new Material(Shader.Find("Hex/Lit"))` — clone a loaded native sheet that has `_BumpMap`.
- [ ] Crusader DEF groups 7/8 (turn) and 11/13 (attack up/down) are skipped. Idle DEF 2 ships as `Crusader_Idle`; mouseover DEF 1 fills stock Skill_*; attack front DEF 12 is the only melee attack clip. GPU/IK motion fits must stay idle-leading; isolated walk/attack starts from bind.
- [ ] Automatic full-set motion is idle-0 linked-master mocap (`run_full_set_scheduler.py` → `run_full_set_mocap_unit.py`). Prefer that mocap path whenever a Mixamo / Eagle / hybrid / zoo / mounted donor can contain the mesh. Idle-0 mocap binds that donor into the delivery mesh; a canonical SmartRig is not required. `wait_smartrig` is only for `smartrig_cascade` without a SmartRig; missing or quarantined meshes use `wait_mesh`. SmartRig GPU cascade (`smartrig_cascade`) is allowed only when that donor is totally unviable and a canonical SmartRig exists; Hydra is the current case. Do not cascade leftover units that still have a viable passthrough donor. Idle-0 bind is a floor column: undo Mixamo 45° facing, pin every ground-contact joint to the mesh floor, height-scale so the top meets the mesh top, yaw until the floor footprint fits, then XZ-only suction up the column into the nearest filled slice (Y stays put). Do not resume silhouette pose-search as that lane. Custom SmartRigs stay out until their rig gate passes. A named `linked_master_ground` experiment does only a floor drop and uniform height scale (no per-bone move). `linked_master_scale` is the previous yaw-fix bind plus the bind-lab origin scale until the feet reach the floor. Both violate bind-first and are not the live idle-0 default. Units with no frozen donor compare demo Mixamo person vs Eagle flyer after that recipe and keep the lower mean vertex-to-bone distance. Remaining units are classified by Mixamo leftover (`classify_demo_donor_mix.py` / `run_classify_remaining_donor_mixes.py`): Mixamo-only, Eagle-only, or Mixamo-body + Eagle-wing graft; an appendage leftover that Eagle does not cover is refused. Angel/griffon Mixamo-body + Eagle-wing-position compose is `run_angel_hybrid_body_wings.py` (yaw-lock wings to Mixamo shoulders; bind-first containment and centering use Mixamo body joints only; not the seated mount composer; not the automatic pick). Human bind cleanup is `tools/homm3_mocap_cleanup` (bind lab: global skeleton similarity, bind-offset length scale, explicit `skinRules` apply including geodesic ignore-narrow-contacts — surface walk stays on the welded sheet and does not hop a visible air gap — optional chain weight follow, plus weight set/trim). The Unit list is creatures; named bind versions appear only when a unit has more than one bind folder. It writes `cleanup_edits/` only, cannot self-accept, and is not the sprite pose editor.
- [ ] Pose picker unit/animation lists come from authentic 12 fps `homm3_lab/*/extracted_battle_source_12fps` (playtest BepInEx plugin lab if source-tree `OfflineUnlockMod/homm3_lab` is gone). Do not treat leftover `*_pose_pipeline` folders as the unit inventory.
- [ ] `one_bone_depth` leftover-blade repair is blob-exhaustive (regional IoU on the attributed distal chain), not `skip_tiny_bones` and not whole-image depth.
- [ ] Sequential `one_bone_depth` later frames copy the previous pose, then sprite-delta-init swings distal bones toward occupancy that appeared/left between consecutive sprites before the local bone walk. Occupancy then abstains on pixels two bones both own, merged leftover blobs keep the distal identity, vanished unique limbs hold, and leftover-gravity picks the next bone from uncovered target pixels assigned to the nearest unique-region (not camera-near order, not soft 1/r² on every bone). Mixed-influence rest-edge strain then penalizes LBS melt and vetoes regional IoU moves that stretch blend vertices past tolerance.
- [ ] Gate: `python tools/validate_crusader_owned_skinned_runtime_contract.py --require-artifact` plus payload/audio validators after deploy. Offline probe ≠ combat smoke. Audio `--name-prefix` is an exact bundle name unless it ends in `_`; `custom_units_h3_mage` must not pull `custom_units_h3_mage_upg`. Remaining-idle0 rows with `sndBattlePrefix` must stage WAVs and build sound prefabs before the bundle rebuild; a Unity `.manifest` with 0 `sounds/*.prefab` fails closed.
- [ ] Mesh particles (fire/sparks) use `Homm3MeshFx` + `homm3_mesh_fx/catalog.json` only. Do not invent a second battle-visual owner, hang 3D fire on billboard phoenix, or bake AnimationEvents into owned clips. Map buildings use Core map FX (Resources key `objects/fx/fx_map_fire`; Core DB calls it `fx/fx_map_fire`) via Il2Cpp runtime invoke of the public static `ResManager.Get<GameObject>` from LateUpdate. `nativeResPath` is always the exact lowercase ResourceManager container key (witness `tools/homm3_vfx/native_res_keys.json`). Adventure-map **sound** is `BhSoundMapObject` / `DB/map_objects_sounds.json` spatial loops, not clip-gated creature WAVs. Plugin `MethodInfo.Invoke` `ResManager.Get` AccessViolation'd Golden Era from `LateUpdate`, `MapObject.Init`, and `ScMainMenu.Start`. Do not Invoke-Get, and do not Get from Init or the main menu. Battle sparks use the same LateUpdate Il2Cpp load. Gate: `python tools/validate_homm3_mesh_fx_catalog_contract.py`. Catalog attach is **source/static** until in-map / in-combat look.

### HoMM2 shade object class

- [ ] Open [homm2_shade_object_class](surfaces/homm2_shade_object_class.md) before inventing a second object-outline path or writing class from pixel colour.
- [ ] Landscape vs visitable is `ObjectConfig.isInteractable` (the always-highlight-interactibles bit). Heroes and battle drawers are visitable. Terrain/UI stay unstamped.
- [ ] Stamp `BhWorldCamera` even when it renders to a texture. Skipping every `targetTexture` camera hides the `landscape=` log and never marks mines.
- [ ] Alpha-only writes use the precompiled `ColorMask A` bundle `homm2_shade_object_class`. Do not runtime-compile ShaderLab and do not draw Internal-Colored without a write mask.
- [ ] Shader bytes still come from `dlssnr-recon/tools/vcmi` after GPU receipt. Do not fork `HoMM2_Palette.fx` inside this repo.
- [ ] Pink/magenta trees or ground is Unity `Hidden/InternalErrorShader` (missing maps). Palettizing that magenta stays pink. That is not object-class detection.
- [ ] In-game ink on mines and not on grass is **user-visible gameplay**; a successful compile is not that proof.

### HoMM2 StyleBlit preview

- [ ] Open [homm2_styleblit_preview](surfaces/homm2_styleblit_preview.md) before treating StyleBlit as a second shade chain or inventing normals from colour.
- [ ] Guidance is reconstructed view-space normals from ReShade depth. Do not use object-class alpha as the StyleBlit guide.
- [ ] 10 Sep 2026: StyleBlit Normals / Linear depth / Raw depth were each one colour. Feeder `dlss5-feed.log` Depth probe is min=max=mean=0. That is a dead ReShade depth texture, not a StyleBlit colour bug. Do not invent normals from pixel colour. Next check is Add-ons → Generic Depth (copy before clear, 3840×2160 buffer). If every listed buffer stays flat, `_CameraDepthTexture` has no documented dump plugin yet.
- [ ] After Generic Depth produced an upside-down picture: set `RESHADE_DEPTH_INPUT_IS_UPSIDE_DOWN=1` (keep `DLSS5_MV_PROVIDER=3`) and Reload. Do not flip Y in the StyleBlit shader. Ground should stay at the bottom of Raw depth.
- [ ] HUD vanishing is StyleBlit replacing the finished frame. UI pixels keep world depth. Cover Whole frame makes Coverage one colour; that is not the HUD bug. Object class 255 is terrain and UI together.
- [ ] `HoMM2_StyleBlit` runs after Shade on `--look full`. `--look styleblit` is StyleBlit with Feed and Shade off. Do not insert StyleBlit between StorePre, Feed, and Shade on `--look full`.
- [ ] `--look dlss_last` is StorePre -> Shade -> StyleBlit -> Lumenite -> Feed. Feed's colour input is the backbuffer at Feed time (capture-card). Chicken settings and the frozen neural DLL stay as they are. This is not VCMI residual lighting. HUD already replaced by StyleBlit stays gone. Quit the game before launch.py rewrites TechniqueSorting.
- [ ] StyleBlit is one colour pass that does not clear the backbuffer. A Guide render target plus ClearRenderTargets after Shade or before StorePre produced a black frame with only the magenta badge. Next to Feed still showed an image because Chicken writes colour after Feed.
- [ ] ReShade FXC has no RED/GREEN/BLUE/ALPHA names. Do not set ColorWriteEnable with those identifiers (X3004).
- [ ] A gray screen with only the magenta badge is a single colour write. View Exemplar (combo 0) must show the Knight-town PNG. If that is still gray, the PNG did not bind.
- [ ] Exemplar showing the town but StyleBlit gray: NNF kept one texel because scene normals do not match the sphere at chunk scale. StyleBlit is the n.xy lookup. Check Normals.
- [ ] Exemplar is a sphere-layout painting (`n.xy` lookup). A town still without matching normals is not this algorithm.
- [ ] In-game look is **user-visible gameplay**; the synthetic compare grid is not Olden Era.

### Town

- [ ] Owned Unity city world paradigm only for new product towns — Route A posters are legacy/comparison.



### Symbols / build / probe / runtime lookups

- [ ] New live pins → `GameSymbols` + pin table; no feature-local hardcodes.
- [ ] Event-hub `Method_N` pins: never equate DiffableCs method-declaration index with live `Method_Public_Void_Object_BattleEventArgs_N`. Prefer field-offset / `GetIl2CppField` short-name join (buff example: `cfin`→field_35→`Method_35`).
- [ ] Before any dict/plan lookup from a Harmony hook arg: **live arg type** matches **map key type**, or an explicit bridge exists (GameSymbols hints). Silent miss + non-empty map = bug.
- [ ] After types match: key Il2Cpp game objects by **native pointer** (`Homm3DirectStateIdentity` / equivalent), not managed `GetHashCode` / `ReferenceEquals` — proxies re-wrap. Matching `nativeKey` = same native object; distinct `nativeKey`s = different objects / wrong ownership key (not “identity proven”).
- [ ] Producer→consumer: keep plan/register state alive until every consumer has run (or own apply on one shared registration surface); do not clear in an earlier postfix than apply. Do not throw fail-closed from optional pilots on `BattleLogic.Init` prefixes (Init also runs under adventure-map / session `Loader`).
- [ ] Il2Cpp collections: verify enumeration surface; prefer `Count` + indexer when managed `foreach` has been empty wrongly.
- [ ] Log **planned / registered** separately from **applied / presented**; never treat the first as gameplay proof. Planned≠applied with quiet miss logs → check timing/ownership before key identity.
- [ ] One ownership path per mutation; do not pattern-copy another feature’s key type or store path without re-pinning identity.
- [ ] Golden Era compile: OfficialDeobf path. Live probe: Golden Era bridge, not “Deobf-only”.
- [ ] Re-read [decomp-search pitfalls](../.cursor/skills/decomp-search/pitfalls.md) when ownership or key identity branches.

---



## Surface card index

Deep cards:

1. [heroic_strike_warrior_ability.md](surfaces/heroic_strike_warrior_ability.md)
2. [mage_hero_battle_ability.md](surfaces/mage_hero_battle_ability.md)
3. [unit_ability_core_overrides.md](surfaces/unit_ability_core_overrides.md)
4. [damage_mutation_law_runtime.md](surfaces/damage_mutation_law_runtime.md)
5. [specialization_bonus_row_types.md](surfaces/specialization_bonus_row_types.md)

Supporting cards:

1. [separate_hero_battle_actions.md](surfaces/separate_hero_battle_actions.md)
2. [buffs_and_statuses.md](surfaces/buffs_and_statuses.md)
3. [faction_laws.md](surfaces/faction_laws.md)
4. [direct_state_index.md](surfaces/direct_state_index.md)
5. [town_city_scene.md](surfaces/town_city_scene.md)
6. [live_probe_and_build.md](surfaces/live_probe_and_build.md)
7. [gamesymbols_obfuscation.md](surfaces/gamesymbols_obfuscation.md)
8. [custom_unit_skinned_mesh.md](surfaces/custom_unit_skinned_mesh.md)
9. [homm2_shade_object_class.md](surfaces/homm2_shade_object_class.md)
10. [homm2_styleblit_preview.md](surfaces/homm2_styleblit_preview.md)

---



## Stale / conflict log


| Old claim                                                                                         | Corrected claim                                                                                                                                                                                                                                                                                                                                    | Evidence                                                                                                                                                            |
| ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Heroic Strike damage is classic Attack vs Defense gap (raise Attack or ignore Defense like HoMM3) | Stock `skill_warrior_ability` / `skill_mage_ability` use `absolute_damage` with `ignoreCasterOffence` + `ignoreEnemyDefence`. Script `hero_ability_skill_damage_ability` sums `heroStat.offence + defence + spellPower + intelligence` into a stat term, then applies level × (`damageMultiplerPerHeroLevel` + `heroicStrikeDamagePerLevelBonus`). | Installed Core `hero_abilities.json` + `hero_ability.script` (`deployed` / `source/static`); recovered `HeroStat.heroicStrikeDamagePerLevelBonus` (`source/static`) |
| Prefer Direct State for any combat shove/teleport/damage because Core is hard                     | Prefer native Core donor envelope first; DS owns traced store transactions only; MovementPush remains gated; Bellwether product uses native `teleport` reshape, DS pilot disabled                                                                                                                                                                  | decomp-search skill; `runtime_mechanics_implementation_handoff.md`; `battle_state_logic_map.md`                                                                     |
| Custom laws need speculative Harmony mutators as the default                                      | Active custom law rows are **native-data replacements**; speculative mutators stay disabled until individually revalidated and packet-promoted                                                                                                                                                                                                     | `docs/custom_law_implementation_status.md`; packet gate; `Homm3TrainingDamageLawRuntime` inert without gate/pilot                                                   |
| Stale `Unit.bbgw` is the committed-damage bind                                                    | Live bind is the exact `BattleUnitApplyDamage` MethodSymbol; do not add `bbgw` as silent fallback                                                                                                                                                                                                                                                  | `GameSymbols.BattleEventLaws.BattleUnitApplyDamage` comments                                                                                                        |
| Official Deobf / live probe is a separate play install                                            | Active install is Golden Era; OfficialDeobf is compile/interop profile; live probe README forbids “Deobf build only”                                                                                                                                                                                                                               | `AGENTS.md`; `tools/live_probe_mcp/README.md`; documentation contract                                                                                               |
| Route A town posters are the product path                                                         | Preferred path is owned Unity city world + native `BhBuilding` + HotA world art                                                                                                                                                                                                                                                                    | `docs/custom_town_scene_paradigm.md` (user-visible Factory proof labeled there)                                                                                     |
| Warcry legacy controller normalization is still the product hook                                  | Legacy native-normalization is quarantined; release-safe slice is icon/bind surfaces                                                                                                                                                                                                                                                               | `Homm3WarcriesHeroAbilityHook.TryRegister` log + `RegisterReleaseSafeIconSlice`                                                                                     |
| Knowledge-base / AGENT_REFERENCE “current” specialty/law wording                                  | Archived snapshots; verify against overlay + installed Core                                                                                                                                                                                                                                                                                        | Archive banners; this hub                                                                                                                                           |
| DiffableCs `eda.bcja` declaration index 39 is live `Method_…_BattleEventArgs_39`                  | Index schemes diverge. Live `Method_39` raises `cfir` (ChangeAbility). Buff got-buff is ISIL `bcja` → `cfin` → `Method_35` (`BuffEventDispatch`).                                                                                                                                    | Live-negative cast log; interop `GetIl2CppField(..., "cfin")` / `"cfir"`; `GameSymbols.BuffDebuffLaws.BuffEventDispatch`                                            |
| Hub had no skinned-mesh custom-unit navigation row                                                | Battle skinned-mesh units are [custom_unit_skinned_mesh](surfaces/custom_unit_skinned_mesh.md); do not invent a second presentation owner or treat billboard `Texture2DArray` as this lane | Pose-pipeline skill; `docs/crusader_owned_bind_skinned_mesh_handoff.md`; `validate_crusader_owned_skinned_runtime_contract.py` |


---



## Related active docs (do not duplicate)


| Doc                                                | Role                                  |
| -------------------------------------------------- | ------------------------------------- |
| `docs/README.md`                                   | Truth order + document classes        |
| `.cursor/skills/decomp-search/SKILL.md`            | Battle / decomp ownership workflow    |
| `.cursor/skills/decomp-search/pitfalls.md`         | Key identity (type/bridge + managed-proxy≠native), producer→consumer windows, Il2Cpp enum, store≠view |
| `docs/homm3_custom_unit_ability_catalog.md`        | Generated unit ability browse surface |
| `docs/gameplay_surface_evidence_matrix.md`         | Packet surface promotion statuses     |
| `docs/runtime_mechanics_implementation_handoff.md` | Direct State ownership matrix         |
| `docs/custom_town_scene_paradigm.md`               | Town product paradigm                 |
| `docs/ability_editor_agent_notes.md`               | Editor / override schema rules        |
| `docs/homm3_custom_faction_porting_checklist.md`   | Full faction port sequence            |
| `docs/crusader_owned_bind_skinned_mesh_handoff.md` | Crusader skinned-mesh OE playbook     |
| `.cursor/skills/homm3-pose-pipeline/SKILL.md`      | 2D→3D pose fit before the Unity lab   |
| `tools/validate_homm3_unit_buff_sid_contract.py`   | Custom unit ability buff SID ↔ Core   |


---



## Open unknowns (hub-level)

- Exact live IL method that evaluates `hero_ability.script` tokens at cast time (script semantics are installed-readback proven; the evaluator type name is not required for data edits).
- Safe, promoted committed-damage mutation semantics for product laws (packet remains unpromoted).
- Whether `Homm3TrainingDamageLawRuntime.TryRegister` is intentionally unreachable from `Plugin` today vs wired through a registration owner that must be reconnected before any pilot — treat as **not product-active** until a startup log shows `REGISTERED_EXACT_PREFIX_PATCHES`.
- Full Attack/Defense gap formula for **ordinary unit melee/ranged** (separate from Heroic Strike absolute script) remains a research surface; do not assume Heroic Strike script applies to creature attacks.

