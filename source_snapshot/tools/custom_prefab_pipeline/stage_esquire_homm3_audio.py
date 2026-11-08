#!/usr/bin/env python3
"""
Stage HoMM3 Complete Pikeman / Halberdier WAVs into the Unity project under
Assets/CustomUnits/esquire/sounds/ for import as AudioClips.

If you use build_esquire_bundle.cmd, the next Unity step runs
EsquireBattleSoundPrefabsBuild.RebuildFromBatch, which writes ESQUIRE_*.prefab
next to each WAV before AssetBundles are built.

Requires a Heroes3.snd (or HotA_lng.snd) path. Default guess: repo sibling
  ../../HoMM 3 Complete/Data/Heroes3.snd
relative to this script.

Does not require Unity — only writes .wav files under:
  <project>/Assets/CustomUnits/esquire/sounds/
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Repo tools/ (parent of custom_prefab_pipeline/) for extract_homm3_snd.py
_TOOLS = Path(__file__).resolve().parents[1]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from extract_homm3_snd import read_index  # noqa: E402


def _extract_one(snd_data: bytes, index: dict[str, tuple[int, int]], name: str) -> bytes:
    if name not in index:
        raise KeyError(name)
    off, sz = index[name]
    if off < 0 or sz <= 0 or off + sz > len(snd_data):
        raise ValueError(f"bad span for {name}: off={off} sz={sz}")
    return snd_data[off : off + sz]


def _emit(blob: bytes, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)


def _clone_to_names(blob: bytes, out_dir: Path, clip_names: list[str]) -> None:
    for cn in clip_names:
        _emit(blob, out_dir / f"{cn}.wav")


_PLUGIN_SFX = Path(__file__).resolve().parents[2] / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_upscaled_sfx"


def _upscaled_blob(clip_id: str, original: bytes) -> bytes:
    catalog = _PLUGIN_SFX / "catalog.json"
    path = _PLUGIN_SFX / "unique" / f"{clip_id}.wav"
    if path.is_file():
        return path.read_bytes()
    if catalog.is_file():
        raise SystemExit(f"stage_esquire_homm3_audio: catalog exists but missing upscaled clip {path}")
    return original


def stage(project_root: Path, snd_path: Path, halb: bool) -> None:
    out_dir = project_root / "Assets" / "CustomUnits" / "esquire" / "sounds"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = snd_path.read_bytes()
    idx = {n: (o, s) for n, o, s in read_index(snd_path)}

    pike_move = _upscaled_blob("PIKEMOVE", _extract_one(data, idx, "PIKEMOVE"))
    pike_attk = _upscaled_blob("PIKEATTK", _extract_one(data, idx, "PIKEATTK"))
    pike_wnce = _upscaled_blob("PIKEWNCE", _extract_one(data, idx, "PIKEWNCE"))
    pike_kill = _upscaled_blob("PIKEKILL", _extract_one(data, idx, "PIKEKILL"))

    _clone_to_names(
        pike_move,
        out_dir,
        [f"ESQUIRE_Walk_{i}" for i in range(1, 5)]
        + [f"ESQUIRE_Victory_A_{i}" for i in range(1, 9)]
        + [f"ESQUIRE_Victory_B_{i}" for i in range(1, 4)],
    )
    _clone_to_names(pike_attk, out_dir, [f"ESQUIRE_Attack_{i}" for i in range(1, 5)])
    _clone_to_names(pike_wnce, out_dir, [f"ESQUIRE_Damage_{i}" for i in range(1, 5)])
    for row in ("A", "B", "C"):
        _clone_to_names(
            pike_kill,
            out_dir,
            [f"ESQUIRE_Death_{row}_{i}" for i in range(1, 5)],
        )

    if halb:
        h_move = _upscaled_blob("HALBMOVE", _extract_one(data, idx, "HALBMOVE"))
        h_attk = _upscaled_blob("HALBATTK", _extract_one(data, idx, "HALBATTK"))
        h_wnce = _upscaled_blob("HALBWNCE", _extract_one(data, idx, "HALBWNCE"))
        h_kill = _upscaled_blob("HALBKILL", _extract_one(data, idx, "HALBKILL"))
        _clone_to_names(h_move, out_dir, [f"ESQUIRE_UPG_Walk_{i}" for i in range(1, 5)])
        _clone_to_names(h_attk, out_dir, [f"ESQUIRE_UPG_Attack_{i}" for i in range(1, 5)])
        _clone_to_names(h_wnce, out_dir, [f"ESQUIRE_UPG_Damage_{i}" for i in range(1, 5)])
        for row in ("A", "B", "C"):
            _clone_to_names(
                h_kill,
                out_dir,
                [f"ESQUIRE_UPG_Death_{row}_{i}" for i in range(1, 5)],
            )

    n = len(list(out_dir.glob("*.wav")))
    print(f"Wrote {n} .wav under {out_dir}")


def main() -> None:
    here = Path(__file__).resolve().parent
    default_snd = (here / ".." / ".." / "HoMM 3 Complete" / "Data" / "Heroes3.snd").resolve()
    ap = argparse.ArgumentParser(description="Stage Esquire battle WAVs from HoMM3 SND")
    ap.add_argument(
        "--unity-project",
        type=Path,
        required=True,
        help="Unity project root (contains Assets/ and ProjectSettings/)",
    )
    ap.add_argument(
        "--snd",
        type=Path,
        default=default_snd if default_snd.is_file() else None,
        help=f"path to Heroes3.snd (default: {default_snd})",
    )
    ap.add_argument(
        "--no-halberdier",
        action="store_true",
        help="skip ESQUIRE_UPG_* (HALB*) clips",
    )
    args = ap.parse_args()
    if not args.snd or not args.snd.is_file():
        ap.error("pass --snd path to Heroes3.snd (HoMM3 Complete Data folder)")
    proj = args.unity_project.resolve()
    if not (proj / "ProjectSettings").is_dir():
        ap.error(f"not a Unity project: {proj}")
    stage(proj, args.snd.resolve(), halb=not args.no_halberdier)


if __name__ == "__main__":
    main()
