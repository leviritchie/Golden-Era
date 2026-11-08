#!/usr/bin/env python3
"""Validate that custom IMGUI UI elements scale with screen resolution.

Reference pattern: Castle Elite Strategem indicator
(Homm3CastleEliteStrategemRuntime.cs) scales height-relative against a 720p
reference with a 0.75-3 clamp. Sister UIs must follow the same shape instead
of stalling at fixed caps or fixed-pixel margins/borders.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def read_text(path: Path, errors: list[str]) -> str:
    if not path.is_file():
        errors.append(f"missing required file: {path}")
        return ""
    return path.read_text(encoding="utf-8-sig", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--plugin-dir", type=Path)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    plugin_dir = (args.plugin_dir or (repo_root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod")).resolve()
    castle_path = plugin_dir / "Homm3CastleEliteStrategemRuntime.cs"
    skeletal_path = plugin_dir / "Homm3SkeletalNecromancyProbe.cs"
    inspector_path = plugin_dir / "Homm3UiInspectorOverlay.cs"
    toggle_path = plugin_dir / "Homm3HomecomingLayerViewToggle.cs"
    csproj_path = plugin_dir / "OfflineUnlockMod.csproj"

    errors: list[str] = []
    castle = read_text(castle_path, errors)
    skeletal = read_text(skeletal_path, errors)
    inspector = read_text(inspector_path, errors)
    toggle = read_text(toggle_path, errors)
    csproj = read_text(csproj_path, errors)

    # Castle reference pattern must stay intact.
    require("ReferenceHeight = 720f" in castle, "castle indicator must keep the 720p reference height", errors)
    require("Screen.height / ReferenceHeight, MinimumScale, MaximumScale" in castle, "castle indicator must keep height-relative clamped scaling", errors)

    # Necropolis sister dialog must match the castle scale range, not stall at 1.25x.
    require("Screen.height / 720f, 0.75f, 3f" in skeletal, "skeletal notification must scale height-relative with a 0.75-3 clamp like castle", errors)
    require("Screen.width / 1280f" not in skeletal, "skeletal notification must not use the old width-capped min() scale", errors)
    require("0.75f, 1.25f" not in skeletal, "skeletal notification must not keep the old 1.25x scale cap", errors)
    require("16f * scale, 12f, 48f" in skeletal, "skeletal notification must use a scaled screen margin", errors)
    require("Screen.height / 180, 4, 12" in skeletal, "skeletal notification font bucket must cover high-DPI heights", errors)
    require("bucket * 4, 18, 44" in skeletal, "skeletal notification body font must keep growing past 28px", errors)

    # Inspector overlay must shrink on low-res screens and scale its border.
    require("Screen.height / 1080f, 0.65f, 2.25f" in inspector, "inspector overlay must allow sub-1x scale for low-res screens", errors)
    require("Screen.height / 1080f, 1f, 2.25f" not in inspector, "inspector overlay must not keep the 1.0 low-res floor", errors)
    require("2f * UiScale()" in inspector, "inspector overlay border must scale with resolution", errors)
    require("rect.width, 2f), s_borderTexture" not in inspector, "inspector overlay must not keep fixed 2px horizontal borders", errors)
    require("2f, rect.height), s_borderTexture" not in inspector, "inspector overlay must not keep fixed 2px vertical borders", errors)

    # Homecoming toggle margin must scale with resolution like its size does.
    require("var margin = ButtonMargin * (UiScale() / DisplayMultiplier);" in toggle, "homecoming toggle must derive a scaled margin", errors)
    require("Screen.width - size - margin" in toggle, "homecoming toggle rect must use the scaled margin", errors)

    require("ValidateHomm3UiScaleContract" in csproj, "OfflineUnlockMod.csproj must run the UI scale validator", errors)
    require("validate_homm3_ui_scale_contract.py" in csproj, "OfflineUnlockMod.csproj must reference the UI scale validator script", errors)

    if errors:
        print("HoMM3 UI scale contract validation failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("HoMM3 UI scale contract validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
