#!/usr/bin/env python3
"""
Stage HoMM3 Heroes3.snd creature WAVs into the Unity lab for lane B:
  <project>/Assets/CustomUnits/homm3_lab/<unitSid>/sounds/

Clip stems follow the same layout as Esquire lane A (see stage_esquire_homm3_audio.py)
but with prefix HOMM3_<unitSid>_ so they match Homm3BattleSoundPrefabsBuild + runtime
Homm3LabBattleAudioPlayer.

Requires units_inventory.json row with:
  "sndBattlePrefix": "GRIF"   # HoMM3 SND logical name prefix (GRIFMOVE, GRIFATTK, …)

Optional: set HOMM3_SND to Heroes3.snd path; default is repo HoMM 3 Complete/Data/Heroes3.snd.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from extract_homm3_snd import read_index  # noqa: E402


def _absolute_no_resolve(path: Path) -> Path:
    return Path(os.path.abspath(path))


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


PLUGIN_SFX = Path(__file__).resolve().parents[2] / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_upscaled_sfx"


def _upscaled_blob(clip_id: str, original: bytes) -> bytes:
    catalog = PLUGIN_SFX / "catalog.json"
    path = PLUGIN_SFX / "unique" / f"{clip_id}.wav"
    if path.is_file():
        return path.read_bytes()
    if catalog.is_file():
        raise SystemExit(f"stage_homm3_unit_audio: catalog exists but missing upscaled clip {path}")
    return original


def _clone_to_names(blob: bytes, out_dir: Path, clip_names: list[str]) -> None:
    for cn in clip_names:
        _emit(blob, out_dir / f"{cn}.wav")


def _stage_blobs(
    *,
    unit_sid: str,
    out_dir: Path,
    blob_move: bytes,
    blob_attk: bytes,
    blob_wnce: bytes,
    blob_kill: bytes,
) -> int:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = f"HOMM3_{unit_sid}_"
    _clone_to_names(
        blob_move,
        out_dir,
        [f"{stem}Walk_{i}" for i in range(1, 5)]
        + [f"{stem}Victory_A_{i}" for i in range(1, 9)]
        + [f"{stem}Victory_B_{i}" for i in range(1, 4)],
    )
    _clone_to_names(blob_attk, out_dir, [f"{stem}Attack_{i}" for i in range(1, 5)])
    _clone_to_names(blob_wnce, out_dir, [f"{stem}Damage_{i}" for i in range(1, 5)])
    for row_letter in ("A", "B", "C"):
        _clone_to_names(
            blob_kill,
            out_dir,
            [f"{stem}Death_{row_letter}_{i}" for i in range(1, 5)],
        )

    return len(list(out_dir.glob("*.wav")))


def _inventory_path(script_dir: Path) -> Path:
    return script_dir / "units_inventory.json"


def _load_row(inventory: Path, unit_sid: str) -> dict:
    data = json.loads(inventory.read_text(encoding="utf-8-sig"))
    for u in data.get("units") or []:
        if u.get("unitSid") == unit_sid:
            return u
    raise SystemExit(f"stage_homm3_unit_audio: unitSid '{unit_sid}' not found in {inventory}")


def stage(
    *,
    unity_project: Path,
    unit_sid: str,
    snd_path: Path,
    inventory: Path,
) -> None:
    row = _load_row(inventory, unit_sid)
    sound_paths = row.get("soundPaths") or {}
    if sound_paths:
        root = inventory.resolve().parents[2]
        out_dir = unity_project / "Assets" / "CustomUnits" / "homm3_lab" / unit_sid / "sounds"

        def read_rel(key: str, *aliases: str) -> bytes:
            rel = sound_paths.get(key)
            for alias in aliases:
                rel = rel or sound_paths.get(alias)
            if not rel:
                raise KeyError(key)
            if "!" in rel:
                zip_rel, member = rel.split("!", 1)
                path = root / zip_rel
                with zipfile.ZipFile(path) as zf:
                    try:
                        return zf.read(member)
                    except KeyError:
                        by_lower = {name.lower(): name for name in zf.namelist()}
                        resolved = by_lower.get(member.lower())
                        if not resolved:
                            raise
                        return zf.read(resolved)
            path = root / rel
            return path.read_bytes()

        def clip_id_from_rel(key: str, *aliases: str) -> str:
            rel = sound_paths.get(key)
            for alias in aliases:
                rel = rel or sound_paths.get(alias)
            if not rel:
                raise KeyError(key)
            return Path(str(rel).split("!", 1)[-1]).stem.upper()

        blob_move = _upscaled_blob(clip_id_from_rel("move"), read_rel("move"))
        blob_attk = _upscaled_blob(clip_id_from_rel("attack"), read_rel("attack"))
        blob_wnce = _upscaled_blob(clip_id_from_rel("wince", "wnce", "damage"), read_rel("wince", "wnce", "damage"))
        blob_kill = _upscaled_blob(clip_id_from_rel("killed", "kill", "death"), read_rel("killed", "kill", "death"))
        n = _stage_blobs(
            unit_sid=unit_sid,
            out_dir=out_dir,
            blob_move=blob_move,
            blob_attk=blob_attk,
            blob_wnce=blob_wnce,
            blob_kill=blob_kill,
        )
        print(f"stage_homm3_unit_audio: wrote {n} .wav under {out_dir} (loose soundPaths)")
        return

    prefix = (row.get("sndBattlePrefix") or "").strip()
    if not prefix:
        print(
            f"stage_homm3_unit_audio: skip (no sndBattlePrefix in units_inventory for '{unit_sid}')",
            file=sys.stderr,
        )
        return

    move = prefix + "MOVE"
    attk = prefix + "ATTK"
    wnce = prefix + "WNCE"
    kill = prefix + "KILL"

    out_dir = unity_project / "Assets" / "CustomUnits" / "homm3_lab" / unit_sid / "sounds"

    data = snd_path.read_bytes()
    idx = {n: (o, s) for n, o, s in read_index(snd_path)}

    blob_move = _upscaled_blob(move, _extract_one(data, idx, move))
    blob_attk = _upscaled_blob(attk, _extract_one(data, idx, attk))
    blob_wnce = _upscaled_blob(wnce, _extract_one(data, idx, wnce))
    blob_kill = _upscaled_blob(kill, _extract_one(data, idx, kill))

    n = _stage_blobs(
        unit_sid=unit_sid,
        out_dir=out_dir,
        blob_move=blob_move,
        blob_attk=blob_attk,
        blob_wnce=blob_wnce,
        blob_kill=blob_kill,
    )
    print(f"stage_homm3_unit_audio: wrote {n} .wav under {out_dir} (SND keys {move}, {attk}, {wnce}, {kill})")


def main() -> int:
    here = Path(__file__).resolve().parent
    default_snd = (here.parent.parent / "HoMM 3 Complete" / "Data" / "Heroes3.snd").resolve()
    ap = argparse.ArgumentParser(description="Stage HoMM3 SND battle WAVs for homm3_lab unit")
    ap.add_argument("--unity-project", type=Path, required=True)
    ap.add_argument("--unit", type=str, required=True, help="unitSid (homm3_lab folder name)")
    ap.add_argument("--snd", type=Path, default=None, help="Heroes3.snd path")
    ap.add_argument(
        "--inventory",
        type=Path,
        default=None,
        help="units_inventory.json (default: next to this script)",
    )
    args = ap.parse_args()

    inv = (args.inventory or _inventory_path(here)).resolve()
    row = _load_row(inv, args.unit.strip())
    has_zip_or_loose_sound_paths = bool(row.get("soundPaths"))
    snd = args.snd or (default_snd if default_snd.is_file() else None)
    if not has_zip_or_loose_sound_paths and (snd is None or not snd.is_file()):
        print(
            "stage_homm3_unit_audio: skip (no Heroes3.snd — set --snd or install HoMM 3 Complete beside repo)",
            file=sys.stderr,
        )
        return 0

    try:
        stage(
            unity_project=_absolute_no_resolve(args.unity_project),
            unit_sid=args.unit.strip(),
            snd_path=snd.resolve() if snd is not None else default_snd,
            inventory=inv,
        )
    except (KeyError, OSError, ValueError) as ex:
        print(f"stage_homm3_unit_audio: {ex}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
