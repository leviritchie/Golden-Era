#!/usr/bin/env python3
"""Collect unique custom-unit battle SFX, UniverSR them, and emit the plugin cache.

Work files stay on F:/olden_era_audio_upscale. The plugin payload is
OfflineUnlockMod/homm3_upscaled_sfx/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1]
_REPO = _TOOLS.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from extract_homm3_snd import read_index  # noqa: E402

INVENTORY = _TOOLS / "homm3_import" / "units_inventory.json"
IMPORT_JSON = _REPO / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_import.json"
PLUGIN_DIR = _REPO / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
WORK = Path(r"F:\olden_era_audio_upscale")
UNIQUE_PCM = WORK / "unique_pcm"
UNIQUE_OUT = WORK / "unique_cache"
PLUGIN_SFX = PLUGIN_DIR / "homm3_upscaled_sfx"

SND_DIRS = [
    _REPO / "HoMM 3 Complete" / "Data" / "Heroes3.snd",
    _REPO / "HoMM 3 Complete" / "Data" / "H3ab_ahd.snd",
    _REPO / "HoMM 3 Complete" / "Data" / "HotA.snd",
    _REPO / "HoMM 3 Complete" / "Data" / "HotA_lng.snd",
]
REQUIRED_ROLES = ("attack", "move", "wince", "killed")
SUFFIX_ROLE = {
    "ATTK": "attack",
    "DFND": "defend",
    "KILL": "killed",
    "MOVE": "move",
    "WNCE": "wince",
    "SHOT": "shot",
}
PATH_ROLE_ALIASES = {
    "attack": "attack",
    "attk": "attack",
    "move": "move",
    "wince": "wince",
    "wnce": "wince",
    "damage": "wince",
    "killed": "killed",
    "kill": "killed",
    "death": "killed",
    "defend": "defend",
    "dfnd": "defend",
    "shot": "shot",
}

CANNON_FILES = [
    PLUGIN_DIR / "homm3_runtime_assets" / "cannon" / "homm3_cove" / "sounds" / "hota" / "cannon" / "CANNSHOT.wav",
    PLUGIN_DIR / "homm3_runtime_assets" / "cannon" / "homm3_cove" / "sounds" / "hota" / "cannon" / "CANNKILL.wav",
    PLUGIN_DIR / "homm3_runtime_assets" / "cannon" / "homm3_cove" / "sounds" / "hota" / "cannon" / "CANNWNCE.wav",
]
PIRATE_SHOT = (
    PLUGIN_DIR
    / "homm3_runtime_assets"
    / "cove"
    / "homm3_cove"
    / "sounds"
    / "hota"
    / "cove"
    / "creatures"
    / "pirate"
    / "PIRTSHOT.wav"
)


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def lab_sid_from_prefab(path: str | None) -> str | None:
    if not path:
        return None
    p = path.replace("\\", "/")
    needle = "/homm3_lab/"
    i = p.lower().find(needle)
    if i < 0:
        return None
    rest = p[i + len(needle) :]
    return rest.split("/", 1)[0].strip() or None


def load_snd_indexes() -> list[tuple[Path, bytes, dict[str, tuple[int, int]]]]:
    out: list[tuple[Path, bytes, dict[str, tuple[int, int]]]] = []
    for path in SND_DIRS:
        if not path.is_file():
            continue
        data = path.read_bytes()
        idx = {n: (o, s) for n, o, s in read_index(path)}
        out.append((path, data, idx))
    if not out:
        raise SystemExit("no Heroes3/HotA .snd archives found")
    return out


def find_snd(indexes, name: str) -> tuple[Path, bytes] | None:
    for path, data, idx in indexes:
        if name in idx:
            off, sz = idx[name]
            return path, data[off : off + sz]
    return None


def names_for_prefix(indexes, prefix: str) -> list[str]:
    found: set[str] = set()
    for _path, _data, idx in indexes:
        for name in idx:
            if name.startswith(prefix):
                found.add(name)
    ordered: list[str] = []
    for suffix in ("ATTK", "DFND", "KILL", "MOVE", "WNCE", "SHOT"):
        n = prefix + suffix
        if n in found:
            ordered.append(n)
            found.remove(n)
    ordered.extend(sorted(found))
    return ordered


def read_sound_path(rel: str) -> bytes:
    if "!" in rel:
        zip_rel, member = rel.split("!", 1)
        path = _REPO / zip_rel
        with zipfile.ZipFile(path) as zf:
            try:
                return zf.read(member)
            except KeyError:
                by_lower = {n.lower(): n for n in zf.namelist()}
                resolved = by_lower.get(member.lower())
                if not resolved:
                    raise
                return zf.read(resolved)
    path = _REPO / rel
    return path.read_bytes()


def decode_to_pcm(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-c:a",
            "pcm_s16le",
            str(dest),
        ],
        check=True,
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def collect_units() -> tuple[dict[str, dict[str, str]], dict[str, dict]]:
    """Return (units[labSid][role]=clip_id, clips[clip_id]=meta)."""
    inv = load_json(INVENTORY)
    import_table = load_json(IMPORT_JSON)
    inv_by_sid = {
        u["unitSid"]: u
        for u in (inv.get("units") or [])
        if isinstance(u, dict) and isinstance(u.get("unitSid"), str)
    }
    indexes = load_snd_indexes()
    units: dict[str, dict[str, str]] = {}
    clips: dict[str, dict] = {}

    def add_clip(clip_id: str, *, kind: str, **meta) -> None:
        if clip_id not in clips:
            clips[clip_id] = {"id": clip_id, "kind": kind, **meta}

    def add_unit_role(lab_sid: str, role: str, clip_id: str) -> None:
        units.setdefault(lab_sid, {})
        units[lab_sid][role] = clip_id

    for entry in import_table.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        lab_sid = lab_sid_from_prefab(entry.get("battlePrefabAssetPath"))
        if not lab_sid:
            continue
        row = inv_by_sid.get(lab_sid)
        if not row:
            continue
        sound_paths = row.get("soundPaths") or {}
        if sound_paths:
            for key, rel in sound_paths.items():
                if not isinstance(key, str) or not isinstance(rel, str):
                    continue
                role = PATH_ROLE_ALIASES.get(key.lower())
                if not role:
                    continue
                clip_id = Path(rel.split("!", 1)[-1]).stem.upper()
                add_clip(clip_id, kind="loose", rel=rel)
                add_unit_role(lab_sid, role, clip_id)
            continue
        prefix = (row.get("sndBattlePrefix") or "").strip()
        if not prefix:
            continue
        for name in names_for_prefix(indexes, prefix):
            suffix = name[len(prefix) :]
            role = SUFFIX_ROLE.get(suffix)
            if role is None:
                continue
            add_clip(name, kind="snd", snd_name=name)
            add_unit_role(lab_sid, role, name)

    for name in ("PIKEMOVE", "PIKEATTK", "PIKEWNCE", "PIKEKILL", "HALBMOVE", "HALBATTK", "HALBWNCE", "HALBKILL"):
        add_clip(name, kind="snd", snd_name=name)
    add_unit_role(
        "esquire",
        "move",
        "PIKEMOVE",
    )
    add_unit_role("esquire", "attack", "PIKEATTK")
    add_unit_role("esquire", "wince", "PIKEWNCE")
    add_unit_role("esquire", "killed", "PIKEKILL")
    add_unit_role("esquire_upg", "move", "HALBMOVE")
    add_unit_role("esquire_upg", "attack", "HALBATTK")
    add_unit_role("esquire_upg", "wince", "HALBWNCE")
    add_unit_role("esquire_upg", "killed", "HALBKILL")

    extra_files = [
        ("CANNSHOT", CANNON_FILES[0], "shot"),
        ("CANNKILL", CANNON_FILES[1], "killed"),
        ("CANNWNCE", CANNON_FILES[2], "wince"),
        ("PIRTSHOT", PIRATE_SHOT, "shot"),
    ]
    for clip_id, path, role in extra_files:
        if path.is_file():
            add_clip(clip_id, kind="plugin_wav", path=str(path))
            owner = "h3_cannon" if clip_id.startswith("CANN") else "hota_cove_pirate"
            add_unit_role(owner, role, clip_id)
            if clip_id == "CANNSHOT":
                add_unit_role("h3_cannon", "attack", clip_id)
            if clip_id.startswith("CANN"):
                add_unit_role("hota_cove_cannon", role, clip_id)
                if clip_id == "CANNSHOT":
                    add_unit_role("hota_cove_cannon", "attack", clip_id)

    return units, clips, indexes


def extract_clips(clips: dict[str, dict], indexes) -> list[str]:
    UNIQUE_PCM.mkdir(parents=True, exist_ok=True)
    raw_dir = WORK / "unique_source"
    raw_dir.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    for clip_id, meta in sorted(clips.items()):
        pcm = UNIQUE_PCM / f"{clip_id}.wav"
        if pcm.is_file() and pcm.stat().st_size > 44:
            continue
        try:
            if meta["kind"] == "snd":
                found = find_snd(indexes, meta["snd_name"])
                if found is None:
                    missing.append(f"{clip_id}: missing SND {meta['snd_name']}")
                    continue
                raw = raw_dir / f"{clip_id}.wav"
                raw.write_bytes(found[1])
                decode_to_pcm(raw, pcm)
            elif meta["kind"] == "loose":
                raw = raw_dir / f"{clip_id}.wav"
                raw.write_bytes(read_sound_path(meta["rel"]))
                decode_to_pcm(raw, pcm)
            elif meta["kind"] == "plugin_wav":
                decode_to_pcm(Path(meta["path"]), pcm)
            else:
                missing.append(f"{clip_id}: unknown kind {meta['kind']}")
        except Exception as ex:
            missing.append(f"{clip_id}: {ex}")
    return missing


def enhance_clips(clip_ids: list[str]) -> None:
    import soundfile as sf
    import torch
    import torchaudio
    from universr import UniverSR

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"UniverSR device={device}")
    torch.manual_seed(0)
    if device == "cuda":
        torch.cuda.manual_seed_all(0)
    model = UniverSR.from_pretrained("woongzip1/universr-audio", device=device)
    UNIQUE_OUT.mkdir(parents=True, exist_ok=True)
    hash_done: dict[str, Path] = {}
    for clip_id in clip_ids:
        src = UNIQUE_PCM / f"{clip_id}.wav"
        dest = UNIQUE_OUT / f"{clip_id}.wav"
        if dest.is_file() and dest.stat().st_size > 44:
            print(f"skip existing {clip_id}")
            continue
        digest = sha256_file(src)
        if digest in hash_done:
            shutil.copy2(hash_done[digest], dest)
            print(f"reuse hash {clip_id} <- {hash_done[digest].stem}")
            continue
        data, sr = sf.read(str(src), dtype="float32", always_2d=True)
        wav = torch.from_numpy(data.T.copy())
        if wav.shape[0] > 1:
            wav = wav.mean(dim=0, keepdim=True)
        model_in = wav if sr == 24000 else torchaudio.functional.resample(wav, orig_freq=sr, new_freq=24000)
        enhanced = model.enhance(
            model_in,
            input_sr=24000,
            ode_method="midpoint",
            ode_steps=4,
            guidance_scale=1.5,
        )
        if enhanced.dim() == 1:
            enhanced = enhanced.unsqueeze(0)
        enhanced = enhanced.detach().cpu().float()
        sf.write(str(dest), enhanced.numpy().T, 48000, subtype="PCM_16")
        hash_done[digest] = dest
        print(f"enhanced {clip_id}: {sr} Hz -> 48000 Hz / {enhanced.shape[-1]} samples")


def write_catalog(units: dict[str, dict[str, str]], clips: dict[str, dict]) -> Path:
    catalog = {
        "version": 1,
        "model": "woongzip1/universr-audio",
        "targetSr": 48000,
        "stemRole": {
            "Attack": "attack",
            "Walk": "move",
            "Victory": "move",
            "Damage": "wince",
            "Death": "killed",
            "Shot": "shot",
        },
        "clips": {
            clip_id: f"unique/{clip_id}.wav"
            for clip_id in sorted(clips)
            if (UNIQUE_OUT / f"{clip_id}.wav").is_file()
        },
        "units": units,
    }
    PLUGIN_SFX.mkdir(parents=True, exist_ok=True)
    unique_plugin = PLUGIN_SFX / "unique"
    if unique_plugin.exists():
        shutil.rmtree(unique_plugin)
    unique_plugin.mkdir(parents=True, exist_ok=True)
    for clip_id in catalog["clips"]:
        shutil.copy2(UNIQUE_OUT / f"{clip_id}.wav", unique_plugin / f"{clip_id}.wav")
    path = PLUGIN_SFX / "catalog.json"
    path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    (WORK / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    return path


def copy_loose_overrides(units: dict[str, dict[str, str]]) -> None:
    mapping = [
        ("hota_cove_cannon", "shot", CANNON_FILES[0]),
        ("hota_cove_cannon", "killed", CANNON_FILES[1]),
        ("hota_cove_cannon", "wince", CANNON_FILES[2]),
        ("hota_cove_pirate", "shot", PIRATE_SHOT),
    ]
    for lab_sid, role, dest in mapping:
        clip_id = units.get(lab_sid, {}).get(role)
        if not clip_id:
            continue
        src = UNIQUE_OUT / f"{clip_id}.wav"
        if not src.is_file() or not dest.parent.is_dir():
            continue
        shutil.copy2(src, dest)
        ref = Path(str(dest).replace("homm3_runtime_assets", "reference_pack"))
        if ref.parent.is_dir():
            shutil.copy2(src, ref)
        print(f"replaced {dest}")


def main() -> int:
    os.environ.setdefault("HF_HOME", r"F:\olden_era_audio_upscale\hf_cache")
    os.environ.setdefault("HF_HUB_CACHE", r"F:\olden_era_audio_upscale\hf_cache\hub")
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect-only", action="store_true")
    args = ap.parse_args()

    units, clips, indexes = collect_units()
    missing_roles: list[str] = []
    for lab_sid, roles in sorted(units.items()):
        if lab_sid in ("hota_cove_cannon", "hota_cove_pirate", "h3_cannon"):
            continue
        for role in REQUIRED_ROLES:
            if role not in roles:
                missing_roles.append(f"{lab_sid}: missing {role}")
    print(f"units={len(units)} unique_clips={len(clips)}")
    if missing_roles:
        print("missing required roles:", file=sys.stderr)
        for row in missing_roles:
            print(f"  {row}", file=sys.stderr)
        return 1
    extract_errors = extract_clips(clips, indexes)
    if extract_errors:
        print("extract errors:", file=sys.stderr)
        for row in extract_errors:
            print(f"  {row}", file=sys.stderr)
        return 1
    print(f"extracted {len(list(UNIQUE_PCM.glob('*.wav')))} unique PCM clips")
    if args.collect_only:
        return 0
    enhance_clips(sorted(clips))
    catalog_path = write_catalog(units, clips)
    copy_loose_overrides(units)
    print(f"wrote {catalog_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
