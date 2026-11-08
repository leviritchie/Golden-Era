#!/usr/bin/env python3
"""Extract HoMM3 campaign video voiceover text (H3C scenario prologText).

VCMI CampaignHandler order per scenario:
  mapName, packedSize, preconditions, color, difficulty,
  regionText (campaign-map blurb),
  prolog {has, video, music, prologText},  # <-- spoken video text
  epilog {...},
  travel options (variable; skipped by anchoring the next map name).

Clip keys are keyed by map filename (Secret-1b → SecretB) even when H3C
scenario order is Secret-1a, Secret-1c, Secret-1b.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import struct
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOD = ROOT / "HoMM 3 Complete" / "Data" / "H3bitmap.lod"
DEFAULT_OUT = Path(__file__).with_name("roe_video_prologue_transcripts.v1.json")

MAP_TO_CLIP = {
    "good-1a.h3m": "Good1a",
    "good-1b.h3m": "Good1b",
    "good-1c.h3m": "Good1c",
    "good-2a.h3m": "Good2a",
    "good-2b.h3m": "Good2b",
    "good-2c.h3m": "Good2c",
    "good-2d.h3m": "Good2d",
    "good-3a.h3m": "Good3a",
    "good-3b.h3m": "Good3b",
    "good-3c.h3m": "Good3c",
    "evil-1a.h3m": "Evil1a",
    "evil-1b.h3m": "Evil1b",
    "evil-1c.h3m": "Evil1c",
    "evil-2a.h3m": "Evil2a",
    "evil-2b.h3m": "Evil2b",
    "evil-2c.h3m": "Evil2c",
    "evil-2d.h3m": "Evil2d",
    "secret-1a.h3m": "SecretA",
    "secret-1b.h3m": "SecretB",
    "secret-1c.h3m": "SecretC",
    "neutral-1a.h3m": "NeutralA",
    "neutral-1b.h3m": "NeutralB",
    "neutral-1c.h3m": "NeutralC",
}

CAMPAIGNS = (
    "Good1.h3c",
    "Good2.h3c",
    "Good3.h3c",
    "evil1.h3c",
    "Evil2.h3c",
    "Secret1.h3c",
    "Neutral1.h3c",
)


class _Reader:
    def __init__(self, blob: bytes) -> None:
        self.b = blob
        self.i = 0

    def u8(self) -> int:
        v = self.b[self.i]
        self.i += 1
        return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.b, self.i)[0]
        self.i += 4
        return v

    def bool(self) -> bool:
        return self.u8() != 0

    def s(self) -> str:
        n = self.u32()
        if n > 2_000_000 or self.i + n > len(self.b):
            raise ValueError(f"bad str n={n} at {self.i}")
        raw = self.b[self.i : self.i + n]
        self.i += n
        return raw.split(b"\x00", 1)[0].decode("cp1252", "replace")


def _read_lod_entries(lod: Path) -> dict[str, tuple[int, int]]:
    data = lod.read_bytes()
    count = struct.unpack_from("<I", data, 8)[0]
    pos = 92
    entries: dict[str, tuple[int, int]] = {}
    for _ in range(count):
        name = data[pos : pos + 16].split(b"\x00", 1)[0].decode("ascii", "replace")
        offset, size_full, _, _ = struct.unpack_from("<IIII", data, pos + 16)
        entries[name.lower()] = (offset, size_full)
        pos += 32
    return entries


def extract_lod_entry(lod: Path, entry_name: str) -> bytes:
    entries = _read_lod_entries(lod)
    key = entry_name.lower()
    if key not in entries:
        raise FileNotFoundError(f"{entry_name} not in {lod}")
    offset, size = entries[key]
    blob = lod.read_bytes()[offset : offset + size]
    if blob[:2] == b"\x1f\x8b":
        return gzip.GzipFile(fileobj=io.BytesIO(blob)).read()
    return blob


def discover_maps(blob: bytes, *, limit: int = 12000) -> list[tuple[int, str]]:
    maps: list[tuple[int, str]] = []
    i = 0
    region = blob[:limit]
    while True:
        j = region.find(b".h3m", i)
        if j < 0:
            break
        for back in range(4, 40):
            off = j - back
            if off < 0:
                continue
            length = struct.unpack_from("<I", blob, off)[0]
            if length == back and 5 <= length <= 24:
                name = blob[off + 4 : off + 4 + length].decode("ascii", "replace")
                if name.lower().endswith(".h3m"):
                    maps.append((off, name))
                break
        i = j + 1
    return maps


def _read_prolog_epilog(reader: _Reader) -> dict[str, Any]:
    has = reader.bool()
    if not has:
        return {"has": False, "video": None, "music": None, "text": ""}
    return {
        "has": True,
        "video": reader.u8(),
        "music": reader.u8(),
        "text": reader.s(),
    }


def parse_campaign(blob: bytes) -> dict[str, Any]:
    maps = discover_maps(blob)
    if not maps:
        raise ValueError("no scenario map names found in H3C header")
    reader = _Reader(blob)
    version = reader.u32()
    map_id = reader.u8()
    name = reader.s()
    desc = reader.s()
    save = reader.i
    last_err: Exception | None = None
    for with_diff in (True, False):
        try:
            reader.i = save
            if with_diff:
                reader.bool()
            music = reader.u8()
            scenarios: list[dict[str, Any]] = []
            for idx, (_off, map_name) in enumerate(maps):
                pref = struct.pack("<I", len(map_name)) + map_name.encode("ascii")
                at = blob.find(pref, reader.i)
                if at < 0:
                    raise ValueError(f"missing map {map_name}")
                reader.i = at
                got = reader.s()
                if got != map_name:
                    raise ValueError(f"expected {map_name} got {got}")
                packed = reader.u32()
                _pre = reader.u8()
                _color = reader.u8()
                _diff = reader.u8()
                region = reader.s()
                prolog = _read_prolog_epilog(reader)
                epilog = _read_prolog_epilog(reader)
                clip = MAP_TO_CLIP.get(map_name.lower())
                if clip is None:
                    raise ValueError(f"unmapped map filename {map_name}")
                scenarios.append(
                    {
                        "clip": clip,
                        "mapName": map_name,
                        "packedSize": packed,
                        "regionText": region,
                        "prolog": prolog,
                        "epilog": epilog,
                    }
                )
                if idx + 1 < len(maps):
                    nxt = maps[idx + 1][1]
                    pref = struct.pack("<I", len(nxt)) + nxt.encode("ascii")
                    at = blob.find(pref, reader.i)
                    if at < 0 or at - reader.i > 500:
                        raise ValueError(f"travel gap to {nxt} invalid (at={at})")
                    reader.i = at
            return {
                "version": version,
                "mapId": map_id,
                "name": name,
                "description": desc,
                "withDiff": with_diff,
                "music": music,
                "scenarios": scenarios,
            }
        except Exception as exc:  # noqa: BLE001 — try alternate header layout
            last_err = exc
            continue
    raise RuntimeError(f"H3C parse failed: {last_err}")


def extract_all(lod: Path) -> dict[str, Any]:
    clips: dict[str, Any] = {}
    parse_meta: dict[str, Any] = {}
    for camp in CAMPAIGNS:
        parsed = parse_campaign(extract_lod_entry(lod, camp))
        parse_meta[camp] = {
            k: parsed[k] for k in ("version", "name", "withDiff", "music", "mapId")
        }
        for scenario in parsed["scenarios"]:
            prolog = scenario["prolog"]
            clips[scenario["clip"]] = {
                "campaign": camp,
                "mapName": scenario["mapName"],
                "regionText": scenario["regionText"],
                "prologText": prolog["text"] if prolog["has"] else "",
                "hasProlog": prolog["has"],
                "prologVideoId": prolog.get("video"),
                "prologMusicId": prolog.get("music"),
                "chars": len(prolog["text"]) if prolog["has"] else 0,
            }
    expected = set(MAP_TO_CLIP.values())
    missing = sorted(expected - set(clips))
    if missing:
        raise RuntimeError(f"missing clips after extract: {missing}")
    return {
        "schema": "homm3.roe_video_prologue_transcripts.v1",
        "source": str(lod.resolve()),
        "note": (
            "prologText = H3C scenario prolog (video voiceover). "
            "regionText = campaign-map blurb. Do not softsub regionText."
        ),
        "clips": clips,
        "parse": parse_meta,
    }


def normalize_prolog(text: str) -> str:
    """Compare voiceover strings ignoring curly apostrophes / whitespace drift."""
    return " ".join(
        text.replace("\u2019", "'").replace("\u2018", "'").replace("\x92", "'").split()
    )


def _precon_byte_count(scenario_count: int) -> int:
    if scenario_count <= 0:
        raise ValueError("scenario_count must be positive")
    return (scenario_count + 7) // 8


def _find_map_name(blob: bytes, map_name: str) -> int:
    pref = struct.pack("<I", len(map_name)) + map_name.encode("ascii")
    at = blob.find(pref)
    if at < 0:
        raise FileNotFoundError(f"map name {map_name!r} not found in H3C")
    return at


def _parse_scenario_at(
    blob: bytes,
    *,
    at: int,
    map_name: str,
    scenario_count: int,
) -> dict[str, Any]:
    reader = _Reader(blob)
    reader.i = at
    got = reader.s()
    if got != map_name:
        raise ValueError(f"expected {map_name!r} got {got!r}")
    packed = reader.u32()
    for _ in range(_precon_byte_count(scenario_count)):
        reader.u8()
    _color = reader.u8()
    _diff = reader.u8()
    region = reader.s()
    prolog = _read_prolog_epilog(reader)
    epilog = _read_prolog_epilog(reader)
    return {
        "mapName": map_name,
        "packedSize": packed,
        "regionText": region,
        "prolog": prolog,
        "epilog": epilog,
    }


def extract_ab_sod_all(
    *,
    data_dir: Path | None = None,
    batch_manifest: Path | None = None,
) -> dict[str, Any]:
    """Extract AB/SoD H3C prologText keyed by VIDEO stem (clip key)."""
    from ab_sod_video_map import (  # noqa: WPS433 — local package import
        AB_SOD_CAMPAIGN_LODS,
        resolve_clip_for_video_index,
    )
    from build_campaign_layered_ir import H3M_NAME_BY_MISSION_BLOCK  # noqa: WPS433
    from campaign_mission import load_batch_manifest  # noqa: WPS433

    root = Path(__file__).resolve().parents[2]
    data_dir = (data_dir or (root / "HoMM 3 Complete" / "Data")).resolve()
    batch_path = (
        batch_manifest
        or (root / "scenarios" / "ab_sod_campaigns" / "batch_manifest.json")
    ).resolve()
    batch = load_batch_manifest(batch_path)

    by_campaign: dict[str, list[Any]] = {}
    for mission in batch.missions:
        by_campaign.setdefault(mission.campaign_entry, []).append(mission)

    clips: dict[str, Any] = {}
    mission_clip_keys: dict[str, str] = {}
    parse_meta: dict[str, Any] = {}

    for campaign_entry, missions in by_campaign.items():
        lod_name = AB_SOD_CAMPAIGN_LODS.get(campaign_entry)
        if not lod_name:
            raise KeyError(f"no LOD mapping for {campaign_entry}")
        lod_path = data_dir / lod_name
        blob = extract_lod_entry(lod_path, campaign_entry)
        scenario_count = len(missions)
        parse_meta[campaign_entry] = {
            "lod": lod_name,
            "scenarioCount": scenario_count,
            "preconBytes": _precon_byte_count(scenario_count),
        }
        for mission in sorted(missions, key=lambda m: m.block_index):
            key = (campaign_entry, mission.block_index)
            map_name = H3M_NAME_BY_MISSION_BLOCK.get(key)
            if not map_name:
                raise KeyError(f"missing H3M name for {key}")
            at = _find_map_name(blob, map_name)
            scenario = _parse_scenario_at(
                blob,
                at=at,
                map_name=map_name,
                scenario_count=scenario_count,
            )
            prolog = scenario["prolog"]
            if not prolog.get("has"):
                raise RuntimeError(
                    f"{mission.mission_id}: H3C prolog missing (map={map_name})"
                )
            video_id = prolog.get("video")
            if not isinstance(video_id, int):
                raise RuntimeError(
                    f"{mission.mission_id}: prolog.video is not an int ({video_id!r})"
                )
            clip_key, narration_snd_key = resolve_clip_for_video_index(video_id)
            text = prolog.get("text") or ""
            if not str(text).strip():
                raise RuntimeError(f"{mission.mission_id}: empty prologText")
            if clip_key in clips and clips[clip_key]["missionId"] != mission.mission_id:
                raise RuntimeError(
                    f"clip {clip_key} claimed by both "
                    f"{clips[clip_key]['missionId']} and {mission.mission_id}"
                )
            clips[clip_key] = {
                "campaign": campaign_entry,
                "missionId": mission.mission_id,
                "hub": mission.hub if hasattr(mission, "hub") else None,
                "mapName": map_name,
                "regionText": scenario["regionText"],
                "prologText": text,
                "hasProlog": True,
                "prologVideoId": video_id,
                "prologMusicId": prolog.get("music"),
                "narrationSndKey": narration_snd_key,
                "chars": len(text),
            }
            # Prefer batch hub id when present on mission objects.
            if hasattr(mission, "hub_id"):
                clips[clip_key]["hub"] = mission.hub_id
            mission_clip_keys[mission.mission_id] = clip_key

    expected_missions = {m.mission_id for m in batch.missions}
    missing = sorted(expected_missions - set(mission_clip_keys))
    if missing:
        raise RuntimeError(f"missing mission clip keys after extract: {missing}")

    return {
        "schema": "homm3.ab_sod_video_prologue_transcripts.v1",
        "sourceDataDir": str(data_dir),
        "batchManifest": str(batch_path),
        "note": (
            "prologText = H3C scenario prolog (video voiceover). "
            "regionText = campaign-map blurb. Do not softsub regionText. "
            "clip keys are VIDEO.VID stems resolved from prolog.video via "
            "ab_sod_video_map.VIDEO_INDEX_TO_CLIP."
        ),
        "clips": clips,
        "missionClipKeys": mission_clip_keys,
        "parse": parse_meta,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lod", type=Path, default=DEFAULT_LOD)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--ab-sod",
        action="store_true",
        help="Extract AB/SoD prologs instead of RoE",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="HoMM3 Complete Data dir (AB/SoD mode)",
    )
    parser.add_argument(
        "--batch-manifest",
        type=Path,
        default=None,
        help="AB/SoD batch_manifest.json (AB/SoD mode)",
    )
    args = parser.parse_args()
    if args.ab_sod:
        out = args.out
        if out == DEFAULT_OUT:
            out = Path(__file__).with_name("ab_sod_video_prologue_transcripts.v1.json")
        doc = extract_ab_sod_all(
            data_dir=args.data_dir,
            batch_manifest=args.batch_manifest,
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {out} ({len(doc['clips'])} clips, {len(doc['missionClipKeys'])} missions)")
        for clip in sorted(doc["clips"]):
            text = doc["clips"][clip]["prologText"]
            print(f"  {clip}: {text[:64]!r}…")
        return 0

    if not args.lod.is_file():
        print(f"missing LOD: {args.lod}", file=sys.stderr)
        return 2
    doc = extract_all(args.lod.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(doc['clips'])} clips)")
    for clip in sorted(doc["clips"]):
        text = doc["clips"][clip]["prologText"]
        print(f"  {clip}: {text[:64]!r}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
