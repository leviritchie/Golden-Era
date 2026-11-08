# Surface: Town / city scene (index)

## Intent

Ship HoMM3 custom town presentation on the **preferred** paradigm — not abandoned overlay-as-goal / Route A posters.

## Ownership preference

Read and follow **`docs/custom_town_scene_paradigm.md`**. Summary: own a Unity city world (`cityFactory` pattern), paint HotA art on native `BhBuilding` slots, keep CityUI native, open construction via HUD navigation.

## Touch points

- Primary paradigm: `docs/custom_town_scene_paradigm.md`
- `tools/validate_factory_city_scene_contract.py`
- `docs/factory_city_scene_load_pins.md`
- `docs/town_unity_scene_replace_plan.md` / `_handoff.md`
- Historical Route A map: `docs/town_scene_render_static_mapping.md` (not destination)

## Pitfalls

Rejected destinations: Route A/C posters, click relays, `city_hive` aliasing onto another faction city, visually-closed panel escape hacks, `bajs` construct storm.

Owned `cityFactory` camera starts as a SolidColor black plate until HotA world art composes. That compose waits for Main to be active and bound. A Harmony `PrefixSpriteResolver` throw on a custom building-icon miss (`sprite-unresolved`) aborts native city UI init, so Main never binds and the player sees a mostly black town with HUD still up. Building-icon `*_source_map.json` entries may be a filename string **or** `{folder, file}`; the runtime parser must accept both. Live-negative: Fortress grail `Build_Spring_of_Life` used `{folder, file}` pointing at `tbfrholy.png`, the old `[^{}]*` regex skipped it, and Fortress town stayed black. Pin: `Homm3StrongholdBuildingIconSpriteCache.ParseSourceMap` via `tools/validate_custom_faction_manifests.py`.

Town music: Core `DB/city_music_sounds.json` must not keep vanilla donor `soundSetName` rows for factions that ship `<faction>_city_music` sidecars — that layers donor BGM under `Homm3StrongholdCityMusic`. Pin: `tools/validate_homm3_city_music_sidecar_contract.py`.

Map cursor under owned `cityFactory`: adventure-map hover keeps applying `ECursor.PlayerInteractCity` / `HeroInteractCity*` while `sessionWorld` stays loaded. Owned by `Homm3OwnedCityMapCursorSuppress` (stack apply Prefix + Normal force on presentation activate). Live-positive rewrite proven 2026-07-31; user-visible town cursor pending post-deploy sample.

## Open unknowns

Conflux completeness and some construct-refresh edges — see paradigm doc; do not revive Route A as the destination.

Factory ownership path is labeled **user-visible gameplay proven** in the paradigm doc (2026-07-23); other factions may still be incomplete.

Hub: [../agent_surface_guide.md](../agent_surface_guide.md).
