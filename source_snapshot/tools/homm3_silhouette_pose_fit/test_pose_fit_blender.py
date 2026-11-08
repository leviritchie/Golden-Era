"""Blender 3.5.1 must resolve to a real executable for GPU preview export."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from pose_fit_blender import ENV_NAME, resolve_pose_fit_blender


def run() -> dict[str, object]:
    blender = resolve_pose_fit_blender()
    assert blender.is_file(), blender
    assert blender.name.lower() == "blender.exe", blender
    probe = subprocess.run(
        [str(blender), "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    output = (probe.stdout or "") + (probe.stderr or "")
    assert probe.returncode == 0, output
    assert "Blender 3.5" in output, output

    missing = Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
    if not missing.is_file():
        try:
            resolve_pose_fit_blender(missing)
            raise AssertionError("an explicit missing path must fail closed")
        except FileNotFoundError as exc:
            assert str(missing) in str(exc), str(exc)

    previous = os.environ.get(ENV_NAME)
    os.environ[ENV_NAME] = str(missing)
    try:
        if not missing.is_file():
            try:
                resolve_pose_fit_blender()
                raise AssertionError("a missing HOMM3_POSE_FIT_BLENDER path must fail closed")
            except FileNotFoundError as exc:
                assert ENV_NAME in str(exc), str(exc)
    finally:
        if previous is None:
            os.environ.pop(ENV_NAME, None)
        else:
            os.environ[ENV_NAME] = previous

    return {"ok": True, "blender": str(blender), "version": output.splitlines()[0] if output else ""}


if __name__ == "__main__":
    print(run())
