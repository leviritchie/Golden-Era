# Mono ResManager and Native Asset Loading Static Evidence

Status: source-generated/static-only. Runtime-unvalidated.

This dossier compares the old Mono demo `Hex.ResManager.dll` against the current Golden Era Cpp2IL shell for `Hex.ResManager`. It focuses on existing mod surfaces that replace unit prefabs, map prefabs, projectiles, portraits, icons, and other bundle-backed assets.

Evidence boundary: static Mono decompilation, current DiffableCs shell, and current mod source review only. This does not prove Harmony patch safety or runtime asset registration timing.

## Existing mod behavior reviewed

| Mod surface | Current approach | Risk/lesson |
|---|---|---|
| `ResManagerGameObjectLaneHooks` | Registers one Harmony postfix on a GameObject/UnityObject resource loader and chains HoMM3 battle/map/SFX replacements through a single lane. | Correct architectural direction: one centralized resource lane. It must remain object-lane only. |
| `Homm3ImportResManagerHook` | Replaces battle and map prefab results based on resource path, then delegates template/layer synchronization. | Native-friendly if the patched loader is truly GameObject/UnityObject-only and path filtering remains explicit. |
| `ResManagerInteropProbe` | Resolves `Hex.ResManager` across assemblies, then shape-matches loader candidates. It explicitly refuses the unsafe shared generic loader that broke startup `TextAsset` loads. | The no-fallback rule matters here: patching a shared generic resource loader corrupts non-GameObject bootstrapping. |
| `Homm3RuntimeManifestPreloader` | Prewarms custom sprite, texture, portrait, and map billboard manifests at main menu and fails fast on errors. | Good hygiene. It moves missing-asset failures earlier instead of deferring to map/town callbacks. |

## Mono/current type evidence

| Surface | Mono evidence | Current deobf evidence | Static conclusion |
|---|---|---|---|
| Assembly split | Demo has separate `Hex.ResManager.dll`. | Current DiffableCs has separate `Hex.ResManager/Hex/ResManager.cs`. | Strong static evidence that resource loading is a separate assembly surface, not main `Hex.dll`. Cross-assembly resolution is required. |
| Singleton | Mono has static `me_`, `me`, `Instance()`, `Awake()`, and `DontDestroyOnLoad`. | Current has static singleton field `clqs`, property `coux`, and singleton methods `bmvg`/`bmvh`. | Strong static singleton shape. Runtime instance discovery should prefer type/shape, not only main-Hex assembly lookup. |
| Bundle loading | Mono `LoadFromBundle` loads from `Application.streamingAssetsPath + "/bundles/" + bundleName`, iterates `GetAllAssetNames`, calls `LoadAssetWithSubAssets`, records path/bundle/type/data, then notifies listeners. | Current has load methods `bmvk`, `bmvl`, `bmvm`, coroutine `bmvn`, dictionary field, listener methods. | Strong static bundle registry shape. Custom bundles should integrate through the native ResManager dictionary where possible. |
| Single asset lookup | Mono static `Get<T>(string)` creates singleton, then calls private `GetAsset<T>`. `GetAsset<T>` checks bundles first, then `Resources.Load(path, typeof(T))`. | Current has static generic `bmvo(string)`, private generic/object candidates `bmvp(string)` and `bmvq(string)`. | Strong static candidate, but exact current method identity needs body/constraint evidence. Do not patch by name alone. |
| All-asset lookup | Mono static `GetAll<T>(string,bool)` checks bundle results first, then `Resources.LoadAll`. | Current has static array methods `bmvr`, private `bmvs`, `bmvt`. | Strong static family. Useful for future bulk asset discovery, not necessarily the prefab replacement lane. |
| File enumeration | Mono static `GetAllFiles<T>(string,bool)` returns `ResFile[]` and bundle-backed file records. | Current has static `bmvu`, private `bmvv`, `bmvw`. | Strong static family. Useful for manifest/debug tools if current `ResFile` shape is mapped. |
| Listener lifecycle | Mono has `Listen`, `Unlisten`, `OnLoad`, `OnUnload` over `IResManagerListener`. | Current has listener-like methods `bmvx`, `bmvy`, `bmvz`, `bmwa`, `bmwb`. | Strong static family; listener/support type aliases are documented below, but callback ordering still needs body or runtime evidence. |


## Current generated-name aliases

These aliases are static-only but strong enough for future decomp searches and centralized symbols. They are not runtime invocation proof.

| Mono semantic type | Current deobf type | Confidence | Evidence summary |
|---|---|---|---|
| `Hex.IResManagerListener` | `fxi` | strong-static | Interface with two callbacks taking `fxj`/`ResBundle`, matching `OnLoadBundle` and `OnUnloadBundle`. |
| `Hex.ResBundle` | `fxj` | strong-static | Fields string bundle name and `AssetBundle` data; release-like method shape. |
| `Hex.FileInfo` | `fxk` | strong-static | Fields path, bundle name, and `Type`; overrides `Equals`/`GetHashCode` with hash-combine helpers. |
| `Hex.ResFile` | `fxl` | strong-static | Fields `fxk`/`FileInfo` plus `UnityEngine.Object` asset data. |

## Generated interop static metadata

Artifact: `experiments/cpp2il_readable_csharp/samples/latest_refresh/runtime_interop_map_resmanager.json` generated from the Golden Era `BepInEx/interop/Hex.ResManager.dll`.

This is static generated interop metadata. It does not prove method bodies, runtime ordering, or Harmony patch safety, but it does prove callable ordinals and generated signatures exposed by the current interop assembly.

| Current concept | Generated interop evidence | Callable ordinal | Static implication |
|---|---|---:|---|
| Static singleton getter | `Hex.ResManager Method_Public_Static_get_ResManager_PDM_0()` | 0 | Matches singleton `me`/`Instance` family. |
| Static instance constructor/getter | `Hex.ResManager Method_Public_Static_ResManager_0()` | 2 | Matches Mono `Instance()` shape. |
| Resource dictionary getter | `Method_Public_get_Dictionary_2_ObjectPublicStclTyStclclUnique_ObjectPublicObclObclUnique_0()` | 3 | Confirms dictionary key/value support types `fxk`/`fxl`. |
| Static single-asset generic load | `a Method_Public_Static_a_String_0(System.String a)` | 10 | Corresponds to static `Get<T>(string)` family by ordinal/signature shape, but generated type variable `a` is not enough to authorize broad patching. |
| Private generic asset lookup | `b Method_Private_b_String_PDM_0(System.String a)` | 11 | Corresponds to private `GetAsset<T>(string)` family. |
| Private bundle object lookup | `UnityEngine.Object Method_Private_Object_String_0(System.String a)` | 12 | Strongest static candidate for bundle/object lookup. This is the method family most relevant to object-lane replacement if body evidence or runtime metadata confirms usage. |
| Static all-assets generic load | `Il2CppArrayBase<d> Method_Public_Static_Il2CppArrayBase_1_d_String_Boolean_0(System.String a, Boolean b)` | 13 | Corresponds to static `GetAll<T>(string,bool)`. |
| Private all-assets from resources | `Il2CppArrayBase<e> Method_Private_Il2CppArrayBase_1_e_String_0(System.String a)` | 14 | Corresponds to one private all-assets branch. Body evidence needed to label bundle vs Resources. |
| Private all-assets from bundle | `Il2CppArrayBase<f> Method_Private_Il2CppArrayBase_1_f_String_1(System.String a)` | 15 | Corresponds to the other private all-assets branch. Body evidence needed to label bundle vs Resources. |
| Static all-files generic load | `Il2CppReferenceArray<ObjectPublicObclObclUnique> Method_Public_Static_Il2CppReferenceArray_1_ObjectPublicObclObclUnique_String_Boolean_PDM_0(System.String a, Boolean b)` | 16 | Corresponds to static `GetAllFiles<T>(string,bool)`, returning `fxl[]`/`ResFile[]`. |
| Private files from bundle/resources | `Method_Private_Il2CppReferenceArray_1_ObjectPublicObclObclUnique_String_PDM_0` and `Method_Private_Il2CppReferenceArray_1_ObjectPublicObclObclUnique_String_0` | 17/18 | Correspond to private file enumeration branches. Body evidence needed to label which is bundle-backed. |
| Bundle lifecycle callbacks | `Method_Public_Void_ObjectPublicStclAsclUnique_0/1/2` | 19/20/21 | Correspond to remove/load/unload notification family over `fxj`/`ResBundle`. Exact semantic names require body/order evidence. |
| Listener registration | `Method_Public_Void_InterfacePublicAbstracthrVoaObhrVoaObUnique_0` and `_PDM_0` | 22/23 | Correspond to `Listen`/`Unlisten` over `fxi`/`IResManagerListener`. Exact order requires body evidence. |

Support type generated metadata:

| Mono semantic type | Current generated runtime type | Current obfuscated type | Interop proof |
|---|---|---|---|
| `IResManagerListener` | `InterfacePublicAbstracthrVoaObhrVoaObUnique` | `fxi` | Two abstract callbacks taking `ObjectPublicStclAsclUnique`/`fxj`. |
| `ResBundle` | `ObjectPublicStclAsclUnique` | `fxj` | Public string field, public `AssetBundle` field, release-like method. |
| `FileInfo` | `ObjectPublicStclTyStclclUnique` | `fxk` | Public string/string/type fields plus `Equals` and `GetHashCode`. |
| `ResFile` | `ObjectPublicObclObclUnique` | `fxl` | Public `fxk` info field plus `UnityEngine.Object` data field. |
## Safe implementation rule

For mod hooks, the safe lane is not "any `Get<T>(string)`". The safe lane is one of:

- a closed current method returning `UnityEngine.GameObject`,
- a closed current method returning `UnityEngine.Object` that is used as the GameObject resource path lane,
- or a generic method proven to be constrained to `UnityEngine.Object` and not shared with boot-critical `TextAsset`/input/font/config loads.

The unsafe lane is a broad static generic loader shared by unrelated resource types. Existing comments describe prior black-screen/startup NRE behavior when that path was patched. Keep that as rejected evidence unless a future body-level dossier proves a narrower current method.

## Recommendations

- Keep `ResManagerInteropProbe` centralized. Do not add faction- or feature-specific ResManager patches.
- Tighten any remaining fallback language in ResManager probing to fail closed on ambiguity. Ambiguous loader candidates should disable the lane rather than guessing.
- Prefer native ResManager bundle registration for custom prefabs/icons/audio over ad hoc `AssetBundle.LoadFromFile` sidecars when load timing can be proven.
- For projectile/battle prefab replacement, prove whether the current object-returning private loader `bmvq(string)` or generic `bmvo(string)` corresponds to Mono `GetAssetFromBundle<T>`/`Get<T>` before changing hook target.
- If the hook remains postfix-based, keep path filtering strict and side-effect-free for non-target paths.

## Unresolved gaps

- Generated interop metadata plus imported method-pointer evidence now proves callable ordinals, signatures, and native virtual addresses for the loader families; method-body evidence for exact branch semantics remains missing.
- Current support type mappings are now documented above; method-body evidence for listener invocation order is still not complete.
- Proof that custom bundle registration occurs before every UI/town/battle asset lookup that needs it.
- Whether native ResManager can replace current custom icon/portrait sprite caches entirely without load-order regressions.




## Current method-pointer evidence

Artifacts:

- `experiments/cpp2il_readable_csharp/samples/latest_refresh/method_pointers_hex_resmanager.csv`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/address_map_resmanager.json`

`out_dummydll_with_attrs` was generated with Cpp2IL `attributeinjector`, then `export_dummydll_method_pointer_map.ps1` converted method RVAs to current virtual addresses using `GameAssembly.dll` image base `0x180000000`. This proves current native addresses for the method families below, but not branch semantics or callback order.

| Current method | VA | Static implication |
|---|---:|---|
| `bmvo(string)` static single-asset generic load | `0x180A84220` | Exact current address for the `Get<T>(string)` family. |
| `bmvp(string)` private generic asset lookup | `0x180A843E0` | Exact current address for the private generic lookup family. |
| `bmvq(string)` private `UnityEngine.Object` lookup | `0x180A844F0` | Exact current address for the object lookup candidate most relevant to resource-lane replacement. |
| `bmvr(string,bool)` static all-assets generic load | `0x180A84890` | Exact current address for the `GetAll<T>` family. |
| `bmvu(string,bool)` static all-files generic load | `0x180A854D0` | Exact current address for the `GetAllFiles<T>` family. |
| `bmvx(fxj)` / `bmvy(fxj)` / `bmvz(fxj)` | `0x181DD8100` / `0x181DD8300` / `0x181DD84C0` | Exact addresses for bundle lifecycle callback family; semantic order still needs body/runtime evidence. |
| `bmwa(fxi)` / `bmwb(fxi)` | `0x181DD8690` / `0x181DD8770` | Exact addresses for listener registration family; registration vs unregistration order still needs body/runtime evidence. |


## Native disassembly evidence

`experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_resmanager.json/md` now disassembles all 51 imported `Hex.ResManager` method-pointer rows from the current `GameAssembly.dll`, with 332 direct calls observed and 168 calls annotated with known address-map targets. This is static native instruction evidence, not managed semantic reconstruction or runtime proof.

## Which loader to invoke (2026-09-26)

Static evidence (Mono `mono_full_resmanager_decompiled.cs` + `native_disasm_resmanager.md`):

- `bmvo` / interop `Method_Public_Static_a_String_0` = Mono `Get<T>`: calls `bmvp` (`GetAsset<T>`), which calls `bmvq` and, when that is null, `UnityEngine.Resources.Load` (disasm call at `0x180A84493`).
- `bmvq` / interop `Method_Private_Object_String_0` = Mono `GetAssetFromBundle<T>`: concatenates a path prefix and walks only the loaded-bundle `resFilesDictionary`; it never calls `Resources.Load`.
- Golden Era ships no `StreamingAssets/bundles`; every vanilla prefab is in `resources.assets` (ResourceManager container, 29947 keys, ASCII-lowercased).

So invoking `bmvq` directly returns null for every vanilla prefab (all Homm3MeshFx particle rows and `fx/fx_map_fire` failed exactly that way). Plugin loads invoke the inflated static `Get<GameObject>` store (`GameSymbols.ImportVisuals.ResManagerStaticGetGenericStore`). The Harmony postfix stays on `bmvq`: it sees every game load and a non-null replacement short-circuits the `Resources.Load` fallback. Keys are the exact container key (`units/nature/1prefabs/phoenix`, `objects/fx/fx_map_fire`); the game's own mixed-case callers (`units/Humans/1Prefabs/esquire`) resolve because `Resources.Load` is case-insensitive, but the catalogue ships the exact key and `tools/validate_homm3_mesh_fx_catalog_contract.py` enforces it against `tools/homm3_vfx/native_res_keys.json`. Runtime proof pending.
