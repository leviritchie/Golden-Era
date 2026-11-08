# verify_esquire_interop

Local `dotnet` harness: loads the same BepInEx **core** and **interop** assemblies as the game, resolves `Hex.ResManager` and the open `Get<T>(string)`-shaped method (obfuscated or not), and runs `MakeGenericMethod(typeof(UnityEngine.GameObject))`. Use this to validate IL2CPP reflection glue without starting a match.

A full game start is still required to prove Harmony applies and `ResManager.Get` is hit, but you can avoid repeated launches when fixing type/method resolution.

## Prerequisite

A Heroes OE playtest (or any install) whose tree contains `BepInEx\core`, `BepInEx\interop\Hex.ResManager.dll`, and `BepInEx\interop\UnityEngine.CoreModule.dll`. Point the tool at the folder **that contains** the `BepInEx` directory (e.g. `.../Heroes of Might & Magic Olden Era Playtest` in this repo).

## Run the harness

From the repository root (or with explicit root):

```bash
cd tools/verify_esquire_interop
dotnet run -- --playtest-root "V:/Games/Olden Era Playtest Tweak/Heroes of Might & Magic Olden Era Playtest"
```

Or set an environment variable and use the default (walks up from the build output, or the current directory, for a folder named `Heroes of Might & Magic Olden Era Playtest`):

```bash
export HEROES_OE_PLAYTEST="V:/Games/Olden Era Playtest Tweak/Heroes of Might & Magic Olden Era Playtest"
dotnet run --project tools/verify_esquire_interop
```

- Exit **0**: resolution + `MakeGenericMethod(GameObject)` succeeded. The program prints the closed `MethodInfo` (e.g. `UnityEngine.GameObject bmeo[GameObject](System.String)` on obfuscated builds).
- Exit **nonzero**: first failing step is written to **stderr** (missing DLL, type not found, `MakeGenericMethod` exception, etc.).

## Optional: dump ResManager method candidates

If resolution fails or you are debugging, list declared generic/`Get*`-ish methods on `Hex.ResManager` only:

**Windows (bash/Git Bash / MSYS):**

```bash
set VERIFY_RES_DUMP=1
dotnet run --project tools/verify_esquire_interop -- --playtest-root "…"
```

**PowerShell:**

```powershell
$env:VERIFY_RES_DUMP = "1"
dotnet run --project tools/verify_esquire_interop -- --playtest-root "…"
```

## Optional: check BepInEx log after one launch

After a single run to the main menu (or any load that executes the mod), you can assert the log contains a successful patch line and none of the “pikeman swap disabled” lines.

**Use Windows PowerShell** (always present on Windows; works in CMD, PowerShell, and Cursor’s integrated terminal):

```powershell
powershell.exe -NoProfile -File tools/verify_esquire_interop/check_bepinex_log.ps1 -PlaytestRoot "V:/path/to/.../Heroes of Might & Magic Olden Era Playtest"
```

**PowerShell 7** (`pwsh`) is optional; if it is installed, you can use `pwsh -File ...` the same way. In **Git Bash**, `pwsh` is often *not* on `PATH` even when PowerShell 7 is installed, while **`powershell` / `powershell.exe`** usually resolve to `Windows\System32\WindowsPowerShell\v1.0\powershell.exe`. From Git Bash you can run:

```bash
"/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe" -NoProfile -File tools/verify_esquire_interop/check_bepinex_log.ps1 -PlaytestRoot "V:/path/to/.../Heroes of Might & Magic Olden Era Playtest"
```

The script works on **Windows PowerShell 5.1** and PowerShell 7. It requires `BepInEx/LogOutput.log` and a line `EsquirePikeman: Harmony prefix on` or `… Harmony postfix on` (and fails if a known `EsquirePikeman: … pikeman swap disabled` line is present). Only text **after the last** `Chainloader initialized` in the file is checked, so an older run’s errors do not block validation after a good launch.

It also counts **`DMD<Hex.InitScene.BhAppStartScript::Update>`** in that same slice (repeating Il2CppInterop `[Error  :Il2CppInterop] …` blocks, e.g. `bxg.pbo` / `bxt.Init` in the stack). If the count is **greater than zero**, the script **fails** by default, because the old Esquire-only check was easy to read as “all OK” while this spam was in `LogOutput.log`. Pass **`-AllowBhAppStartIl2CppNre`** when you only care about the Esquire lines. Other Il2CppInterop errors (e.g. `Hex.UI.BhFont`) may also appear in the file; the printed sample is anchored to the first BhAppStart DMD line when present.

## Optional: launch the game, then always stop after a timeout

`tools/run_playtest_10s.ps1` starts `HeroesOE.exe` in the playtest root, then **stops the process** after 10 seconds (or `-Seconds 30` for a deeper smoke test). Use this for automated or repeated checks so a crashed or hung playtest is not left running. A **10 second** run often stops while Unity is still in store/early init. To confirm a full data load, check `%LOCALAPPDATA%\..\LocalLow\Unfrozen\HeroesOE\Player.log` for `[Config] db is loaded` after a **~30** second run with this script, then re-run the BepInEx log check if needed.

`tools/iterate_playtest_smoke.ps1` runs that launcher **N times** (default 3) with BepInEx log validation after each stop, and optionally a final **deep** run: `-DeepLoadSeconds 30` also asserts `Player.log` contains `[Config] db is loaded` in the last 4000 lines. Pass **`-AllowBhAppStartIl2CppNre`** to forward the same opt-out to `check_bepinex_log.ps1` on every pass.

```powershell
powershell.exe -NoProfile -File tools/iterate_playtest_smoke.ps1 -PlaytestRoot "V:/path/.../Heroes of Might & Magic Olden Era Playtest" -Rounds 5 -Seconds 10 -DeepLoadSeconds 30
```

## Shared code with the mod

`ResManagerInteropProbe.cs` lives under `OfflineUnlockMod` and is **linked** into this project so the harness and `EsquirePikemanVisuals` never drift. Change resolution logic in that file only.

The probe only inspects **methods declared on `Hex.ResManager`**. It does not walk `MonoBehaviour` / `Component` base types: that used to pull in hundreds of `GetComponent` / `Get…` methods and could **freeze the game for a long time** at BepInEx load. It also does **not** call `MakeGenericMethod` during discovery (IL2CPP can misbehave if many generic instantiations are probed at startup).
