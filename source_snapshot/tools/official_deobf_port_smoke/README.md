# Golden Era port-smoke workflow

Runtime-first patch porting on the isolated **Golden Era** Steam install.

## One-command setup

Close the game first, then from repo root:

```bash
bash tools/deploy_official_deobf_port_smoke.sh
```

Automated startup gate probe (deploy + launch + parse log):

```bash
bash tools/launch_official_deobf_startup_probe.sh
```

Set `DEPLOY=0` to re-test the already-deployed DLL without rebuilding. Set `WAIT_SEC=90` for a longer main-menu/auto-launch window.

This will:

1. Build `OfflineUnlockMod` with `-p:OfficialDeobfBuild=true`
2. Deploy the DLL + HoMM3 payload to the experiment install
3. Install `config.port_smoke.json` as plugin `config.json`
4. Install game-root `OfflineLauncherConfig.json` (Blitz skirmish preset; **autoLaunchOnMenu=true** for hands-free map load)
5. Enable diagnostic flag files under `BepInEx/plugins/OfflineUnlockMod/`

Restore prior configs/flags:

```bash
bash tools/restore_official_deobf_port_smoke.sh
```

## After launch

1. Read **`BepInEx/LogOutput.log`** before clicking anything — startup `RegisterRequired*` / `LogFatal` lines mean stale `GameSymbols` surfaces.
2. With `autoLaunchOnMenu=true`, wait ~6s on the main menu for the configured Blitz match to start (grep `Auto-launch:` / `Started configured` in the log).
3. Minimal smoke path: map load → move hero → enter Stronghold town → recruit screen → start battle with HoMM3 unit → check selected-unit HUD / turn queue.
4. In-game UI inspector: **F8** toggle overlay, **F7** dump hovered control to log (`HOMM3_UI_INSPECTOR`).

## Log grep keys

| Pattern | Meaning |
|---------|---------|
| `Port-smoke profile active` | Port-smoke config loaded |
| `RegisterRequired` / `failed during startup` | Symbol/surface drift — fix before gameplay |
| `HOMM3_UI_CARD_DIAG` | UI binder hit/miss diagnostics |
| `HOMM3_UI_INSPECTOR` | F7 UI dump |
| `Auto-launch:` | Skirmish bootstrap |
| `HOMM3_BATTLE_UNIT_INIT_DIAG` | Battle unit init failure |
| `Homm3Import` | Map/battle visual lane |

Also check **`Player.log`** if Unity exits without a clear BepInEx fatal.

## Files in this folder

| File | Deploy target |
|------|----------------|
| `config.port_smoke.json` | `BepInEx/plugins/OfflineUnlockMod/config.json` |
| `OfflineLauncherConfig.json` | Game install root (next to `HeroesOldenEra_Data`) |
| `flags/*.flag` | `BepInEx/plugins/OfflineUnlockMod/` |

## Notes

- Requires `portSmokeProfile: true` in mod config so release-safe profile keeps high-signal diagnostics enabled.
- Legacy playtest `autoLaunchOnMenu` is off by default; do not re-enable unless explicitly testing that path.
- Official install `Core.zip` already ships HoMM3 Stronghold rows; no Core overlay step required for this smoke.
- Compile gate only: build must use `OfficialDeobfBuild=true` (`tools/build_official_deobf.cmd`).
