"""Compose classic HoMM3 campaign cutscenes into Olden-ready MP4s.

Classic RoE cutscenes loop a short VIDEO/*.ogv strip while HEROES3CD.SND narration
(G1A/G1B/…) plays longer, with prolog text on screen. Native Olden BhVideoPlayer
plays one finished MP4 once (optional softsubs via *.mp4.json + LocKit SIDs).

Recipe (fail-closed):
  - Mission clips Good1a–c / Good2a–d require VIDEO OGV + CD narration WAV + prolog text.
  - Hub strips Cgood1/Cgood2 have no CD narration → refuse compose (hover/menu only).
  - Prefer softsubs (haveSubtitles + sidecar JSON + cinematic.json LocKit) over burn-in.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from campaign_video_clip import (
    TARGET_HEIGHT,
    TARGET_WIDTH,
    mp4_meets_native_canvas,
    probe_mp4,
    resolve_ffmpeg,
)

DEFAULT_HD_ROOT = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might & Magic III - HD Edition"
)
DEFAULT_HD_VIDEO_DIR = DEFAULT_HD_ROOT / "data" / "VIDEO"
DEFAULT_HD_CD_SND = DEFAULT_HD_ROOT / "data" / "LOC" / "EN" / "HEROES3CD.SND"
DEFAULT_COMPLETE_SND = (
    Path(__file__).resolve().parents[2] / "HoMM 3 Complete" / "Data" / "Heroes3.snd"
)
DEFAULT_COMPLETE_LOD = (
    Path(__file__).resolve().parents[2] / "HoMM 3 Complete" / "Data" / "H3bitmap.lod"
)
DEFAULT_AB_SOD_VIDEO_DIR = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "campaign_port_poc"
    / "ab_sod_campaigns"
    / "video_sources"
    / "video"
)
_TRANSCRIPTS_PATH = Path(__file__).with_name("roe_video_prologue_transcripts.v1.json")
_AB_SOD_TRANSCRIPTS_PATH = Path(__file__).with_name(
    "ab_sod_video_prologue_transcripts.v1.json"
)


def load_h3c_prolog_texts(path: Path | None = None) -> dict[str, str]:
    """Load video voiceover strings (H3C prologText), not regionText blurbs."""
    doc = json.loads((path or _TRANSCRIPTS_PATH).read_text(encoding="utf-8"))
    rows = doc.get("clips") if isinstance(doc, dict) else None
    if not isinstance(rows, dict) or not rows:
        raise RuntimeError(f"missing clips in {_TRANSCRIPTS_PATH}")
    out: dict[str, str] = {}
    for key, row in rows.items():
        if not isinstance(row, dict):
            continue
        text = row.get("prologText")
        if isinstance(text, str) and text.strip():
            out[str(key)] = text
    if not out:
        raise RuntimeError(f"no prologText entries in {_TRANSCRIPTS_PATH}")
    return out


_H3C_PROLOG_TEXTS = load_h3c_prolog_texts()


def _prolog(clip_key: str) -> str:
    text = _H3C_PROLOG_TEXTS.get(clip_key)
    if not text:
        raise KeyError(
            f"missing H3C prologText for {clip_key} in {_TRANSCRIPTS_PATH.name}"
        )
    return text


# Composed duration must cover narration; allow small mux/encoder slack.
DURATION_SLACK_SEC = 0.75
# Floor rejects silent hover-strip leftovers (~5s). A few classic RoE CD clips
# (Evil1c / Evil2b) are legitimately ~14–16s, so keep this below 18.
MIN_COMPOSED_DURATION_SEC = 12.0


@dataclass(frozen=True)
class ComposedClipRecipe:
    clip_key: str
    role: str  # mission_cutscene | hub_hover_strip
    video_stem: str
    narration_snd_key: str | None
    campaign_entry: str | None
    prolog_text: str | None
    # Expected narration length from HEROES3CD.SND (source/static probe).
    expected_narration_sec: float | None

    @property
    def is_composable(self) -> bool:
        return (
            self.role == "mission_cutscene"
            and bool(self.narration_snd_key)
            and bool(self.prolog_text)
            and self.expected_narration_sec is not None
        )


# Prolog texts come from roe_video_prologue_transcripts.v1.json (H3C prologText =
# video voiceover). Never use regionText (campaign-map blurb) for softsubs.
COMPOSED_CLIP_RECIPES: dict[str, ComposedClipRecipe] = {
    "Cgood1": ComposedClipRecipe(
        clip_key="Cgood1",
        role="hub_hover_strip",
        video_stem="Cgood1",
        narration_snd_key=None,
        campaign_entry=None,
        prolog_text=None,
        expected_narration_sec=None,
    ),
    "Cgood2": ComposedClipRecipe(
        clip_key="Cgood2",
        role="hub_hover_strip",
        video_stem="Cgood2",
        narration_snd_key=None,
        campaign_entry=None,
        prolog_text=None,
        expected_narration_sec=None,
    ),
    "Good1a": ComposedClipRecipe(
        clip_key="Good1a",
        role="mission_cutscene",
        video_stem="Good1a",
        narration_snd_key="G1A",
        campaign_entry="Good1.h3c",
        prolog_text=_prolog("Good1a"),
        expected_narration_sec=22.92,
    ),
    "Good1b": ComposedClipRecipe(
        clip_key="Good1b",
        role="mission_cutscene",
        video_stem="Good1b",
        narration_snd_key="G1B",
        campaign_entry="Good1.h3c",
        prolog_text=_prolog("Good1b"),
        expected_narration_sec=41.02,
    ),
    "Good1c": ComposedClipRecipe(
        clip_key="Good1c",
        role="mission_cutscene",
        video_stem="Good1c",
        narration_snd_key="G1C",
        campaign_entry="Good1.h3c",
        prolog_text=_prolog("Good1c"),
        expected_narration_sec=24.98,
    ),
    "Good2a": ComposedClipRecipe(
        clip_key="Good2a",
        role="mission_cutscene",
        video_stem="Good2a",
        narration_snd_key="G2A",
        campaign_entry="Good2.h3c",
        prolog_text=_prolog("Good2a"),
        expected_narration_sec=21.26,
    ),
    "Good2b": ComposedClipRecipe(
        clip_key="Good2b",
        role="mission_cutscene",
        video_stem="Good2b",
        narration_snd_key="G2B",
        campaign_entry="Good2.h3c",
        prolog_text=_prolog("Good2b"),
        expected_narration_sec=45.83,
    ),
    "Good2c": ComposedClipRecipe(
        clip_key="Good2c",
        role="mission_cutscene",
        video_stem="Good2c",
        narration_snd_key="G2C",
        campaign_entry="Good2.h3c",
        prolog_text=_prolog("Good2c"),
        expected_narration_sec=30.00,
    ),
    "Good2d": ComposedClipRecipe(
        clip_key="Good2d",
        role="mission_cutscene",
        video_stem="Good2d",
        narration_snd_key="G2D",
        campaign_entry="Good2.h3c",
        prolog_text=_prolog("Good2d"),
        expected_narration_sec=42.66,
    ),
    # Remaining RoE hubs (exclude HotA). Prolog strings from H3C block0.
    "Cgood3": ComposedClipRecipe(
        clip_key="Cgood3",
        role="hub_hover_strip",
        video_stem="Cgood3",
        narration_snd_key=None,
        campaign_entry=None,
        prolog_text=None,
        expected_narration_sec=None,
    ),
    "Cevil1": ComposedClipRecipe(
        clip_key="Cevil1",
        role="hub_hover_strip",
        video_stem="Cevil1",
        narration_snd_key=None,
        campaign_entry=None,
        prolog_text=None,
        expected_narration_sec=None,
    ),
    "Cevil2": ComposedClipRecipe(
        clip_key="Cevil2",
        role="hub_hover_strip",
        video_stem="Cevil2",
        narration_snd_key=None,
        campaign_entry=None,
        prolog_text=None,
        expected_narration_sec=None,
    ),
    "Csecret": ComposedClipRecipe(
        clip_key="Csecret",
        role="hub_hover_strip",
        video_stem="Csecret",
        narration_snd_key=None,
        campaign_entry=None,
        prolog_text=None,
        expected_narration_sec=None,
    ),
    "Cneutral": ComposedClipRecipe(
        clip_key="Cneutral",
        role="hub_hover_strip",
        video_stem="Cneutral",
        narration_snd_key=None,
        campaign_entry=None,
        prolog_text=None,
        expected_narration_sec=None,
    ),
    "Good3a": ComposedClipRecipe(
        clip_key="Good3a",
        role="mission_cutscene",
        video_stem="Good3a",
        narration_snd_key="G3A",
        campaign_entry="Good3.h3c",
        prolog_text=_prolog("Good3a"),
        expected_narration_sec=43.48,
    ),
    "Good3b": ComposedClipRecipe(
        clip_key="Good3b",
        role="mission_cutscene",
        video_stem="Good3b",
        narration_snd_key="G3B",
        campaign_entry="Good3.h3c",
        prolog_text=_prolog("Good3b"),
        expected_narration_sec=23.75,
    ),
    "Good3c": ComposedClipRecipe(
        clip_key="Good3c",
        role="mission_cutscene",
        video_stem="Good3c",
        narration_snd_key="G3C",
        campaign_entry="Good3.h3c",
        prolog_text=_prolog("Good3c"),
        expected_narration_sec=44.55,
    ),
    "Evil1a": ComposedClipRecipe(
        clip_key="Evil1a",
        role="mission_cutscene",
        video_stem="Evil1a",
        narration_snd_key="E1A",
        campaign_entry="EVIL1.H3C",
        prolog_text=_prolog("Evil1a"),
        expected_narration_sec=25.01,
    ),
    "Evil1b": ComposedClipRecipe(
        clip_key="Evil1b",
        role="mission_cutscene",
        video_stem="Evil1b",
        narration_snd_key="E1B",
        campaign_entry="EVIL1.H3C",
        prolog_text=_prolog("Evil1b"),
        expected_narration_sec=33.66,
    ),
    "Evil1c": ComposedClipRecipe(
        clip_key="Evil1c",
        role="mission_cutscene",
        video_stem="Evil1c",
        narration_snd_key="E1C",
        campaign_entry="EVIL1.H3C",
        prolog_text=_prolog("Evil1c"),
        expected_narration_sec=15.89,
    ),
    "Evil2a": ComposedClipRecipe(
        clip_key="Evil2a",
        role="mission_cutscene",
        video_stem="Evil2a",
        narration_snd_key="E2A",
        campaign_entry="Evil2.h3c",
        prolog_text=_prolog("Evil2a"),
        expected_narration_sec=61.07,
    ),
    "Evil2b": ComposedClipRecipe(
        clip_key="Evil2b",
        role="mission_cutscene",
        video_stem="Evil2b",
        narration_snd_key="E2B",
        campaign_entry="Evil2.h3c",
        prolog_text=_prolog("Evil2b"),
        expected_narration_sec=13.81,
    ),
    "Evil2c": ComposedClipRecipe(
        clip_key="Evil2c",
        role="mission_cutscene",
        video_stem="Evil2c",
        narration_snd_key="E2C",
        campaign_entry="Evil2.h3c",
        prolog_text=_prolog("Evil2c"),
        expected_narration_sec=23.20,
    ),
    "Evil2d": ComposedClipRecipe(
        clip_key="Evil2d",
        role="mission_cutscene",
        video_stem="Evil2d",
        narration_snd_key="E2D",
        campaign_entry="Evil2.h3c",
        prolog_text=_prolog("Evil2d"),
        expected_narration_sec=30.14,
    ),
    "SecretA": ComposedClipRecipe(
        clip_key="SecretA",
        role="mission_cutscene",
        video_stem="SecretA",
        narration_snd_key="S1A",
        campaign_entry="Secret1.h3c",
        prolog_text=_prolog("SecretA"),
        expected_narration_sec=35.08,
    ),
    "SecretB": ComposedClipRecipe(
        clip_key="SecretB",
        role="mission_cutscene",
        video_stem="SecretB",
        narration_snd_key="S1B",
        campaign_entry="Secret1.h3c",
        prolog_text=_prolog("SecretB"),
        expected_narration_sec=33.04,
    ),
    "SecretC": ComposedClipRecipe(
        clip_key="SecretC",
        role="mission_cutscene",
        video_stem="SecretC",
        narration_snd_key="S1C",
        campaign_entry="Secret1.h3c",
        prolog_text=_prolog("SecretC"),
        expected_narration_sec=34.37,
    ),
    "NeutralA": ComposedClipRecipe(
        clip_key="NeutralA",
        role="mission_cutscene",
        video_stem="NeutralA",
        narration_snd_key="N1A",
        campaign_entry="Neutral1.h3c",
        prolog_text=_prolog("NeutralA"),
        expected_narration_sec=38.11,
    ),
    "NeutralB": ComposedClipRecipe(
        clip_key="NeutralB",
        role="mission_cutscene",
        video_stem="NeutralB",
        narration_snd_key="N1B",
        campaign_entry="Neutral1.h3c",
        prolog_text=_prolog("NeutralB"),
        expected_narration_sec=47.30,
    ),
    "NeutralC": ComposedClipRecipe(
        clip_key="NeutralC",
        role="mission_cutscene",
        video_stem="NeutralC",
        narration_snd_key="N1C_D",
        campaign_entry="Neutral1.h3c",
        prolog_text=_prolog("NeutralC"),
        expected_narration_sec=46.70,
    ),
}


def mission_compose_keys() -> tuple[str, ...]:
    return tuple(
        key
        for key, recipe in COMPOSED_CLIP_RECIPES.items()
        if recipe.role == "mission_cutscene"
    )


def ensure_composed_recipe(clip_key: str):
    """Return recipe for clip_key, lazy-registering AB/SoD recipes when needed."""
    recipe = COMPOSED_CLIP_RECIPES.get(clip_key)
    if recipe is not None:
        return recipe
    if clip_key.startswith("H3AB") or clip_key.startswith("H3x2_"):
        if not _AB_SOD_RECIPES_REGISTERED and _AB_SOD_TRANSCRIPTS_PATH.is_file():
            register_ab_sod_composed_recipes()
        return COMPOSED_CLIP_RECIPES.get(clip_key)
    return None


MISSION_COMPOSE_KEYS: tuple[str, ...] = mission_compose_keys()

_AB_SOD_RECIPES_REGISTERED = False


def softsub_sid(clip_key: str, index: int) -> str:
    lowered = clip_key.lower()
    if clip_key.startswith("H3AB") or clip_key.startswith("H3x2_"):
        # LocKit SIDs cannot use raw underscores from H3x2_* in a confusing way;
        # keep the stem lowercased as one token segment.
        safe = lowered.replace("h3x2_", "h3x2")
        return f"homm3_absod_{safe}_video_{index}"
    return f"homm3_roe_{lowered}_video_{index}"


def probe_media_duration_sec(path: Path, *, ffmpeg: Path | None = None) -> float:
    """Duration via ffmpeg -i (supports ADPCM WAV / SMK / BIK where probe_mp4 is thin)."""
    ffmpeg = ffmpeg or resolve_ffmpeg()
    proc = subprocess.run(
        [str(ffmpeg), "-i", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    blob = (proc.stderr or "") + "\n" + (proc.stdout or "")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", blob)
    if not match:
        raise RuntimeError(f"ffmpeg could not read duration for {path}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def resolve_recipe_video_path(
    recipe: ComposedClipRecipe,
    *,
    hd_video_dir: Path = DEFAULT_HD_VIDEO_DIR,
    ab_sod_video_dir: Path | None = None,
) -> Path:
    """Prefer HD OGV; else Complete extract SMK/BIK under ab_sod video_sources."""
    ogv = hd_video_dir / f"{recipe.video_stem}.ogv"
    if ogv.is_file():
        return ogv
    video_dir = (ab_sod_video_dir or DEFAULT_AB_SOD_VIDEO_DIR).resolve()
    for ext in (".smk", ".bik", ".SMK", ".BIK"):
        candidate = video_dir / f"{recipe.video_stem}{ext}"
        if candidate.is_file():
            return candidate
    return ogv


def register_ab_sod_composed_recipes(
    *,
    transcripts_path: Path | None = None,
    complete_snd: Path | None = None,
) -> list[str]:
    """Add AB/SoD mission cutscene recipes from prologue transcripts JSON."""
    global MISSION_COMPOSE_KEYS, _AB_SOD_RECIPES_REGISTERED
    path = (transcripts_path or _AB_SOD_TRANSCRIPTS_PATH).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"missing AB/SoD transcripts: {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = doc.get("clips")
    if not isinstance(rows, dict) or not rows:
        raise RuntimeError(f"missing clips in {path}")
    snd_path = (complete_snd or DEFAULT_COMPLETE_SND).resolve()
    if not snd_path.is_file():
        raise FileNotFoundError(f"missing Complete SND: {snd_path}")
    registered: list[str] = []
    for clip_key, row in rows.items():
        if not isinstance(row, dict):
            continue
        prolog = row.get("prologText")
        snd_key = row.get("narrationSndKey")
        if not isinstance(prolog, str) or not prolog.strip():
            raise RuntimeError(f"{clip_key}: missing prologText")
        if not isinstance(snd_key, str) or not snd_key.strip():
            raise RuntimeError(f"{clip_key}: missing narrationSndKey")
        # Prefer extracted WAV duration; fall back to SND extract in temp.
        audio_wav = (
            DEFAULT_AB_SOD_VIDEO_DIR.parent / "audio" / f"{snd_key}.wav"
        )
        if audio_wav.is_file():
            narr_sec = probe_media_duration_sec(audio_wav)
        else:
            with tempfile.TemporaryDirectory(prefix="absod_narr_") as tmp:
                wav = Path(tmp) / f"{snd_key}.wav"
                extract_snd_wav(snd_path, snd_key, wav)
                narr_sec = probe_media_duration_sec(wav)
        if narr_sec < MIN_COMPOSED_DURATION_SEC:
            raise RuntimeError(
                f"{clip_key}: narration {narr_sec:.2f}s below "
                f"MIN_COMPOSED_DURATION_SEC={MIN_COMPOSED_DURATION_SEC}"
            )
        from ab_sod_video_map import resolve_video_stem_for_clip

        COMPOSED_CLIP_RECIPES[str(clip_key)] = ComposedClipRecipe(
            clip_key=str(clip_key),
            role="mission_cutscene",
            video_stem=resolve_video_stem_for_clip(str(clip_key)),
            narration_snd_key=snd_key,
            campaign_entry=str(row.get("campaign") or ""),
            prolog_text=prolog,
            expected_narration_sec=float(narr_sec),
        )
        registered.append(str(clip_key))
    # Hub strips: register as non-composable for inventory parity.
    from ab_sod_video_map import HUB_STRIP_STEMS

    for stem in sorted(set(HUB_STRIP_STEMS.values())):
        if stem in COMPOSED_CLIP_RECIPES:
            continue
        COMPOSED_CLIP_RECIPES[stem] = ComposedClipRecipe(
            clip_key=stem,
            role="hub_hover_strip",
            video_stem=stem,
            narration_snd_key=None,
            campaign_entry=None,
            prolog_text=None,
            expected_narration_sec=None,
        )
    MISSION_COMPOSE_KEYS = mission_compose_keys()
    _AB_SOD_RECIPES_REGISTERED = True
    return sorted(registered)


def split_prolog_sentences(text: str) -> list[str]:
    cleaned = " ".join(text.split())
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    sentences = [part.strip() for part in parts if part.strip()]
    if not sentences:
        raise ValueError("prolog text produced no subtitle sentences")
    return sentences


def build_softsub_cues(
    *,
    clip_key: str,
    prolog_text: str,
    duration_sec: float,
) -> list[dict[str, Any]]:
    """Allocate softsub windows by character weight across narration duration."""
    if duration_sec <= 0:
        raise ValueError(f"{clip_key}: softsub duration must be positive")
    sentences = split_prolog_sentences(prolog_text)
    weights = [max(1, len(s)) for s in sentences]
    total = float(sum(weights))
    cues: list[dict[str, Any]] = []
    cursor = 0.0
    for index, (sentence, weight) in enumerate(zip(sentences, weights), start=1):
        span = duration_sec * (weight / total)
        start = cursor
        end = duration_sec if index == len(sentences) else min(duration_sec, cursor + span)
        if end <= start:
            end = min(duration_sec, start + 0.5)
        cues.append(
            {
                "sid": softsub_sid(clip_key, index),
                "start": round(start, 2),
                "end": round(end, 2),
                "text": sentence,
            }
        )
        cursor = end
    return cues


def write_softsub_sidecar(mp4_path: Path, cues: list[dict[str, Any]]) -> Path:
    sidecar = mp4_path.with_suffix(mp4_path.suffix + ".json")
    payload = {
        "subtitles": [
            {"sid": cue["sid"], "start": cue["start"], "end": cue["end"]} for cue in cues
        ]
    }
    sidecar.write_text(json.dumps(payload, indent="\t") + "\n", encoding="utf-8")
    return sidecar


def refresh_softsub_text_for_clip(*, clip_key: str, mp4_path: Path) -> dict[str, Any]:
    """Rewrite softsub sidecar cues from current H3C prologText without re-encoding MP4."""
    recipe = COMPOSED_CLIP_RECIPES.get(clip_key)
    if recipe is None:
        raise KeyError(f"unknown clip key {clip_key}")
    if not recipe.is_composable or not recipe.prolog_text:
        raise RuntimeError(f"{clip_key}: not a composable mission cutscene with prolog text")
    if not mp4_path.is_file():
        raise FileNotFoundError(f"missing composed MP4: {mp4_path}")
    probe = probe_mp4(mp4_path)
    ok, reason = composed_mp4_meets_contract(probe, recipe)
    if not ok:
        raise RuntimeError(f"{clip_key}: refuse softsub refresh; {reason}")
    duration = float(probe.get("duration_sec") or 0.0)
    cues = build_softsub_cues(
        clip_key=clip_key,
        prolog_text=recipe.prolog_text,
        duration_sec=duration,
    )
    sidecar = write_softsub_sidecar(mp4_path, cues)
    return {
        "clipKey": clip_key,
        "status": "softsub_text_refreshed",
        "mp4": str(mp4_path),
        "sidecar": str(sidecar),
        "durationSec": duration,
        "prologText": recipe.prolog_text,
        "softsubCues": cues,
        "subtitleMode": "softsub_sidecar_and_lockit",
        "burnIn": False,
    }


def assert_recipe_prolog_matches_h3c_transcripts(
    *,
    transcripts_path: Path | None = None,
    ab_sod_transcripts_path: Path | None = None,
) -> None:
    """Fail closed if recipe softsub source drifts from H3C prologText."""
    from extract_h3c_prolog_texts import normalize_prolog

    expected = load_h3c_prolog_texts(transcripts_path)
    ab_path = ab_sod_transcripts_path or _AB_SOD_TRANSCRIPTS_PATH
    if ab_path.is_file():
        expected.update(load_h3c_prolog_texts(ab_path))
    for clip_key, recipe in COMPOSED_CLIP_RECIPES.items():
        if not recipe.is_composable:
            continue
        want = expected.get(clip_key)
        if not want:
            raise RuntimeError(f"{clip_key}: missing prologText in transcripts JSON")
        got = recipe.prolog_text or ""
        if normalize_prolog(got) != normalize_prolog(want):
            raise RuntimeError(
                f"{clip_key}: recipe prolog_text is not H3C prologText "
                f"(got starts {got[:48]!r}; want {want[:48]!r})"
            )
        # regionText must never be used as softsub source when it differs.
        # Guard the known NeutralA / Good1b failure modes by opening prefix.
        if got.lstrip().startswith("You are offered a mercenary"):
            raise RuntimeError(
                f"{clip_key}: softsub source looks like NeutralA regionText, not prolog"
            )
        if got.lstrip().startswith("Reports of Angels near the town"):
            raise RuntimeError(
                f"{clip_key}: softsub source looks like Good1b regionText, not prolog"
            )


def read_snd_index(snd_path: Path) -> dict[str, tuple[int, int]]:
    data = snd_path.read_bytes()
    if len(data) < 48:
        raise FileNotFoundError(f"SND too small: {snd_path}")
    (count,) = __import__("struct").unpack_from("<I", data, 0)
    pos = 4
    out: dict[str, tuple[int, int]] = {}
    for _ in range(count):
        raw = data[pos : pos + 40]
        name = raw.split(b"\x00", 1)[0].decode("ascii", "replace")
        off, size = __import__("struct").unpack_from("<ii", data, pos + 40)
        out[name] = (off, size)
        pos += 48
    return out


def extract_snd_wav(snd_path: Path, entry_name: str, dest_wav: Path) -> dict[str, Any]:
    data = snd_path.read_bytes()
    index = read_snd_index(snd_path)
    if entry_name not in index:
        raise FileNotFoundError(f"{snd_path} missing narration entry {entry_name}")
    off, size = index[entry_name]
    if off < 0 or size <= 0 or off + size > len(data):
        raise RuntimeError(f"bad SND span for {entry_name}: off={off} size={size}")
    blob = data[off : off + size]
    if blob[:4] != b"RIFF":
        raise RuntimeError(f"{entry_name} from {snd_path} is not RIFF WAVE")
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    dest_wav.write_bytes(blob)
    return {
        "entry": entry_name,
        "sndPath": str(snd_path),
        "wavPath": str(dest_wav),
        "bytes": size,
    }


def resolve_narration_snd(
    explicit: Path | None = None,
    *,
    narration_snd_key: str | None = None,
) -> Path:
    if explicit is not None:
        if not explicit.is_file():
            raise FileNotFoundError(f"narration SND missing: {explicit}")
        return explicit.resolve()
    key = narration_snd_key or ""
    if key.startswith("ABVO") or key.startswith("H3X2"):
        if DEFAULT_COMPLETE_SND.is_file():
            return DEFAULT_COMPLETE_SND.resolve()
        raise FileNotFoundError(f"Complete SND required for {key}: {DEFAULT_COMPLETE_SND}")
    if DEFAULT_HD_CD_SND.is_file():
        return DEFAULT_HD_CD_SND.resolve()
    if DEFAULT_COMPLETE_SND.is_file():
        return DEFAULT_COMPLETE_SND.resolve()
    raise FileNotFoundError(
        "no narration SND found; expected HD "
        f"{DEFAULT_HD_CD_SND} or Complete {DEFAULT_COMPLETE_SND}"
    )


def inventory_clip_sources(
    *,
    clip_key: str,
    hd_video_dir: Path = DEFAULT_HD_VIDEO_DIR,
    narration_snd: Path | None = None,
    ab_sod_video_dir: Path | None = None,
) -> dict[str, Any]:
    recipe = COMPOSED_CLIP_RECIPES.get(clip_key)
    if recipe is None:
        raise KeyError(f"unknown clip key {clip_key}")
    video_path = resolve_recipe_video_path(
        recipe,
        hd_video_dir=hd_video_dir,
        ab_sod_video_dir=ab_sod_video_dir,
    )
    row: dict[str, Any] = {
        "clipKey": clip_key,
        "role": recipe.role,
        "composable": recipe.is_composable,
        "videoOgv": {
            "path": str(video_path),
            "present": video_path.is_file(),
            "bytes": video_path.stat().st_size if video_path.is_file() else 0,
            "kind": video_path.suffix.lower().lstrip(".") or "missing",
        },
        "narration": None,
        "prologText": recipe.prolog_text,
        "expectedNarrationSec": recipe.expected_narration_sec,
        "subtitleFiles": [],
        "decision": None,
    }
    if recipe.role == "hub_hover_strip":
        row["decision"] = (
            "fail_closed_compose: hub hover strip has no HEROES3CD/Heroes3 narration / "
            "prolog pair; do not ship silent menu strip as a finished campaign cutscene"
        )
        return row

    snd_path = resolve_narration_snd(
        narration_snd, narration_snd_key=recipe.narration_snd_key
    )
    index = read_snd_index(snd_path)
    key = recipe.narration_snd_key or ""
    present = key in index
    size = index[key][1] if present else 0
    row["narration"] = {
        "sndPath": str(snd_path),
        "entry": key,
        "present": present,
        "bytes": size,
    }
    # Classic ships voice in SND + prolog text in H3C; no separate .txt/.vxt beside VIDEO.
    row["subtitleFiles"] = [
        {
            "kind": "h3c_prolog_text",
            "campaignEntry": recipe.campaign_entry,
            "present": bool(recipe.prolog_text),
            "note": "embedded length-prefixed prolog string in H3C block0 (not a loose .txt/.vxt)",
        }
    ]
    missing: list[str] = []
    if not video_path.is_file():
        missing.append(f"video source {video_path}")
    if not present:
        missing.append(f"narration SND entry {key} in {snd_path}")
    if not recipe.prolog_text:
        missing.append("prolog text")
    if missing:
        row["decision"] = "fail_closed_compose: missing " + "; ".join(missing)
        row["composable"] = False
    else:
        row["decision"] = (
            "compose: loop video until SND narration ends; mux AAC; softsubs via "
            f"{clip_key}.mp4.json + Lang/english/texts/cinematic.json LocKit SIDs"
        )
    return row


def compose_campaign_cutscene_mp4(
    *,
    clip_key: str,
    dest_mp4: Path,
    hd_video_dir: Path = DEFAULT_HD_VIDEO_DIR,
    narration_snd: Path | None = None,
    ab_sod_video_dir: Path | None = None,
    ffmpeg: Path | None = None,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    """Loop HoMM3 OGV/SMK/BIK until SND narration ends; letterbox; softsub sidecar."""
    recipe = COMPOSED_CLIP_RECIPES.get(clip_key)
    if recipe is None:
        raise KeyError(f"unknown clip key {clip_key}")
    if not recipe.is_composable:
        raise RuntimeError(
            f"{clip_key}: refuse compose ({recipe.role}); missing narration/prolog sources"
        )

    inventory = inventory_clip_sources(
        clip_key=clip_key,
        hd_video_dir=hd_video_dir,
        narration_snd=narration_snd,
        ab_sod_video_dir=ab_sod_video_dir,
    )
    if not inventory.get("composable"):
        raise RuntimeError(inventory.get("decision") or f"{clip_key}: not composable")

    video_path = Path(inventory["videoOgv"]["path"])
    snd_path = Path(inventory["narration"]["sndPath"])
    ffmpeg = ffmpeg or resolve_ffmpeg()
    dest_mp4.parent.mkdir(parents=True, exist_ok=True)

    own_tmp = work_dir is None
    tmp_root = Path(work_dir) if work_dir else Path(
        tempfile.mkdtemp(prefix=f"roe_compose_{clip_key}_")
    )
    try:
        wav = tmp_root / f"{recipe.narration_snd_key}.wav"
        extract_meta = extract_snd_wav(snd_path, recipe.narration_snd_key or "", wav)
        try:
            narr_dur = probe_media_duration_sec(wav, ffmpeg=ffmpeg)
        except Exception:
            narr_dur = float(recipe.expected_narration_sec or 0)
        narr_dur = float(narr_dur)
        if narr_dur < MIN_COMPOSED_DURATION_SEC:
            raise RuntimeError(
                f"{clip_key}: narration duration {narr_dur:.2f}s below "
                f"MIN_COMPOSED_DURATION_SEC={MIN_COMPOSED_DURATION_SEC}"
            )

        vf = (
            f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
            "fps=30,format=yuv420p"
        )
        tmp_out = tmp_root / dest_mp4.name
        # Loop video infinitely; end on narration (-shortest). Discard source
        # embedded audio — classic cutscene audio is the SND voice track.
        cmd = [
            str(ffmpeg),
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(video_path),
            "-i",
            str(wav),
            "-vf",
            vf,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-shortest",
            "-movflags",
            "+faststart",
            str(tmp_out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not tmp_out.is_file():
            raise RuntimeError(
                f"{clip_key}: ffmpeg compose failed:\n"
                + (proc.stderr or proc.stdout or "(no output)")
            )

        probe = probe_mp4(tmp_out)
        ok, reason = mp4_meets_native_canvas(probe)
        if not ok:
            raise RuntimeError(f"{clip_key}: composed MP4 rejected: {reason}")
        if not probe.get("has_audio"):
            raise RuntimeError(f"{clip_key}: composed MP4 has no audio track")
        out_dur = float(probe.get("duration_sec") or 0.0)
        min_dur = max(
            MIN_COMPOSED_DURATION_SEC,
            narr_dur - DURATION_SLACK_SEC,
        )
        if out_dur < min_dur:
            raise RuntimeError(
                f"{clip_key}: composed duration {out_dur:.2f}s < required {min_dur:.2f}s "
                f"(narration {narr_dur:.2f}s); refuse short hover-strip encode"
            )

        cues = build_softsub_cues(
            clip_key=clip_key,
            prolog_text=recipe.prolog_text or "",
            duration_sec=out_dur,
        )

        backup = None
        if dest_mp4.is_file():
            backup = dest_mp4.with_suffix(dest_mp4.suffix + ".pre_compose_bak")
            if backup.exists():
                backup.unlink()
            shutil.copy2(dest_mp4, backup)
        shutil.copy2(tmp_out, dest_mp4)
        sidecar = write_softsub_sidecar(dest_mp4, cues)
        final = probe_mp4(dest_mp4)
        return {
            "clipKey": clip_key,
            "status": "composed",
            "subtitleMode": "softsub_sidecar_and_lockit",
            "burnIn": False,
            "sourceVideo": str(video_path),
            "sourceOgv": str(video_path),
            "narration": extract_meta,
            "narrationDurationSec": narr_dur,
            "probe": final,
            "sidecar": str(sidecar),
            "softsubCues": cues,
            "backup": str(backup) if backup else None,
            "ffmpegCmd": cmd,
            "inventory": inventory,
            "decisionLog": [
                {
                    "decision": "prefer_softsubs_over_burn_in",
                    "reason": (
                        "Native Campaign_Intro uses haveSubtitles + *.mp4.json + "
                        "Lang/*/texts/cinematic.json LocKit SIDs; match that path"
                    ),
                },
                {
                    "decision": "discard_source_embedded_audio",
                    "reason": (
                        "Mission SMK/OGV mux short beds; classic cutscene voice is "
                        "HEROES3CD/Heroes3.snd narration entries"
                    ),
                },
                {
                    "decision": "loop_video_until_narration_ends",
                    "reason": "VCMI/classic prolog: video array loops while voice plays",
                },
                {
                    "decision": "prolog_text_source_h3c_block0",
                    "reason": (
                        f"{recipe.campaign_entry} length-prefixed prolog string; "
                        "no loose .txt/.vxt beside VIDEO/"
                    ),
                },
            ],
        }
    finally:
        if own_tmp and tmp_root.exists():
            shutil.rmtree(tmp_root, ignore_errors=True)


def clips_info_row_composed(clip_key: str) -> dict[str, Any]:
    return {
        "key": clip_key,
        "val": {
            "name": f"{clip_key}.mp4",
            "canSkip": True,
            "haveSubtitles": True,
            "skipByHoldingEsc": True,
            "playVideoShowAnimation": False,
        },
    }


def merge_cinematic_lockit(existing: dict[str, Any], cues: list[dict[str, Any]]) -> dict[str, Any]:
    tokens = [{"sid": cue["sid"], "text": cue["text"]} for cue in cues]
    by_sid = {t["sid"]: t for t in tokens}
    for key in ("tokens", "array"):
        rows = list(existing.get(key) or [])
        present = {str(row.get("sid")) for row in rows if isinstance(row, dict)}
        for sid, token in by_sid.items():
            if sid in present:
                for row in rows:
                    if isinstance(row, dict) and row.get("sid") == sid:
                        row["text"] = token["text"]
            else:
                rows.append({"sid": sid, "text": token["text"]})
                present.add(sid)
        existing[key] = rows
    return existing


def upsert_cinematic_lockit_in_core(
    core_zip: Path,
    cue_batches: list[list[dict[str, Any]]],
    *,
    languages: tuple[str, ...] = ("english",),
) -> Path:
    """Merge softsub LocKit rows into Lang/<lang>/texts/cinematic.json."""
    import datetime as _dt

    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = core_zip.with_name(core_zip.name + f".roe_cinematic_backup_{stamp}")
    if backup.exists():
        raise FileExistsError(f"backup already exists: {backup}")

    flat_cues: list[dict[str, Any]] = []
    for batch in cue_batches:
        flat_cues.extend(batch)

    temp_dir = Path(tempfile.mkdtemp(prefix="roe_cinematic_", dir=str(core_zip.parent)))
    temp_zip = temp_dir / core_zip.name
    try:
        with zipfile.ZipFile(core_zip, "r") as source:
            replacements: dict[str, bytes] = {}
            for lang in languages:
                member = f"Lang/{lang}/texts/cinematic.json"
                if member not in source.namelist():
                    raise FileNotFoundError(f"Core.zip missing {member}")
                existing = json.loads(source.read(member).decode("utf-8-sig"))
                merged = merge_cinematic_lockit(existing, flat_cues)
                replacements[member] = (
                    json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
                ).encode("utf-8")
            with zipfile.ZipFile(temp_zip, "w") as target:
                for info in source.infolist():
                    data = (
                        replacements[info.filename]
                        if info.filename in replacements
                        else source.read(info.filename)
                    )
                    replacement = zipfile.ZipInfo(info.filename, info.date_time)
                    replacement.comment = info.comment
                    replacement.extra = info.extra
                    replacement.internal_attr = info.internal_attr
                    replacement.external_attr = info.external_attr
                    replacement.compress_type = info.compress_type
                    target.writestr(replacement, data)
        shutil.copy2(core_zip, backup)
        shutil.copy2(temp_zip, core_zip)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return backup


def composed_mp4_meets_contract(probe: dict[str, Any], recipe: ComposedClipRecipe) -> tuple[bool, str]:
    ok, reason = mp4_meets_native_canvas(probe)
    if not ok:
        return False, reason
    if not probe.get("has_audio"):
        return False, "missing audio track"
    duration = float(probe.get("duration_sec") or 0.0)
    expected = float(recipe.expected_narration_sec or MIN_COMPOSED_DURATION_SEC)
    min_dur = max(MIN_COMPOSED_DURATION_SEC, expected - DURATION_SLACK_SEC)
    if duration < min_dur:
        return (
            False,
            f"duration {duration:.2f}s < composed minimum {min_dur:.2f}s "
            f"(expected narration ~{expected:.2f}s)",
        )
    return True, "ok"
