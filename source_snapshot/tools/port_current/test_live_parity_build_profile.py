#!/usr/bin/env python3
"""Contract test for the live-parity stager's --build-profile mode.

Proves, on small synthetic files, that a build profile:
  * refuses a game root whose GameAssembly.dll is another build;
  * refuses profile sources that do not match their recorded sha256;
  * refuses an already-staged payload whose unity_data/metadata are another build's
    (the "Golden Era copy shipped onto the current build" downgrade);
  * accepts matching files.
It does not exercise the Golden Era default path, which is unchanged.

Run: python tools/port_current/test_live_parity_build_profile.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STAGER = REPO / "tools" / "release_installer" / "stage_golden_era_live_parity_payload.py"


def load_stager():
    spec = importlib.util.spec_from_file_location("stager", STAGER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def expect_fail(fn, label: str) -> None:
    try:
        fn()
    except SystemExit as e:
        if not str(e).startswith("FAIL"):
            raise
        print(f"ok refuses: {label}")
        return
    raise AssertionError(f"expected failure: {label}")


def main() -> int:
    st = load_stager()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        game = tmp / "game"
        game.mkdir()
        (game / "GameAssembly.dll").write_bytes(b"current-build")
        src = tmp / "patched"
        contents = {rel: f"patched {rel}".encode() for rel in st.PROFILE_FILES}
        files = {}
        for rel, data in contents.items():
            p = src / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            files[rel] = {"source": str(p), "sha256": sha(data)}  # absolute: REPO / abs == abs
        profile = {
            "schema": "live_parity_build_profile.v1",
            "buildid": "test",
            "gameAssemblySha256": sha(b"current-build"),
            "files": files,
        }
        prof_path = tmp / "profile.json"
        prof_path.write_text(json.dumps(profile), encoding="utf-8")
        loaded = st.load_build_profile(prof_path)

        st.assert_game_root_build(game, loaded)
        other = tmp / "other"
        other.mkdir()
        (other / "GameAssembly.dll").write_bytes(b"golden-era")
        expect_fail(lambda: st.assert_game_root_build(other, loaded), "game root of another build")

        stage = tmp / "stage"
        st.stage_profile_files(loaded, stage)
        st.assert_build_identity(stage, loaded)

        (stage / "payload" / "il2cpp_metadata" / "global-metadata.dat").write_bytes(b"golden-era meta")
        expect_fail(lambda: st.assert_build_identity(stage, loaded), "staged metadata of another build")

        (src / "unity_data" / "resources.assets").write_bytes(b"tampered")
        expect_fail(lambda: st.stage_profile_files(loaded, tmp / "stage2"), "tampered profile source")

        bad = dict(profile, files={k: v for k, v in files.items() if "metadata" not in k})
        bad_path = tmp / "bad.json"
        bad_path.write_text(json.dumps(bad), encoding="utf-8")
        expect_fail(lambda: st.load_build_profile(bad_path), "profile missing a file")
    print("PASS live-parity build-profile contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
