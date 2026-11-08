AssetRipper (headless export for StockEsquireBattle.controller)

ONE-SHOT (recommended)
  pipeline_esquire_reference_headless.cmd
  Optional env vars:
    FORCE_EXPORT=1   — re-run rip even if tools\reference\assetripper_olden_demo_unity\Assets exists
    SKIP_EXPORT=1    — only copy from existing export
    SKIP_BOOTSTRAP=1 — skip download; require dist\AssetRipper.GUI.Free.exe
    RUN_UNITY=1      — after copy, run custom_prefab_pipeline\build_esquire_bundle.cmd

  Edit UNITY_PROJECT= and GAME_DATA= inside the .cmd if paths differ.

PIECES
  bootstrap.cmd
    Downloads AssetRipper 1.3.14 win_x64 into dist\AssetRipper.GUI.Free.exe

  export_heroesoe_unity_project.cmd / .ps1
    Exports HeroesOE_Data -> tools\reference\assetripper_olden_demo_unity\

  select_and_copy_esquire_stock_controller.ps1
    Scores *.controller under the export, copies winner + same-folder .anim into:
    <UnityProject>\Assets\CustomUnits\esquire\Reference\StockEsquireBattle.controller

  find_esquire_animator_controllers.ps1
    Manual listing / debugging of candidates.

Notes
- Full export is large and slow; tools\reference\.gitignore ignores assetripper_olden_demo_unity\
- If selection fails (low score), inspect the export and copy a controller manually.
- Upstream: https://github.com/AssetRipper/AssetRipper
