#!/usr/bin/env python3
"""Submit an exact-size SD1.5 img2img job to the local ComfyUI API (V:\\ml\\ComfyUI).

Fails closed if width/height are omitted. Designed for collapse-authentic portrait loops
where hosted generators previously drifted aspect ratio.

Optional ControlNet Tile locks local structure so diffusion can add detail without
redesigning the source masses.

Methodological note (collapse-authentic upscale):
  Do NOT nearest-neighbor the source before Tile. Tile matches the local appearance
  of the control image; an NN mosaic at target size is treated as desired structure,
  so outputs stay blocky. Soft-scale (lanczos/bicubic) the original low-res canvas
  to WxH for both img2img init and the Tile hint, then let denoise invent within-
  block CGI shading.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8188
DEFAULT_CKPT = "v1-5-pruned-emaonly.safetensors"
DEFAULT_TILE_CONTROLNET = "control_v11f1e_sd15_tile.pth"
DEFAULT_LORA = "retrocgi_sd15_v1.safetensors"
DEFAULT_LORA_TRIGGER = "rtrcgi"
# Soft resize is required for Tile upscale; nearest-exact locks source pixel blocks.
DEFAULT_UPSCALE_METHOD = "lanczos"
ALLOWED_UPSCALE_METHODS = (
    "lanczos",
    "bicubic",
    "bilinear",
    "area",
    "nearest-exact",
)


def _api(host: str, port: int, path: str, payload: dict | None = None) -> dict | list | bytes:
    url = f"http://{host}:{port}{path}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read()
        ctype = resp.headers.get("Content-Type", "")
        if "application/json" in ctype or path.startswith("/prompt") or path.startswith("/history"):
            return json.loads(body.decode("utf-8"))
        return body


def upload_image(host: str, port: int, image_path: Path, name: str) -> str:
    # ComfyUI /upload/image expects multipart; keep a tiny stdlib multipart writer.
    boundary = f"----comfy{uuid.uuid4().hex}"
    file_bytes = image_path.read_bytes()
    body = b"".join(
        [
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8"),
            file_bytes,
            (
                f"\r\n--{boundary}\r\n"
                'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
                "true\r\n"
                f"--{boundary}--\r\n"
            ).encode("utf-8"),
        ]
    )
    req = urllib.request.Request(
        f"http://{host}:{port}/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        info = json.loads(resp.read().decode("utf-8"))
    return info["name"]


def build_img2img_workflow(
    *,
    image_name: str,
    positive: str,
    negative: str,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    denoise: float,
    seed: int,
    ckpt: str,
    controlnet_tile: str | None = None,
    controlnet_strength: float = 0.85,
    controlnet_start: float = 0.0,
    controlnet_end: float = 1.0,
    lora_name: str | None = None,
    lora_strength_model: float = 0.7,
    lora_strength_clip: float = 0.7,
    upscale_method: str = DEFAULT_UPSCALE_METHOD,
    control_blur_radius: int = 0,
    control_blur_sigma: float = 1.0,
    init_upscale_model: str | None = None,
    filename_prefix: str = "collapse_exact",
) -> dict:
    """API-format graph: exact WxH soft-scale -> optional LoRA/Tile -> img2img."""
    if upscale_method not in ALLOWED_UPSCALE_METHODS:
        raise ValueError(
            f"upscale_method must be one of {ALLOWED_UPSCALE_METHODS}, got {upscale_method!r}"
        )
    if control_blur_radius < 0:
        raise ValueError("control_blur_radius must be >= 0")
    graph: dict = {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": ckpt},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": filename_prefix, "images": ["8", 0]},
        },
        "10": {
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
        },
    }

    # Init canvas: optional RealESRGAN (or other) then exact soft resize to WxH.
    init_src: list = ["10", 0]
    if init_upscale_model:
        graph["14"] = {
            "class_type": "UpscaleModelLoader",
            "inputs": {"model_name": init_upscale_model},
        }
        graph["15"] = {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {"upscale_model": ["14", 0], "image": ["10", 0]},
        }
        init_src = ["15", 0]

    graph["11"] = {
        "class_type": "ImageScale",
        "inputs": {
            "image": init_src,
            "upscale_method": upscale_method,
            "width": width,
            "height": height,
            "crop": "disabled",
        },
    }
    graph["12"] = {
        "class_type": "VAEEncode",
        "inputs": {"pixels": ["11", 0], "vae": ["4", 2]},
    }

    # Optional softer Tile hint (split init vs control).
    control_image_ref: list = ["11", 0]
    if control_blur_radius > 0:
        graph["16"] = {
            "class_type": "ImageBlur",
            "inputs": {
                "image": ["11", 0],
                "blur_radius": control_blur_radius,
                "sigma": control_blur_sigma,
            },
        }
        control_image_ref = ["16", 0]

    if lora_name:
        graph["30"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["4", 0],
                "clip": ["4", 1],
                "lora_name": lora_name,
                "strength_model": lora_strength_model,
                "strength_clip": lora_strength_clip,
            },
        }
        model_ref: list = ["30", 0]
        clip_ref: list = ["30", 1]
    else:
        model_ref = ["4", 0]
        clip_ref = ["4", 1]

    graph["6"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": positive, "clip": clip_ref},
    }
    graph["7"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": negative, "clip": clip_ref},
    }

    if controlnet_tile:
        graph["20"] = {
            "class_type": "ControlNetLoader",
            "inputs": {"control_net_name": controlnet_tile},
        }
        # Soft exact-size canvas (optionally blurred) as Tile hint — never NN mosaic.
        graph["21"] = {
            "class_type": "ControlNetApplyAdvanced",
            "inputs": {
                "positive": ["6", 0],
                "negative": ["7", 0],
                "control_net": ["20", 0],
                "image": control_image_ref,
                "strength": controlnet_strength,
                "start_percent": controlnet_start,
                "end_percent": controlnet_end,
            },
        }
        positive_ref: list = ["21", 0]
        negative_ref: list = ["21", 1]
    else:
        positive_ref = ["6", 0]
        negative_ref = ["7", 0]

    if filename_prefix == "collapse_exact":
        if lora_name and controlnet_tile:
            graph["9"]["inputs"]["filename_prefix"] = "collapse_tile_lora"
        elif controlnet_tile:
            graph["9"]["inputs"]["filename_prefix"] = "collapse_tile"
        elif lora_name:
            graph["9"]["inputs"]["filename_prefix"] = "collapse_lora"

    graph["3"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": denoise,
            "model": model_ref,
            "positive": positive_ref,
            "negative": negative_ref,
            "latent_image": ["12", 0],
        },
    }
    return graph


def wait_history(host: str, port: int, prompt_id: str, timeout_s: float = 300.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        hist = _api(host, port, f"/history/{prompt_id}")
        if isinstance(hist, dict) and prompt_id in hist:
            return hist[prompt_id]
        time.sleep(1.0)
    raise TimeoutError(f"ComfyUI prompt {prompt_id} timed out after {timeout_s}s")


def download_output(host: str, port: int, filename: str, subfolder: str, out_path: Path) -> None:
    q = f"/view?filename={urllib.request.quote(filename)}&subfolder={urllib.request.quote(subfolder)}&type=output"
    data = _api(host, port, q)
    assert isinstance(data, (bytes, bytearray))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", type=Path, required=True, help="Source image (prefer original low-res)")
    ap.add_argument("--out", type=Path, required=True, help="Output PNG path")
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--positive", type=str, required=True)
    ap.add_argument(
        "--negative",
        type=str,
        default="hand-painted, oil painting, illustration, anime, photoreal modern, text, watermark",
    )
    ap.add_argument("--steps", type=int, default=28)
    ap.add_argument("--cfg", type=float, default=5.0)
    ap.add_argument("--denoise", type=float, default=0.35)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ckpt", type=str, default=DEFAULT_CKPT)
    ap.add_argument(
        "--upscale-method",
        type=str,
        default=DEFAULT_UPSCALE_METHOD,
        choices=ALLOWED_UPSCALE_METHODS,
        help=(
            "ImageScale method used for BOTH img2img init and ControlNet Tile hint "
            f"(default: {DEFAULT_UPSCALE_METHOD}). Use nearest-exact only for deliberate "
            "pixel-grid ablation; it makes Tile lock source blocks."
        ),
    )
    ap.add_argument(
        "--controlnet-tile",
        nargs="?",
        const=DEFAULT_TILE_CONTROLNET,
        default=None,
        help=(
            "Enable SD1.5 ControlNet Tile. Optional value is the model filename under "
            f"models/controlnet/ (default: {DEFAULT_TILE_CONTROLNET})."
        ),
    )
    ap.add_argument("--controlnet-strength", type=float, default=0.85)
    ap.add_argument("--controlnet-start", type=float, default=0.0)
    ap.add_argument("--controlnet-end", type=float, default=1.0)
    ap.add_argument(
        "--control-blur-radius",
        type=int,
        default=0,
        help="If >0, blur the Tile control image (init stays sharp). Split init vs control.",
    )
    ap.add_argument("--control-blur-sigma", type=float, default=1.5)
    ap.add_argument(
        "--init-upscale-model",
        type=str,
        default=None,
        help="Optional models/upscale_models name (e.g. RealESRGAN_x4plus.pth) before exact resize.",
    )
    ap.add_argument(
        "--lora",
        nargs="?",
        const=DEFAULT_LORA,
        default=None,
        help=(
            "Enable an SD1.5 LoRA. Optional value is the filename under models/loras/ "
            f"(default: {DEFAULT_LORA})."
        ),
    )
    ap.add_argument("--lora-strength", type=float, default=0.7, help="Model+CLIP LoRA strength")
    ap.add_argument("--lora-strength-model", type=float, default=None)
    ap.add_argument("--lora-strength-clip", type=float, default=None)
    ap.add_argument(
        "--lora-trigger",
        type=str,
        default=DEFAULT_LORA_TRIGGER,
        help=f"Prepended to --positive when --lora is set (default: {DEFAULT_LORA_TRIGGER})",
    )
    ap.add_argument("--no-lora-trigger", action="store_true", help="Do not prepend the LoRA trigger word")
    ap.add_argument("--filename-prefix", type=str, default="collapse_exact")
    ap.add_argument("--host", type=str, default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument(
        "--project-nearest-collapse",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "After decode, stamp portrait RGB onto Pillow-NEAREST sample sites so the "
            "candidate nearest-collapses to --image (default: on). Other HR pixels stay "
            "(CGI detail). Pass --no-project-nearest-collapse to disable."
        ),
    )
    ap.add_argument(
        "--nearest-collapse-strength",
        type=float,
        default=1.0,
        help="1.0 hard-stamp NN sample pixels; (0,1) blends toward the portrait",
    )
    args = ap.parse_args()

    if args.width <= 0 or args.height <= 0:
        raise SystemExit("width and height must be positive")
    if args.width % 8 != 0 or args.height % 8 != 0:
        raise SystemExit(f"SD1.5 latents require multiples of 8; got {args.width}x{args.height}")
    if args.project_nearest_collapse:
        from PIL import Image as _PILImage

        with _PILImage.open(args.image) as _src:
            sw, sh = _src.size
        if args.width % sw != 0 or args.height % sh != 0:
            raise SystemExit(
                "--project-nearest-collapse requires width/height integer multiples of "
                f"source {sw}x{sh}; got {args.width}x{args.height}"
            )
        if not (0.0 < args.nearest_collapse_strength <= 1.0):
            raise SystemExit("--nearest-collapse-strength must be in (0, 1]")
    if not (0.0 <= args.controlnet_strength <= 10.0):
        raise SystemExit("controlnet-strength out of range")
    if not (0.0 <= args.controlnet_start <= 1.0 and 0.0 <= args.controlnet_end <= 1.0):
        raise SystemExit("controlnet start/end must be in [0,1]")
    if args.controlnet_start > args.controlnet_end:
        raise SystemExit("controlnet-start must be <= controlnet-end")
    if args.controlnet_tile and args.upscale_method == "nearest-exact":
        raise SystemExit(
            "refusing ControlNet Tile with --upscale-method nearest-exact: that combo "
            "locks the source pixel grid and produces the blocky outputs we already saw. "
            "Pass --upscale-method lanczos (default) or bicubic, then optionally "
            "--project-nearest-collapse to enforce NN sample-site validity without "
            "painting flat NN tiles into Tile."
        )
    if args.control_blur_radius < 0:
        raise SystemExit("control-blur-radius must be >= 0")
    if args.control_blur_radius > 0 and not args.controlnet_tile:
        raise SystemExit("--control-blur-radius requires --controlnet-tile")

    lora_strength_model = args.lora_strength if args.lora_strength_model is None else args.lora_strength_model
    lora_strength_clip = args.lora_strength if args.lora_strength_clip is None else args.lora_strength_clip
    if args.lora is not None and not (-100.0 <= lora_strength_model <= 100.0 and -100.0 <= lora_strength_clip <= 100.0):
        raise SystemExit("lora strengths out of range")

    positive = args.positive
    if args.lora and not args.no_lora_trigger and args.lora_trigger:
        trigger = args.lora_trigger.strip()
        if trigger and not positive.lower().startswith(trigger.lower()):
            positive = f"{trigger}, {positive}"

    image_path = args.image.resolve()
    if not image_path.is_file():
        raise SystemExit(f"image not found: {image_path}")

    try:
        _api(args.host, args.port, "/system_stats")
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"ComfyUI not reachable at http://{args.host}:{args.port} ({exc}). "
            "Start it with: bash tools/local_imagegen/comfyui_vdrive.sh serve"
        ) from exc

    uploaded = upload_image(args.host, args.port, image_path, image_path.name)
    workflow = build_img2img_workflow(
        image_name=uploaded,
        positive=positive,
        negative=args.negative,
        width=args.width,
        height=args.height,
        steps=args.steps,
        cfg=args.cfg,
        denoise=args.denoise,
        seed=args.seed,
        ckpt=args.ckpt,
        controlnet_tile=args.controlnet_tile,
        controlnet_strength=args.controlnet_strength,
        controlnet_start=args.controlnet_start,
        controlnet_end=args.controlnet_end,
        lora_name=args.lora,
        lora_strength_model=lora_strength_model,
        lora_strength_clip=lora_strength_clip,
        upscale_method=args.upscale_method,
        control_blur_radius=args.control_blur_radius,
        control_blur_sigma=args.control_blur_sigma,
        init_upscale_model=args.init_upscale_model,
        filename_prefix=args.filename_prefix,
    )
    client_id = str(uuid.uuid4())
    resp = _api(args.host, args.port, "/prompt", {"prompt": workflow, "client_id": client_id})
    assert isinstance(resp, dict)
    if resp.get("node_errors"):
        raise SystemExit(f"ComfyUI node_errors: {json.dumps(resp['node_errors'], indent=2)}")
    real_id = resp["prompt_id"]
    hist = wait_history(args.host, args.port, real_id)
    status = hist.get("status") or {}
    if status.get("status_str") == "error" or status.get("completed") is False:
        raise SystemExit(f"ComfyUI job failed: {json.dumps(hist)[:1000]}")
    outputs = hist.get("outputs") or {}
    images = []
    for node_out in outputs.values():
        images.extend(node_out.get("images") or [])
    if not images:
        raise SystemExit(f"no images in ComfyUI history for {real_id}: {json.dumps(hist)[:500]}")
    img = images[0]
    download_output(args.host, args.port, img["filename"], img.get("subfolder", ""), args.out.resolve())

    from PIL import Image

    with Image.open(args.out) as im:
        if im.size != (args.width, args.height):
            raise SystemExit(f"size mismatch: expected {args.width}x{args.height}, got {im.size}")

    nearest_meta = None
    if args.project_nearest_collapse:
        from nearest_collapse import nearest_collapse_metrics, project_nearest_collapse

        lr = Image.open(image_path)
        before = nearest_collapse_metrics(Image.open(args.out), lr)
        projected = project_nearest_collapse(
            Image.open(args.out),
            lr,
            strength=args.nearest_collapse_strength,
        )
        if projected.size != (args.width, args.height):
            raise SystemExit(
                f"nearest project changed size: expected {args.width}x{args.height}, got {projected.size}"
            )
        projected.convert("RGB").save(args.out)
        after = nearest_collapse_metrics(projected, lr)
        nearest_meta = {
            "enabled": True,
            "strength": args.nearest_collapse_strength,
            "before": before,
            "after": after,
            "rule": "Pillow NEAREST sample sites (integer S: offset S//2 in each block)",
        }

    meta = {
        "schema": "local_imagegen.exact_img2img.v5",
        "image": str(image_path),
        "out": str(args.out.resolve()),
        "width": args.width,
        "height": args.height,
        "seed": args.seed,
        "denoise": args.denoise,
        "cfg": args.cfg,
        "steps": args.steps,
        "ckpt": args.ckpt,
        "positive": positive,
        "upscale_method": args.upscale_method,
        "control_blur_radius": args.control_blur_radius if args.controlnet_tile else None,
        "control_blur_sigma": args.control_blur_sigma if args.control_blur_radius > 0 else None,
        "init_upscale_model": args.init_upscale_model,
        "controlnet_tile": args.controlnet_tile,
        "controlnet_strength": args.controlnet_strength if args.controlnet_tile else None,
        "controlnet_start": args.controlnet_start if args.controlnet_tile else None,
        "controlnet_end": args.controlnet_end if args.controlnet_tile else None,
        "lora": args.lora,
        "lora_strength_model": lora_strength_model if args.lora else None,
        "lora_strength_clip": lora_strength_clip if args.lora else None,
        "lora_trigger": args.lora_trigger if args.lora and not args.no_lora_trigger else None,
        "project_nearest_collapse": nearest_meta,
        "prompt_id": real_id,
        "proof": (
            "local ComfyUI exact-size img2img"
            + f" ({args.upscale_method} pre-scale)"
            + (" + ControlNet Tile" if args.controlnet_tile else "")
            + (" + LoRA" if args.lora else "")
            + (" + nearest-collapse project" if args.project_nearest_collapse else "")
            + " (size check passed)"
        ),
    }
    args.out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
