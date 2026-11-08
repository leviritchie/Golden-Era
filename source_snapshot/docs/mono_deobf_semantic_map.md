# Mono Demo to Golden Era Semantic Map

Status: source-generated/static-only. Runtime-unvalidated.

This map compares the old Mono demo `Hex.dll` against the current Golden Era Cpp2IL DiffableCs shells. It is intended to make future mod surface work more native-friendly by preserving semantic evidence from the readable Mono build while keeping proof levels explicit.

Evidence boundary: Static metadata and DiffableCs shell comparison only. This does not prove runtime invocation order, method body equivalence, or patch safety.

## Summary

| Metric | Count |
|---|---:|
| Mono types parsed | 6494 |
| Current deobf types parsed | 11981 |
| Mono types with candidates | 2247 |
| Focus types with candidates | 573 |
| Strong static matches | 2129 |
| Probable static matches | 96 |
| Candidate matches | 22 |
| Weak candidates | 0 |
| Rejected simple-name collisions | 118 |

## How to read confidence

- `strong-static`: exact full type-name evidence plus shape agreement and enough separation from the next candidate.
- `probable-static`: exact simple-name or full-name evidence with candidate separation, but not enough to treat as proven runtime behavior.
- `candidate`: useful hypothesis for decomp follow-up.
- `weak-candidate`: shape-only or ambiguous. Do not implement from this without stronger evidence.
- `rejected simple-name collision`: same simple type name, but namespace/domain evidence contradicts a useful semantic match. These are tracked separately so they do not pollute implementation candidates.

## Rejected simple-name collisions

These rows had an exact simple-name match, but namespace/domain evidence contradicted a useful semantic match. They remain in the JSON under `rejectedSimpleNameCollisions` for auditability and are excluded from implementation candidate counts.

| Mono type | Rejected current type | Score | Reason |
|---|---|---:|---|
| `PointerInputModule` | `UnityEngine.EventSystems.PointerInputModule` | 104.0 | rejected global-to-UnityEngine framework simple-name collision |
| `MagicOnion.Resolvers.PreserveAttribute` | `Unity.Burst.PreserveAttribute` | 42.16 | rejected MagicOnion-to-Unity framework simple-name collision |
| `MagicOnion.Resolvers.PreserveAttribute` | `Unity.Burst.PreserveAttribute` | 51.0 | rejected MagicOnion-to-Unity framework simple-name collision |
| `MagicOnion.Resolvers.PreserveAttribute` | `UnityEngine.Scripting.PreserveAttribute` | 99.0 | rejected MagicOnion-to-UnityEngine framework simple-name collision |
| `Code.Network.ILobbyService` | `Hex.SharedLibrary.Services.ILobbyService` | 62.2 | rejected Code-to-Hex simple-name collision |
| `Code.Network.Map` | `Hex.Map.Map` | 46.11 | rejected Code-to-Hex simple-name collision |
| `Code.Network.Map` | `Hex.StoryHub.View.Map` | 58.07 | rejected Code-to-Hex simple-name collision |
| `Code.Network.Map` | `Hex.SharedLibrary.Models.Lobby.Map` | 62.77 | rejected Code-to-Hex simple-name collision |
| `Code.Network.SendType` | `Steamworks.Data.SendType` | 94.0 | rejected Code-to-Steamworks framework simple-name collision |
| `Code.Network.Steam.Extensions` | `Epic.OnlineServices.Extensions` | 49.67 | rejected Code-to-Epic framework simple-name collision |
| `Code.Network.Steam.Extensions` | `Hex.SharedLibrary.Extensions` | 48.67 | rejected Code-to-Hex simple-name collision |
| `Code.Network.Steam.Extensions` | `Newtonsoft.Json.Linq.Extensions` | 48.11 | rejected Code-to-Newtonsoft framework simple-name collision |
| `Code.Network.Steam.Extensions` | `Newtonsoft.Json.Schema.Extensions` | 52.0 | rejected Code-to-Newtonsoft framework simple-name collision |
| `Code.Network.Steam.Extensions` | `Unity.Collections.NotBurstCompatible.Extensions` | 52.0 | rejected Code-to-Unity framework simple-name collision |
| `Code.Network.Steam.Extensions` | `Unity.Collections.LowLevel.Unsafe.NotBurstCompatible.Extensions` | 52.0 | rejected Code-to-Unity framework simple-name collision |
| `Code.Network.Hex.Extensions` | `Epic.OnlineServices.Extensions` | 49.67 | rejected Code-to-Epic framework simple-name collision |
| `Code.Network.Hex.Extensions` | `Hex.SharedLibrary.Extensions` | 44.67 | rejected Code-to-Hex simple-name collision |
| `Code.Network.Hex.Extensions` | `Newtonsoft.Json.Linq.Extensions` | 47.44 | rejected Code-to-Newtonsoft framework simple-name collision |
| `Code.Network.Hex.Extensions` | `Newtonsoft.Json.Schema.Extensions` | 52.0 | rejected Code-to-Newtonsoft framework simple-name collision |
| `Code.Network.Hex.Extensions` | `Unity.Collections.NotBurstCompatible.Extensions` | 49.0 | rejected Code-to-Unity framework simple-name collision |
| `Code.Network.Hex.Extensions` | `Unity.Collections.LowLevel.Unsafe.NotBurstCompatible.Extensions` | 49.0 | rejected Code-to-Unity framework simple-name collision |
| `Code.Network.Hex.GameId` | `Steamworks.Data.GameId` | 73.47 | rejected Code-to-Steamworks framework simple-name collision |
| `Code.Network.Hex.Game.Game` | `Unity.Microsoft.GDK.Game` | 44.86 | rejected Code-to-Unity framework simple-name collision |
| `Code.Network.Epic.Messages.IMessage` | `System.Runtime.Remoting.Messaging.IMessage` | 47.0 | rejected Code-to-System framework simple-name collision |
| `Code.Network.Epic.Connections.Connection` | `Steamworks.Data.Connection` | 55.73 | rejected Code-to-Steamworks framework simple-name collision |
| `Hex.FontData` | `UnityEngine.UI.FontData` | 43.19 | rejected Hex-to-UnityEngine simple-name collision |
| `Hex.SharedLibrary.Extensions` | `Epic.OnlineServices.Extensions` | 52.8 | rejected Hex-to-Epic simple-name collision |
| `Hex.SharedLibrary.Extensions` | `Newtonsoft.Json.Linq.Extensions` | 45.67 | rejected Hex-to-Newtonsoft simple-name collision |
| `Hex.SharedLibrary.Extensions` | `Newtonsoft.Json.Schema.Extensions` | 51.71 | rejected Hex-to-Newtonsoft simple-name collision |
| `Hex.SharedLibrary.Extensions` | `Unity.Collections.NotBurstCompatible.Extensions` | 57.2 | rejected Hex-to-Unity simple-name collision |
| `Hex.SharedLibrary.Extensions` | `Unity.Collections.LowLevel.Unsafe.NotBurstCompatible.Extensions` | 57.2 | rejected Hex-to-Unity simple-name collision |
| `Hex.SharedLibrary.Requests.AuthResponse` | `Steamworks.AuthResponse` | 42.0 | rejected Hex-to-Steamworks simple-name collision |
| `Hex.SharedLibrary.Models.Lobby.CreateLobbyOptions` | `Epic.OnlineServices.Lobby.CreateLobbyOptions` | 52.0 | rejected Hex-to-Epic simple-name collision |
| `Hex.SharedLibrary.Models.Leaderboard.LeaderboardEntry` | `Steamworks.Data.LeaderboardEntry` | 44.62 | rejected Hex-to-Steamworks simple-name collision |
| `Hex.Ui.Logger` | `UnityEngine.Logger` | 51.0 | rejected Hex-to-UnityEngine simple-name collision |
| `Hex.StoryHub.View.Map` | `Code.Network.Map` | 55.52 | rejected Hex-to-Code simple-name collision |
| `Hex.StoryHub.Legacy.Item` | `Steamworks.Ugc.Item` | 46.5 | rejected Hex-to-Steamworks simple-name collision |
| `Hex.StoryHub.Data.Item` | `Steamworks.Ugc.Item` | 47.23 | rejected Hex-to-Steamworks simple-name collision |
| `Hex.Storage.FileInfo` | `System.IO.FileInfo` | 48.67 | rejected Hex-to-System simple-name collision |
| `Hex.Render.LightingSettings` | `UnityEngine.LightingSettings` | 52.0 | rejected Hex-to-UnityEngine simple-name collision |
| `Hex.QuestScript.Action` | `System.Action` | 54.8 | rejected Hex-to-System simple-name collision |
| `Hex.Processing.Backends.Net.Modes.Base` | `Steamworks.ServerList.Base` | 45.28 | rejected Hex-to-Steamworks simple-name collision |
| `Hex.Pick.Timer` | `System.Threading.Timer` | 53.32 | rejected Hex-to-System simple-name collision |
| `Hex.MapGenerator.Connection` | `Steamworks.Data.Connection` | 42.83 | rejected Hex-to-Steamworks simple-name collision |
| `Hex.MapGenerator.ReadOnlyArray`1` | `UnityEngine.InputSystem.Utilities.ReadOnlyArray`1` | 57.67 | rejected Hex-to-UnityEngine simple-name collision |
| `Hex.MapGenerator.MemoryPool`1` | `System.Buffers.MemoryPool`1` | 63.75 | rejected Hex-to-System simple-name collision |
| `Hex.Map.Map` | `Code.Network.Map` | 44.65 | rejected Hex-to-Code simple-name collision |
| `Hex.Map.PropertyContainer` | `Unity.Properties.PropertyContainer` | 43.14 | rejected Hex-to-Unity simple-name collision |
| `Hex.InputSys.Bindings` | `Epic.OnlineServices.Bindings` | 42.14 | rejected Hex-to-Epic simple-name collision |
| `Hex.InputSys.InputAction` | `UnityEngine.InputSystem.InputAction` | 43.41 | rejected Hex-to-UnityEngine simple-name collision |
| `Hex.InputSys.InputSystem` | `UnityEngine.InputSystem.InputSystem` | 49.48 | rejected Hex-to-UnityEngine simple-name collision |
| `Hex.InitScene.State` | `System.IO.Pipelines.State` | 55.57 | rejected Hex-to-System simple-name collision |
| `Hex.Info.Context` | `Mono.Globalization.Unicode.Context` | 46.91 | rejected Hex-to-Mono simple-name collision |
| `Hex.Info.Context` | `System.Runtime.Remoting.Contexts.Context` | 51.46 | rejected Hex-to-System simple-name collision |
| `Hex.Info.Info` | `Epic.OnlineServices.Presence.Info` | 46.75 | rejected Hex-to-Epic simple-name collision |
| `Hex.Guides.TextElement` | `UnityEngine.TextCore.Text.TextElement` | 43.82 | rejected Hex-to-UnityEngine simple-name collision |
| `Hex.Guides.TextElement` | `UnityEngine.UIElements.TextElement` | 42.22 | rejected Hex-to-UnityEngine simple-name collision |
| `Hex.GameHub.NetHub.ConnectChecker.State` | `System.IO.Pipelines.State` | 53.07 | rejected Hex-to-System simple-name collision |
| `Hex.GameHub.Lobby.Logic.Slot` | `System.Linq.Slot` | 48.83 | rejected Hex-to-System simple-name collision |
| `Hex.GameHub.Lobby.Logic.User` | `Discord.User` | 43.0 | rejected Hex-to-Discord simple-name collision |
| `Hex.GameHub.Lobby.Data.Slot` | `System.Linq.Slot` | 51.17 | rejected Hex-to-System simple-name collision |
| `Hex.Session.Mode` | `System.Net.Mode` | 52.09 | rejected Hex-to-System simple-name collision |
| `Hex.Session.Quests2.Context` | `Mono.Globalization.Unicode.Context` | 46.58 | rejected Hex-to-Mono simple-name collision |
| `Hex.Session.Quests2.Context` | `System.Runtime.Remoting.Contexts.Context` | 45.95 | rejected Hex-to-System simple-name collision |
| `Hex.Session.Quests2.Data.Action` | `System.Action` | 64.67 | rejected Hex-to-System simple-name collision |
| `Hex.Session.Quests2.Actions.Action` | `System.Action` | 57.07 | rejected Hex-to-System simple-name collision |
| `Hex.Session.Logic.Item` | `Steamworks.Ugc.Item` | 49.05 | rejected Hex-to-Steamworks simple-name collision |
| `Hex.Session.Logic.Logger` | `UnityEngine.Logger` | 51.0 | rejected Hex-to-UnityEngine simple-name collision |
| `Hex.Session.City.Logger` | `UnityEngine.Logger` | 51.0 | rejected Hex-to-UnityEngine simple-name collision |
| `Hex.Session.Battle.Hex` | `MessagePack.Hex` | 42.94 | rejected Hex-to-MessagePack simple-name collision |
| `Hex.Session.Data.Logger` | `UnityEngine.Logger` | 51.0 | rejected Hex-to-UnityEngine simple-name collision |
| `Hex.Session.World.Logger` | `UnityEngine.Logger` | 51.0 | rejected Hex-to-UnityEngine simple-name collision |
| `Hex.Session.World.Ai.Task` | `System.Threading.Tasks.Task` | 49.37 | rejected Hex-to-System simple-name collision |
| `Hex.Session.World.Ai.Profiler.Profiler` | `UnityEngine.Profiling.Profiler` | 44.86 | rejected Hex-to-UnityEngine simple-name collision |
| `Hex.Session.World.Ai.Pathfinder.Base` | `Steamworks.ServerList.Base` | 58.92 | rejected Hex-to-Steamworks simple-name collision |
| `Hex.Session.World.Ai.MakeHeroTask.Mode` | `System.Net.Mode` | 51.71 | rejected Hex-to-System simple-name collision |
| `Hex.Arena.Logic.Mode` | `System.Net.Mode` | 52.8 | rejected Hex-to-System simple-name collision |
| `MouseState` | `UnityEngine.InputSystem.LowLevel.MouseState` | 51.63 | rejected global-to-UnityEngine framework simple-name collision |
| `Key` | `UnityEngine.InputSystem.Key` | 42.0 | rejected global-to-UnityEngine framework simple-name collision |
| `Vertex` | `UnityEngine.UIElements.Vertex` | 94.45 | rejected global-to-UnityEngine framework simple-name collision |
| ... | ... | ... | 38 more omitted from Markdown; see JSON artifact. |

## Manual obfuscated type aliases

These aliases cannot be discovered by exact simple-name matching because the current build keeps obfuscated global type names. They are authored from focused Mono/current dossiers and remain static-only until runtime-proven.

| Mono semantic type | Current deobf type | Confidence | Domain | Evidence |
|---|---|---|---|---|
| `Hex.Sound.SoundsClientBase` | `fwr` | strong-static | sound-runtime | same protected fields: enabled/player/container; same Init/Release/Enable/Disable/PlaySingleSound shape; current fwr derives no namespace but matches Mono abstract client base |
| `Hex.Sound.SoundConstantParameters` | `fws` | strong-static | sound-runtime | same seven audio constants: min/max volume, pitch, random pitch, min fade |
| `Hex.Sound.SoundClipData` | `fwt` | strong-static | sound-runtime | constructor AudioClip + SoundClipConfig + SoundSetConfig; same clip/config/released backing fields; same volume/pitch/active accessors |
| `Hex.Sound.SoundGroupData` | `fwv` | strong-static | sound-runtime | SoundGroupConfig field plus list of sound sets; Init(groupName, SoundGroupConfig, List); GetSoundSet(string) shape |
| `Hex.Sound.ISoundGroupsDataListener` | `fww` | strong-static | sound-runtime | single update callback method; implemented by current fxf matching SoundSetsContainer |
| `Hex.Sound.SoundGroupsData` | `fwx` | strong-static | sound-runtime | inherits current fxi matching IResManagerListener; dictionary + listener list fields; GetSoundGroup/GetSoundSet/listen/unlisten/load/unload callback shape |
| `Hex.Sound.SoundGroupsDataLoader` | `fwy` | strong-static | sound-runtime | static loader-only class; loads SoundGroupConfig out param; loads List of SoundSetConfig out param |
| `Hex.Sound.SoundSetData` | `fwz` | strong-static | sound-runtime | fields SoundGroupConfig + SoundSetConfig; constructor SoundSetConfig + SoundGroupConfig; random clip and named clip getters returning fwt/SoundClipData |
| `Hex.Sound.AudioListenerController` | `fxa` | probable-static | sound-runtime | MonoBehaviour with enable/disable lifecycle; paired with singleton-style current fxb matching AudioListenerControllers |
| `Hex.Sound.AudioListenerControllers` | `fxb` | probable-static | sound-runtime | singleton/list of fxa controllers; push/pop/register/unregister controller shape |
| `Hex.Sound.MixerGroupVolumeController` | `fxd` | strong-static | sound-runtime | status/transition enums; mixer group name + return/mute curves + AudioMixer fields; transition and set-volume method shape |
| `Hex.Sound.PlaybackReceiver` | `fxe` | strong-static | sound-runtime | single Action field; playback-complete callback methods taking int |
| `Hex.Sound.SoundSetsContainer` | `fxf` | strong-static | sound-runtime | implements fww/ISoundGroupsDataListener; fields SoundGroupsData + dictionary + list + string[] group names; Init(string[]), Release, GetSoundSet(string,bool), update callback shape |
| `Hex.IResManagerListener` | `fxi` | strong-static | resmanager | two callback interface methods; both callbacks take fxj/ResBundle; implemented by sound-runtime fwx/SoundGroupsData |
| `Hex.ResBundle` | `fxj` | strong-static | resmanager | string bundle name field; AssetBundle data field; release-like method |
| `Hex.FileInfo` | `fxk` | strong-static | resmanager | path/bundleName/Type fields; Equals override; GetHashCode plus hash-combine helpers |
| `Hex.ResFile` | `fxl` | strong-static | resmanager | FileInfo/fxk info field; UnityEngine.Object data field; used by ResManager file enumeration methods |
| `Hex.DirectoryHelper` | `fwo` | strong-static | utils | static utility class; same resource-path helper signatures; used by Mono ResManager for bundle path normalization and matching |
| `Hex.Sound.SoundSetsPlayer` | `fxg` | strong-static | sound-runtime | PlaybackInfo/SoundSetInfo nested structs; dictionaries and playback id field; Play overloads returning int |

## Priority selected-HUD and battle-UI matches

| Mono type | Best current deobf candidate | Confidence | Score | Key reasons |
|---|---|---|---:|---|
| `Hex.Storage.IconData` | `Hex.Storage.IconData` | strong-static | 107.57 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.14 |
| `Hex.Render.SoTerrainMaterial` | `Hex.Render.SoTerrainMaterial` | strong-static | 109.4 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.20 |
| `Hex.Map.BhSoundMapObject` | `Hex.Map.BhSoundMapObject` | strong-static | 116.6 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.47 |
| `Hex.Configs.AbilityViewConfig` | `Hex.Configs.AbilityViewConfig` | strong-static | 106.41 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.11 |
| `Hex.Configs.BiomesInfo` | `Hex.Configs.BiomesInfo` | strong-static | 113.67 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.33 |
| `Hex.Configs.HeroAbilityConfig` | `Hex.Configs.HeroAbilityConfig` | strong-static | 108.15 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.20 |
| `Hex.Configs.HeroAbilityLevelConfig` | `Hex.Configs.HeroAbilityLevelConfig` | strong-static | 101.06 | exact full type name; namespace/name token overlap 1.00; param-count histogram similarity 0.91 |
| `Hex.Configs.ProjectileConfig` | `Hex.Configs.ProjectileConfig` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Configs.BattleCommonSoundsConfig` | `Hex.Configs.BattleCommonSoundsConfig` | strong-static | 133.12 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Configs.CityCommonSoundsConfig` | `Hex.Configs.CityCommonSoundsConfig` | strong-static | 113.67 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.33 |
| `Hex.Configs.CitySoundConfig` | `Hex.Configs.CitySoundConfig` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Configs.MapAmbientSoundsConfig` | `Hex.Configs.MapAmbientSoundsConfig` | strong-static | 110.73 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.20 |
| `Hex.Configs.MapAmbientSoundConfig` | `Hex.Configs.MapAmbientSoundConfig` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Configs.MapHeroSoundsConfig` | `Hex.Configs.MapHeroSoundsConfig` | strong-static | 110.73 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.20 |
| `Hex.Configs.MapHeroSoundConfig` | `Hex.Configs.MapHeroSoundConfig` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Configs.ESpatialSoundType` | `Hex.Configs.ESpatialSoundType` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Configs.MusicSoundsConfig` | `Hex.Configs.MusicSoundsConfig` | strong-static | 109.67 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.33 |
| `Hex.Configs.MusicSoundConfig` | `Hex.Configs.MusicSoundConfig` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Configs.SpriteConfig` | `Hex.Configs.SpriteConfig` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Configs.EAmbientSoundType` | `Hex.Configs.EAmbientSoundType` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Configs.EHeroSoundType` | `Hex.Configs.EHeroSoundType` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Sound.TrackedSoundInfo` | `Hex.Sound.TrackedSoundInfo` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.UI.BhIcon` | `Hex.UI.BhIcon` | strong-static | 109.4 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.20 |
| `Hex.Session.UI.HeroProfile.BhHeroPortraitView` | `Hex.Session.UI.HeroProfile.BhHeroPortraitView` | strong-static | 97.28 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.12 |
| `Hex.Session.UI.HeroProfile.BhHeroSkillView` | `Hex.Session.UI.HeroProfile.BhHeroSkillView` | strong-static | 124.33 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.67 |
| `Hex.Session.UI.HeroProfile.BhHeroSpecializationView` | `Hex.Session.UI.HeroProfile.BhHeroSpecializationView` | strong-static | 110.8 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.40 |
| `Hex.Session.UI.HeroProfile.BhHeroSubSkillView` | `Hex.Session.UI.HeroProfile.BhHeroSubSkillView` | strong-static | 124.33 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.67 |
| `Hex.Session.City.BhCitySoundObject` | `Hex.Session.City.BhCitySoundObject` | strong-static | 106.88 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.18 |
| `Hex.Session.City.BhHireUnitAbilityItemView` | `Hex.Session.City.BhHireUnitAbilityItemView` | strong-static | 124.9 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.69 |
| `Hex.Session.City.BhHireUnitAbilityView` | `Hex.Session.City.BhHireUnitAbilityView` | strong-static | 119.83 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.55 |
| `Hex.Session.Battle.BhProjectileController` | `Hex.Session.Battle.BhProjectileController` | strong-static | 111.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.25 |
| `Hex.Session.Battle.BhProjectileDrawerEmulator` | `Hex.Session.Battle.BhProjectileDrawerEmulator` | strong-static | 119.53 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.60 |
| `Hex.Session.Battle.BattleEventArgs` | `Hex.Session.Battle.BattleEventArgs` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Session.Battle.HotkeyAbilityArgs` | `Hex.Session.Battle.HotkeyAbilityArgs` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Session.Battle.ProjectileEventArgs` | `Hex.Session.Battle.ProjectileEventArgs` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Session.Battle.BhBattleQueueView` | `Hex.Session.Battle.BhBattleQueueView` | strong-static | 107.57 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.14 |
| `Hex.Session.Battle.BhSelectedUnitHud` | `Hex.Session.Battle.BhSelectedUnitHud` | strong-static | 105.75 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.25 |
| `Hex.Session.Battle.BhSelectedUnitView` | `Hex.Session.Battle.BhSelectedUnitView` | strong-static | 113.67 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.33 |
| `Hex.Session.Battle.BhTurnView` | `Hex.Session.Battle.BhTurnView` | strong-static | 105.23 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.16 |
| `Hex.Session.Battle.BhUnitAbilityView` | `Hex.Session.Battle.BhUnitAbilityView` | strong-static | 104.81 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.17 |
| `Hex.Session.Battle.BhUnitControlsView` | `Hex.Session.Battle.BhUnitControlsView` | strong-static | 106.38 | exact full type name; namespace/name token overlap 1.00; public-method overlap 0.43 |
| `Hex.Session.World.Minimap` | `Hex.Session.World.Minimap` | strong-static | 88.16 | exact full type name; namespace/name token overlap 1.00; param-count histogram similarity 0.41 |
| `Hex.Session.World.SoMinimapConfig` | `Hex.Session.World.SoMinimapConfig` | strong-static | 107.06 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.14 |
| `Hex.ResManager` | `Hex.ResManager` | strong-static | 101.75 | exact full type name; namespace/name token overlap 1.00; param-count histogram similarity 1.00 |
| `Hex.Sound.MixerConfig` | `Hex.Sound.MixerConfig` | strong-static | 105.16 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.11 |
| `Hex.Sound.MixerGroupConfig` | `Hex.Sound.MixerGroupConfig` | strong-static | 107.11 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.11 |
| `Hex.Sound.MixersConfig` | `Hex.Sound.MixersConfig` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Sound.SoundClipConfig` | `Hex.Sound.SoundClipConfig` | strong-static | 103.0 | exact full type name; namespace/name token overlap 1.00; param-count histogram similarity 1.00 |
| `Hex.Sound.SoundGroupConfig` | `Hex.Sound.SoundGroupConfig` | strong-static | 103.0 | exact full type name; namespace/name token overlap 1.00; param-count histogram similarity 1.00 |
| `Hex.Sound.SoundSetConfig` | `Hex.Sound.SoundSetConfig` | strong-static | 103.0 | exact full type name; namespace/name token overlap 1.00; param-count histogram similarity 1.00 |
| `Hex.Sound.SoundMixersManager` | `Hex.Sound.SoundMixersManager` | strong-static | 101.46 | exact full type name; namespace/name token overlap 1.00; param-count histogram similarity 0.92 |
| `Hex.Sound.SoSoundSettings` | `Hex.Sound.SoSoundSettings` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Sound.SoundSettings` | `Hex.Sound.SoundSettings` | strong-static | 109.4 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.20 |
| `Hex.Sound.SoundsManager` | `Hex.Sound.SoundsManager` | strong-static | 110.33 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.33 |
| `Hex.Sound.SoundSource` | `Hex.Sound.SoundSource` | strong-static | 104.76 | exact full type name; namespace/name token overlap 1.00; public-method overlap 0.18 |
| `Hex.Sound.SoundSourcesPool` | `Hex.Sound.SoundSourcesPool` | strong-static | 109.93 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.25 |

## Focused mod-relevant matches

| Mono type | Best current deobf candidate | Confidence | Score | Key reasons |
|---|---|---|---:|---|
| `EHeroStatLimitType` | `EHeroStatLimitType` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `MeshBufferTest` | `MeshBufferTest` | strong-static | 126.2 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.60 |
| `HeroAbilityID` | `HeroAbilityID` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `BhSideHeroesViewController` | `BhSideHeroesViewController` | strong-static | 108.5 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.25 |
| `BhSideHerosArrowsViewController` | `BhSideHerosArrowsViewController` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `BhHeroLoader` | `BhHeroLoader` | strong-static | 97.04 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.27 |
| `BhUnitTest` | `BhUnitTest` | strong-static | 118.5 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.25 |
| `UnityEngine.Experimental.Rendering.SRPBatcherProfiler` | `UnityEngine.Experimental.Rendering.SRPBatcherProfiler` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.BhMagicPreviewItem` | `Hex.Arena.View.UI.BhMagicPreviewItem` | probable-static | 105.15 | exact simple type name; Hex namespace migration candidate: Hex -> Hex.Arena.View.UI; namespace/name token overlap 0.62 |
| `Hex.BhUiBuff` | `Hex.BhUiBuff` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.BhHeroSelectButton` | `Hex.BhHeroSelectButton` | strong-static | 111.36 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.25 |
| `Hex.BhOpacityImage` | `Hex.BhOpacityImage` | strong-static | 133.33 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.BhOpacityText` | `Hex.BhOpacityText` | strong-static | 102.17 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.17 |
| `Hex.BhSimulatedBattleHeroesView` | `Hex.BhSimulatedBattleHeroesView` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.ScObserverHeroHud` | `Hex.ScObserverHeroHud` | strong-static | 103.0 | exact full type name; namespace/name token overlap 1.00; param-count histogram similarity 1.00 |
| `Hex.BhUnitPreviews` | `Hex.BhUnitPreviews` | strong-static | 100.51 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.12 |
| `Hex.BhHireUnitAbilities` | `Hex.BhHireUnitAbilities` | strong-static | 110.73 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.20 |
| `Hex.BhMagicRangSelector` | `Hex.Session.UI.BhMagicRangSelector` | probable-static | 98.95 | exact simple type name; Hex namespace migration candidate: Hex -> Hex.Session.UI; namespace/name token overlap 0.71 |
| `Hex.BhMagicSelectorsGroup` | `Hex.Session.UI.BhMagicSelectorsGroup` | probable-static | 87.43 | exact simple type name; Hex namespace migration candidate: Hex -> Hex.Session.UI; namespace/name token overlap 0.71 |
| `Hex.TypeIconArrow` | `Hex.TypeIconArrow` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.BhCityUpgradeStatsView` | `Hex.BhCityUpgradeStatsView` | strong-static | 108.67 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.17 |
| `Hex.SharedLibrary.Models.Settings.GameModeHeroSettings` | `Hex.SharedLibrary.Models.Settings.GameModeHeroSettings` | strong-static | 81.03 | exact full type name; namespace/name token overlap 1.00; param-count histogram similarity 0.15 |
| `Hex.SharedLibrary.Models.Analytics.PnB.An_CityBuilding` | `Hex.SharedLibrary.Models.Analytics.PnB.An_CityBuilding` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.SharedLibrary.Models.Analytics.PnB.An_HeroSkills` | `Hex.SharedLibrary.Models.Analytics.PnB.An_HeroSkills` | strong-static | 125.38 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.92 |
| `Hex.SharedLibrary.Models.Analytics.PnB.An_Heroes` | `Hex.SharedLibrary.Models.Analytics.PnB.An_Heroes` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.SharedLibrary.Models.Analytics.PnB.An_Magic` | `Hex.SharedLibrary.Models.Analytics.PnB.An_Magic` | strong-static | 113.74 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.69 |
| `Hex.SharedLibrary.Models.Analytics.PnB.An_PnB_Heroes` | `Hex.SharedLibrary.Models.Analytics.PnB.An_PnB_Heroes` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.SharedLibrary.Models.Analytics.PnB.An_Units` | `Hex.SharedLibrary.Models.Analytics.PnB.An_Units` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Videoplayer.ClipInfo` | `Hex.Videoplayer.ClipInfo` | strong-static | 107.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.50 |
| `Hex.Cheat.UI.StateHeroes` | `Hex.Cheat.UI.StateHeroes` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Cheat.UI.StateMagic` | `Hex.Cheat.UI.StateMagic` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Cheat.UI.StateAddResource` | `Hex.Cheat.UI.StateAddResource` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Cheat.UI.StateAddUnit` | `Hex.Cheat.UI.StateAddUnit` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Cheat.UI.StateChooseHero` | `Hex.Cheat.UI.StateChooseHero` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Cheat.UI.StateChooseMagic` | `Hex.Cheat.UI.StateChooseMagic` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Cheat.UI.StateCreateHero` | `Hex.Cheat.UI.StateCreateHero` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Cheat.UI.BhCheatItemHero` | `Hex.Cheat.UI.BhCheatItemHero` | strong-static | 132.5 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Cheat.UI.BhCheatItemMagic` | `Hex.Cheat.UI.BhCheatItemMagic` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Cheat.UI.BhCheatItemUnit` | `Hex.Cheat.UI.BhCheatItemUnit` | strong-static | 131.67 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Cheat.UI.BhResourcePanel` | `Hex.Cheat.UI.BhResourcePanel` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Cheat.UI.BhWindowHeroPick` | `Hex.Cheat.UI.BhWindowHeroPick` | strong-static | 131.33 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.91 |
| `Hex.Cheat.UI.BhWindowMagicPick` | `Hex.Cheat.UI.BhWindowMagicPick` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Cheat.UI.BhWindowUnitPick` | `Hex.Cheat.UI.BhWindowUnitPick` | strong-static | 127.67 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.82 |
| `Hex.Cheat.UI.BhWindowWorldHeroPick` | `Hex.Cheat.UI.BhWindowWorldHeroPick` | strong-static | 130.56 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.89 |
| `Hex.Cheat.UI.HighlightIcon` | `Hex.Cheat.UI.HighlightIcon` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Cheat.UI.BhCityCheatPanel` | `Hex.Cheat.UI.BhCityCheatPanel` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Cheat.UI.BhWindowCity` | `Hex.Cheat.UI.BhWindowCity` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Cheat.UI.BhWindowHero` | `Hex.Cheat.UI.BhWindowHero` | strong-static | 132.43 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.94 |
| `Hex.Cheat.UI.BhWindowMagic` | `Hex.Cheat.UI.BhWindowMagic` | strong-static | 131.69 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.93 |
| `Hex.StoryHub.Logic.Hero` | `Hex.StoryHub.Logic.Hero` | strong-static | 99.25 | exact full type name; namespace/name token overlap 1.00; param-count histogram similarity 1.00 |
| `Hex.StoryHub.UI.BhHeroInfo` | `Hex.StoryHub.UI.BhHeroInfo` | strong-static | 115.24 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.29 |
| `Hex.StoryHub.UI.BhHeroSection` | `Hex.StoryHub.UI.BhHeroSection` | strong-static | 104.6 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.30 |
| `Hex.StoryHub.UI.BhHeroSkill` | `Hex.StoryHub.UI.BhHeroSkill` | strong-static | 121.25 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.38 |
| `Hex.StoryHub.UI.BhHeroSkillsPanel` | `Hex.StoryHub.UI.BhHeroSkillsPanel` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.StoryHub.UI.BhHeroesPanel` | `Hex.StoryHub.UI.BhHeroesPanel` | strong-static | 115.17 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.36 |
| `Hex.StoryHub.UI.BhHeroesSelection` | `Hex.StoryHub.UI.BhHeroesSelection` | strong-static | 101.0 | exact full type name; namespace/name token overlap 1.00; public-method overlap 0.33 |
| `Hex.StoryHub.UI.ScHeroSelectionPanel` | `Hex.StoryHub.UI.ScHeroSelectionPanel` | strong-static | 115.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.27 |
| `Hex.StoryHub.Data.Hero` | `Hex.StoryHub.Data.Hero` | strong-static | 106.56 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.11 |
| `Hex.StoryHub.DB.Config.HeroArmy` | `Hex.StoryHub.DB.Config.HeroArmy` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.StoryHub.DB.Config.Unit` | `Hex.StoryHub.DB.Config.Unit` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.StoryHub.DB.Config.Hero` | `Hex.StoryHub.DB.Config.Hero` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Storage.IconData` | `Hex.Storage.IconData` | strong-static | 107.57 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.14 |
| `Hex.Settings.UI.BhSoundSection` | `Hex.Settings.UI.BhSoundSection` | strong-static | 110.0 | exact full type name; namespace/name token overlap 1.00; public-method overlap 1.00 |
| `Hex.Tools.UnitsTestConfig` | `Hex.Tools.UnitsTestConfig` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Tools.UnitsTestConfigs` | `Hex.Tools.UnitsTestConfigs` | strong-static | 113.67 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.33 |
| `Hex.Tools.BhUnitAnimationListener` | `Hex.Tools.BhUnitAnimationListener` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Tools.BhUnitAnimationcsCam` | `Hex.Tools.BhUnitAnimationcsCam` | strong-static | 109.4 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.20 |
| `Hex.Tools.UnitsListView` | `Hex.Tools.UnitsListView` | strong-static | 118.49 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.44 |
| `Hex.Tools.BhUnitsTestView` | `Hex.Tools.BhUnitsTestView` | strong-static | 111.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.25 |
| `Hex.Render.BhBlendIntoTerrain` | `Hex.Render.BhBlendIntoTerrain` | strong-static | 106.14 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.18 |
| `Hex.Render.LightingClip` | `Hex.Render.LightingClip` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Render.SoTerrainMaterial` | `Hex.Render.SoTerrainMaterial` | strong-static | 109.4 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.20 |
| `Hex.Render.TerrainTexturesCount` | `Hex.Render.TerrainTexturesCount` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Pick.HeroInfo` | `Hex.Pick.HeroInfo` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Pick.BhHeroDetails` | `Hex.Pick.BhHeroDetails` | strong-static | 105.66 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.23 |
| `Hex.Pick.BhUnitSlot` | `Hex.Pick.BhUnitSlot` | strong-static | 113.67 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.33 |
| `Hex.MapGenerator.ResourceFractionDistribution` | `Hex.MapGenerator.ResourceFractionDistribution` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.MapGenerator.BiomeRuleType` | `Hex.MapGenerator.BiomeRuleType` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.MapGenerator.BiomeRule` | `Hex.MapGenerator.BiomeRule` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.MapGenerator.AmbientPickupDistribution` | `Hex.MapGenerator.AmbientPickupDistribution` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |

## Priority member-level hypotheses

### `Hex.Storage.IconData` -> `Hex.Storage.IconData`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `bytes_`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_bytes`/0 | `.ctor`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 1 | `get_isEmpty`/0 | `.ctor`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 2 | `.ctor`/1 | `izr`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 3 | `.ctor`/1 | `izs`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 4 | `GenerateSprite`/0 | `izt`/0 | candidate | same declaration ordinal; same parameter count; same public flag |

### `Hex.Render.SoTerrainMaterial` -> `Hex.Render.SoTerrainMaterial`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `biomes`, `blendBias`, `blendDepth`, `blendDistance`, `instance`, `objectsBlendDepth`, `objectsBlendTexture`, `objectsBlendTextureScale`, `terrainMaterial`, `tilesMask`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `GetInstance`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `GetTerrainMaterial`/0 | `kwf`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 2 | `.ctor`/0 | `kwg`/0 | candidate | same declaration ordinal; same parameter count; same public flag |

### `Hex.Map.BhSoundMapObject` -> `Hex.Map.BhSoundMapObject`

Exact method-name survivals: `.ctor`, `Awake`, `Init`, `OnDisable`, `OnEnable`, `PlaySingleFullLengthSound`, `PlaySingleShortSound`

Exact field-name survivals: `animationStartRandomizer`, `animator`, `bhMapObject`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_mapObject`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `Awake`/0 | `Awake`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |
| 2 | `OnEnable`/0 | `Init`/1 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 3 | `OnDisable`/0 | `OnDisable`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |
| 4 | `Init`/1 | `OnEnable`/0 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 5 | `SetSoundPlayer`/1 | `oqs`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 6 | `GetPlaybackStartPosition`/1 | `oqt`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 7 | `GetPlaybackStartMoment`/1 | `oqu`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 8 | `PlaySingleFullLengthSound`/0 | `oqv`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 9 | `PlaySingleShortSound`/0 | `PlaySingleFullLengthSound`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 10 | `.ctor`/0 | `PlaySingleShortSound`/0 | candidate | same declaration ordinal; same parameter count; same public flag |

### `Hex.Configs.AbilityViewConfig` -> `Hex.Configs.AbilityViewConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `abilityType`, `additionalDescription`, `animationIndex`, `ascentTime`, `canShowOnUI`, `damageTimeOffset`, `descentTime`, `description`, `emitter`, `endTpTime`, `excaptionInTooltip`, `flightSound`, `flyHeight`, `icon`, `infoDescription`, `jumpEndTime`, `jumpFlyTime`, `jumpMaxHeight`, `jumpPrepareTime`, `maxHeight`, `moveSpeed`, `name`, `projectile`, `projectileAngle`, `projectileDelay`, `projectileSpeed`, `shield`, `startProjectileDelay`, `startTpTime`, `trajectory`, `useExpandTooltip`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_id`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `set_id`/1 | `roe`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 2 | `GetProjectileConfig`/0 | `rof`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 3 | `get_trajectoryType`/0 | `rog`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 4 | `.ctor`/0 | `roh`/0 | candidate | same declaration ordinal; same parameter count; same public flag |

### `Hex.Configs.BiomesInfo` -> `Hex.Configs.BiomesInfo`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `fractionsByBiome`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `GetFractionForBiome`/1 | `.ctor`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 1 | `.ctor`/0 | `rqy`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |

### `Hex.Configs.HeroAbilityConfig` -> `Hex.Configs.HeroAbilityConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `animationIndex`, `levels`, `showSeparately`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_sid`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `PostLoad`/0 | `oql`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 2 | `.ctor`/0 | `rwd`/0 | candidate | same declaration ordinal; same parameter count; same public flag |

### `Hex.Configs.HeroAbilityLevelConfig` -> `Hex.Configs.HeroAbilityLevelConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `abilityType`, `actionCost`, `additionalDescription`, `aiValue`, `allyDealer`, `armedCd`, `attackTimeAfter`, `attackTimeBefore`, `castTargetEffectPrefab`, `castType_`, `casterEffect`, `casterEffectPrefab`, `castsPerBattle`, `cd`, `charges`, `damageDealer`, `description`, `dontUseEnergy`, `effect`, `effectTime`, `energyLevel`, `excaptionInTooltip`, `globalEffect`, `globalEffectPrefab`, `hexEffect`, `hexEffectTime`, `infoDescription`, `instacast`, `name`, `orderedEffects`, `projectileConfig`, `projectilesCount`, `startCd`, `targetHexEffectPrefab`, `useAllEnergy`, `useAllEnergyLevels`, `useExpandTooltip`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_trajectoryType`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `GetProjectileConfig`/0 | `rwe`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 2 | `Plus`/1 | `rwf`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 3 | `GetCasterEffect`/0 | `rwg`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 4 | `GetCastTargetEffect`/0 | `rwh`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 5 | `GetTargetHexEffect`/0 | `rwi`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 6 | `GetGlobalEffect`/0 | `rwj`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 7 | `get_castType`/0 | `rwk`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 8 | `ParseCastType`/1 | `rwl`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 9 | `.ctor`/0 | `rwm`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 10 | `.cctor`/0 | `-` | missing-side | method exists on only one side at this ordinal |

### `Hex.Configs.ProjectileConfig` -> `Hex.Configs.ProjectileConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `angle`, `delay`, `emitter`, `flightSound`, `maxHeight`, `path`, `speed`, `startDelay`, `trajectory`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `.ctor`/9 | `.ctor`/9 | strong-static | same declaration ordinal; same parameter count; same public flag |
| 1 | `.ctor`/1 | `.ctor`/1 | strong-static | same declaration ordinal; same parameter count; same public flag |

### `Hex.Configs.BattleCommonSoundsConfig` -> `Hex.Configs.BattleCommonSoundsConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `defeat`, `start`, `victory`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `.ctor`/0 | `.ctor`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |

### `Hex.Configs.CityCommonSoundsConfig` -> `Hex.Configs.CityCommonSoundsConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `array`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `GetSound`/1 | `.ctor`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 1 | `.ctor`/0 | `sbh`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |

### `Hex.Configs.CitySoundConfig` -> `Hex.Configs.CitySoundConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `soundSetName`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `.ctor`/0 | `.ctor`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |

### `Hex.Configs.MapAmbientSoundsConfig` -> `Hex.Configs.MapAmbientSoundsConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `array`, `largeZoomAmbientSound`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `GetAmbientSoundConfig`/1 | `.ctor`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 1 | `GetStrType`/1 | `sbi`/1 | candidate | same declaration ordinal; same parameter count; same static flag |
| 2 | `.ctor`/0 | `sbj`/1 | candidate | same declaration ordinal; parameter count differs; same static flag |

### `Hex.Configs.MapAmbientSoundConfig` -> `Hex.Configs.MapAmbientSoundConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `additionalSound`, `commonSound`, `maxDelay`, `minDelay`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `.ctor`/0 | `.ctor`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |

### `Hex.Configs.MapHeroSoundsConfig` -> `Hex.Configs.MapHeroSoundsConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `array`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `GetHeroSoundConfig`/1 | `.ctor`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 1 | `GetStrType`/1 | `sbs`/1 | candidate | same declaration ordinal; same parameter count; same static flag |
| 2 | `.ctor`/0 | `sbt`/1 | candidate | same declaration ordinal; parameter count differs; same static flag |

### `Hex.Configs.MapHeroSoundConfig` -> `Hex.Configs.MapHeroSoundConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `maxDistance`, `rollOffDecayCurve`, `soundSetName`, `spreadCurve`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `.ctor`/0 | `.ctor`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |

### `Hex.Configs.ESpatialSoundType` -> `Hex.Configs.ESpatialSoundType`

Exact method-name survivals: none

Exact field-name survivals: none

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|

### `Hex.Configs.MusicSoundsConfig` -> `Hex.Configs.MusicSoundsConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `array`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `GetSoundConfig`/1 | `.ctor`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 1 | `.ctor`/0 | `scb`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |

### `Hex.Configs.MusicSoundConfig` -> `Hex.Configs.MusicSoundConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `soundSetName`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `.ctor`/0 | `.ctor`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |

### `Hex.Configs.SpriteConfig` -> `Hex.Configs.SpriteConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `sprite`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `.ctor`/0 | `.ctor`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |

### `Hex.Configs.EAmbientSoundType` -> `Hex.Configs.EAmbientSoundType`

Exact method-name survivals: none

Exact field-name survivals: none

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|

### `Hex.Configs.EHeroSoundType` -> `Hex.Configs.EHeroSoundType`

Exact method-name survivals: none

Exact field-name survivals: none

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|

### `Hex.Sound.TrackedSoundInfo` -> `Hex.Sound.TrackedSoundInfo`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `playbackId`, `source`, `trackedTransform`, `trackingTime`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `.ctor`/4 | `.ctor`/4 | strong-static | same declaration ordinal; same parameter count; same public flag |

### `Hex.UI.BhIcon` -> `Hex.UI.BhIcon`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `skillIconImage`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `Setup`/1 | `.ctor`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 1 | `GetIconRectTransform`/0 | `suj`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 2 | `.ctor`/0 | `suk`/0 | candidate | same declaration ordinal; same parameter count; same public flag |

### `Hex.Session.UI.HeroProfile.BhHeroPortraitView` -> `Hex.Session.UI.HeroProfile.BhHeroPortraitView`

Exact method-name survivals: `.ctor`, `OnHide`, `OnPointerDown`

Exact field-name survivals: `specializationView`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `Update`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 1 | `LateUpdate`/0 | `OnHide`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 2 | `SetTextGold`/0 | `OnPointerDown`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 3 | `SetTextWhite`/0 | `zxx`/3 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 4 | `SetIgnoreFill`/1 | `zxy`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 5 | `SetLevelUp`/1 | `zxz`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 6 | `AnimateX`/0 | `zya`/1 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 7 | `Set`/3 | `zyb`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 8 | `Set`/1 | `zyc`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 9 | `Set`/1 | `zyd`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 10 | `OnHide`/0 | `zye`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 11 | `OnPointerDown`/1 | `zyf`/0 | weak-candidate | same declaration ordinal; parameter count differs; same static flag |
| 12 | `SetResourcePoints`/0 | `-` | missing-side | method exists on only one side at this ordinal |
| 13 | `Refresh`/1 | `-` | missing-side | method exists on only one side at this ordinal |
| 14 | `SetEnergy`/0 | `-` | missing-side | method exists on only one side at this ordinal |
| 15 | `OnLeftClick`/0 | `-` | missing-side | method exists on only one side at this ordinal |
| 16 | `OnRightClick`/0 | `-` | missing-side | method exists on only one side at this ordinal |
| 17 | `.ctor`/0 | `-` | missing-side | method exists on only one side at this ordinal |

### `Hex.Session.UI.HeroProfile.BhHeroSkillView` -> `Hex.Session.UI.HeroProfile.BhHeroSkillView`

Exact method-name survivals: `.ctor`, `OnEnter`, `OnExit`, `OnHide`

Exact field-name survivals: `level`, `rect`, `skillIcon`, `subSkillSecondLevel`, `subSkillThirdLevel`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `OnShow`/1 | `.ctor`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 1 | `OnHide`/0 | `OnEnter`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 2 | `OnEnter`/0 | `OnExit`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 3 | `OnExit`/0 | `OnHide`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 4 | `.ctor`/0 | `zyg`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |

### `Hex.Session.UI.HeroProfile.BhHeroSpecializationView` -> `Hex.Session.UI.HeroProfile.BhHeroSpecializationView`

Exact method-name survivals: `.ctor`, `OnEnter`, `OnExit`, `OnHide`

Exact field-name survivals: `icon`, `rect`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `SetConfig`/1 | `.ctor`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 1 | `OnShow`/1 | `OnEnter`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 2 | `OnHide`/0 | `OnExit`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 3 | `OnEnter`/0 | `OnHide`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 4 | `OnExit`/0 | `OnPointerEnter`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 5 | `.ctor`/0 | `OnPointerExit`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 6 | `-` | `zyx`/1 | missing-side | method exists on only one side at this ordinal |
| 7 | `-` | `zyy`/1 | missing-side | method exists on only one side at this ordinal |

### `Hex.Session.UI.HeroProfile.BhHeroSubSkillView` -> `Hex.Session.UI.HeroProfile.BhHeroSubSkillView`

Exact method-name survivals: `.ctor`, `OnEnter`, `OnExit`, `OnHide`

Exact field-name survivals: `icon`, `rect`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `OnShow`/1 | `.ctor`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 1 | `OnHide`/0 | `OnEnter`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 2 | `OnEnter`/0 | `OnExit`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 3 | `OnExit`/0 | `OnHide`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 4 | `.ctor`/0 | `zze`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |

### `Hex.Session.City.BhCitySoundObject` -> `Hex.Session.City.BhCitySoundObject`

Exact method-name survivals: `.ctor`, `OnDisable`, `OnEnable`

Exact field-name survivals: `maxDistance`, `rollOffDecayCurve`, `soundPath`, `spreadCurve`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_SoundPath`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `get_MaxDistance`/0 | `bamj`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 2 | `get_RollOffDecayCurve`/0 | `bamk`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 3 | `get_SpreadCurve`/0 | `baml`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 4 | `PushPlayback`/1 | `bamm`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 5 | `PopPlayback`/0 | `bamn`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 6 | `IsPlaying`/0 | `bamo`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 7 | `OnEnable`/0 | `bamp`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 8 | `OnDisable`/0 | `OnDisable`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |
| 9 | `.ctor`/0 | `OnEnable`/0 | candidate | same declaration ordinal; same parameter count; same static flag |

### `Hex.Session.City.BhHireUnitAbilityItemView` -> `Hex.Session.City.BhHireUnitAbilityItemView`

Exact method-name survivals: `.ctor`, `Awake`, `Hide`, `Init`, `OnExit`, `OnHover`, `OnPointerEnter`, `OnPointerExit`, `Show`

Exact field-name survivals: `alphaAnim`, `moveAnim`, `pic`, `rect`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `Awake`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 1 | `Init`/1 | `Awake`/0 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 2 | `Show`/1 | `banl`/2 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 3 | `Hide`/1 | `banm`/2 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 4 | `Set`/2 | `Hide`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 5 | `SetPassive`/2 | `Hide`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 6 | `OnHover`/0 | `Init`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 7 | `OnExit`/0 | `OnExit`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |
| 8 | `Hide`/0 | `OnHover`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 9 | `OnPointerEnter`/1 | `OnPointerEnter`/1 | strong-static | same declaration ordinal; same parameter count; same public flag |
| 10 | `OnPointerExit`/1 | `OnPointerExit`/1 | strong-static | same declaration ordinal; same parameter count; same public flag |
| 11 | `.ctor`/0 | `Show`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |

### `Hex.Session.City.BhHireUnitAbilityView` -> `Hex.Session.City.BhHireUnitAbilityView`

Exact method-name survivals: `.ctor`, `Hide`, `OnExit`, `OnHover`, `OnPointerEnter`, `OnPointerExit`

Exact field-name survivals: `label`, `pic`, `rect`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `SetView`/2 | `.ctor`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 1 | `SetView`/2 | `bann`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 2 | `OnHover`/0 | `bano`/2 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 3 | `OnExit`/0 | `Hide`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 4 | `Hide`/0 | `hmh`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 5 | `OnPointerEnter`/1 | `OnExit`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 6 | `OnPointerExit`/1 | `OnHover`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 7 | `OnChangeLocale`/0 | `OnPointerEnter`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 8 | `.ctor`/0 | `OnPointerExit`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |

### `Hex.Session.Battle.BhProjectileController` -> `Hex.Session.Battle.BhProjectileController`

Exact method-name survivals: `.ctor`, `Init`

Exact field-name survivals: `flySound`, `flySpeed`, `maxHeight`, `startSound`, `staticId`, `trajectoryType`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `InitFromEmulator`/3 | `.ctor`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 1 | `Init`/9 | `bbst`/3 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 2 | `PlayOnce`/0 | `bbsu`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 3 | `Process`/1 | `bbsv`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 4 | `.ctor`/0 | `Init`/9 | candidate | same declaration ordinal; parameter count differs; same public flag |

### `Hex.Session.Battle.BhProjectileDrawerEmulator` -> `Hex.Session.Battle.BhProjectileDrawerEmulator`

Exact method-name survivals: `.ctor`, `OnValidate`, `Update`

Exact field-name survivals: `targetHex`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `OnValidate`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 1 | `Process`/1 | `bbso`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 2 | `Update`/0 | `OnValidate`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 3 | `.ctor`/0 | `Update`/0 | candidate | same declaration ordinal; same parameter count; same static flag |

### `Hex.Session.Battle.BattleEventArgs` -> `Hex.Session.Battle.BattleEventArgs`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `roundNumber`, `target`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `.ctor`/0 | `.ctor`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |

### `Hex.Session.Battle.HotkeyAbilityArgs` -> `Hex.Session.Battle.HotkeyAbilityArgs`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `idButton`, `isEsc`, `isReturnDeselect`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `.ctor`/1 | `.ctor`/1 | strong-static | same declaration ordinal; same parameter count; same public flag |

### `Hex.Session.Battle.ProjectileEventArgs` -> `Hex.Session.Battle.ProjectileEventArgs`

Exact method-name survivals: `.ctor`

Exact field-name survivals: none

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `.ctor`/0 | `.ctor`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |

### `Hex.Session.Battle.BhBattleQueueView` -> `Hex.Session.Battle.BhBattleQueueView`

Exact method-name survivals: `.ctor`, `Awake`, `Clear`, `Init`

Exact field-name survivals: `me`, `posCalc`, `roundSwiper`, `turnViews`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_NextMyUnit`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `Awake`/0 | `Awake`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |
| 2 | `Init`/1 | `befq`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 3 | `Clear`/0 | `befr`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 4 | `SelectUnit`/1 | `befs`/2 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 5 | `OnUnitDied`/2 | `beft`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 6 | `ClearRounds`/2 | `befu`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 7 | `UpdateStacks`/2 | `befv`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 8 | `IterateRound`/2 | `befw`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 9 | `SwipeToCurrent`/2 | `befx`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 10 | `RemoveFirstRound`/2 | `befy`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 11 | `UpdateRounds`/2 | `befz`/1 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 12 | `FillRoundsToMax`/1 | `bega`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 13 | `GenQueue`/0 | `begb`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 14 | `ShowQueue`/1 | `Clear`/0 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 15 | `.ctor`/0 | `Init`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |

### `Hex.Session.Battle.BhSelectedUnitHud` -> `Hex.Session.Battle.BhSelectedUnitHud`

Exact method-name survivals: `.ctor`, `Clear`, `Init`, `OnDestroy`, `Start`, `Update`

Exact field-name survivals: `basicCommands`, `bottomPanelRaycaster`, `controlsView`, `frame`, `hpFill`, `hpText`, `leftSmoke`, `next`, `notYourTurnAnimator`, `queue`, `rightSmoke`, `unitBlockCanvasGroup`, `unitCommands`, `unitView`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `Start`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 1 | `Update`/0 | `bejm`/1 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 2 | `OnDestroy`/0 | `bejn`/2 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 3 | `Subscribe`/1 | `bejo`/2 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 4 | `Init`/0 | `bejp`/2 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 5 | `Clear`/0 | `bejq`/2 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 6 | `SetUnit`/2 | `bejr`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 7 | `NotifyUnitChanged`/2 | `bejs`/1 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 8 | `RegisterForFilmingMode`/0 | `Clear`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 9 | `UnregisterForFilmingMode`/0 | `Init`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 10 | `OnFilmingModeChanged`/1 | `OnDestroy`/0 | weak-candidate | same declaration ordinal; parameter count differs; same static flag |
| 11 | `OnUnitStartTurn`/2 | `Start`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 12 | `OnContinueAfterWait`/2 | `svb`/0 | weak-candidate | same declaration ordinal; parameter count differs; same static flag |
| 13 | `.ctor`/0 | `svc`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 14 | `-` | `svd`/1 | missing-side | method exists on only one side at this ordinal |
| 15 | `-` | `Update`/0 | missing-side | method exists on only one side at this ordinal |

### `Hex.Session.Battle.BhSelectedUnitView` -> `Hex.Session.Battle.BhSelectedUnitView`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `pic`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `SetUnit`/1 | `.ctor`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 1 | `.ctor`/0 | `bejt`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |

### `Hex.Session.Battle.BhTurnView` -> `Hex.Session.Battle.BhTurnView`

Exact method-name survivals: `.ctor`, `Awake`, `Init`, `OnClick`, `OnDestroy`, `OnExit`, `OnHover`, `Show`, `UpdateView`

Exact field-name survivals: `blur`, `cg`, `frame`, `neutralBacks`, `recolorBack`, `rect`, `round`, `separatorObj`, `stacks`, `tempPic`, `unitPic`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_IsSpawned`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `set_IsSpawned`/1 | `Awake`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 2 | `get_deathAnimTime`/0 | `bejy`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 3 | `set_deathAnimTime`/1 | `bejz`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 4 | `add_returnView`/1 | `beka`/0 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 5 | `remove_returnView`/1 | `bekb`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 6 | `Awake`/0 | `bekc`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 7 | `OnDestroy`/0 | `bekd`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 8 | `Init`/2 | `beke`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 9 | `SetRound`/1 | `bekf`/2 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 10 | `MoveTo`/2 | `bekg`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 11 | `Init`/0 | `bekh`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 12 | `EnableView`/1 | `beki`/2 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 13 | `Release`/0 | `bekj`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 14 | `UpdateView`/3 | `bekk`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 15 | `UpdateStacks`/2 | `bekl`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 16 | `SelectAnim`/0 | `bekm`/2 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 17 | `DeselectAnim`/0 | `bekn`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 18 | `DeathAnim`/0 | `beko`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 19 | `OnClick`/1 | `bekp`/2 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 20 | `OnHover`/0 | `bekq`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 21 | `OnExit`/0 | `Init`/2 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 22 | `SetIndicator`/2 | `Init`/0 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 23 | `ClearView`/0 | `OnClick`/1 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 24 | `ShowSeparator`/0 | `OnDestroy`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 25 | `Show`/0 | `OnExit`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 26 | `SetStateSize`/2 | `OnHover`/0 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 27 | `SetInteractable`/1 | `OnPointerClick`/1 | candidate | same declaration ordinal; same parameter count; same public flag |

### `Hex.Session.Battle.BhUnitAbilityView` -> `Hex.Session.Battle.BhUnitAbilityView`

Exact method-name survivals: `.ctor`, `Awake`, `OnClicked`, `OnEnter`, `OnExit`

Exact field-name survivals: `controlsView`, `viewBase`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_ViewBase`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `get_Ability`/0 | `Awake`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 2 | `Awake`/0 | `bekw`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 3 | `ClearView`/0 | `bekx`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 4 | `SetView`/2 | `beky`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 5 | `TryToPlayUnCdAnim`/0 | `bekz`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 6 | `Contains`/1 | `bela`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 7 | `SetSelected`/1 | `belb`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 8 | `UpdateSkill`/0 | `belc`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 9 | `CanUpdateSkill`/0 | `beld`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 10 | `SetClickable`/1 | `bele`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 11 | `CanUseHotKey`/0 | `belf`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 12 | `OnClicked`/0 | `belg`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 13 | `OnEnter`/0 | `OnClicked`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 14 | `OnExit`/0 | `OnEnter`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 15 | `CheckIfArmed`/0 | `OnExit`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 16 | `CheckIfChargesAvailable`/1 | `-` | missing-side | method exists on only one side at this ordinal |
| 17 | `.ctor`/0 | `-` | missing-side | method exists on only one side at this ordinal |

### `Hex.Session.Battle.BhUnitControlsView` -> `Hex.Session.Battle.BhUnitControlsView`

Exact method-name survivals: `.ctor`, `Clear`, `Init`

Exact field-name survivals: `abilities`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `Init`/1 | `.ctor`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 1 | `Clear`/0 | `beln`/3 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 2 | `SetSkills`/3 | `belo`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 3 | `OnSkillClicked`/1 | `belp`/1 | candidate | same declaration ordinal; same parameter count; same static flag |
| 4 | `SendCmdSelectSkill`/1 | `belq`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 5 | `SendCmdDeselectSelectedSkill`/0 | `belr`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 6 | `ActivateSkill`/2 | `bels`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 7 | `SelectAbility`/1 | `belt`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 8 | `UpdateSkill`/2 | `belu`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 9 | `UnitGotBuff`/2 | `belv`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 10 | `TryUpdateSkill`/1 | `belw`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 11 | `TryToUnCdAbility`/2 | `belx`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 12 | `ResetSelectedAbility`/0 | `bely`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 13 | `SetAbilitiesClickable`/1 | `belz`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 14 | `TryAddUIAbilitiesForUnitAbilities`/1 | `bema`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 15 | `UpdateUIAbilities`/1 | `bemb`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 16 | `OnResetSelectedAbility`/2 | `bemc`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 17 | `OnSkillsClickabilityChanged`/2 | `bemd`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 18 | `OnHotkeyClickAbility`/2 | `beme`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 19 | `OnSideEnergyChanged`/2 | `bemf`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 20 | `.ctor`/0 | `Clear`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 21 | `-` | `Init`/1 | missing-side | method exists on only one side at this ordinal |

### `Hex.Session.World.Minimap` -> `Hex.Session.World.Minimap`

Exact method-name survivals: `.ctor`

Exact field-name survivals: none

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `.ctor`/1 | `.ctor`/1 | strong-static | same declaration ordinal; same parameter count; same public flag |
| 1 | `Update`/0 | `bhmz`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 2 | `AddObject`/1 | `bhna`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 3 | `RemoveObject`/1 | `bhnb`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 4 | `RemoveAllObjects`/0 | `bhnc`/2 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 5 | `SetSizeOnCanvas`/1 | `bhnd`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 6 | `get_MinimapTexture`/0 | `bhne`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 7 | `-` | `bhnf`/1 | missing-side | method exists on only one side at this ordinal |
| 8 | `-` | `bhng`/1 | missing-side | method exists on only one side at this ordinal |
| 9 | `-` | `bhnh`/0 | missing-side | method exists on only one side at this ordinal |
| 10 | `-` | `bhni`/1 | missing-side | method exists on only one side at this ordinal |
| 11 | `-` | `bhnj`/0 | missing-side | method exists on only one side at this ordinal |
| 12 | `-` | `bhnk`/0 | missing-side | method exists on only one side at this ordinal |
| 13 | `-` | `bhnl`/0 | missing-side | method exists on only one side at this ordinal |
| 14 | `-` | `bhnm`/1 | missing-side | method exists on only one side at this ordinal |
| 15 | `-` | `bhnn`/1 | missing-side | method exists on only one side at this ordinal |
| 16 | `-` | `bhno`/1 | missing-side | method exists on only one side at this ordinal |

### `Hex.Session.World.SoMinimapConfig` -> `Hex.Session.World.SoMinimapConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `bioms`, `cameraFrustumColor`, `cameraFrustumWidth`, `cliffsTexture`, `fogOfWarTexture`, `fogOfWarTextureScale`, `fogOfWarTextureUnderground`, `iconOutlineTexture`, `iconTexture`, `icons`, `iconsByObjectType`, `iconsSize`, `maxIconScaleFactor`, `minIconScaleFactor`, `neutralColor`, `obstaclesColor`, `overlayTexture`, `roadColor`, `roadTiles`, `sheetSize`, `shoreNoiseScale`, `shoreNoiseStrength`, `shoreNoiseTexture`, `shoreTexture`, `shoreWidth`, `smoothing`, `waterTexture`, `waterTextureScale`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `GetIcon`/1 | `.ctor`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 1 | `GetSpritesheet`/0 | `bich`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 2 | `BuildIconsDictionary`/0 | `bici`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 3 | `.ctor`/0 | `bicj`/0 | candidate | same declaration ordinal; same parameter count; same static flag |

### `Hex.ResManager` -> `Hex.ResManager`

Exact method-name survivals: `.ctor`, `Awake`, `Load`

Exact field-name survivals: `rootPath`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_me`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `Awake`/0 | `Awake`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |
| 2 | `Instance`/0 | `bmvg`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 3 | `get_resFilesDictionary`/0 | `bmvh`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 4 | `set_resFilesDictionary`/1 | `bmvi`/0 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 5 | `Load`/1 | `bmvj`/1 | candidate | same declaration ordinal; same parameter count; same virtual flag |
| 6 | `LoadFromBundle`/1 | `bmvk`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 7 | `LoadAsync`/1 | `bmvl`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 8 | `LoadBundleAsync`/1 | `bmvm`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 9 | `LoadInCoroutine`/1 | `bmvn`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 10 | `Get`/1 | `bmvo`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 11 | `GetAsset`/1 | `bmvp`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 12 | `GetAssetFromBundle`/1 | `bmvq`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 13 | `GetAll`/2 | `bmvr`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 14 | `GetAllAssetsFromRes`/1 | `bmvs`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 15 | `GetAllAssetsFromBundle`/1 | `bmvt`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 16 | `GetAllFiles`/2 | `bmvu`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 17 | `GetFilesFromBundle`/1 | `bmvv`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 18 | `GetFilesFromResources`/1 | `bmvw`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 19 | `RemoveBundle`/1 | `bmvx`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 20 | `OnLoad`/1 | `bmvy`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 21 | `OnUnload`/1 | `bmvz`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 22 | `Listen`/1 | `bmwa`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 23 | `Unlisten`/1 | `bmwb`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 24 | `.ctor`/0 | `Load`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |

### `Hex.Sound.MixerConfig` -> `Hex.Sound.MixerConfig`

Exact method-name survivals: `.ctor`, `Refresh`

Exact field-name survivals: `excludedGroups`, `mixerGroups`, `mixerName`, `output`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_MixerName`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `set_MixerName`/1 | `bmnn`/0 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 2 | `get_Output`/0 | `bmno`/1 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 3 | `set_Output`/1 | `bmnp`/0 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 4 | `get_MixerGroups`/0 | `bmnq`/1 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 5 | `get_dirty`/0 | `bmnr`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 6 | `.ctor`/0 | `bmns`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 7 | `Refresh`/1 | `bmnt`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 8 | `CancelDirty`/0 | `bmnu`/1 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 9 | `CheckExcluded`/1 | `Refresh`/1 | candidate | same declaration ordinal; same parameter count; same static flag |
| 10 | `.cctor`/0 | `-` | missing-side | method exists on only one side at this ordinal |

### `Hex.Sound.MixerGroupConfig` -> `Hex.Sound.MixerGroupConfig`

Exact method-name survivals: `.ctor`, `Refresh`

Exact field-name survivals: `groupName`, `index`, `mixerName`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_GroupName`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `set_GroupName`/1 | `bmnv`/0 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 2 | `get_MixerName`/0 | `bmnw`/1 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 3 | `set_MixerName`/1 | `bmnx`/0 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 4 | `get_Index`/0 | `bmny`/1 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 5 | `set_Index`/1 | `bmnz`/0 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 6 | `get_dirty`/0 | `bmoa`/1 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 7 | `Refresh`/2 | `bmob`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 8 | `CancelDirty`/0 | `bmoc`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 9 | `.ctor`/0 | `Refresh`/2 | candidate | same declaration ordinal; parameter count differs; same public flag |

### `Hex.Sound.MixersConfig` -> `Hex.Sound.MixersConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `assetPath`, `mixers`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `.ctor`/0 | `.ctor`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |

### `Hex.Sound.SoundClipConfig` -> `Hex.Sound.SoundClipConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `active`, `activeRandomPitch`, `assetName`, `assetPath`, `guid`, `pitch`, `randomPitchMaxValue`, `randomPitchMinValue`, `volumeInDb`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_GUID`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `set_GUID`/1 | `bmod`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 2 | `get_AssetName`/0 | `bmoe`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 3 | `set_AssetName`/1 | `bmof`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 4 | `get_AssetPath`/0 | `bmog`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 5 | `set_AssetPath`/1 | `bmoh`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 6 | `get_VolumeInDb`/0 | `bmoi`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 7 | `get_Volume`/0 | `bmoj`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 8 | `get_Active`/0 | `bmok`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 9 | `get_Pitch`/0 | `bmol`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 10 | `get_ActiveRandomPitch`/0 | `bmom`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 11 | `get_RandomPitchMinValue`/0 | `bmon`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 12 | `get_RandomPitchMaxValue`/0 | `bmoo`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 13 | `get_dirty`/0 | `bmop`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 14 | `set_dirty`/1 | `bmoq`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 15 | `.ctor`/0 | `bmor`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |

### `Hex.Sound.SoundGroupConfig` -> `Hex.Sound.SoundGroupConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `assetName`, `audioMixerGroup`, `bundleName`, `dirty`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_AssetName`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `set_AssetName`/1 | `bmos`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 2 | `get_BundleName`/0 | `bmot`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 3 | `set_BundleName`/1 | `bmou`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 4 | `get_AudioMixerGroup`/0 | `bmov`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 5 | `.ctor`/0 | `bmow`/0 | candidate | same declaration ordinal; same parameter count; same public flag |

### `Hex.Sound.SoundSetConfig` -> `Hex.Sound.SoundSetConfig`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `activeFadeCurves`, `activeRandomPitch`, `assetName`, `assetPath`, `audioMixerGroup`, `delayBetweenPlaybacks`, `dirty`, `fadeInTime`, `fadeInVolumeCurve`, `fadeOutTime`, `fadeOutVolumeCurve`, `overrideAudioMixerGroup`, `playbacksCountWithoutRepeats`, `randomPitchMaxValue`, `randomPitchMinValue`, `soundClipsConfigs`, `tempSoundClipsConfigs`, `volumeInDb`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_AssetPath`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `set_AssetPath`/1 | `bmox`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 2 | `get_AssetName`/0 | `bmoy`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 3 | `set_AssetName`/1 | `bmoz`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 4 | `get_OverrideAudioMixerGroup`/0 | `bmpa`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 5 | `get_AudioMixerGroup`/0 | `bmpb`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 6 | `get_Volume`/0 | `bmpc`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 7 | `get_PlaybacksCountWithoutRepeats`/0 | `bmpd`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 8 | `get_DelayBetweenPlaybacks`/0 | `bmpe`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 9 | `get_ActiveFadeCurves`/0 | `bmpf`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 10 | `get_FadeInTime`/0 | `bmpg`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 11 | `get_FadeInVolumeCurve`/0 | `bmph`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 12 | `get_FadeOutTime`/0 | `bmpi`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 13 | `get_FadeOutVolumeCurve`/0 | `bmpj`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 14 | `get_ActiveRandomPitch`/0 | `bmpk`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 15 | `get_RandomPitchMinValue`/0 | `bmpl`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 16 | `get_RandomPitchMaxValue`/0 | `bmpm`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 17 | `get_SoundClipsConfigs`/0 | `bmpn`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 18 | `get_ActiveClipsCount`/0 | `bmpo`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 19 | `get_ActiveClipsBitMask`/0 | `bmpp`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 20 | `get_MaxPlaybacksCountWithoutRepeats`/0 | `bmpq`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 21 | `.ctor`/0 | `bmpr`/0 | candidate | same declaration ordinal; same parameter count; same public flag |

### `Hex.Sound.SoundMixersManager` -> `Hex.Sound.SoundMixersManager`

Exact method-name survivals: `.ctor`, `Awake`

Exact field-name survivals: `fadeToMuteVolume`, `fadeToReturnVolume`, `mainMixer`, `mixers`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `Awake`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 1 | `Process`/0 | `Awake`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 2 | `OnFocusChanged`/1 | `bmsj`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 3 | `Mute`/0 | `bmsk`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 4 | `Return`/0 | `bmsl`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 5 | `SetVolume`/2 | `bmsm`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 6 | `SetVolumeInMixerGroup`/3 | `bmsn`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 7 | `GetVolumeInMixerGroup`/2 | `bmso`/2 | candidate | same declaration ordinal; same parameter count; same public flag |
| 8 | `GetAudioGroup`/1 | `bmsp`/3 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 9 | `GetMixerByGroup`/1 | `bmsq`/2 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 10 | `ChangeSnapshot`/3 | `bmsr`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 11 | `.ctor`/0 | `bmss`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 12 | `-` | `bmst`/3 | missing-side | method exists on only one side at this ordinal |

### `Hex.Sound.SoSoundSettings` -> `Hex.Sound.SoSoundSettings`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `soundSettings`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `.ctor`/0 | `.ctor`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |

### `Hex.Sound.SoundSettings` -> `Hex.Sound.SoundSettings`

Exact method-name survivals: `.ctor`

Exact field-name survivals: `fadeOutCurve`, `loop`, `loopOnlyOneClip`, `maxDelayBetweenLoops`, `maxDistance`, `minDelayBetweenLoops`, `pan`, `panCurve`, `playbackStartPosition`, `rollOffDecayCurve`, `spatial`, `spreadCurve`, `volume`, `worldPosition`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `.ctor`/14 | `.ctor`/14 | strong-static | same declaration ordinal; same parameter count; same public flag |
| 1 | `Clone`/0 | `bmtr`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 2 | `CreateDefault`/0 | `bmts`/0 | candidate | same declaration ordinal; same parameter count; same public flag |

### `Hex.Sound.SoundsManager` -> `Hex.Sound.SoundsManager`

Exact method-name survivals: `.ctor`, `Awake`, `Init`, `OnApplicationFocus`, `Update`

Exact field-name survivals: `globalAudioListener`, `mixersManager`, `soundSourcesPool`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_Instance`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `Awake`/0 | `Awake`/0 | strong-static | same declaration ordinal; same parameter count; same public flag |
| 2 | `get_MixersManager`/0 | `bmtt`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 3 | `get_SoundSourcesPool`/0 | `bmtu`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 4 | `get_GlobalAudioListener`/0 | `bmtv`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 5 | `get_GroupsData`/0 | `bmtw`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 6 | `Init`/0 | `bmtx`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 7 | `Update`/0 | `Init`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 8 | `OnApplicationFocus`/1 | `OnApplicationFocus`/1 | strong-static | same declaration ordinal; same parameter count; same public flag |
| 9 | `.ctor`/0 | `Update`/0 | candidate | same declaration ordinal; same parameter count; same static flag |

### `Hex.Sound.SoundSource` -> `Hex.Sound.SoundSource`

Exact method-name survivals: `.ctor`, `Play`, `Stop`

Exact field-name survivals: `OnCompletePlayback`, `audioSource`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `get_playStatus`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 1 | `Play`/3 | `bmty`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 2 | `Stop`/0 | `bmtz`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 3 | `SetVolume`/1 | `bmua`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 4 | `SetPan`/1 | `bmub`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 5 | `Pause`/0 | `bmuc`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 6 | `Unpause`/0 | `bmud`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 7 | `Process`/0 | `bmue`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 8 | `SetPosition`/1 | `bmuf`/0 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 9 | `StopSource`/0 | `bmug`/0 | candidate | same declaration ordinal; same parameter count; same public flag |
| 10 | `PauseSource`/0 | `bmuh`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 11 | `ProcessPlayingState`/1 | `bmui`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 12 | `ProcessReleaseState`/1 | `bmuj`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 13 | `ProcessClipsPlaying`/1 | `bmuk`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 14 | `ProcessVolumeChange`/1 | `bmul`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 15 | `OnVolumeFadeIn`/1 | `bmum`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 16 | `OnVolumeFadeOut`/1 | `bmun`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 17 | `ProcessPanChange`/1 | `bmuo`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 18 | `OnPanFadeIn`/1 | `bmup`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 19 | `OnPanFadeOut`/1 | `bmuq`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 20 | `OnStartPlayingClip`/1 | `bmur`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 21 | `OnPlayingClip`/1 | `bmus`/1 | candidate | same declaration ordinal; same parameter count; same public flag |
| 22 | `OnStopPlayingClip`/1 | `bmut`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 23 | `IsAudioClipPlaybackCompleted`/0 | `bmuu`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 24 | `OnUnpauseClip`/1 | `bmuv`/2 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 25 | `RollValueBetween`/2 | `Play`/3 | candidate | same declaration ordinal; parameter count differs; same static flag |
| 26 | `.ctor`/0 | `Stop`/0 | candidate | same declaration ordinal; same parameter count; same public flag |

### `Hex.Sound.SoundSourcesPool` -> `Hex.Sound.SoundSourcesPool`

Exact method-name survivals: `.ctor`, `Awake`

Exact field-name survivals: `currentCount`, `sourcesList`

Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.

| Ordinal | Mono member | Current deobf member | Confidence | Reasons |
|---:|---|---|---|---|
| 0 | `Awake`/0 | `.ctor`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 1 | `Pop`/0 | `Awake`/0 | candidate | same declaration ordinal; same parameter count; same static flag |
| 2 | `Push`/1 | `bmuw`/0 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 3 | `Process`/0 | `bmux`/1 | candidate | same declaration ordinal; parameter count differs; same public flag |
| 4 | `.ctor`/0 | `bmuy`/0 | candidate | same declaration ordinal; same parameter count; same public flag |


## Strong static matches sample

| Mono type | Best current deobf candidate | Confidence | Score | Key reasons |
|---|---|---|---:|---|
| `System.Runtime.CompilerServices.IsReadOnlyAttribute` | `System.Runtime.CompilerServices.IsReadOnlyAttribute` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `CameraShake` | `CameraShake` | strong-static | 108.2 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.14 |
| `ShakeSettings` | `ShakeSettings` | strong-static | 106.56 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.11 |
| `SoShakeSettings` | `SoShakeSettings` | strong-static | 108.14 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.14 |
| `AttackPatternElement` | `AttackPatternElement` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `ESelectionAreaType` | `ESelectionAreaType` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `ETargetCondition` | `ETargetCondition` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `ESideCastType` | `ESideCastType` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `EHeroStatLimitType` | `EHeroStatLimitType` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `BhConnectCircle` | `BhConnectCircle` | strong-static | 111.76 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.33 |
| `PointerInputModule` | `PointerInputModule` | strong-static | 111.75 | exact full type name; namespace/name token overlap 1.00; public-method overlap 1.00 |
| `VirtualInputModule` | `VirtualInputModule` | strong-static | 103.74 | exact full type name; namespace/name token overlap 1.00; public-method overlap 0.12 |
| `BhTournamentRules` | `BhTournamentRules` | strong-static | 110.45 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.33 |
| `BhSoftMaskedUI` | `BhSoftMaskedUI` | strong-static | 118.41 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.32 |
| `BhBookCanvasRaycaster` | `BhBookCanvasRaycaster` | strong-static | 116.33 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.33 |
| `LayerAttribute` | `LayerAttribute` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `SkeletonsStressTest` | `SkeletonsStressTest` | strong-static | 126.2 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.60 |
| `MeshBufferTest` | `MeshBufferTest` | strong-static | 126.2 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.60 |
| `MeshCombineTest` | `MeshCombineTest` | strong-static | 116.14 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.14 |
| `BhArenaObstructionsManager` | `BhArenaObstructionsManager` | strong-static | 103.69 | exact full type name; namespace/name token overlap 1.00; public-method overlap 0.14 |
| `ObstructionInstanceConfig` | `ObstructionInstanceConfig` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `ObstructionSetConfig` | `ObstructionSetConfig` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `HeroAbilityID` | `HeroAbilityID` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `KeyValuePairGeneric`2` | `KeyValuePairGeneric`2` | strong-static | 83.0 | exact full type name; namespace/name token overlap 1.00; param-count histogram similarity 0.00 |
| `SerializableDictionary`2` | `SerializableDictionary`2` | strong-static | 117.67 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.67 |
| `BhDayPanelLighting` | `BhDayPanelLighting` | strong-static | 101.33 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.17 |
| `BhSideHeroesViewController` | `BhSideHeroesViewController` | strong-static | 108.5 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.25 |
| `BhSideHerosArrowsViewController` | `BhSideHerosArrowsViewController` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `SideScrollElemenets` | `SideScrollElemenets` | strong-static | 104.95 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.19 |
| `BhHeroLoader` | `BhHeroLoader` | strong-static | 97.04 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.27 |
| `PerlinLayerInfo` | `PerlinLayerInfo` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `ScContactInfo` | `ScContactInfo` | strong-static | 104.0 | exact full type name; namespace/name token overlap 1.00; public-method overlap 0.20 |
| `BhUnitTest` | `BhUnitTest` | strong-static | 118.5 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.25 |
| `PolymorphicMessagePack.PolymorphicAttribute` | `PolymorphicMessagePack.PolymorphicAttribute` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `PolymorphicMessagePack.PolymorphicMessagePackSerializerOptions` | `PolymorphicMessagePack.PolymorphicMessagePackSerializerOptions` | strong-static | 128.33 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `UnityEngine.Experimental.Rendering.SRPBatcherProfiler` | `UnityEngine.Experimental.Rendering.SRPBatcherProfiler` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Code.Network.AnalyticsCollector` | `Code.Network.AnalyticsCollector` | strong-static | 105.17 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.15 |
| `Code.Network.EReplayState` | `Code.Network.EReplayState` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Code.Network.ILobbyService` | `Code.Network.ILobbyService` | strong-static | 94.43 | exact full type name; namespace/name token overlap 1.00; param-count histogram similarity 0.57 |
| `Code.Network.Map` | `Code.Network.Map` | strong-static | 110.35 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.31 |
| `Code.Network.MapId` | `Code.Network.MapId` | strong-static | 109.01 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.25 |
| `Code.Network.MetricsCollector` | `Code.Network.MetricsCollector` | strong-static | 107.17 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.19 |
| `Code.Network.PlayerId` | `Code.Network.PlayerId` | strong-static | 108.35 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.23 |
| `Code.Network.SendType` | `Code.Network.SendType` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Code.Network.Steam.AuthTicketWebApiException` | `Code.Network.Steam.AuthTicketWebApiException` | strong-static | 108.67 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.33 |
| `Code.Network.Hex.GameId` | `Code.Network.Hex.GameId` | strong-static | 109.01 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.25 |
| `Code.Network.Hex.Profile.ProfileData` | `Code.Network.Hex.Profile.ProfileData` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Code.Network.Exceptions.GameAlreadyAcceptedException` | `Code.Network.Exceptions.GameAlreadyAcceptedException` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Code.Network.Exceptions.GameNotFoundException` | `Code.Network.Exceptions.GameNotFoundException` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Code.Network.Exceptions.LobbyNotFoundException` | `Code.Network.Exceptions.LobbyNotFoundException` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Code.Network.Exceptions.WrongPasswordException` | `Code.Network.Exceptions.WrongPasswordException` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Code.Network.Epic.Messages.Ack` | `Code.Network.Epic.Messages.Ack` | strong-static | 112.67 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.67 |
| `Code.Network.Epic.Messages.EChannel` | `Code.Network.Epic.Messages.EChannel` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Code.Network.Epic.Connections.ConnectionId` | `Code.Network.Epic.Connections.ConnectionId` | strong-static | 112.49 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.40 |
| `Hex.BhArenaLine` | `Hex.BhArenaLine` | strong-static | 117.33 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.50 |
| `Hex.BhArenaLineItem` | `Hex.BhArenaLineItem` | strong-static | 114.43 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.43 |
| `Hex.BhUiBuff` | `Hex.BhUiBuff` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.BhWorldCamera` | `Hex.BhWorldCamera` | strong-static | 99.18 | exact full type name; namespace/name token overlap 1.00; param-count histogram similarity 0.94 |
| `Hex.MovementSettings` | `Hex.MovementSettings` | strong-static | 133.75 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.ZoomSettings` | `Hex.ZoomSettings` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.CameraShakeOld` | `Hex.CameraShakeOld` | strong-static | 117.33 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.50 |
| `Hex.CameraZoom` | `Hex.CameraZoom` | strong-static | 106.69 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.11 |
| `Hex.BhCameraAnimationController` | `Hex.BhCameraAnimationController` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.EConditionsLogic` | `Hex.EConditionsLogic` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.FontContent` | `Hex.FontContent` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.FontData` | `Hex.FontData` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.ESpawnType` | `Hex.ESpawnType` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.ESpawnPointType` | `Hex.ESpawnPointType` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.MapDataMiscSpawn` | `Hex.MapDataMiscSpawn` | strong-static | 134.55 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.EMapGameMode` | `Hex.EMapGameMode` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.BhHierarchyGroup` | `Hex.BhHierarchyGroup` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.BhTopDropDownMenu` | `Hex.BhTopDropDownMenu` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.Neighbourhood` | `Hex.Neighbourhood` | strong-static | 105.17 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.25 |
| `Hex.EPlay` | `Hex.EPlay` | strong-static | 130.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.IntChancePair` | `Hex.IntChancePair` | strong-static | 135.0 | exact full type name; namespace/name token overlap 1.00; method-name overlap 1.00 |
| `Hex.JsonDateTime` | `Hex.JsonDateTime` | strong-static | 109.4 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.20 |
| `Hex.NeighboursPattern` | `Hex.NeighboursPattern` | strong-static | 110.73 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.20 |
| `Hex.BhFactionDetails` | `Hex.BhFactionDetails` | strong-static | 113.67 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.33 |
| `Hex.BhFactionSelectButton` | `Hex.BhFactionSelectButton` | strong-static | 111.36 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.25 |
| `Hex.BhHeroSelectButton` | `Hex.BhHeroSelectButton` | strong-static | 111.36 | exact full type name; namespace/name token overlap 1.00; method-name overlap 0.25 |

## Probable static matches sample

| Mono type | Best current deobf candidate | Confidence | Score | Key reasons |
|---|---|---|---:|---|
| `Code.Network.InitializeOnGameLoad` | `Code.Initialization.InitializeOnGameLoad` | probable-static | 80.86 | exact simple type name; namespace/name token overlap 0.71; method-name overlap 0.50 |
| `Hex.BhMagicPreviewItem` | `Hex.Arena.View.UI.BhMagicPreviewItem` | probable-static | 105.15 | exact simple type name; Hex namespace migration candidate: Hex -> Hex.Arena.View.UI; namespace/name token overlap 0.62 |
| `Hex.BhEditorSpawnColors` | `Hex.MapEditor.BhEditorSpawnColors` | probable-static | 96.67 | exact simple type name; Hex namespace migration candidate: Hex -> Hex.MapEditor; namespace/name token overlap 0.83 |
| `Hex.BhMagicRangSelector` | `Hex.Session.UI.BhMagicRangSelector` | probable-static | 98.95 | exact simple type name; Hex namespace migration candidate: Hex -> Hex.Session.UI; namespace/name token overlap 0.71 |
| `Hex.BhMagicSelectorsGroup` | `Hex.Session.UI.BhMagicSelectorsGroup` | probable-static | 87.43 | exact simple type name; Hex namespace migration candidate: Hex -> Hex.Session.UI; namespace/name token overlap 0.71 |
| `Hex.BhBlockSubClass` | `Hex.UI.BhBlockSubClass` | probable-static | 81.04 | exact simple type name; Hex namespace migration candidate: Hex -> Hex.UI; namespace/name token overlap 0.83 |
| `Hex.BhTooltipsSubClass` | `Hex.UI.Tooltips.BhTooltipsSubClass` | probable-static | 67.51 | exact simple type name; Hex namespace migration candidate: Hex -> Hex.UI.Tooltips; namespace/name token overlap 0.83 |
| `Hex.SharedLibrary.Commands.CmdLobbyChangeAttribute` | `Hex.SharedLibrary.Commands.Lobby.CmdLobbyChangeAttribute` | probable-static | 113.5 | exact simple type name; Hex namespace migration candidate: Hex.SharedLibrary.Commands -> Hex.SharedLibrary.Commands.Lobby; namespace/name token overlap 1.00 |
| `Hex.StoryHub.Act` | `Hex.StoryHub.DB.Config.Act` | probable-static | 70.67 | exact simple type name; Hex namespace migration candidate: Hex.StoryHub -> Hex.StoryHub.DB.Config; namespace/name token overlap 0.67 |
| `Hex.StoryHub.Mission` | `Hex.StoryHub.DB.Config.Mission` | probable-static | 70.96 | exact simple type name; Hex namespace migration candidate: Hex.StoryHub -> Hex.StoryHub.DB.Config; namespace/name token overlap 0.67 |
| `Hex.StoryHub.MissionVariant` | `Hex.StoryHub.DB.Config.MissionVariant` | probable-static | 73.09 | exact simple type name; Hex namespace migration candidate: Hex.StoryHub -> Hex.StoryHub.DB.Config; namespace/name token overlap 0.71 |
| `Hex.StoryHub.StoryHubAction` | `Hex.StoryHub.Data.StoryHubAction` | probable-static | 72.13 | exact simple type name; Hex namespace migration candidate: Hex.StoryHub -> Hex.StoryHub.Data; namespace/name token overlap 0.80 |
| `Hex.StoryHub.View.Node` | `Hex.StoryHub.Data.Node` | probable-static | 64.6 | exact simple type name; Hex namespace migration candidate: Hex.StoryHub.View -> Hex.StoryHub.Data; namespace/name token overlap 0.67 |
| `Hex.StoryHub.Profiles.Profile` | `Hex.StoryHub.Profiles.Data.Profile` | probable-static | 74.63 | exact simple type name; Hex namespace migration candidate: Hex.StoryHub.Profiles -> Hex.StoryHub.Profiles.Data; namespace/name token overlap 0.83 |
| `Hex.StoryHub.Logic.Counter` | `Hex.StoryHub.DB.Config.Counter` | probable-static | 65.07 | exact simple type name; Hex namespace migration candidate: Hex.StoryHub.Logic -> Hex.StoryHub.DB.Config; namespace/name token overlap 0.57 |
| `Hex.Storage.FileInfo` | `Hex.Files.FileInfo` | probable-static | 60.37 | exact simple type name; Hex namespace migration candidate: Hex.Storage -> Hex.Files; namespace/name token overlap 0.60 |
| `Hex.Storage.FolderInfo` | `Hex.Files.FolderInfo` | probable-static | 58.8 | exact simple type name; Hex namespace migration candidate: Hex.Storage -> Hex.Files; namespace/name token overlap 0.60 |
| `Hex.Statistics.ArenaInfo` | `Hex.Configs.ArenaInfo` | probable-static | 68.8 | exact simple type name; Hex namespace migration candidate: Hex.Statistics -> Hex.Configs; namespace/name token overlap 0.60 |
| `Hex.GameHub.Lobby.Events` | `Hex.GameHub.NetHub.Events` | probable-static | 112.65 | exact simple type name; Hex namespace migration candidate: Hex.GameHub.Lobby -> Hex.GameHub.NetHub; namespace/name token overlap 0.67 |
| `Hex.GameHub.Lobby.TimerValidator` | `Hex.SharedLibrary.Models.Lobby.TimerValidator` | probable-static | 111.0 | exact simple type name; Hex namespace migration candidate: Hex.GameHub.Lobby -> Hex.SharedLibrary.Models.Lobby; namespace/name token overlap 0.44 |
| `Hex.GameHub.Lobby.Logic.Slots` | `Hex.SharedLibrary.Models.Lobby.Slots` | probable-static | 64.02 | exact simple type name; Hex namespace migration candidate: Hex.GameHub.Lobby.Logic -> Hex.SharedLibrary.Models.Lobby; param-count histogram similarity 0.59 |
| `Hex.GameHub.Lobby.Data.Data` | `Hex.Session.Quests2.Data.Data` | probable-static | 63.16 | exact simple type name; Hex namespace migration candidate: Hex.GameHub.Lobby.Data -> Hex.Session.Quests2.Data; method-name overlap 0.14 |
| `Hex.Dialogs.Logic.EAction` | `Hex.QuestScript.EAction` | probable-static | 98.0 | exact simple type name; Hex namespace migration candidate: Hex.Dialogs.Logic -> Hex.QuestScript; method-name overlap 1.00 |
| `Hex.Configs.BuildingConfig` | `Hex.Dead.BuildingConfig` | probable-static | 88.2 | exact simple type name; Hex namespace migration candidate: Hex.Configs -> Hex.Dead; namespace/name token overlap 0.60 |
| `Hex.Session.ETimeType` | `Hex.SharedLibrary.Models.Lobby.ETimeType` | probable-static | 104.75 | exact simple type name; Hex namespace migration candidate: Hex.Session -> Hex.SharedLibrary.Models.Lobby; namespace/name token overlap 0.38 |
| `Hex.Session.ETimerGroup` | `Hex.SharedLibrary.Models.Lobby.ETimerGroup` | probable-static | 104.75 | exact simple type name; Hex namespace migration candidate: Hex.Session -> Hex.SharedLibrary.Models.Lobby; namespace/name token overlap 0.38 |
| `Hex.Session.SideTimerSettings` | `Hex.SharedLibrary.Models.Lobby.SideTimerSettings` | probable-static | 58.76 | exact simple type name; Hex namespace migration candidate: Hex.Session -> Hex.SharedLibrary.Models.Lobby; namespace/name token overlap 0.44 |
| `Hex.Session.Quests2.Logic.Counter` | `Hex.Session.Quests2.Data.Counter` | probable-static | 65.65 | exact simple type name; Hex namespace migration candidate: Hex.Session.Quests2.Logic -> Hex.Session.Quests2.Data; namespace/name token overlap 0.67 |
| `Hex.Session.Quests2.Logic.Interruption` | `Hex.Session.Quests2.Data.Interruption` | probable-static | 69.89 | exact simple type name; Hex namespace migration candidate: Hex.Session.Quests2.Logic -> Hex.Session.Quests2.Data; namespace/name token overlap 0.67 |
| `Hex.Session.Quests2.Logic.Quest` | `Hex.Session.Quests2.Data.Quest` | probable-static | 63.44 | exact simple type name; Hex namespace migration candidate: Hex.Session.Quests2.Logic -> Hex.Session.Quests2.Data; namespace/name token overlap 0.67 |
| `Hex.Session.Quests2.Logic.SubQuestGroup` | `Hex.QuestScript.SubQuestGroup` | probable-static | 71.33 | exact simple type name; Hex namespace migration candidate: Hex.Session.Quests2.Logic -> Hex.QuestScript; namespace/name token overlap 0.50 |
| `Hex.Session.Quests2.Logic.Trigger` | `Hex.Session.Quests2.Data.Trigger` | probable-static | 69.41 | exact simple type name; Hex namespace migration candidate: Hex.Session.Quests2.Logic -> Hex.Session.Quests2.Data; namespace/name token overlap 0.67 |
| `Hex.Session.Logic.PickedBonuses` | `Hex.Session.Data.PickedBonuses` | probable-static | 80.9 | exact simple type name; Hex namespace migration candidate: Hex.Session.Logic -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.Logic.Buffs` | `Hex.Session.Data.Buffs` | probable-static | 61.15 | exact simple type name; Hex namespace migration candidate: Hex.Session.Logic -> Hex.Session.Data; namespace/name token overlap 0.60 |
| `Hex.Session.Logic.HeroSpecialization` | `Hex.Session.Data.HeroSpecialization` | probable-static | 66.52 | exact simple type name; Hex namespace migration candidate: Hex.Session.Logic -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.Logic.HeroSubClass` | `Hex.Session.Data.HeroSubClass` | probable-static | 67.29 | exact simple type name; Hex namespace migration candidate: Hex.Session.Logic -> Hex.Session.Data; namespace/name token overlap 0.71 |
| `Hex.Session.Logic.SubClassActivationCondition` | `Hex.Configs.SubClassActivationCondition` | probable-static | 65.78 | exact simple type name; Hex namespace migration candidate: Hex.Session.Logic -> Hex.Configs; namespace/name token overlap 0.62 |
| `Hex.Session.Logic.HeroSubClasses` | `Hex.Session.Data.HeroSubClasses` | probable-static | 74.52 | exact simple type name; Hex namespace migration candidate: Hex.Session.Logic -> Hex.Session.Data; namespace/name token overlap 0.71 |
| `Hex.Session.Logic.SkillRollChance` | `Hex.Configs.SkillRollChance` | probable-static | 70.02 | exact simple type name; Hex namespace migration candidate: Hex.Session.Logic -> Hex.Configs; namespace/name token overlap 0.57 |
| `Hex.Session.Logic.HeroMagics` | `Hex.Session.Data.HeroMagics` | probable-static | 64.51 | exact simple type name; Hex namespace migration candidate: Hex.Session.Logic -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.Logic.HeroSkill` | `Hex.Session.Data.HeroSkill` | probable-static | 68.6 | exact simple type name; Hex namespace migration candidate: Hex.Session.Logic -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.Logic.HeroSkills` | `Hex.Session.Data.HeroSkills` | probable-static | 72.0 | exact simple type name; Hex namespace migration candidate: Hex.Session.Logic -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.Logic.HeroSubSkill` | `Hex.Session.Data.HeroSubSkill` | probable-static | 69.52 | exact simple type name; Hex namespace migration candidate: Hex.Session.Logic -> Hex.Session.Data; namespace/name token overlap 0.71 |
| `Hex.Session.Logic.Side` | `Hex.Session.Data.Side` | probable-static | 63.07 | exact simple type name; Hex namespace migration candidate: Hex.Session.Logic -> Hex.Session.Data; namespace/name token overlap 0.60 |
| `Hex.Session.Logic.SideMagic` | `Hex.Session.Data.SideMagic` | probable-static | 67.33 | exact simple type name; Hex namespace migration candidate: Hex.Session.Logic -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.Logic.SideMagics` | `Hex.Session.Data.SideMagics` | probable-static | 61.92 | exact simple type name; Hex namespace migration candidate: Hex.Session.Logic -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.Logic.Week` | `Hex.Session.Data.Week` | probable-static | 66.92 | exact simple type name; Hex namespace migration candidate: Hex.Session.Logic -> Hex.Session.Data; namespace/name token overlap 0.60 |
| `Hex.Session.Logic.Weeks` | `Hex.Session.Data.Weeks` | probable-static | 80.27 | exact simple type name; Hex namespace migration candidate: Hex.Session.Logic -> Hex.Session.Data; namespace/name token overlap 0.60 |
| `Hex.Session.City.BuildingArtifactChanger` | `Hex.Session.Data.BuildingArtifactChanger` | probable-static | 65.36 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.71 |
| `Hex.Session.City.BuildingArtifactMarket` | `Hex.Session.Data.BuildingArtifactMarket` | probable-static | 69.05 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.71 |
| `Hex.Session.City.BuildingBank` | `Hex.Session.Data.BuildingBank` | probable-static | 76.61 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.City.BuildingCityBonusBank` | `Hex.Session.Data.BuildingCityBonusBank` | probable-static | 85.93 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.86 |
| `Hex.Session.City.BuildingHeroBonusBank` | `Hex.Session.Data.BuildingHeroBonusBank` | probable-static | 75.42 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.75 |
| `Hex.Session.City.BuildingHire` | `Hex.Session.Data.BuildingHire` | probable-static | 76.13 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.City.BuildingIntelligence` | `Hex.Session.Data.BuildingIntelligence` | probable-static | 77.0 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.City.BuildingMagicGuild` | `Hex.Session.Data.BuildingMagicGuild` | probable-static | 69.36 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.71 |
| `Hex.Session.City.BuildingMain` | `Hex.Session.Data.BuildingMain` | probable-static | 71.45 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.City.BuildingManaFountain` | `Hex.Session.Data.BuildingManaFountain` | probable-static | 77.69 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.71 |
| `Hex.Session.City.BuildingMarket` | `Hex.Session.Data.BuildingMarket` | probable-static | 89.0 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.City.BuildingMyceliumRoots` | `Hex.Session.Data.BuildingMyceliumRoots` | probable-static | 81.19 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.71 |
| `Hex.Session.City.BuildingPortalSummoning` | `Hex.Session.Data.BuildingPortalSummoning` | probable-static | 67.19 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.71 |
| `Hex.Session.City.BuildingShrineOfRebirth` | `Hex.Session.Data.BuildingShrineOfRebirth` | probable-static | 70.7 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.75 |
| `Hex.Session.City.BuildingTavern` | `Hex.Session.Data.BuildingTavern` | probable-static | 95.33 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.City.BuildingTrainingRange` | `Hex.Session.Data.BuildingTrainingRange` | probable-static | 72.97 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.71 |
| `Hex.Session.City.BuildingUnitsConverter` | `Hex.Session.Data.BuildingUnitsConverter` | probable-static | 71.86 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.71 |
| `Hex.Session.City.BuildingWall` | `Hex.Session.Data.BuildingWall` | probable-static | 68.68 | exact simple type name; Hex namespace migration candidate: Hex.Session.City -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.Battle.Side` | `Hex.Session.Data.Side` | probable-static | 64.61 | exact simple type name; Hex namespace migration candidate: Hex.Session.Battle -> Hex.Session.Data; namespace/name token overlap 0.60 |
| `Hex.Session.Data.ETurnMode` | `Hex.SharedLibrary.Models.Lobby.ETurnMode` | probable-static | 98.0 | exact simple type name; Hex namespace migration candidate: Hex.Session.Data -> Hex.SharedLibrary.Models.Lobby; method-name overlap 1.00 |
| `Hex.Session.World.HiredUnitSet` | `Hex.Session.Data.HiredUnitSet` | probable-static | 66.69 | exact simple type name; Hex namespace migration candidate: Hex.Session.World -> Hex.Session.Data; namespace/name token overlap 0.71 |
| `Hex.Session.World.MapMagic` | `Hex.Session.Data.MapMagic` | probable-static | 61.33 | exact simple type name; Hex namespace migration candidate: Hex.Session.World -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.World.MapMagics` | `Hex.Session.Data.MapMagics` | probable-static | 67.92 | exact simple type name; Hex namespace migration candidate: Hex.Session.World -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.World.MapBonuses` | `Hex.Session.Data.MapBonuses` | probable-static | 78.5 | exact simple type name; Hex namespace migration candidate: Hex.Session.World -> Hex.Session.Data; namespace/name token overlap 0.67 |
| `Hex.Session.World.WinConditions` | `Hex.MapGenerator.WinConditions` | probable-static | 71.73 | exact simple type name; Hex namespace migration candidate: Hex.Session.World -> Hex.MapGenerator; namespace/name token overlap 0.43 |
| `Hex.Session.World.Ai.Conditions.Condition` | `Hex.Session.Quests2.Data.Condition` | probable-static | 66.89 | exact simple type name; Hex namespace migration candidate: Hex.Session.World.Ai.Conditions -> Hex.Session.Quests2.Data; namespace/name token overlap 0.38 |
| `InputMode` | `Discord.InputMode` | probable-static | 109.33 | exact simple type name; namespace/name token overlap 0.67; method-name overlap 1.00 |
| `EOperationType` | `Hex.StoryHub.Condition.EOperationType` | probable-static | 94.0 | exact simple type name; method-name overlap 1.00; public-method overlap 1.00 |
| `GameMode` | `Hex.SharedLibrary.Models.GameMode` | probable-static | 94.0 | exact simple type name; method-name overlap 1.00; public-method overlap 1.00 |
| `HeroInfo` | `Hex.Pick.HeroInfo` | probable-static | 108.0 | exact simple type name; namespace/name token overlap 0.50; method-name overlap 1.00 |
| `Difficulty` | `Hex.StoryHub.DB.Config.Difficulty` | probable-static | 95.5 | exact simple type name; method-name overlap 1.00; public-method overlap 1.00 |
| `EResult` | `Hex.Info.EResult` | probable-static | 94.0 | exact simple type name; method-name overlap 1.00; public-method overlap 1.00 |

## Next use

For a concrete surface, start from the JSON row in `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_deobf_semantic_map.json`, then collect at least one additional evidence class before changing runtime hooks:

- current DiffableCs/ISIL method body or call-site evidence,
- generated interop metadata from the current Golden Era install,
- targeted live bridge metadata if runtime is available,
- runtime log proof for invocation ordering only after static candidates are narrow.

## Recommended next expansion slices

Expand from existing mod pain points, not alphabetically through the whole assembly:

| Slice | Why it matters | Seed types from this map | Proof needed before implementation |
|---|---|---|---|
| Town/city screen load | Town scenes work but load slowly; Mono can identify native lifecycle, city view binding, building tooltip, and resource/cost contracts. | `Hex.BhCityUpgradeStatsView`, `Hex.Cheat.UI.BhCityCheatPanel`, `Hex.Cheat.UI.BhWindowCity`, city/building analytics/config types. | Current deobf dossiers for scene open, building view bind, tooltip open/close, and resource affordability/spend routes. |
| Selected unit HUD/action bar | Custom unit SIDs can hit native UI dictionaries unexpectedly; this slice now has focused evidence. | `Hex.Session.Battle.BhSelectedUnitHud`, `BhUnitControlsView`, `BhUnitAbilityView`, `BattleEventArgs`, `HotkeyAbilityArgs`. | Use `docs/mono_priority_battle_ui_static_evidence.md`; remaining gaps are `bejo` exact role, `belz` clickability drift, and current-build hotkey index base. |
| Unit ability/tooltip panels | Custom abilities need precise data adapters instead of broad UI guards. | `Hex.BhHireUnitAbilities`, `Hex.BhUiBuff`, `Hex.BhUnitPreviews`, `Hex.Tools.BhUnitAnimationListener`. | Current dossiers for ability dictionary lookup, icon binding, buff/debuff panel item creation, tooltip text/image source. |
| Hero/army UI adapters | Existing hero/unit import code likely benefits from native identity and slot binding instead of defensive patches. | `BhSideHeroesViewController`, `BhHeroLoader`, `Hex.Pick.BhUnitSlot`, `Hex.Pick.BhHeroDetails`, story/pick hero types. | Current dossiers for hero slot bind, portrait load, army slot bind, unit stack tooltip, and hero selection refresh. |
| Custom biome/minimap/terrain | Current custom biome code should stay data-driven instead of renderer-rewrite driven; Mono confirms the original config contracts. | `Hex.Session.World.Minimap`, `Hex.Session.World.SoMinimapConfig`, `Hex.Render.SoTerrainMaterial`, `Hex.Configs.BiomesInfo`, sound enums. | Use `docs/mono_custom_biome_minimap_static_evidence.md`; remaining runtime proof is visual correctness and sound selector behavior only. |
| Icon/portrait/sprite binding | Law icons, hero portraits, ability icons, and specialization icons should use native bind contracts instead of broad UI/resource fallbacks. | `Hex.UI.BhIcon`, `IconData`, `SpriteConfig`, `AbilityViewConfig`, hero profile views, city ability views. | Use `docs/mono_icon_portrait_static_evidence.md`; remaining runtime proof is sprite availability and exact UI surface coverage. |
| Audio/music/projectile routing | Existing sidecar audio works but bypasses native sound-set, projectile flight, and city/map spatial sound routes. | `ProjectileConfig`, `BhProjectileController`, `MusicSoundsConfig`, `CityCommonSoundsConfig`, `MapHeroSoundsConfig`, `BhCitySoundObject`, `BhSoundMapObject`. | Use `docs/mono_audio_music_static_evidence.md`; remaining proof is exact current key selection and sound-set asset registration. |
| Sound runtime and mixer routing | Sidecar audio bypasses native sound groups, sound sets, pooled sources, mixer groups, focus fades, and ResManager bundle notifications. | `SoundsManager`, `SoundGroupConfig`, `SoundSetConfig`, `SoundClipConfig`, `SoundSource`, `SoundSourcesPool`, `SoundMixersManager`. | Use `docs/mono_sound_runtime_static_evidence.md`; remaining proof is custom sound bundle registration and exact music key selection. |
| ResManager/native asset loading | Existing prefab/icon/portrait/audio hooks depend on custom bundles resolving safely through native resource lookup. | `Hex.ResManager`, `ProjectileConfig`, `IconData`, sprite/portrait cache consumers. | Use `docs/mono_resmanager_static_evidence.md`; remaining proof is exact current loader body identity and bundle registration timing. |
| Utility path normalization | ResManager bundle lookup depends on normalized resource paths and case-insensitive matching. | `Hex.DirectoryHelper` -> `fwo`. | Use `docs/mono_hex_utils_static_evidence.md`; remaining proof is current method-body identity for individual obfuscated helpers. |
| Cheat/AI driver surfaces | Old Mono names can clarify intended cheat window owner and command surfaces used by automation. | `Hex.Cheat.UI.State*`, `BhWindowHero`, `BhWindowMagic`, `BhWindowWorldHeroPick`, `BhResourcePanel`. | Current dossiers plus live metadata only; no command exposure without runtime freshness and exact owner instance proof. |

Do not use this map as a direct replacement for `GameSymbols.cs`. It is a candidate/evidence source that should feed centralized symbols after review.

## Focused evidence documents

- Town screen load and city UI lifecycle: `docs/mono_town_screen_static_evidence.md`
- Battle visual drawer and spawn surfaces: `docs/mono_battle_visual_static_evidence.md`
- Unit visual presentation and UnitViewConfig: `docs/mono_unit_visual_presentation_static_evidence.md`
- Unit tooltip, preview, hire ability, and selected-unit UI: `docs/mono_unit_tooltip_preview_static_evidence.md`
- Hero and army UI adapter surfaces: `docs/mono_hero_army_ui_static_evidence.md`
- Battle damage forecast and kill mapping: `docs/mono_damage_forecast_static_evidence.md`
- Map squad visuals and fog adapter: `docs/mono_map_squad_visual_static_evidence.md`
- Custom biome, minimap, terrain material, and terrain sound: `docs/mono_custom_biome_minimap_static_evidence.md`
- Icon, portrait, sprite, and ability image binding: `docs/mono_icon_portrait_static_evidence.md`
- Audio, music, projectile, city/map spatial sound routing: `docs/mono_audio_music_static_evidence.md`
- Sound runtime, sound-set, pooled-source, and mixer routing: `docs/mono_sound_runtime_static_evidence.md`
- ResManager and native asset loading: `docs/mono_resmanager_static_evidence.md`
- Hex utility path normalization: `docs/mono_hex_utils_static_evidence.md`
- Static boundary audit for exhausted/missing body evidence: `docs/mono_deobf_static_boundary_audit.md`

## Generated interop metadata artifacts

- Main Hex interop map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/runtime_interop_map.json`
- ResManager interop map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/runtime_interop_map_resmanager.json`
- Sound runtime interop map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/runtime_interop_map_sound_runtime.json`
- Hex utils interop map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/runtime_interop_map_hex_utils.json`
- Full method-pointer import from attribute-injected dummy DLLs: `experiments/cpp2il_readable_csharp/samples/latest_refresh/method_pointers_from_dummydll_with_attrs.csv`
- ResManager method-pointer subset/address map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/method_pointers_hex_resmanager.csv`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/address_map_resmanager.json`
- Sound runtime method-pointer subset/address map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/method_pointers_hex_sound_runtime.csv`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/address_map_sound_runtime.json`
- Hex utils method-pointer subset/address map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/method_pointers_hex_utils.csv`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/address_map_hex_utils.json`
- Native disassembly packs: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_resmanager.json/md`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_hex_utils.json/md`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_sound_runtime.json/md`
- Full imported method address map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/address_map_all_dummydll_methods.json`
- External-domain native call graph: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_call_graph_external_domains.json/md`
- Core gameplay/UI method-pointer subsets: `method_pointers_hex_session_battle.csv`, `method_pointers_hex_session_city.csv`, `method_pointers_hex_cheat_ui.csv`, `method_pointers_hex_ui.csv`
- Core gameplay/UI native disassembly packs: `native_disasm_hex_session_battle.json/md`, `native_disasm_hex_session_city.json/md`, `native_disasm_hex_cheat_ui.json/md`, `native_disasm_hex_ui.json/md`
- Core gameplay/UI native call graph: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_call_graph_core_gameplay_ui.json/md`
- Additional mod-relevant method-pointer subsets/disassembly packs: `Hex.Session.Data`, `Hex.Map`, `Hex.Configs`, `Hex.Render`, `Hex.Storage`, `Hex.Session.UI`, `Hex.Session.Hud`, `Hex.Session.Logic`, and `Hex.Session.World`
- Broad mod-relevant native call graph: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_call_graph_mod_relevant_domains.json/md`
- Remaining Hex game-code pack: `method_pointers_hex_remaining_game.csv`, `native_disasm_hex_remaining_game.json/md`
- All-Hex game-domain native call graph: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_call_graph_all_hex_game_domains.json/md`
- Reusable all-Hex anchor/path query report: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_call_graph_anchor_report.json/md`
- All-Hex gameplay/UI anchor matrix: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_anchor_matrix_all_hex_game_domains.json/md`
- All-Hex positive anchor path dossiers with native instruction context: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_anchor_path_dossiers_all_hex_game_domains.json/md`
- Heuristic all-Hex anchor path triage: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_anchor_path_triage_all_hex_game_domains.json/md`
- All-Hex native call graph annotated with Mono semantic type aliases: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_call_graph_with_mono_aliases_all_hex_game_domains.json/md`
- Focused high-priority anchor path review pack: `experiments/cpp2il_readable_csharp/samples/latest_refresh/focused_anchor_path_review_pack_high_priority.json/md`
- Unresolved high-priority static action queue: `experiments/cpp2il_readable_csharp/samples/latest_refresh/unresolved_anchor_path_actions_high_priority.json/md`
- Unmapped high-priority current type notes: `experiments/cpp2il_readable_csharp/samples/latest_refresh/unmapped_high_priority_current_type_notes.json/md`
- Confirm ordinal-candidate static review: `experiments/cpp2il_readable_csharp/samples/latest_refresh/confirm_ordinal_candidate_static_review.json/md`

## Focused high-priority action reviews

The broad semantic map is now complemented by focused action artifacts under `experiments/cpp2il_readable_csharp/samples/latest_refresh`:

- `unresolved_anchor_path_actions_high_priority.md`: falsifiable action queue for high-priority anchor-path gaps.
- `confirm_ordinal_candidate_static_review.md`: review of seven ordinal-candidate rows after current method dossiers.
- `high_priority_action_static_review.md`: review of body/xref and target-endpoint dossier batches. Current static result: body/xref has 4 supported-static, 4 weak-static, 1 likely-misnamed, and 3 missing-ISIL rows; target endpoints have 5 supported-static, 2 weak-static, and 5 missing-ISIL rows.

- `missing_isil_native_callgraph_supplement.md`: native disassembly call-graph supplement for high-priority rows where ISIL type files are absent. It found 6 outbound-only, 2 inbound+outbound, and 2 inbound-only exact-label rows.

These focused reviews are static-only. They improve candidate selection and drift resistance; they do not prove runtime reachability, call order, or hook safety.
