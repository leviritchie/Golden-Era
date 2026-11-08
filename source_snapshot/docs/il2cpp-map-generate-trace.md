# Map generate / `Map.Init` chain (Il2Cpp dump)

This note ties **Player.log** stacks (`epw.GenerateMap` → `Hex.Map.Map.Init` → `buz` / `buf` constructors) to **Il2CppDumper** output so you can continue in a disassembler with named symbols.

## Generating the dump (local)

- **Downloader:** [Perfare/Il2CppDumper releases](https://github.com/Perfare/Il2CppDumper/releases). Use a build that supports your Unity / il2cpp version (this playtest was dumped with **v6.7.46**; try a newer release if the dumper errors).
- **Install (local only):** unzip so **`Il2CppDumper.exe`** lives in  
  `Heroes of Might & Magic Olden Era Playtest/tools/il2cpp_dumper/`  
  That directory is **gitignored** (binaries are not committed).
- **Inputs (game install):** from the same folder as `HeroesOE.exe` (playtest root):
  - `GameAssembly.dll`
  - `HeroesOE_Data/il2cpp_data/Metadata/global-metadata.dat`
- **Run (Windows):** double-click or run from a prompt (paths with spaces are fine if you use the repo copy):  
  `Heroes of Might & Magic Olden Era Playtest\tools\run_il2cpp_dumper.cmd`  
  From Git Bash, prefer `bash tools/run_il2cpp_dumper.sh` so `Il2CppDumper.exe` is not split on spaces.  
  It writes to **`tools/il2cpp_out/`** (also gitignored). If `config.json` in `tools/il2cpp_dumper/` has `RequireAnyKey: true`, the runner runs `il2cpp_dumper_headless_config.py` first so non-interactive sessions do not hang on “Press any key”.
- **Run (Git Bash / Linux binary):** `bash tools/run_il2cpp_dumper.sh` from the playtest root, or `cd tools && bash run_il2cpp_dumper.sh`.
- **CLI shape:** `Il2CppDumper.exe <GameAssembly.dll> <global-metadata.dat> <output-dir>`.

**After the dump — LocKit / localization**

- Open **`tools/il2cpp_out/dump.cs`** in an editor and search for: `LocKit`, `LocInfo`, `MapInfoLocalization`, `does not contain`, `homm3_stronghold`, `[LocInfo]`.
- Optional: **`stringliteral.json`** in the same output folder holds string literals; search there for the exact log format string.
- Quick helper (from `tools/`):  
  `python search_il2cpp_dump.py LocKit "does not contain" MapInfoLocalization`

The main artifact for browsing types is `dump.cs`. **Method bodies are not decompiled** (empty stubs), so which exact reference is null must be read from **native x64** at the RVAs below, optionally after importing with Il2CppDumper’s `ghidra.py` or `ida.py`.

## Session map type

The relevant type is **`Hex.Map.Map`** (other `Map` types exist in other namespaces, e.g. StoryHub). It holds a callback `btv`, `MapData`, and many subsystems. The object implicated in the constructor chain is the **`buz`** aggregate, stored in the generated backing field/property roughly named **`bupj`** in the dump.

- **`buz`**: small façade; fields include **`buf buxu`** plus `bty`, `bun`, `buj`, `bvi`, `buh`. `buz..ctor(Hex.Map.Map)`.
- **`buf`**: extends `bdx`; private **`Map burw`**; mesh/material buffers. `buf..ctor(Hex.Map.Map)`.

## RVAs in `GameAssembly.dll` (for Ghidra / IDA / x64dbg)

Same addresses appear as **`Address`** in `tools/il2cpp_out/script.json` and match the **RVA** column in `dump.cs`.

| Method | Decimal | Hex RVA |
|--------|---------|---------|
| `epw$$GenerateMap` | 34426352 | `0x20D4DF0` |
| `Hex.Map.Map$$Init` | 42775312 | `0x28CB310` |
| `buf$$.ctor` | 42831392 | `0x28D8E20` |
| `buz$$.ctor` | 42994288 | `0x2900A70` |
| `Hex.Map.Map$$.ctor` (default) | 42779632 | `0x28CC3F0` |
| `btz$$ocf` | 42810272 | `0x28D3BA0` |
| `bva$$.ctor` | 42995184 | `0x2900DF0` |
| `bvk$$.ctor` | 43051968 | `0x290EBC0` |
| `bwe$$.ctor` | 43225360 | `0x2939110` |
| `bvh$$.ctor` | 43002320 | `0x29029D0` |
| `bts$$Init` (called from end of `bwe..ctor`) | 42735088 | `0x28C15F0` |
| `bts$$.ctor` | 42735248 | `0x28C1690` |

`Map$$Init` signature in metadata: `void (Hex.Map.Map this, btv _callback)`.

## `Map.Init` construction order (named; playtest disasm)

After the cctor prologue, **`Map.Init`** (from **`0x28CB44C`** onward) does at least the following, in order, before and including **`buz`**. Object names are from `script.json`; field offsets are **`Hex.Map.Map`** in `dump.cs` (e.g. `bupf` = `+0x28` is **`bua`**, built in register **`r14`** with **`[bua+0x10] = Map`** and then linked from **`[Map+0x28]`**).

| Step | Callee | RVA | `Map` field (offset) |
|------|--------|-----|----------------------|
| 1 | `btz$$ocf` | `0x28D3BA0` | (factory / helper; used with next allocs) |
| 2 | `bva$$.ctor` | `0x2900DF0` | `buph` / `bva` @ **`+0x38`** |
| 3 | `bvk$$.ctor` | `0x290EBC0` | `bupe` / `bvk` @ **`+0x20`** |
| 4 | (inline) `bua` graph | — | `bupf` / `bua` @ **`+0x28`**; **`bua` holds `Map*` at `bua+0x10`** |
| 5 | `bwe$$.ctor(Map)` | `0x2939110` | `bupi` / `bwe` @ **`+0x40`** |
| 6 | `bvh$$.ctor(Map)` | `0x29029D0` | `bupg` / `bvh` @ **`+0x30`** |
| 7 | `buz$$.ctor(Map)` | `0x2900A70` | `bupj` / `buz` @ **`+0x48`** |

So an NRE **inside `Map.Init` but before `buz..ctor`** can still be caused by failure or null paths in **`bua` / `bwe` / `bvh` / `bva` / `bvk`**, not only in **`buz`/`buf`**. Cross-check the stack frame with this ordering.

## `buz..ctor` child order (named)

Within **`buz..ctor`**, the game builds children in this **call** order (each `..ctor` takes **`Hex_Map_Map_o* a`** in the usual **`rdx/rsi`** slot). `dump.cs` field names for **`buz`**: `buxu`…`buxz`.

| Call order | Callee | RVA | Written field (`buz` + offset) |
|------------|--------|-----|--------------------------------|
| 1 | `buf$$.ctor` | `0x28D8E20` | **`+0x10`** `buxu` |
| 2 | `bun$$.ctor` | `0x28E5BF0` | **`+0x20`** `buxw` |
| 3 | `bty$$.ctor` | `0x28D1CC0` | **`+0x18`** `buxv` |
| 4 | `buj$$.ctor` | `0x28E0810` | **`+0x28`** `buxx` |
| 5 | `bvi$$.ctor` | `0x290DD60` | **`+0x30`** `buxy` |
| 6 | `buh$$.ctor` | `0x28DC8A0` | **`+0x38`** `buxz` |

The compiler emits **`bun` before `bty`** in instruction order; final field layout still matches the obfuscated class (see `dump.cs`).

## Native call chain (verified, playtest `GameAssembly`)

This section is from **x64 disassembly** of the playtest build (not from empty `dump.cs` bodies).

### `epw$$GenerateMap` → `Map$$Init`

- After cctor/registration, `GenerateMap` calls **`il2cpp` helper** @ `0x488210` (type lookup), then **`Hex.Map.Map` default ctor** @ `0x28CC3F0`, and stores the instance at **`epw` field offset `+0x50`** (generated property for `Map` in `dump.cs`, e.g. `cgwd`).
- It null-checks that map, then: **`call 0x28CB310`** with **`rcx` = `Map*`, `rdx` = `epw*`** (session controller implements **`btv`** and is the `_callback` passed into `Init`).

So the log order **`epw.GenerateMap` above `Map.Init` is a direct call**, not a coincidence.

### `Map$$Init` → `buz` / `buf`

- Real work begins after the method’s static-init branch (jump to `0x28CB44C+`).
- The callback is written at **`[Map + 0x10]`** (field **`bupc`** / `btv`).
- Subsystems and **`buz`** are built in the order in the **`Map.Init` construction order** section above.
- **`buz` ctor** is invoked @ **`0x28CB5E6`**: **`call 0x2900A70`**, result stored at **`[Map + 0x48]`** — **`bupj`**.

### `buz$$.ctor` → `buf$$.ctor`

- `buz..ctor` builds **`buf`** first: **`call 0x28D8E20`**, then assigns the return value to **`[buz + 0x10]`** (field **`buxu`** / `buf`).
- `buf..ctor` writes **`[buf + 0x10] = Map`**, allocates **`[buf + 0x28]`**, and later touches **Il2Cpp class statics** (pointer loaded via `rip` + `cmp [rcx+0E4]`) before more setup — a null **TypeInfo** there would be a runtime init bug, not a missing `Map` reference on `buf` itself.

If your **NRE** sits on **`buz`/`buf` in the log**, the next step in Ghidra/IDA is the **first `mov`/`call` that uses `Map` in `rdx`/`rsi`** after each ctor’s prologue, or a failed **`test`/`je`** to an error path (Il2Cpp often encodes `ThrowHelper` that way).

## Deep dive (picked): `bwe$$.ctor` (`0x2939110`)

**Why this one:** It runs in **`Map.Init` after `bua` and before `bvh` / `buz`**, and the implementation mixes **static Unity/`ScriptableObject`-style data** (loads through **`[TypeInfo+0xB8]`** static field slots) with the **`Map*`** parameter. That gives **three different NRE “shapes”** in one function: failed allocation, null statics, and null **`Map` / child `bts`**.

**Type (`dump.cs`):** `bwe` holds `Map bvfm` @ **`+0x10`**, `bvb[] bvfn` @ `+0x18`, `bts bvfo` @ `+0x20`, `Quaternion[] bvfq` @ `+0x28`.

**What the assembly does (playtest `GameAssembly`, tail of the ctor is clearest):**

- Allocates a small **`List<Quaternion>`-like buffer** in **`rbx`**, then fills it from **several distinct static class pointers** (pattern: `mov rax, [rip+…]; mov rax, [rax+0xB8];` then `movsd` / `movups` from offsets such as `+0x3c`, `+0x44`, `+0x54`, `+0x5c` …). Early **`test rbx, rbx; je` → `0x488260`** and **`jbe` on `[rbx+0x18]`** are **OOB/throw** paths, not `Map` yet.
- Stores that buffer at **`[bwe+0x28]`** (`bvfq`), runs the usual empty **base** call @ **`0x5B4E40`**, then **finally assigns `Map`**: **`[bwe+0x10] = Map`** (register **`rsi`** in this build).
- Constructs **`bts`** via **`0x28C1690`**, stores at **`[bwe+0x20]`**, **`test` + branch** if null → throw helper **`0x488260`**.
- On success, **`jmp` to `bts$$Init` @ `0x28C15F0`** (metadata: `bts__Init (bts this, Hex_Map_Map_o* _map, …)`) with **`Map` in `rdx`**. The preceding **`call` @ `0x28C1690` is `bts$$.ctor`**; store field @ **`[bwe+0x20]`** (`bts` / `bvfo`).

`py disasm_il2cpp_rva.py GameAssembly.dll 0x28C15F0 40` is the next hop after **`bwe..ctor`**.

**How to use this for a real `Player.log` NRE:** If the top frame is **`bwe`**, decide whether the faulting line is in the **static data load** (early `rax` / `[rax+offset]`), the **`[bwe+0x10]`** store, or the **`bts` / `0x28C15F0`** path — each implies a different fix (content pipeline vs. map reference vs. subsystem init).

## Quick disassembly in the repo

`Heroes of Might & Magic Olden Era Playtest/tools/disasm_il2cpp_rva.py` prints Capstone disassembly for an RVA. Dependencies: `pip install pefile capstone`. Example (from the playtest game folder, adjust path):

`py disasm_il2cpp_rva.py GameAssembly.dll 0x28CB310 60`

## Plan implementation: evidence, triage, disasm, fix locus, updates

The following subsections follow the **Map.Init NRE follow-up** workflow: capture logs, triage a stack, confirm with **`disasm_il2cpp_rva.py`**, decide where a fix lives, and refresh after a game patch. *(Runtime repro and saving logs is on your machine; the repo does not check in `*.log`.)*

### 1) Capture a failing run (config + log paths)

- **Reproduce** once with a **fixed mod config** so results are comparable. Note the **resolved** `config.json` the game read (BepInEx may merge with [`OfflineUnlockMod`](V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest\BepInEx\plugins\OfflineUnlockMod) — see [`Plugin.cs`](V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\Plugin.cs) / `LauncherConfig` for resolution order).
- **Copy these after the crash** (default layout):
  - Unity: `%USERPROFILE%\AppData\LocalLow\<Company>\<Product>\Player.log` (exact folder varies; search for `Player.log` by modified time if needed).
  - BepInEx: `<GameRoot>\BepInEx\LogOutput.log` (or `BepInEx/LogOutput.log` under the playtest install).
- **Optional** mod-side artifacts already wired in this project: `BepInEx/plugins/OfflineUnlockMod/esquire_diagnostics.log`, `esquire_unity_correlator.log` (see `LauncherConfig` / `EsquirePikemanVisuals` when diagnostics / correlator are enabled).
- **Record** a one-line “run fingerprint”: map/mod used, `esquirePikemanApplyHarmony` / `DeferPatch` on or off, and time.

**Checklist (paste into an issue or scratch file):** `[ ] Player.log` `[ ] BepInEx log` `[ ] config snapshot` `[ ] which map/session`.

### 2) Triage: map stack frames → subsystem

Walk the **innermost** managed frames **upward** until you hit a name you can place in the construction-order table (or **`buz` child** table if inside **`buz`**).

**Blank triage (fill in):**

| Your innermost game frame (paste) | Matched step / callee | Next RVA to disasm |
|----------------------------------|------------------------|-------------------|
| | e.g. `bwe..ctor` / `bts$$Init` / `buz` / `buf` | from RVA table above |

**Example (synthetic):** if the stack shows `Hex.Map.Map:Init` → `bwe:.ctor` → `bts:Init` with NRE, start with **`0x2939110`** (early static loads) and **`0x28C15F0`** (stores `Map` on `bts` then tail to **`0x28C9930`**).

### 3) `bts$$Init` + tail (disasm notes; playtest `GameAssembly`)

Commands (from the directory that contains `GameAssembly.dll`):

`py path/to/tools/disasm_il2cpp_rva.py GameAssembly.dll 0x28C15F0 25`

`py path/to/tools/disasm_il2cpp_rva.py GameAssembly.dll 0x28C9930 50`

| Region | RVA | Null-risk (instruction-level) |
|--------|-----|--------------------------------|
| `bts$$Init` prologue | `0x28C15F0` | Stores **`_map`** at **`[bts+0x28]`**, `jmp 0x28C9930`. No `Map` deref in the first instructions beyond the field write. |
| Tail (shared) | `0x28C9930` (after cctor) | Calls **`0x28C9EA0`**, then **`btz$$ocf`**-like path (`0x28D3BA0`); then **`test rax; je` throw path**; **`mov rcx, [rax+0x20]`** / **`[rcx+0x10]`** — first serious **indirect** use of a graph coming off **`btz` output**; if that chain is null, you fault here **after** `bwe` stored cliff quaternions. |

Cross-check: compare with **`bwe..ctor` deep dive** (statics vs `Map` vs `bts` null) in this file.

### 4) Fix ownership (mod vs content vs engine)

- **Stack + disasm in `bwe..ctor` “early”** (loads from **`[TypeInfo+0xB8]`**): treat as **data/static asset** or class-init order; mod fixes are only plausible if the mod **replaces or delays** those assets (e.g. **Esquire** / `ResManager` paths — align with your actual hooks).
- **Fault in `bts$$Init` / `0x28C9930` tail** (broken **`btz` / `Map` graph** after `0x18` / `0x20` loads): **engine/content** (bad session map data) unless a mod **patches map load** or the same `btz` result.
- **Only `buz` / `buf`**: use **child order table**; then **disasm that ctor’s RVA** only.
- **Harmony on/off** changes the crash: add **targeted** logging (not broad patches): central entry is **[`Plugin.cs`](V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\Plugin.cs) `Load()`**; follow patterns in **`esquirePikemanDiagnostics`** / **Unity error correlator** in [`LauncherConfig.cs`](V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\LauncherConfig.cs) — a future **`MapInit` diagnostics** flag should mirror that (guarded, off by default, logs scene + session ids only, no PII).

**One-paragraph template:** “Root cause: {subsystem + early/late in ctor}. Fix locus: {mod config / mod hook / not mod}. Next action: {disasm RVA / file issue / no change}.”

### 5) When the game updates (re-dump, re-verify)

- Re-run **Il2CppDumper** (see “Generating the dump” at top) on the new **`GameAssembly.dll`** and **`global-metadata.dat`**.
- **Re-verify** at least: `Hex.Map.Map$$Init` (`0x28CB310`), `bwe$$.ctor` (`0x2939110`), `bts$$Init` (`0x28C15F0`), `buz$$.ctor` (`0x2900A70`) using **`disasm_il2cpp_rva.py`** — expect a similar **prologue** (push/save, cctor, then body). If the **file offset** fails or the pattern is wildly different, **RVAs moved**; update the table in this doc and the **`script.json` Address** line you used.
- Fast **section** check: `py tools/il2cpp_rva_sanity_check.py GameAssembly.dll` (lists **`KNOWN_RVAS`**; edit the script or pass `Name 0xRVA` pairs if you track extra methods). Exit code **1** if any RVA is not inside a PE section.
- **Build fingerprint** for this document (edit when you refresh the dump): **metadata / il2cpp 31 / 31**; **GameAssembly** from playtest install path you used; **date of last RVA check:** _fill when verified_.

## What to do next (Ghidra / long-form)

1. Load **`GameAssembly.dll`** in Ghidra/IDA, apply the Il2Cpp script for this dump so methods resolve to names.
2. Start at **`Hex_Map_Map__Init`**, then follow the **`call 0x2900A70`** to **`buz`**, and **`0x28D8E20`** to **`buf`**; mark the first load/use of **`Map`** (register from ctor’s second arg) that can be null in your failure save.
3. Correlate with mod code (e.g. `ResManager` / asset timing) only if the disassembly shows a dependency; otherwise treat engine init order and asset nulls as primary.

Metadata / il2cpp version for the playtest build used for this dump: **31 / 31** (from the dumper run; re-run if the game updates).
