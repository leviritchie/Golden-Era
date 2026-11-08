#!/usr/bin/env python3
"""Tag prop landmarks on sprite frames with a vision model (OpenAI).

The caller supplies prop names + marking instructions in a definitions JSON.
The vision model returns pixel coordinates per frame; this script writes
``props_coords.json`` and the preview GIF via ``authorwrite_prop_keypoints``.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from PIL import Image

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from authorwrite_prop_keypoints import _frames_xy_from_coords  # noqa: E402
from prop_author_common import write_prop_authored_clip  # noqa: E402


def _load_definitions(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    props = data.get("props")
    if not isinstance(props, list) or not props:
        raise ValueError("definitions JSON must contain a non-empty 'props' array")
    for entry in props:
        if "name" not in entry or "mark" not in entry:
            raise ValueError("each prop needs 'name' and 'mark'")
    return data


def _load_bundle(path: Path) -> dict[str, Any]:
    bundle = json.loads(path.read_text(encoding="utf-8"))
    if bundle.get("schema") != "homm3_prop_author_bundle.v1":
        raise ValueError(f"unsupported bundle schema: {bundle.get('schema')}")
    return bundle


def _resize_for_api(image: Image.Image, max_side: int) -> tuple[Image.Image, float, float]:
    width, height = image.size
    scale = min(1.0, float(max_side) / float(max(width, height)))
    if scale >= 1.0:
        return image.copy(), 1.0, 1.0
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    sx = width / new_w
    sy = height / new_h
    return resized, sx, sy


def _image_to_data_url(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _safe_coord_number(raw: Any) -> float:
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return float(text)
    if re.fullmatch(r"[\d\.\s+\-*/()]+", text):
        value = eval(text, {"__builtins__": {}})  # noqa: S307 — model-emitted int math only
        return float(value)
    raise ValueError(f"unsupported coordinate expression: {raw!r}")


def _parse_json_content(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # LLaVA sometimes emits invalid JSON like [512 - 2, 347].
        repaired = re.sub(
            r"\[\s*([^,\]]+)\s*,\s*([^,\]]+)\s*\]",
            lambda match: json.dumps(
                [_safe_coord_number(match.group(1)), _safe_coord_number(match.group(2))]
            ),
            text,
        )
        data = json.loads(repaired)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object, got {type(data).__name__}")
    return data


def _build_prompt(
    *,
    definitions: dict[str, Any],
    sent_width: int,
    sent_height: int,
    full_width: int,
    full_height: int,
    frame_index: int,
) -> str:
    prop_lines = "\n".join(
        f'- "{entry["name"]}": {entry["mark"]}' for entry in definitions["props"]
    )
    facing = definitions.get("facing", "")
    facing_line = f"\nFacing / layout: {facing}\n" if facing else "\n"
    return (
        "You are marking 2D sprite prop landmarks for a game animation frame.\n"
        f"Frame index: {frame_index}.\n"
        f"The attached image is {sent_width}x{sent_height} pixels (top-left origin).\n"
        f"Return coordinates in THIS image's pixel space ({sent_width}x{sent_height}).\n"
        f"{facing_line}"
        "Mark exactly these props:\n"
        f"{prop_lines}\n\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "frameIndex": <int>,\n'
        '  "xy": {\n'
        '    "<PropName>": [x, y],\n'
        "    ...\n"
        "  }\n"
        "}\n"
        "Use integer pixel coordinates. Every listed prop must be present."
    )


def _ollama_generate(*, model: str, prompt: str, image: Image.Image) -> str:
    import urllib.error
    import urllib.request

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [encoded],
        "stream": False,
    }
    request = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"ollama request failed: {exc}") from exc
    return str(data.get("response") or "")


def _coords_from_payload(
    payload: dict[str, Any],
    *,
    frame_index: int,
    expected: list[str],
    sent_w: int,
    sent_h: int,
    sx: float,
    sy: float,
    full_w: int,
    full_h: int,
) -> dict[str, tuple[int, int]]:
    if int(payload.get("frameIndex", frame_index)) != int(frame_index):
        raise ValueError(f"frame {frame_index}: model returned wrong frameIndex")
    raw_xy = payload.get("xy")
    if not isinstance(raw_xy, dict):
        raise ValueError(f"frame {frame_index}: missing xy object")
    out: dict[str, tuple[int, int]] = {}
    for name in expected:
        if name not in raw_xy:
            raise ValueError(f"frame {frame_index}: missing prop {name}")
        pair = raw_xy[name]
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(f"frame {frame_index}: bad coordinate for {name}")
        x_raw = _safe_coord_number(pair[0])
        y_raw = _safe_coord_number(pair[1])
        if 0.0 <= x_raw <= 1.0 and 0.0 <= y_raw <= 1.0:
            x = int(round(x_raw * (full_w - 1)))
            y = int(round(y_raw * (full_h - 1)))
            space = "normalized"
        elif 0.0 <= x_raw <= float(sent_w) and 0.0 <= y_raw <= float(sent_h):
            x = int(round(x_raw * sx))
            y = int(round(y_raw * sy))
            space = "sent_pixels"
        else:
            raise ValueError(
                f"frame {frame_index}: {name} coords ({x_raw}, {y_raw}) are neither "
                f"normalized 0-1 nor sent-image pixels 0-{sent_w}/0-{sent_h}"
            )
        if not (0 <= x < full_w and 0 <= y < full_h):
            raise ValueError(
                f"frame {frame_index}: {name} out of bounds ({x}, {y}) for {full_w}x{full_h} "
                f"(from {space} ({x_raw}, {y_raw}))"
            )
        out[name] = (x, y)
    return out


def tag_frame_with_vision(
    client: Any,
    *,
    sprite_path: Path,
    frame_index: int,
    definitions: dict[str, Any],
    model: str,
    max_side: int,
    provider: str,
) -> dict[str, tuple[int, int]]:
    with Image.open(sprite_path) as im:
        image = im.convert("RGBA")
    full_w, full_h = image.size
    sent, sx, sy = _resize_for_api(image, max_side)
    sent_w, sent_h = sent.size
    prompt = _build_prompt(
        definitions=definitions,
        sent_width=sent_w,
        sent_height=sent_h,
        full_width=full_w,
        full_height=full_h,
        frame_index=frame_index,
    )
    if provider == "openai":
        response = client.chat.completions.create(
            model=model,
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You locate precise pixel landmarks on sprite art. "
                        "Output valid JSON only."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": _image_to_data_url(sent), "detail": "high"},
                        },
                    ],
                },
            ],
        )
        content = response.choices[0].message.content or ""
    elif provider == "anthropic":
        buf = io.BytesIO()
        sent.save(buf, format="PNG")
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            temperature=0.0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": encoded,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        content = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                content += block.text
    elif provider == "ollama":
        facing = definitions.get("facing", "")
        facing_line = f"Facing / layout: {facing}\n" if facing else ""
        ollama_prompt = (
            "You are marking 2D sprite prop landmarks for a game animation frame.\n"
            f"Frame index: {frame_index}.\n"
            f"Image size: {sent_w}x{sent_h} pixels (origin top-left).\n"
            f"{facing_line}"
            "Mark these props:\n"
            + "\n".join(f'- {entry["name"]}: {entry["mark"]}' for entry in definitions["props"])
            + "\n\nReturn ONLY valid JSON. Use decimal numbers 0.0-1.0 for x and y "
            "(x=0 is left edge, y=0 is top edge). No math expressions.\n"
            "{\n"
            f'  "frameIndex": {frame_index},\n'
            '  "xy": {\n'
            + ",\n".join(
                f'    "{entry["name"]}": [x, y]'
                for entry in definitions["props"]
            )
            + "\n  }\n}"
        )
        content = _ollama_generate(model=model, prompt=ollama_prompt, image=sent)
    else:
        raise ValueError(f"unsupported provider: {provider}")

    payload = _parse_json_content(content)
    expected = [str(entry["name"]) for entry in definitions["props"]]
    if provider == "ollama":
        return _coords_from_payload(
            payload,
            frame_index=frame_index,
            expected=expected,
            sent_w=sent_w,
            sent_h=sent_h,
            sx=sx,
            sy=sy,
            full_w=full_w,
            full_h=full_h,
        )

    if int(payload.get("frameIndex", frame_index)) != int(frame_index):
        raise ValueError(f"frame {frame_index}: model returned wrong frameIndex")
    raw_xy = payload.get("xy")
    if not isinstance(raw_xy, dict):
        raise ValueError(f"frame {frame_index}: missing xy object")
    out: dict[str, tuple[int, int]] = {}
    for name in expected:
        if name not in raw_xy:
            raise ValueError(f"frame {frame_index}: missing prop {name}")
        pair = raw_xy[name]
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(f"frame {frame_index}: bad coordinate for {name}")
        x = int(round(float(pair[0]) * sx))
        y = int(round(float(pair[1]) * sy))
        if not (0 <= x < full_w and 0 <= y < full_h):
            raise ValueError(
                f"frame {frame_index}: {name} out of bounds ({x}, {y}) for {full_w}x{full_h}"
            )
        out[name] = (x, y)
    return out


def tag_frames(
    *,
    frame_jobs: list[tuple[int, Path]],
    definitions: dict[str, Any],
    model: str,
    max_side: int,
    workers: int,
    provider: str,
) -> list[dict[str, Any]]:
    if provider == "openai":
        from openai import OpenAI

        client = OpenAI()
    elif provider == "anthropic":
        from anthropic import Anthropic

        client = Anthropic()
    elif provider == "ollama":
        client = None
    else:
        raise ValueError(f"unsupported provider: {provider}")
    results: dict[int, dict[str, tuple[int, int]]] = {}

    def _job(frame_index: int, sprite_path: Path) -> tuple[int, dict[str, tuple[int, int]]]:
        xy = tag_frame_with_vision(
            client,
            sprite_path=sprite_path,
            frame_index=frame_index,
            definitions=definitions,
            model=model,
            max_side=max_side,
            provider=provider,
        )
        return frame_index, xy

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(_job, idx, path) for idx, path in frame_jobs]
        for future in as_completed(futures):
            frame_index, xy = future.result()
            results[frame_index] = xy

    frames_out = []
    for frame_index, _ in frame_jobs:
        frames_out.append({"frameIndex": int(frame_index), "xy": results[int(frame_index)]})
    return frames_out


def write_coords_and_preview(
    *,
    coords_path: Path,
    frames_dir: Path,
    out_dir: Path,
    clip_id: str,
    unit_sid: str,
    definitions: dict[str, Any],
    frames: list[dict[str, Any]],
    method_note: str,
) -> dict[str, Any]:
    joint_names = [str(entry["name"]) for entry in definitions["props"]]
    coords_doc = {
        "clipId": clip_id,
        "unitSid": unit_sid,
        "joints": joint_names,
        "edgeSet": str(definitions.get("edgeSet") or "crusader_sword_shield"),
        "notes": method_note,
        "frames": frames,
    }
    coords_path.parent.mkdir(parents=True, exist_ok=True)
    coords_path.write_text(json.dumps(coords_doc, indent=2) + "\n", encoding="utf-8")

    frames_xy, frame_indices = _frames_xy_from_coords(coords_doc)
    result = write_prop_authored_clip(
        clip_id=clip_id,
        unit_sid=unit_sid,
        frames_dir=frames_dir,
        out_dir=out_dir,
        frames_xy=frames_xy,
        joint_names=joint_names,
        notes=method_note,
        edge_set=str(definitions.get("edgeSet") or "crusader_sword_shield"),
        frame_indices=frame_indices,
    )
    # Patch method metadata for downstream readers.
    keypoints_path = Path(result["keypoints"])
    doc = json.loads(keypoints_path.read_text(encoding="utf-8"))
    doc["method"] = "vision_model_landmark_authoring"
    doc["proof"] = (
        f"prop landmarks tagged by vision model ({method_note}); "
        "not OE runtime; not mesh projection"
    )
    for frame in doc.get("frames", []):
        joints = frame.get("joints", {})
        for joint in joints.values():
            joint["source"] = "vision_model"
    keypoints_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    result["coords"] = str(coords_path).replace("\\", "/")
    result["method"] = "vision_model_landmark_authoring"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vision-model prop landmark tagger")
    parser.add_argument(
        "--definitions",
        type=Path,
        default=_SCRIPT_DIR / "prop_definitions/crusader_sword_shield.json",
        help="Prop names + marking instructions JSON",
    )
    parser.add_argument("--bundle", type=Path, help="author_bundle.json from prep_prop_author_bundle.py")
    parser.add_argument("--frames-dir", type=Path, help="Sprite directory (without --bundle)")
    parser.add_argument("--out-dir", type=Path, help="Output directory (without --bundle)")
    parser.add_argument("--clip-id", type=str, default="move_g0")
    parser.add_argument("--unit-sid", type=str, default="h3_crusader")
    parser.add_argument("--provider", choices=("ollama", "anthropic", "openai"), default="ollama")
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--max-side", type=int, default=512, help="Resize longest side sent to vision model")
    parser.add_argument("--workers", type=int, default=1, help="Parallel frame requests (ollama: keep at 1)")
    args = parser.parse_args(argv)

    definitions = _load_definitions(args.definitions)
    provider = str(args.provider)
    model = args.model or {
        "ollama": "llava:7b",
        "anthropic": "claude-sonnet-4-20250514",
        "openai": "gpt-4o",
    }[provider]

    if args.bundle:
        bundle = _load_bundle(args.bundle)
        frames_dir = Path(bundle["spritesDir"])
        out_dir = Path(args.out_dir or bundle["outDir"]).with_name(
            Path(bundle["outDir"]).name + "_vision"
        )
        clip_id = str(bundle.get("clipId") or args.clip_id)
        unit_sid = str(bundle.get("unitSid") or args.unit_sid)
        frame_jobs = [
            (int(entry["frameIndex"]), Path(entry["stagedSprite"]))
            for entry in bundle["frames"]
        ]
        sequence = str(bundle.get("sequence") or clip_id)
    else:
        if not args.frames_dir or not args.out_dir:
            parser.error("--frames-dir and --out-dir are required without --bundle")
        frames_dir = Path(args.frames_dir)
        out_dir = Path(args.out_dir)
        clip_id = args.clip_id
        unit_sid = args.unit_sid
        sequence = clip_id
        numbered = sorted(
            [p for p in frames_dir.glob("*.png") if p.stem.isdigit()],
            key=lambda p: int(p.stem),
        )
        if not numbered:
            raise FileNotFoundError(f"no numbered PNG sprites in {frames_dir}")
        frame_jobs = [(int(p.stem), p) for p in numbered]

    method_note = (
        f"{sequence}; vision model {provider}/{model}; props="
        + ",".join(str(entry["name"]) for entry in definitions["props"])
    )
    frames = tag_frames(
        frame_jobs=frame_jobs,
        definitions=definitions,
        model=model,
        max_side=int(args.max_side),
        workers=int(args.workers),
        provider=provider,
    )
    coords_path = out_dir / "props_coords.json"
    result = write_coords_and_preview(
        coords_path=coords_path,
        frames_dir=frames_dir,
        out_dir=out_dir,
        clip_id=clip_id,
        unit_sid=unit_sid,
        definitions=definitions,
        frames=frames,
        method_note=method_note,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
