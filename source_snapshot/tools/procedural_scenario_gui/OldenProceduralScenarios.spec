from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]

analysis = Analysis(
    [str(ROOT / "tools" / "procedural_scenario_gui.py")],
    pathex=[str(ROOT), str(ROOT / "experiments" / "campaign_port_poc"), str(ROOT / "experiments" / "campaign_port_poc" / "approach_cell")],
    binaries=[],
    datas=[],
    hiddenimports=[
        "tools.map_load_preflight",
        "port_homecoming_poc",
        "campaign_runtime_script",
        "object_property_namespaces",
        "scenario_menu_shell",
        "surface_emit",
        "dialog_portrait_plan",
        "h3m_hero_sid",
        "campaign_starting_bonus",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="OldenProceduralScenarios",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)