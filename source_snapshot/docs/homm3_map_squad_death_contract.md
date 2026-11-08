# HoMM3 map squad death contract

Status: active contract (2026-10-02). Vanilla side is source/static (live Golden Era ISIL plus mono demo decompile). Our side is source/static and generated/installed-bundle validated. Map playback is not runtime-proven or user-visible-proven yet; the in-game check is queued in `ingame_check_queue.md`.

Gate: `tools/validate_homm3_map_squad_death_contract.py`. The source half runs in the `-p:FullValidation=true` tier (`ValidateHomm3MapSquadDeathContract`). The bundle half runs in the installed `homm3_bundles` readback (`ValidateInstalledHomm3BundleDir`).

## Vanilla: what happens when a map stack is defeated

Evidence kept under `V:/olden_port_work/units_map_death/evidence/`: `live_isil/{ezp,fdh,fdl,ctp}.txt` (Cpp2IL `--output-as isil` on the live install), `mono/*.cs` (ilspycmd on the demo `Hex.dll`), and `vanilla_map_prefab_probe_all.json`. These can be regenerated with the same tools.

Short answer: vanilla plays the unit's own death clip on the adventure map, holds the final pose, and then removes the object. It does not fade or dissolve.

| Step | Mono demo (readable names) | Live Golden Era (ISIL, `GameAssembly.dll` 2026-06-04) | Evidence |
| --- | --- | --- | --- |
| Battle mode ends and the world is back | `ModeBattle.OnEndAfterWakeUp` -> `UtilityAfterBattle.AfterBattle` -> `CmdBattleApply` -> `battlesManager.ApplyResult` | not re-traced | mono source; live order is a hypothesis |
| Loser squad with no living units is killed | `Battle.Manager.ApplyResult`: `squads.Kill(entityIdInWorld, EReleaseStatus.Killed)` | not re-traced | mono source |
| Release dispatch | `WorldSquad.Release(status)`: None -> `Destroy`, Killed -> `Die`, Escaped -> `Escape`, Joined -> `Join` | `fdh.bjiv(fdh+EReleaseStatus)` switch -> `ezp.bigg` / `ezp.bigh` / `ezp.bigi` / `ezp.bigj` | xref (`fdh.txt`) |
| Animator binding | `SquadDrawer.Init`: `animator = instance.GetComponentInChildren<Animator>()` (active objects only, depth-first, first hit), then `animator.Play(idle, 0, Random.Range(0, 10))` | `ezp.Init`: `GetComponentInChildren<Animator>` -> field `cjbg` (`field_Private_Animator_0`), then `Animator.Play` | xref (`ezp.txt`) |
| Die | `SquadDrawer.Die`: `SetTrigger(AnimationsIDs.die)`, `SetBool(AnimationsIDs.isDead, true)`, disable the child `BoxCollider`, `new WorldSquadToDestroy(this, GetDieDuration())`, hide the quest marker. With no animator it calls `Destroy()` at once | `ezp.bigh` (identical bodies `ui`, `mxs`): quest-marker hide (`bigm`), animator null -> `bigg`, else `Animator.SetTrigger(int)` with `ctp`+0x40, `SetBool(int,bool)` with `ctp`+0x44 and `true`, `Collider.set_enabled(false)`, `new fdl(this, bigp())` | xref |
| Trigger names | `AnimationsIDs`: 18 `Animator.StringToHash` ints; `die` is index 16 (+0x40), `isDead` index 17 (+0x44) | `ctp..cctor`: 18 `StringToHash` stores, +0x40 and +0x44 in the same order | xref plus mono structural match |
| Destroy delay | `GetDieDuration`: `UnitViewConfig.deathTimeOffset + 2f` (5 s if there is no view) | `ezp.bigp`: view `+0xC4` + const `2.0`, fallback const `5.0` (constants read from `GameAssembly.dll` at `0x1843A5628` and `0x1843A54AC`) | xref |
| Removal | `WorldSquadToDestroy.Update`: counts `Time.deltaTime` down, then calls `SquadDrawer.Destroy()` (`Object.Destroy`) | `fdl.lhf`: `Time.get_deltaTime` subtract, `ccx.Remove`, `ezp.bigg` | xref |

The map also plays the common `onSquadKilled` sound (`WorldMapSounds.OnSquadKilled`, mono). Escape and Join do not use the animator: they play `map_unit_escape` / `map_unit_join` world VFX and remove the squad after 0.3 s.

### Required on the prefab

`UnitViewConfig.mapMesh` (`units/<mapMesh>`) must give one Animator that is the first one found by `GetComponentInChildren<Animator>()` and has:

- Trigger `die` and Bool `isDead`;
- an AnyState transition on `die` into the DYING sub-state machine (`Base Layer.DYING.die 0`), which plays the death clip and holds;
- a death clip no longer than `deathTimeOffset + 2` s, because the object is destroyed at that point.

Vanilla data meets this everywhere. All 148 vanilla `*_map` prefabs named by `units_views` (UnityPy readback of `resources.assets`) have an Animator with `die`, `isDead` and a DYING state. 143 of them use `_Battle_Unit_Anim_ctrl_v2` (the battle controller, through a per-unit `AnimatorOverrideController`, for example `Esquire_ctrl`, where `21.Death` -> `Death`). The map prefab carries the same controller as the battle prefab. Vanilla prefabs keep the unit Animator under `scale_roll`/`Scale_roll`/`Scale_roll_pos`, never on the root. Probe script: `V:/olden_port_work/units_map_death/scripts/vanilla_map_prefab_probe.py`.

## Our side: owned skinned map squads

- 271 of the 272 installed `homm3_import.json` entries are owned skinned. Each one has `mapPrefabAssetPath` = the battle `OwnedSkinned/owned_skinned.prefab`. The prefab's single Animator uses the `owned_skinned` override over `_Battle_Unit_Anim_ctrl_v2` (`Homm3OwnedSkinnedLabBuild.StockMap`: `21.Death` -> `Unit_Death`). So the data contract was already there: `die`/`isDead`, the AnyState `die` -> DYING transition and the `Unit_Death` override are all in the bundle.
- The map prefab the game instantiates is a native shell (`Homm3ImportVisuals.CreateNativeShellMapPrefabForAdventure`): a clone of the donor `*_map` prefab whose renderers stay hidden as fog-of-war probes, with our visual `homm3_map_visual` as its last child. Before 2026-10-02 the donor Animator came first in depth-first order. `ezp.Init` therefore bound the hidden donor, and `Die` killed the invisible donor while the owned mesh kept idling until the squad was destroyed `deathTimeOffset + 2` s later.
- Fix (one path, no fallback): `Homm3ImportVisuals.BindOwnedSkinnedMapDeathAnimator`, called from `FinishOwnedSkinnedAdventureMapPresentation`, which both the create and the refresh shell paths use. It `DestroyImmediate`s every Animator outside the owned visual. It has to be immediate because the game instantiates the template in the same frame. The donor renderers stay as fog probes. If the first Animator is still not the owned one, it logs an error with marker `homm3.mapSquadDeath.ownedAnimatorBind.v1`. After that, vanilla's own `Init` (`Play(idle)` with a random phase) and `Die` drive the owned Animator. There is no Harmony hook on the death path.

## Validator

`python tools/validate_homm3_map_squad_death_contract.py` (source only), or add the installed bundle readback:

```
python tools/validate_homm3_map_squad_death_contract.py --bundle-dir "<GE>/BepInEx/plugins/OfflineUnlockMod/homm3_bundles" --name-prefix custom_units_ --import "<GE>/BepInEx/plugins/OfflineUnlockMod/homm3_import.json"
```

Bundle mode checks every owned skinned map bundle for:

- exactly one Animator;
- an `owned_skinned` override over `_Battle_Unit_Anim_ctrl_v2`;
- Trigger `die` and Bool `isDead`, plus an AnyState `die` transition into a DYING state;
- `21.Death` mapped to a `*_Death` clip;
- a clip length no longer than `deathTimeOffset + 2` from the installed Core views.

2026-10-02 readback: OK, 271 map units.

## Open risks

- Live ordering of battle result -> `Kill` -> return to the map is taken from the mono demo. The live `Release` -> `Die` -> `fdl` chain is xref-proven, but the battle-manager caller is not re-traced.
- `Homm3LabClipAudioDriver` maps `Base Layer.DYING.die 0` to the `21.Death` stem, so the creature death SFX probably also plays on the map. It is unknown whether vanilla map deaths carry a creature sound.
- Billboard (non-skinned) HoMM3 map units are out of scope here. As of 2026-10-02 there is one non-owned-skinned entry in `homm3_import.json`.
