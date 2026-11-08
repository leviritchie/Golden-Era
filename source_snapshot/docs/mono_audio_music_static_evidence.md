# Mono Audio, Music, and Projectile Static Evidence

Status: source-generated/static-only. Runtime-unvalidated.

This dossier compares the old Mono demo `Hex.dll` against the current Golden Era Cpp2IL DiffableCs shells for existing audio/music/projectile mod surfaces. It is intended to reduce sidecar audio hooks over time by identifying native data contracts that survived into the current build.

Evidence boundary: static Mono decompilation, current DiffableCs shells, and existing mod source review only. This does not prove runtime asset availability, sound-set registration, mixer routing, or invocation timing.

## Existing mod behavior reviewed

| Mod surface | Current approach | Native-friendly opportunity |
|---|---|---|
| `EsquireBattleAudioPlayer` | Adds its own `AudioSource` under a battle prefab root and plays custom `AudioClip`s by animation clip category. It intentionally avoids `Hex.Sound.*`. | Keep sidecar only for animation-timed bespoke voice/SFX unless a native unit-animation event contract is mapped. |
| `Homm3CoveCannonShotAudio` | Loads WAV bytes, creates `AudioClip`, creates a persistent sidecar `AudioSource`, and debounces `PlayOneShot`. | Candidate replacement is `ProjectileConfig.flightSound` plus native projectile playback if the projectile asset route can reference the desired cannon shot sound set. |
| `Homm3CovePirateShotAudio` | Same sidecar WAV and `PlayOneShot` pattern as cannon shot. | Same projectile-native candidate route as cannon shot. |
| `Homm3GlobalCombatMusic` | Loads `homm3_combat_music` AssetBundle and starts/stops sidecar music from `BhBattleLog.Start` and `BhBattleEnd.OnBtnExit`. | Candidate replacement is native music sound config, but lifecycle and current battle music key selection still need a specific current-build call-site dossier. |
| `Homm3StrongholdCityMusic` | Sidecar town music selected by faction SID. It loads `SoundGroupConfig`/`SoundSetConfig` assets but does not patch a native music route. | Candidate replacement is native `CityCommonSoundsConfig`/`CitySoundConfig.soundSetName` if city music selection keys are data-driven by faction or city SID. |

## Mono/current type evidence

| Surface | Mono evidence | Current deobf evidence | Static conclusion |
|---|---|---|---|
| Projectile data | `Hex.Configs.ProjectileConfig` has `path`, `flightSound`, `emitter`, `trajectory`, `speed`, `maxHeight`, `angle`, `delay`, `startDelay`. | Current `ProjectileConfig` keeps the same fields and constructors. | Strong static data contract. Projectile SFX should prefer `flightSound` over sidecar one-shot where projectile config is controllable. |
| Projectile playback | Mono `BhProjectileController.Init(...)` accepts `flySound`, speed, delay, trajectory, height, and angle; `PlayOnce`/`Process` call battle sound playback for projectile flight and spatial start sounds. | Current `BhProjectileController` keeps `Init(...)`, `bbst`, `bbsu`, and `bbsv`; fields preserve `startSound`, `flySound`, `flySpeed`, `maxHeight`, `trajectoryType`. | Strong static owner and data-flow shape. Exact obfuscated method names require method-body/ISIL confirmation before patching behavior. |
| Battle common sounds | Mono `BattleCommonSoundsConfig` stores battle start/victory/defeat/escape/capitulation strings. | Current shell stores battle start/victory/defeat variants. | Strong static config family, but fields drifted between demo and current; do not copy Mono field names blindly. |
| Music config | Mono `MusicSoundConfig.soundSetName`; `MusicSoundsConfig.array.GetSoundConfig(key)`. | Current `MusicSoundConfig.soundSetName`; current `MusicSoundsConfig` adds delay fields and keeps obfuscated lookup `scb(string)`. | Strong static config family. Native music replacement should identify the key used for combat/town contexts rather than inject sidecar lifecycle hooks. |
| City sound config | Mono `CitySoundConfig.soundSetName`; `CityCommonSoundsConfig.GetSound(key)`. | Current `CitySoundConfig.soundSetName`; current `CityCommonSoundsConfig.sbh(string)`. | Strong static config family. Faction/town music may be data-driven if city key selection is mapped. |
| Map hero sounds | Mono `MapHeroSoundsConfig.GetHeroSoundConfig(EHeroSoundType)` maps enum values to string keys. | Current `MapHeroSoundsConfig.sbs(EHeroSoundType)` with same config shape. | Strong static route for terrain/biome hero movement sound reuse. |
| Map ambient sounds | Mono `MapAmbientSoundsConfig.GetAmbientSoundConfig(EAmbientSoundType)` maps enum values to string keys. | Current same config family exists and is already represented in `GameSymbols.TerrainSound`. | Strong static route for terrain ambient sound reuse; custom biomes should alias existing enum values unless enum extension is proven. |
| Map object spatial sounds | Mono `BhSoundMapObject` registers/unregisters with `WorldMapSpatialSounds` and drives single full-length/short sounds from animation events. | Current `BhSoundMapObject` keeps same serialized fields and methods `Init`, `OnEnable`, `OnDisable`, `PlaySingleFullLengthSound`, `PlaySingleShortSound`, plus obfuscated accessors. | Strong static route for native map-object spatial sound behavior. Useful for future map-object import, not battle music. |
| City spatial sound objects | Mono `BhCitySoundObject` exposes `SoundPath`, distance, rolloff/spread curves, playback id, and hooks OnEnable/OnDisable to city spatial sounds. | Current `BhCitySoundObject` keeps the same serialized fields and playback methods with obfuscated getter names. | Strong static route for city spatial sound objects. This is not the same as town background music, but it can replace some sidecar ambient object sounds. |


## Current music owner candidates

These are current-build owner candidates from DiffableCs field evidence. They improve search targeting but do not expose the actual music key strings because method bodies are unavailable in the shells.

| Current deobf type | Static role | Evidence | Remaining gap |
|---|---|---|---|
| `cjw` | Global config aggregate | Singleton-like config holder with `MenuMusicSoundsConfig`, three `MusicSoundsConfig` fields, `CityCommonSoundsConfig`, `BattleCommonSoundsConfig`, map sound configs, and many other global configs. | Need field-source/load-body evidence to name each `MusicSoundsConfig` slot. |
| `bxc` | Menu music client | Derives `fwr`/`SoundsClientBase`, owns `MenuMusicSoundsConfig`, playback id, and current string field. | Menu key selection body hidden. |
| `dxt` | City common sound client | Derives `fwr`, owns `CityCommonSoundsConfig`, event bus field, and start-day handlers. | City sound key derivation body hidden. |
| `ezk` | Map/adventure music client | Derives `fwr`, owns `MusicSoundsConfig`, playback receiver, playback id, current string field, delay/status fields, and start-day/event handlers. | Exact map/combat/town music key selection body hidden. |

Static conclusion: native music migration should focus next on body/xref evidence for `ezk` and `dxt`, not on lifecycle sidecar hooks. DiffableCs alone identifies owners but not the strings selected by those owners.

## Current ISIL body evidence

The current ISIL dump does not include `Hex.Sound.Runtime` player bodies, but it does include map sound helper structs in the main `Hex` assembly:

| Current type/method | ISIL evidence | Static conclusion |
|---|---|---|
| `eze+SoundInfo..ctor(fwz, ESpatialSoundType)` | `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/eze_NestedType_SoundInfo.txt` stores `fwz` into `SoundSet` and `ESpatialSoundType` into `Type`. | Proven-static current body evidence that map object spatial sound data carries native `SoundSetData` plus spatial type. |
| `ezi+PlaybackSounds..ctor(int,int)` | `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/ezi_NestedType_PlaybackSounds.txt` stores common and additional playback ids. | Proven-static current body evidence that map ambient playback tracks native playback ids for common/additional sounds. |

This strengthens map-object/ambient sound evidence, but it does not prove battle/city/music key selection or direct `Hex.Sound.Runtime` playback method bodies.
## Recommendations

- Projectile weapon SFX should be migrated toward `ProjectileConfig.flightSound` and native `BhProjectileController` playback when the projectile config row is under our control. This is the best candidate to retire sidecar cannon/pirate shot audio.
- City/town background music should not be patched through arbitrary scene lifecycle methods if a city music key route can be found. The next static step is a focused xref/body dossier for current `CityCommonSoundsConfig.sbh(string)` and `MusicSoundsConfig.scb(string)` callers.
- Combat music should not be moved to native config until the battle music key selection route is mapped. `BattleCommonSoundsConfig` is a common-SFX config, not automatically proof of combat background music.
- Custom biome sound should continue to use existing `EHeroSoundType` and `EAmbientSoundType` aliases unless enum extension and config lookup behavior are proven in current runtime.
- Sidecar audio remains acceptable for bespoke animation-timed unit sounds when no native unit-animation sound event contract has been mapped.

## Unresolved gaps

- Current owner candidates for menu/city/map music are documented above; exact key derivation still needs body/xref evidence.
- Sound group/set config loading is statically mapped through `SoundGroupsDataLoader`/`fwy` and `ResManager.GetAll<T>` generated interop metadata; exact method-body branch order and custom bundle timing remain unproven.
- Whether custom sound-set assets in mod bundles are registered early enough for native sound config lookups.
- Whether projectile config can be changed entirely through Core data for imported units, or whether generated ability/projectile rows also need patching.
- Mixer group, volume category, and stop/fade semantics for native music replacement.



