#!/usr/bin/env python3
"""Extract SMK/BIK clips from HoMM3 Complete *.VID archives and WAV from Heroes3.snd.

VID layout (Complete / GOG):
  uint32 count
  count × (char name[40] + uint32 offset)
  payload blobs; size = next_offset - offset (last = EOF - offset)

SND layout matches experiments/campaign_port_poc/campaign_video_compose.read_snd_index.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPLETE = ROOT / "HoMM 3 Complete" / "Data"
DEFAULT_OUT = (
    ROOT / "artifacts" / "campaign_port_poc" / "ab_sod_campaigns" / "video_sources"
)

# Mission cutscenes + SoD/AB hub strips needed for StoryHub parity bake.
AB_SOD_VIDEO_STEMS = frozenset(
    {
        # AB missions
        "H3ABab1",
        "H3ABab2",
        "H3ABab3",
        "H3ABab4",
        "H3ABab5",
        "H3ABab6",
        "H3ABab7",
        "H3ABab8",
        "H3ABab9",
        "H3ABdb1",
        "H3ABdb2",
        "H3ABdb3",
        "H3ABdb4",
        "H3ABdb4b",
        "H3ABdb5",
        "H3ABds1",
        "H3ABds2",
        "H3ABds3",
        "H3ABds4",
        "H3ABds5",
        "H3ABfl1",
        "H3ABfl2",
        "H3ABfl3",
        "H3ABfl4",
        "H3ABfl5",
        "H3ABfw1",
        "H3ABfw2",
        "H3ABfw3",
        "H3ABfw4",
        "H3ABfw5",
        "H3ABpf1",
        "H3ABpf2",
        "H3ABpf3",
        "H3ABpf4",
        # SoD missions
        "H3x2_BBa",
        "H3x2_BBb",
        "H3x2_BBc",
        "H3x2_BBd",
        "H3x2_BBe",
        "H3x2_BBf",
        "H3x2_ELa",
        "H3x2_ELb",
        "H3x2_ELc",
        "H3x2_ELd",
        "H3x2_ELe",
        "H3x2_HSa",
        "H3x2_HSc",
        "H3x2_HSd",
        "H3x2_HSe",
        "H3x2_NBa",
        "H3x2_NBb",
        "H3x2_NBc",
        "H3x2_NBd",
        "H3x2_NBe",
        "H3x2_RNa",
        "H3x2_RNb",
        "H3x2_RNc",
        "H3x2_RNd",
        "H3x2_RNe1",
        "H3x2_RNe2",
        "H3x2_UAa",
        "H3x2_UAb",
        "H3x2_UAc",
        "H3x2_UAd",
        "H3x2_UAe",
        "H3x2_UAf",
        "H3x2_UAg",
        "H3x2_UAh",
        "H3x2_UAi",
        "H3x2_UAj",
        "H3x2_UAk",
        "H3x2_UAl",
        "H3x2_UAm",
        # SoD hub strips (VIDEO.VID)
        "Birth",
        "elixir",
        "hack",
        "new",
        "rise",
        "unholy",
        # Specter of Power hub strip (distinct from Seeds Csecret)
        "spectre",
    }
)

AB_HUB_STRIP_STEMS = frozenset(
    {"C1ab7", "C1db2", "C1ds1", "C1fl3", "C1fw1", "C1pf2"}
)

AB_SOD_NARRATION_KEYS = frozenset(
    {
        *(f"ABVOAB{i}" for i in range(1, 10)),
        *(f"ABVODB{i}" for i in range(1, 6)),
        *(f"ABVODS{i}" for i in range(1, 6)),
        *(f"ABVOFL{i}" for i in range(1, 6)),
        *(f"ABVOFW{i}" for i in range(1, 6)),
        *(f"ABVOPF{i}" for i in range(1, 5)),
        *(f"H3X2BB{c}" for c in "ABCDEF"),
        *(f"H3X2EL{c}" for c in "ABCDE"),
        *(f"H3X2HS{c}" for c in "ABCDE"),
        *(f"H3X2NB{c}" for c in "ABCDE"),
        *(f"H3X2RN{c}" for c in "ABCDE"),
        *(f"H3X2UA{c}" for c in "ABCDEFGHIJKLM"),
    }
)


def fail(message: str) -> None:
    raise SystemExit(f"extract_homm3_complete_vid failed: {message}")


def list_vid_entries(vid_path: Path) -> list[tuple[str, int, int]]:
    data = vid_path.read_bytes()
    if len(data) < 4:
        fail(f"VID too small: {vid_path}")
    (count,) = struct.unpack_from("<I", data, 0)
    if count <= 0 or count > 10_000:
        fail(f"implausible VID count {count} in {vid_path}")
    entries: list[tuple[str, int]] = []
    pos = 4
    for _ in range(count):
        if pos + 44 > len(data):
            fail(f"VID directory overrun in {vid_path}")
        name = data[pos : pos + 40].split(b"\x00", 1)[0].decode("latin1")
        (offset,) = struct.unpack_from("<I", data, pos + 40)
        entries.append((name, offset))
        pos += 44
    out: list[tuple[str, int, int]] = []
    for index, (name, offset) in enumerate(entries):
        end = entries[index + 1][1] if index + 1 < len(entries) else len(data)
        if end < offset:
            fail(f"VID entry {name!r} has end {end} < offset {offset}")
        out.append((name, offset, end - offset))
    return out


def stem_of(filename: str) -> str:
    return Path(filename).stem


def extract_vid(
    vid_path: Path,
    dest_dir: Path,
    *,
    wanted_stems: frozenset[str],
    label: str,
) -> list[dict[str, Any]]:
    data = vid_path.read_bytes()
    rows = list_vid_entries(vid_path)
    by_stem: dict[str, tuple[str, int, int]] = {}
    for name, offset, size in rows:
        stem = stem_of(name)
        # Prefer .smk over .bik when both exist (UAm has both).
        prev = by_stem.get(stem)
        if prev is None or (name.lower().endswith(".smk") and not prev[0].lower().endswith(".smk")):
            by_stem[stem] = (name, offset, size)

    missing = sorted(wanted_stems - set(by_stem))
    if missing:
        fail(f"{label} missing stems: {missing}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, Any]] = []
    for stem in sorted(wanted_stems):
        name, offset, size = by_stem[stem]
        if size <= 0:
            fail(f"{label} empty payload for {name}")
        blob = data[offset : offset + size]
        if len(blob) != size:
            fail(f"{label} short read for {name}")
        out_path = dest_dir / name
        out_path.write_bytes(blob)
        written.append(
            {
                "stem": stem,
                "name": name,
                "path": str(out_path),
                "bytes": size,
                "sourceVid": str(vid_path),
            }
        )
    return written


def extract_snd_wavs(
    snd_path: Path,
    dest_dir: Path,
    *,
    wanted_keys: frozenset[str],
) -> list[dict[str, Any]]:
    sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))
    from campaign_video_compose import extract_snd_wav, read_snd_index  # noqa: E402

    index = read_snd_index(snd_path)
    missing = sorted(wanted_keys - set(index))
    # H3X2HSB exists in SND even when HSb.smk is absent from VIDEO.VID.
    if missing:
        fail(f"Heroes3.snd missing narration keys: {missing}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, Any]] = []
    for key in sorted(wanted_keys):
        dest = dest_dir / f"{key}.wav"
        meta = extract_snd_wav(snd_path, key, dest)
        written.append(meta)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--complete-data", type=Path, default=DEFAULT_COMPLETE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--inventory-only", action="store_true")
    args = parser.parse_args()
    complete = args.complete_data.resolve()
    out = args.out.resolve()
    video_vid = complete / "VIDEO.VID"
    ab_vid = complete / "H3ab_ahd.vid"
    snd = complete / "Heroes3.snd"
    for path in (video_vid, ab_vid, snd):
        if not path.is_file():
            fail(f"missing {path}")

    if args.inventory_only:
        report = {
            "videoVid": [
                {"name": n, "offset": o, "bytes": s}
                for n, o, s in list_vid_entries(video_vid)
            ],
            "h3abAhdVid": [
                {"name": n, "offset": o, "bytes": s}
                for n, o, s in list_vid_entries(ab_vid)
            ],
        }
        print(json.dumps(report, indent=2))
        return 0

    video_rows = extract_vid(
        video_vid,
        out / "video",
        wanted_stems=AB_SOD_VIDEO_STEMS,
        label="VIDEO.VID",
    )
    hub_rows = extract_vid(
        ab_vid,
        out / "hub_strips",
        wanted_stems=AB_HUB_STRIP_STEMS,
        label="H3ab_ahd.vid",
    )
    # SoD hub strips also live in VIDEO.VID; copy into hub_strips for one place.
    sod_hub = frozenset({"Birth", "elixir", "hack", "new", "rise", "unholy"})
    for row in video_rows:
        if row["stem"] in sod_hub:
            dest = out / "hub_strips" / Path(row["name"]).name
            dest.write_bytes(Path(row["path"]).read_bytes())
            hub_rows.append({**row, "path": str(dest), "copiedFrom": "VIDEO.VID"})

    audio_rows = extract_snd_wavs(
        snd, out / "audio", wanted_keys=AB_SOD_NARRATION_KEYS
    )
    report = {
        "schema": "homm3.ab_sod_video_sources.v1",
        "outRoot": str(out),
        "videoCount": len(video_rows),
        "hubStripCount": len(hub_rows),
        "audioCount": len(audio_rows),
        "video": video_rows,
        "hubStrips": hub_rows,
        "audio": audio_rows,
    }
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / "extract_report.v1.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(report_path), **{k: report[k] for k in ("videoCount", "hubStripCount", "audioCount")}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
