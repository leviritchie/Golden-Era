# Selected-unit HUD hotkey probe (local)

Static analysis: [STATIC_ANALYSIS.md](./STATIC_ANALYSIS.md).

## Safety

- Default Golden Era builds **do not compile** `Homm3SelectedUnitHudHotkeyProbe.cs`.
- Release candidate builds never compile it.
- Normal plugin deploy **deletes** the flag from the install if present.
- Activation requires both an MSBuild switch and a local flag file next to the deployed DLL.

## Enable (local machine only)

From repo root (adjust `GameRoot` if needed):

```bash
# 1) Build + deploy plugin with probe compiled in
dotnet build "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/OfflineUnlockMod.csproj" \
  -p:OfficialDeobfBuild=true \
  -p:EnableSelectedUnitHudHotkeyProbe=true \
  -p:GameRoot="V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"

# 2) Place flag AFTER deploy (deploy deletes it)
python experiments/selected_unit_hud_hotkey_static/enable_local_probe_flag.py
```

Or create an empty file:

`…/BepInEx/plugins/OfflineUnlockMod/homm3_selected_unit_hud_hotkey_probe.flag`

Optional companion (existing): `homm3_selected_hud_diag.flag` for the production hotkey-prefix decision logs.

## What to do in battle

1. Start Golden Era with the probe-enabled DLL + flag.
2. Confirm log: `HOMM3_SUH_HOTKEY_PROBE registered patched=…`
3. Select a **vanilla** unit with 2+ abilities; press `1` / `2`.
4. Select a **custom** unit with 2+ abilities; press `1` / `2`; also mouse-click once.
5. Grep BepInEx log for `HOMM3_SUH_HOTKEY_PROBE`.

## How to read results

| Log cue | Meaning |
| --- | --- |
| `hud.*.finalizer.ex … KeyNotFoundException` | Q1: native HUD dictionary miss for custom SID |
| `slots=… emb=false` after bind/recovery | Q2: native hotkey gate will bail (`chae` missing) |
| `hotkey.prefix … idButton=N` | Q3: index base for number keys |
| `nativePredict=would-belo` vs `bail` | Q4: whether native `beme` would call `belo` |
| `hotkey.postfix` + `controls.click` | Q5: native path ran (if mod prefix skipped native, postfix may be absent — correlate with `Homm3Import release ability hotkey`) |
| Vanilla shows `emb=true` + `would-belo` | Q6: control baseline |

Do not change production bind/hotkey logic until these questions have live answers.
