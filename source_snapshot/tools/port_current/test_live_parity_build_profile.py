#!/usr/bin/env python3
"""Contract test for the live-parity stager's --build-profile mode.

Proves, on small synthetic files, that a build profile:
  * refuses a game root whose GameAssembly.dll is another build;
  * refuses profile sources that do not match their recorded sha256;
  * refuses an already-staged payload whose unity_data/metadata are another build's
    (the "Golden Era copy shipped onto the current build" downgrade);
  * accepts matching files.
It does not exercise the Golden Era default path, which is unchanged.

It also checks every committed tools/port_current/live_parity_build_<buildid>.json against its
frozen mirror manifest: buildid, depotManifest, GameAssembly.dll sha256 and each file's base
(mirror path, size, sha256) must match. --verify-sources BUILDID additionally requires that
profile's patched sources (gitignored, under artifacts/port_current/patched_<buildid>/) to exist
with the recorded size and sha256; other profiles' sources are not read.

Run: python tools/port_current/test_live_parity_build_profile.py [--verify-sources 26297049]
"""
from __future__ import annotations

import argparse
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


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def check_committed_profiles(st, verify_sources: set[str]) -> None:
    profiles = sorted((REPO / "tools" / "port_current").glob("live_parity_build_*.json"))
    if not profiles:
        raise AssertionError("no committed live_parity_build_*.json profiles found")
    for path in profiles:
        profile = st.load_build_profile(path)
        build = path.stem.removeprefix("live_parity_build_")
        if profile.get("buildid") != build:
            raise AssertionError(f"{path.name}: buildid {profile.get('buildid')!r} does not match its file name")
        manifest_path = REPO / profile.get("mirrorManifest", "")
        if not manifest_path.is_file():
            raise AssertionError(f"{path.name}: mirrorManifest {profile.get('mirrorManifest')!r} missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mbuild = manifest["build"]
        if mbuild.get("buildid") != build:
            raise AssertionError(f"{path.name}: mirror manifest is build {mbuild.get('buildid')!r}")
        if profile.get("depotManifest") != mbuild.get("depotManifest"):
            raise AssertionError(
                f"{path.name}: depotManifest {profile.get('depotManifest')!r} != mirror {mbuild.get('depotManifest')!r}"
            )
        mfiles = {e["path"]: e for e in manifest["files"]}
        ga = mfiles.get("GameAssembly.dll")
        if not ga or ga["sha256"] != profile["gameAssemblySha256"]:
            raise AssertionError(f"{path.name}: gameAssemblySha256 does not match the mirror's GameAssembly.dll")
        for rel, spec in sorted(profile["files"].items()):
            base = spec.get("base") or {}
            entry = mfiles.get(base.get("mirrorPath"))
            if not entry or (entry["size"], entry["sha256"]) != (base.get("size"), base.get("sha256")):
                raise AssertionError(f"{path.name}: {rel} base does not match mirror entry {base.get('mirrorPath')!r}")
            if not isinstance(spec.get("size"), int) or len(spec.get("sha256", "")) != 64:
                raise AssertionError(f"{path.name}: {rel} lacks a patched size/sha256")
            if build in verify_sources:
                src = REPO / spec["source"]
                if not src.is_file():
                    raise AssertionError(f"{path.name}: {rel} source missing: {src}")
                if src.stat().st_size != spec["size"] or sha_file(src) != spec["sha256"]:
                    raise AssertionError(f"{path.name}: {rel} source {src} does not match its recorded size/sha256")
        what = "mirror manifest + patched sources" if build in verify_sources else "mirror manifest"
        print(f"ok profile {path.name} matches its {what}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--verify-sources", action="append", default=[], metavar="BUILDID",
        help="also hash this build profile's patched sources (repeatable)",
    )
    args = ap.parse_args()
    st = load_stager()
    unknown = set(args.verify_sources) - {
        p.stem.removeprefix("live_parity_build_") for p in (REPO / "tools" / "port_current").glob("live_parity_build_*.json")
    }
    if unknown:
        raise AssertionError(f"--verify-sources names no committed profile: {sorted(unknown)}")
    check_committed_profiles(st, set(args.verify_sources))
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
