# Mono Sound Runtime Static Evidence

Status: source-generated/static-only. Runtime-unvalidated.

This dossier compares the old Mono demo `Hex.Sound.Runtime.dll` against the current Golden Era Cpp2IL sound-runtime shells. It focuses on whether existing sidecar audio systems can be moved toward native sound groups, sound sets, mixers, and pooled sources.

Evidence boundary: static Mono decompilation and current DiffableCs shells only. This does not prove custom bundle registration timing, live mixer availability, or safe direct invocation of obfuscated current methods.

## Core native sound pipeline

| Surface | Mono evidence | Current deobf evidence | Static conclusion |
|---|---|---|---|
| Sound manager singleton | Mono `SoundsManager` owns `SoundMixersManager`, `SoundSourcesPool`, `GlobalAudioListener`, and `SoundGroupsData`; `Awake` initializes singleton and `Update` processes pool/listener/mixers. | Current `SoundsManager` has the same serialized fields, singleton field/property, `Init`, `Update`, and focus hook, with obfuscated accessors. | Strong static owner. Native playback should route through `SoundsManager` rather than creating independent long-lived `AudioSource`s where possible. |
| Sound group loading | Mono `SoundGroupsData` implements `IResManagerListener`, listens to `ResManager`, lazily loads groups by name, and updates listeners when bundles containing `sound` load/unload. | Current deobf has generated sound-group data classes under obfuscated names plus matching `SoundsManager` group-data field. | Strong static system shape, but current generated type names need a separate member map before direct patching. |
| Sound group config | Mono `SoundGroupConfig` contains `assetName`, `bundleName`, and `audioMixerGroup`. | Current `SoundGroupConfig` keeps the same fields and getters/setters. | Strong static asset contract. Custom sound groups need valid group config assets and bundle names. |
| Sound set config | Mono `SoundSetConfig` contains `assetPath`, `assetName`, mixer override, volume, repeat suppression, delay, fade curves, random pitch, and clip configs. | Current `SoundSetConfig` keeps the same fields and computed accessors. | Strong static asset contract. Custom sound sets can express fade, random pitch, repeat suppression, and mixer override natively. |
| Sound clip config | Mono `SoundClipConfig` contains GUID, asset name/path, volume, active flag, pitch, random pitch. | Current `SoundClipConfig` keeps the same fields and accessors. | Strong static asset contract. This is the native replacement for ad hoc WAV metadata where clips are bundle assets. |
| Sound source playback | Mono `SoundSource.Play` applies spatial settings, mixer group, fade curves, random clip selection, loop behavior, pan/volume, pause/stop, and completion callback. | Current `SoundSource` has matching fields, enums, `Play`, `Stop`, setters, and process methods. | Strong static playback engine. Direct calls require current `SoundSetData` mapping, but behavior is not speculative. |
| Sound source pool | Mono `SoundSourcesPool` queues `SoundSource`s, pops/pushes, and processes every source. | Current `SoundSourcesPool` has matching queue/list fields and methods. | Strong static route for pooled playback. Sidecar source creation bypasses this pool. |
| Mixer routing | Mono `SoundMixersManager` finds mixer groups by string, sets mixer volumes, handles focus/mute fades. | Current `SoundMixersManager`, `MixerConfig`, `MixerGroupConfig`, and `MixersConfig` preserve fields and method shells. | Strong static route for volume category/mixer correctness. Sidecar audio risks wrong mixer/focus behavior. |
| Sound settings | Mono `SoundSettings` carries volume, loop, loop-only-one-clip, delay, playback start position, spatial position, max distance, rolloff/pan/spread/fade curves, and has `CreateDefault`. | Current `SoundSettings` keeps the same fields and constructor shape. | Strong static route for replacing bespoke one-shot/loop settings. |


## Current generated-name aliases

These aliases are static-only but strong enough to guide future decomp searches and centralized symbols. They are backed by Mono/DiffableCs shape plus generated interop metadata from `experiments/cpp2il_readable_csharp/samples/latest_refresh/runtime_interop_map_sound_runtime.json`. They are not runtime invocation proof.

| Mono semantic type | Current deobf type | Confidence | Evidence summary |
|---|---|---|---|
| `Hex.Sound.SoundsClientBase` | `fwr` | strong-static | Protected enabled/player/container fields and same Init/Release/Enable/Disable/PlaySingleSound shape. |
| `Hex.Sound.SoundConstantParameters` | `fws` | strong-static | Same seven audio constants for volume, pitch, random pitch, and minimum fade time. |
| `Hex.Sound.SoundClipData` | `fwt` | strong-static | Constructor takes `AudioClip`, `SoundClipConfig`, `SoundSetConfig`; same clip/config/released backing fields and volume/pitch accessors. |
| `Hex.Sound.SoundGroupData` | `fwv` | strong-static | `SoundGroupConfig` plus sound-set list; same `Init(groupName, config, list)` and `GetSoundSet(string)` shape. |
| `Hex.Sound.ISoundGroupsDataListener` | `fww` | strong-static | Single update callback; implemented by current `fxf` matching `SoundSetsContainer`. |
| `Hex.Sound.SoundGroupsData` | `fwx` | strong-static | Resource-manager listener type with dictionary/list fields and sound group/set lookup plus load/unload callbacks. |
| `Hex.Sound.SoundGroupsDataLoader` | `fwy` | strong-static | Static loader-only class loading `SoundGroupConfig` and list of `SoundSetConfig`, returning `fwv`. |
| `Hex.Sound.SoundSetData` | `fwz` | strong-static | Fields `SoundGroupConfig` and `SoundSetConfig`; constructor matches; random/named clip getters return `fwt`. |
| `Hex.Sound.AudioListenerController` | `fxa` | probable-static | MonoBehaviour enable/disable lifecycle paired with singleton controller collection. |
| `Hex.Sound.AudioListenerControllers` | `fxb` | probable-static | Singleton/list of `fxa` controllers with register/unregister and pop/get methods. |
| `Hex.Sound.MixerGroupVolumeController` | `fxd` | strong-static | Status/transition enums, mixer group name, return/mute curves, `AudioMixer`, and transition methods. |
| `Hex.Sound.PlaybackReceiver` | `fxe` | strong-static | Single `Action` field and playback-complete callback methods taking an int playback id. |
| `Hex.Sound.SoundSetsContainer` | `fxf` | strong-static | Implements listener, owns `fwx`, dictionary/list/string-array group names, init/release/update and set lookup methods. |
| `Hex.Sound.SoundSetsPlayer` | `fxg` | strong-static | PlaybackInfo/SoundSetInfo nested structs, playback dictionaries/id, play/stop/pause/volume/pan/source methods. |
## Implications for existing mod surfaces

| Existing behavior | Static implication |
|---|---|
| Cannon/pirate shot WAV sidecars | Best native target is still projectile config `flightSound`, but the sound-runtime dossier explains how that string should resolve: a sound set name from a loaded sound group, played through pooled `SoundSource`s and mixer routing. |
| Global combat music sidecar | Native sound runtime supports looping, fade curves, mixer routing, and playback source pooling, but the current battle music key-selection surface is still unmapped. Do not move combat music until that key route is known. |
| Stronghold/city music sidecar | Native runtime can play sound sets correctly once city music key selection and group registration are mapped. This likely belongs in config/data first, not a scene lifecycle hook. |
| Custom unit animation SFX sidecars | If the SFX is tied to an imported animation event and no native unit-animation sound-event binding is mapped, sidecar may remain appropriate. If the clip can be expressed as projectile/ability sound-set data, prefer native. |
| Custom sound bundle loading | Sound groups intentionally listen for ResManager bundle load/unload where bundle names contain `sound`. Custom bundles should integrate with ResManager if replacing sidecars. |

## Native-friendly migration path

1. Register/load custom sound bundles through native `ResManager` so `SoundGroupsData` sees load/unload events.
2. Ensure every custom sound group has a `SoundGroupConfig` with the correct `bundleName` and mixer group.
3. Ensure every custom sound set has `SoundSetConfig` plus `SoundClipConfig` entries for the clips.
4. Point existing data surfaces, such as projectile `flightSound`, city sound config, or mapped battle music keys, at those sound-set names.
5. Only patch direct playback methods after current `SoundSetData`/`SoundSetsPlayer` generated names are mapped and static body evidence identifies invocation contracts.

## Unresolved gaps

- Current generated names for core sound-runtime data/player classes are documented above and corroborated by generated interop metadata plus imported method-pointer addresses; method-level body evidence for direct invocation contracts is still not complete.
- Exact battle music key and city music key selection surfaces are still not mapped.
- Exact load timing for mod sound bundles through native `ResManager` is not proven.
- Direct invocation of current `SoundSource.Play` is statically plausible but not a recommended hook target until source-pool ownership, live `SoundSetData` acquisition, and playback lifecycle ordering are proven.




## Current method-pointer evidence

Artifacts:

- `experiments/cpp2il_readable_csharp/samples/latest_refresh/method_pointers_hex_sound_runtime.csv`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/address_map_sound_runtime.json`

`out_dummydll_with_attrs` was generated with Cpp2IL `attributeinjector`, then `export_dummydll_method_pointer_map.ps1` converted method RVAs to current virtual addresses using `GameAssembly.dll` image base `0x180000000`. The imported map currently contributes 334 `Hex.Sound.Runtime` addresses to `address_map_sound_runtime.json`.

High-value examples:

| Current method | VA | Static implication |
|---|---:|---|
| `Hex.Sound.SoundsManager::Awake()` | `0x181E4A1A0` | Exact native address for sound manager initialization. |
| `Hex.Sound.SoundsManager::Init()` | `0x181E4A3F0` | Exact native address for sound manager internal init candidate. |
| `Hex.Sound.SoundsManager::Update()` | `0x181E4A640` | Exact native address for sound manager update loop. |
| `Hex.Sound.SoundsManager::bmtx()` returning `fwx` | `0x180584E90` | Exact address for sound group data accessor candidate. |
| `Hex.Sound.SoundSource::Play(fwz,int,SoundSettings)` | `0x181E48660` | Exact native address for low-level source playback; direct invocation still requires ownership/lifecycle proof. |
| `Hex.Sound.SoundSource::Stop()` | `0x181E48AF0` | Exact native address for source stop. |
| `Hex.Sound.SoundSourcesPool::bmuw()` | `0x181E49E70` | Exact native address for source acquisition candidate. |
| `Hex.Sound.SoundSourcesPool::bmux(SoundSource)` | `0x181E49EE0` | Exact native address for source return/release candidate. |

These addresses improve patch drift tracking and runtime metadata correlation. They do not by themselves prove custom bundle registration timing, music key selection, or safe direct playback calls.


## Native disassembly evidence

`experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_sound_runtime.json/md` now disassembles all 422 imported `Hex.Sound.Runtime` method-pointer rows from the current `GameAssembly.dll`, with 1,867 direct calls observed and 1,206 calls annotated with known address-map targets. This is static native body evidence; deeper sound playback semantics still require focused interpretation of selected methods.
