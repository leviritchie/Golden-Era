#!/usr/bin/env python3
"""Extract AB/SoD hub-strip stills, crop candidates, and bake main_icon art."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))

from ab_sod_video_map import HUB_STRIP_STEMS  # noqa: E402
from campaign_selection_icon import (  # noqa: E402
    COMPOSE_VERTICAL_FOCUS,
    build_main_icon_from_still,
)
from campaign_video_clip import resolve_ffmpeg  # noqa: E402

HUB_STRIPS_DIR = (
    ROOT
    / "artifacts"
    / "campaign_port_poc"
    / "ab_sod_campaigns"
    / "video_sources"
    / "hub_strips"
)
OUT_DIR = (
    ROOT
    / "artifacts"
    / "campaign_port_poc"
    / "ab_sod_campaigns"
    / "storyhub_visual"
)
CROPS_CATALOG = ROOT / "scenarios" / "ab_sod_campaigns" / "selection_icon_crops.v1.json"

# Curated after still extract + visual review of letterbox-trimmed hub frames.
DEFAULT_CROPS: dict[str, dict[str, Any]] = {
    "ab": {
        "focusX": 0.50,
        "focusY": 0.42,
        "reason": "Armageddon's Blade planted in the cyan blast column",
    },
    "blood": {
        "focusX": 0.50,
        "focusY": 0.45,
        "reason": "Twin dragons coiled around the glowing blood vial",
    },
    "slayer": {
        "focusX": 0.68,
        "focusY": 0.45,
        "reason": "Crystal dragon head and talons on the snow mound",
    },
    "festival": {
        "focusX": 0.50,
        "focusY": 0.42,
        "reason": "Battlefield corpse mound and clan flags under the fire sky",
    },
    "fire": {
        "focusX": 0.32,
        "focusY": 0.48,
        "reason": "Family group in the ruined timber interior (Playing with Fire / C1pf2)",
    },
    "fool": {
        "focusX": 0.42,
        "focusY": 0.55,
        "reason": "Shoreline figure at the surf line between jungle and sea (Foolhardy / C1fw1)",
    },
    "yog": {
        "focusX": 0.28,
        "focusY": 0.45,
        "reason": "Hooded figure overlooking the snowy mountain valley",
    },
    "gelu": {
        "focusX": 0.48,
        "focusY": 0.40,
        "reason": "Central armored heroine raising the blade with Gelu at left",
    },
    "crag": {
        "focusX": 0.50,
        "focusY": 0.48,
        "reason": "Barbarian and hooded contact across the glowing tavern table",
    },
    "gem": {
        "focusX": 0.35,
        "focusY": 0.45,
        "reason": "Green-cloaked heroine at the candlelit meeting table",
    },
    "sandro": {
        "focusX": 0.52,
        "focusY": 0.40,
        "reason": "Red dragon perched on the cavern castle spires",
    },
    "final": {
        "focusX": 0.55,
        "focusY": 0.42,
        "reason": "Necropolis castle with spectral blue dragon over the right wall",
    },
}

FOCUS_SWEEP = (0.28, 0.40, 0.50, 0.55, 0.65, 0.72, 0.82)


def fail(msg: str) -> None:
    raise SystemExit(f"ab/sod selection icon bake failed: {msg}")


def resolve_hub_strip(stem: str) -> Path:
    for ext in (".bik", ".smk", ".BIK", ".SMK"):
        path = HUB_STRIPS_DIR / f"{stem}{ext}"
        if path.is_file():
            return path
    fail(f"missing hub strip for stem {stem} under {HUB_STRIPS_DIR}")


def extract_still_png(source: Path, dest: Path, *, frame_fraction: float = 0.35) -> None:
    ffmpeg = resolve_ffmpeg()
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Probe duration then seek.
    probe = subprocess.run(
        [str(ffmpeg), "-i", str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    import re

    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", probe.stderr or "")
    if not match:
        fail(f"could not probe duration for {source}")
    duration = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
    seek = max(0.0, min(duration * frame_fraction, max(0.0, duration - 0.05)))
    cmd = [
        str(ffmpeg),
        "-y",
        "-ss",
        f"{seek:.3f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not dest.is_file():
        fail(f"ffmpeg still extract failed for {source}: {proc.stderr[-400:]}")


def write_crop_candidates(hub: str, still: Path, cand_dir: Path) -> list[Path]:
    from PIL import Image

    cand_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for fx in FOCUS_SWEEP:
        out = cand_dir / f"{hub}_fx{fx:.2f}.png"
        build_main_icon_from_still(
            still,
            icon_out=out,
            compose_policy=COMPOSE_VERTICAL_FOCUS,
            focus_x=fx,
            focus_y=0.48,
        )
        written.append(out)
        # also keep a tiny preview name with size stamp
        _ = Image.open(out).size
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hub", action="append", dest="hubs", default=None)
    parser.add_argument("--skip-candidates", action="store_true")
    parser.add_argument("--crops-only", action="store_true", help="Rewrite catalog + icons from existing stills")
    args = parser.parse_args()

    hubs = list(args.hubs) if args.hubs else list(HUB_STRIP_STEMS.keys())
    for hub in hubs:
        if hub not in HUB_STRIP_STEMS:
            fail(f"unknown hub {hub}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    icons_dir = OUT_DIR / "icons"
    cand_dir = OUT_DIR / "crop_candidates"
    icons_dir.mkdir(parents=True, exist_ok=True)

    crops_doc: dict[str, Any] = {
        "schema": "homm3_campaign_selection_icon_crops.v1",
        "nativeMainIconSize": [378, 693],
        "composePolicy": COMPOSE_VERTICAL_FOCUS,
        "notes": (
            "AB/SoD hub strips → selection still → curated vertical focus into "
            "native 378×693 main_icon. focusX/focusY are normalized [0,1] in the "
            "letterbox-trimmed still."
        ),
        "crops": {},
    }

    reports: list[dict[str, Any]] = []
    for hub in hubs:
        stem = HUB_STRIP_STEMS[hub]
        still = OUT_DIR / f"{hub}_selection_still.png"
        if not args.crops_only:
            source = resolve_hub_strip(stem)
            print(f"extract still {hub} <- {source.name}")
            extract_still_png(source, still)
            if not args.skip_candidates:
                cands = write_crop_candidates(hub, still, cand_dir)
                print(f"  wrote {len(cands)} crop candidates")

        if not still.is_file():
            fail(f"missing still {still}")

        crop = dict(DEFAULT_CROPS[hub])
        # If a prior catalog exists, preserve curated focus when re-baking.
        if CROPS_CATALOG.is_file():
            prior = json.loads(CROPS_CATALOG.read_text(encoding="utf-8"))
            prior_row = (prior.get("crops") or {}).get(hub)
            if isinstance(prior_row, dict) and "focusX" in prior_row:
                crop["focusX"] = float(prior_row["focusX"])
                crop["focusY"] = float(prior_row.get("focusY", crop["focusY"]))
                if prior_row.get("reason"):
                    crop["reason"] = prior_row["reason"]

        icon_out = icons_dir / f"{hub}_main_icon.png"
        meta = build_main_icon_from_still(
            still,
            icon_out=icon_out,
            compose_policy=COMPOSE_VERTICAL_FOCUS,
            focus_x=float(crop["focusX"]),
            focus_y=float(crop["focusY"]),
        )
        rel_still = str(still.relative_to(ROOT)).replace("\\", "/")
        rel_icon = str(icon_out.relative_to(ROOT)).replace("\\", "/")
        crops_doc["crops"][hub] = {
            "focusX": float(crop["focusX"]),
            "focusY": float(crop["focusY"]),
            "reason": crop["reason"],
            "hubStripStem": stem,
            "stillArtifact": rel_still,
            "iconArtifact": rel_icon,
        }
        reports.append({"hub": hub, **meta})
        print(
            f"  icon {hub}: focus=({crop['focusX']},{crop['focusY']}) "
            f"still={meta['stillSize']} -> {meta['iconSize']}"
        )

    # Merge with any hubs not in this run.
    if CROPS_CATALOG.is_file() and args.hubs:
        prior = json.loads(CROPS_CATALOG.read_text(encoding="utf-8"))
        for key, row in (prior.get("crops") or {}).items():
            if key not in crops_doc["crops"]:
                crops_doc["crops"][key] = row

    CROPS_CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CROPS_CATALOG.write_text(json.dumps(crops_doc, indent=2) + "\n", encoding="utf-8")
    report_path = OUT_DIR / "selection_icon_bake.v1.json"
    report_path.write_text(
        json.dumps(
            {
                "schema": "homm3.ab_sod_selection_icon_bake.v1",
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "cropsCatalog": str(CROPS_CATALOG.relative_to(ROOT)).replace("\\", "/"),
                "hubs": reports,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {CROPS_CATALOG}")
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
