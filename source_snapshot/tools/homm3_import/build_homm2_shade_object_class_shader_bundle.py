#!/usr/bin/env python3
"""Build the HoMM2 shade object-class ColorMask-A shader bundle.

Uses the slim Unity 6000.0.66f2 project at V:/homm3_artifact_mesh_build by default.
Do not point this at oldenera_factions / homm3_unity_work — that tree is too large
for a one-shader bundle. Runtime must load this precompiled bundle; do not
compile ShaderLab from a string in the player.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Unity jobs go through the Unity queue (docs/unity_queue_runner.md): agents submit, not launch. --unity-direct is the
# explicit, loudly logged opt-out.
import importlib.util as _uq_ilu  # noqa: E402
_uq_spec = _uq_ilu.spec_from_file_location("unity_queue", Path(__file__).resolve().parents[1] / "unity_queue" / "unity_queue.py")
UQ = _uq_ilu.module_from_spec(_uq_spec)
_uq_spec.loader.exec_module(UQ)
UNITY_DIRECT = UQ.take_direct_flag()

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
UNITY = Path(
    os.environ.get(
        "UNITY_EDITOR",
        r"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe",
    )
)
PROJECT = Path(
    os.environ.get("HOMM2_SHADE_UNITY_PROJECT", r"V:\homm3_artifact_mesh_build")
)
OUT = SCRIPT_DIR / "build_out"
LOG = SCRIPT_DIR / "unity_homm2_shade_object_class_shader_bundle.log"
SHADER_SRC = SCRIPT_DIR / "unity_shaders" / "Homm2ShadeObjectClass.shader"
EDITOR_SRC = SCRIPT_DIR / "unity_editor" / "Homm2ShadeObjectClassShaderBundleBuild.cs"
BUNDLE_NAME = "homm2_shade_object_class"


def main() -> int:
    if not UNITY.is_file():
        print("Unity editor missing: " + str(UNITY), file=sys.stderr)
        return 1
    if not (PROJECT / "ProjectSettings" / "ProjectVersion.txt").is_file():
        print("Unity project missing: " + str(PROJECT), file=sys.stderr)
        return 1
    if not SHADER_SRC.is_file():
        print("Shader missing: " + str(SHADER_SRC), file=sys.stderr)
        return 1
    if not EDITOR_SRC.is_file():
        print("Editor script missing: " + str(EDITOR_SRC), file=sys.stderr)
        return 1

    shaders_dir = PROJECT / "Assets" / "Shaders"
    editor_dir = PROJECT / "Assets" / "Editor"
    shaders_dir.mkdir(parents=True, exist_ok=True)
    editor_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SHADER_SRC, shaders_dir / "Homm2ShadeObjectClass.shader")
    shutil.copy2(EDITOR_SRC, editor_dir / "Homm2ShadeObjectClassShaderBundleBuild.cs")

    OUT.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(UNITY),
        "-batchmode",
        "-quit",
        "-nographics",
        "-projectPath",
        str(PROJECT),
        "-buildTarget",
        "StandaloneWindows64",
        "-executeMethod",
        "OldenEra.Homm3Import.Homm2ShadeObjectClassShaderBundleBuild.BuildFromBatch",
        "-outputPath",
        str(OUT),
        "-logFile",
        str(LOG),
    ]
    print("Using Unity project: " + str(PROJECT))
    completed = UQ.run_cmd(cmd, kind="homm2_shade_shader_bundle", direct=UNITY_DIRECT)
    bundle = OUT / BUNDLE_NAME
    if completed.returncode != 0 or not bundle.is_file():
        print("Shader bundle build failed; see " + str(LOG), file=sys.stderr)
        return completed.returncode or 1
    print("Built " + str(bundle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
