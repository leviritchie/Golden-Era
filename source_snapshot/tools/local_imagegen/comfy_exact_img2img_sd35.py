#!/usr/bin/env python3
"""Submit an exact-size SD3.5 Medium job to the local ComfyUI API.

Modes:
  --init lanczos  img2img from soft-scaled portrait (legacy)
  --init none     text2img from empty latent; portrait is collapse target only

Inter-step nearest-collapse via KSamplerNearestCollapse (default on).

Requires:
  V:\\ml\\ComfyUI\\models\\checkpoints\\sd3.5_medium_incl_clips_t5xxlfp8scaled.safetensors
  V:\\ml\\ComfyUI\\custom_nodes\\nearest_collapse_constrain\\
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
DEFAULT_CKPT = "sd3.5_medium_incl_clips_t5xxlfp8scaled.safetensors"
DEFAULT_SD3_TILE_CONTROLNET = "sd3_controlnet_tile_instantx.safetensors"
DEFAULT_UPSCALE_METHOD = "lanczos"
ALLOWED_UPSCALE_METHODS = (
    "lanczos",
    "bicubic",
    "bilinear",
    "area",
    "nearest-exact",
)
# SD3 EmptySD3LatentImage / latent packing expects multiples of 16.
SD35_SIZE_MULTIPLE = 16


def _api(host: str, port: int, path: str, payload: dict | None = None) -> dict | list | bytes:
    url = f"http://{host}:{port}{path}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = resp.read()
        ctype = resp.headers.get("Content-Type", "")
        if "application/json" in ctype or path.startswith("/prompt") or path.startswith("/history"):
            return json.loads(body.decode("utf-8"))
        return body


def upload_image(host: str, port: int, image_path: Path, name: str) -> str:
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


def build_sd35_img2img_workflow(
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
    upscale_method: str = DEFAULT_UPSCALE_METHOD,
    model_shift: float = 3.0,
    sampler_name: str = "euler",
    scheduler: str = "sgm_uniform",
    controlnet_name: str | None = None,
    controlnet_strength: float = 0.75,
    controlnet_start: float = 0.0,
    controlnet_end: float = 1.0,
    control_blur_radius: int = 0,
    control_blur_sigma: float = 1.5,
    filename_prefix: str = "collapse_sd35",
    init_mode: str = "lanczos",
    init_image_name: str | None = None,
    interstep_nearest_collapse: bool = True,
    project_mode: str = "hybrid",
    block_pull: float = 0.25,
    exact_sample: bool = False,
    spare_nn_samples: bool = True,
    spare_latent_mask: bool = False,
    project_every_n: int = 1,
    project_start_percent: float = 0.0,
    project_end_percent: float = 1.0,
    influence_radius: float = 0.0,
    influence_falloff: str = "quad",
) -> dict:
    """API-format graph for SD3.5 exact-size generation with inter-step collapse.

    init_mode:
      - lanczos: soft-scale portrait -> VAEEncode (img2img)
      - none: EmptySD3LatentImage (text2img); portrait is only the collapse target
      - hr: encode init_image_name at WxH (Stage A surface); portrait remains collapse target
    """
    if init_mode not in ("lanczos", "none", "hr"):
        raise ValueError(f"init_mode must be lanczos|none|hr, got {init_mode!r}")
    if init_mode == "hr" and not init_image_name:
        raise ValueError("init_mode=hr requires init_image_name")
    if upscale_method not in ALLOWED_UPSCALE_METHODS:
        raise ValueError(
            f"upscale_method must be one of {ALLOWED_UPSCALE_METHODS}, got {upscale_method!r}"
        )
    if interstep_nearest_collapse and sampler_name != "euler":
        raise ValueError(
            "interstep nearest-collapse sampler is Euler-only; pass sampler_name='euler' "
            f"or disable interstep (got {sampler_name!r})"
        )
    if project_mode not in ("latent", "pixel", "samples", "hybrid", "repaint"):
        raise ValueError(
            f"project_mode must be latent|pixel|samples|hybrid|repaint, got {project_mode!r}"
        )
    if init_mode == "none" and controlnet_name:
        raise ValueError("ControlNet Tile requires an image init (lanczos or hr)")
    if init_mode == "none" and denoise < 0.999:
        denoise = 1.0

    graph: dict = {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": ckpt},
        },
        "13": {
            "class_type": "ModelSamplingSD3",
            "inputs": {"model": ["4", 0], "shift": model_shift},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": ["4", 1]},
        },
        "10": {
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
        },
    }

    if init_mode == "lanczos":
        graph["11"] = {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["10", 0],
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
    elif init_mode == "hr":
        graph["11"] = {
            "class_type": "LoadImage",
            "inputs": {"image": init_image_name},
        }
        graph["14"] = {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["11", 0],
                "upscale_method": "lanczos",
                "width": width,
                "height": height,
                "crop": "disabled",
            },
        }
        graph["12"] = {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["14", 0], "vae": ["4", 2]},
        }
        control_image_ref = ["14", 0]
        if filename_prefix == "collapse_sd35":
            filename_prefix = "collapse_sd35_stageb"
    else:
        graph["12"] = {
            "class_type": "EmptySD3LatentImage",
            "inputs": {
                "width": width,
                "height": height,
                "batch_size": 1,
            },
        }
        control_image_ref = ["10", 0]
        if filename_prefix == "collapse_sd35":
            filename_prefix = "collapse_sd35_t2i"

    if controlnet_name:
        graph["20"] = {
            "class_type": "ControlNetLoader",
            "inputs": {"control_net_name": controlnet_name},
        }
        graph["21"] = {
            "class_type": "ControlNetApplySD3",
            "inputs": {
                "positive": ["6", 0],
                "negative": ["7", 0],
                "control_net": ["20", 0],
                "vae": ["4", 2],
                "image": control_image_ref,
                "strength": controlnet_strength,
                "start_percent": controlnet_start,
                "end_percent": controlnet_end,
            },
        }
        positive_ref: list = ["21", 0]
        negative_ref: list = ["21", 1]
        if filename_prefix == "collapse_sd35":
            filename_prefix = "collapse_sd35_tile"
    else:
        positive_ref = ["6", 0]
        negative_ref = ["7", 0]

    if interstep_nearest_collapse:
        graph["3"] = {
            "class_type": "KSamplerNearestCollapse",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "scheduler": scheduler,
                "denoise": denoise,
                "model": ["13", 0],
                "vae": ["4", 2],
                "portrait": ["10", 0],
                "positive": positive_ref,
                "negative": negative_ref,
                "latent_image": ["12", 0],
                "project_mode": project_mode,
                "pixel_width": width,
                "pixel_height": height,
                "block_pull": block_pull,
                "exact_sample": exact_sample,
                "spare_nn_samples": spare_nn_samples,
                "spare_latent_mask": spare_latent_mask,
                "every_n": project_every_n,
                "start_percent": project_start_percent,
                "end_percent": project_end_percent,
                "influence_radius": influence_radius,
                "influence_falloff": influence_falloff,
            },
        }
    else:
        graph["3"] = {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": denoise,
                "model": ["13", 0],
                "positive": positive_ref,
                "negative": negative_ref,
                "latent_image": ["12", 0],
            },
        }
    graph["8"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
    }
    graph["9"] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": filename_prefix, "images": ["8", 0]},
    }
    return graph


def wait_history(host: str, port: int, prompt_id: str, timeout_s: float = 600.0) -> dict:
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
    ap.add_argument("--image", type=Path, required=True, help="Portrait / collapse target (TwCrPort)")
    ap.add_argument("--out", type=Path, required=True, help="Output PNG path")
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--positive", type=str, required=True)
    ap.add_argument(
        "--negative",
        type=str,
        default=(
            "pixel art, mosaic, nearest neighbor blocks, hand-painted, oil painting, "
            "illustration, anime, photoreal modern, text, watermark"
        ),
    )
    ap.add_argument("--steps", type=int, default=28)
    ap.add_argument("--cfg", type=float, default=4.5)
    ap.add_argument(
        "--denoise",
        type=float,
        default=0.45,
        help="Img2img denoise; forced to 1.0 when --init none (text2img)",
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ckpt", type=str, default=DEFAULT_CKPT)
    ap.add_argument("--model-shift", type=float, default=3.0)
    ap.add_argument("--sampler", type=str, default="euler")
    ap.add_argument("--scheduler", type=str, default="sgm_uniform")
    ap.add_argument(
        "--init",
        type=str,
        choices=("lanczos", "none", "hr"),
        default="none",
        help=(
            "none=text2img; lanczos=img2img from soft-scaled portrait; "
            "hr=img2img from --init-hr Stage A surface"
        ),
    )
    ap.add_argument(
        "--init-hr",
        type=Path,
        default=None,
        help="Stage A HR PNG when --init hr (exact or scalable to WxH)",
    )
    ap.add_argument(
        "--upscale-method",
        type=str,
        default=DEFAULT_UPSCALE_METHOD,
        choices=ALLOWED_UPSCALE_METHODS,
        help=f"Pre-scale method when --init lanczos (default: {DEFAULT_UPSCALE_METHOD})",
    )
    ap.add_argument(
        "--controlnet-tile",
        nargs="?",
        const=DEFAULT_SD3_TILE_CONTROLNET,
        default=None,
        help=(
            "Enable SD3 ControlNet Tile via ControlNetApplySD3 (requires --init lanczos). "
            f"Optional filename under models/controlnet/ (default: {DEFAULT_SD3_TILE_CONTROLNET})."
        ),
    )
    ap.add_argument("--controlnet-strength", type=float, default=0.75)
    ap.add_argument("--controlnet-start", type=float, default=0.0)
    ap.add_argument("--controlnet-end", type=float, default=1.0)
    ap.add_argument("--control-blur-radius", type=int, default=0)
    ap.add_argument("--control-blur-sigma", type=float, default=1.5)
    ap.add_argument("--filename-prefix", type=str, default="collapse_sd35")
    ap.add_argument("--host", type=str, default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument(
        "--interstep-nearest-collapse",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Use KSamplerNearestCollapse so the collapse constraint runs BETWEEN Euler "
            "steps (default: on). Requires custom_nodes/nearest_collapse_constrain."
        ),
    )
    ap.add_argument(
        "--project-mode",
        type=str,
        choices=("latent", "pixel", "samples", "hybrid", "repaint"),
        default="hybrid",
        help=(
            "Inter-step projector: latent=mosaic lerp; pixel=block pull; "
            "samples=lock only NEAREST sample pixels (spare known-good sites); "
            "hybrid=latent lerp then sample lock (default)."
        ),
    )
    ap.add_argument(
        "--block-pull",
        type=float,
        default=0.25,
        help="Latent/pixel pull strength toward portrait mosaic/blocks in [0,1].",
    )
    ap.add_argument(
        "--exact-sample",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="pixel mode only: also lock NEAREST sample pixels. samples/hybrid always lock.",
    )
    ap.add_argument(
        "--spare-nn-samples",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Plant portrait RGB at NEAREST sample sites in the init and lock them with a "
            "denoise mask so they are not noised/updated (default: on). Also reinstates "
            "them in pixel space each step. Pass --no-spare-nn-samples to disable."
        ),
    )
    ap.add_argument(
        "--spare-latent-mask",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Also freeze whole VAE latent cells covering sample sites (~8x8). Off by "
            "default — Stage B should leave this off."
        ),
    )
    ap.add_argument("--project-every-n", type=int, default=1, help="Project every N Euler steps")
    ap.add_argument("--project-start-percent", type=float, default=0.0)
    ap.add_argument("--project-end-percent", type=float, default=1.0)
    ap.add_argument(
        "--influence-radius",
        type=float,
        default=0.0,
        help="Soft pull radius (px) around NN samples for project_mode=repaint (0=hard dots)",
    )
    ap.add_argument(
        "--influence-falloff",
        choices=("linear", "quad", "cosine", "gauss"),
        default="quad",
        help="Falloff inside --influence-radius",
    )
    ap.add_argument(
        "--project-nearest-collapse",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "OPTIONAL post-SaveImage sample-site stamp. Off by default — prefer "
            "--project-mode samples|hybrid inside the sampler."
        ),
    )
    ap.add_argument(
        "--nearest-collapse-strength",
        type=float,
        default=1.0,
        help="Strength for optional post-hoc --project-nearest-collapse only",
    )
    args = ap.parse_args()

    if args.width <= 0 or args.height <= 0:
        raise SystemExit("width and height must be positive")
    if args.width % SD35_SIZE_MULTIPLE != 0 or args.height % SD35_SIZE_MULTIPLE != 0:
        raise SystemExit(
            f"SD3.5 sizes require multiples of {SD35_SIZE_MULTIPLE}; "
            f"got {args.width}x{args.height}"
        )
    needs_integer = args.interstep_nearest_collapse or args.project_nearest_collapse
    if needs_integer:
        from PIL import Image as _PILImage

        with _PILImage.open(args.image) as _src:
            sw, sh = _src.size
        if args.width % sw != 0 or args.height % sh != 0:
            raise SystemExit(
                "nearest-collapse requires width/height integer multiples of source "
                f"{sw}x{sh}; got {args.width}x{args.height}"
            )
    if not (0.0 <= args.block_pull <= 1.0):
        raise SystemExit("--block-pull must be in [0, 1]")
    if args.project_every_n < 1:
        raise SystemExit("--project-every-n must be >= 1")
    if not (0.0 <= args.project_start_percent <= 1.0 and 0.0 <= args.project_end_percent <= 1.0):
        raise SystemExit("project start/end percent must be in [0, 1]")
    if args.project_start_percent > args.project_end_percent:
        raise SystemExit("project-start-percent must be <= project-end-percent")
    if args.project_nearest_collapse and not (0.0 < args.nearest_collapse_strength <= 1.0):
        raise SystemExit("--nearest-collapse-strength must be in (0, 1]")
    if args.init == "lanczos" and args.upscale_method == "nearest-exact":
        raise SystemExit(
            "refusing --upscale-method nearest-exact: that locks mosaic blocks into the "
            "init. Prefer --init none, or lanczos with inter-step collapse."
        )
    if args.controlnet_tile and args.init == "none":
        raise SystemExit("--controlnet-tile requires --init lanczos or --init hr")
    if args.init == "hr" and args.init_hr is None:
        raise SystemExit("--init hr requires --init-hr")
    if args.control_blur_radius < 0:
        raise SystemExit("control-blur-radius must be >= 0")
    if args.control_blur_radius > 0 and not args.controlnet_tile:
        raise SystemExit("--control-blur-radius requires --controlnet-tile")

    effective_denoise = 1.0 if args.init == "none" else args.denoise

    image_path = args.image.resolve()
    if not image_path.is_file():
        raise SystemExit(f"image not found: {image_path}")
    init_hr_path = args.init_hr.resolve() if args.init_hr is not None else None
    if init_hr_path is not None and not init_hr_path.is_file():
        raise SystemExit(f"init-hr not found: {init_hr_path}")
    if args.init == "hr":
        from PIL import Image as _PILImage

        with _PILImage.open(init_hr_path) as _hr:
            if _hr.size[0] % args.width != 0 and _hr.size != (args.width, args.height):
                # ImageScale will resize; require positive size only
                pass
            if _hr.size[0] <= 0:
                raise SystemExit("init-hr has invalid size")

    ckpt_path = Path(r"V:/ml/ComfyUI/models/checkpoints") / args.ckpt
    if not ckpt_path.is_file():
        raise SystemExit(
            f"SD3.5 checkpoint missing: {ckpt_path}. "
            "Download with: hf download Comfy-Org/stable-diffusion-3.5-fp8 "
            "sd3.5_medium_incl_clips_t5xxlfp8scaled.safetensors "
            "--local-dir V:/ml/ComfyUI/models/checkpoints"
        )
    if args.controlnet_tile:
        cn_path = Path(r"V:/ml/ComfyUI/models/controlnet") / args.controlnet_tile
        if not cn_path.is_file():
            raise SystemExit(f"SD3 ControlNet missing: {cn_path}")

    try:
        _api(args.host, args.port, "/system_stats")
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"ComfyUI not reachable at http://{args.host}:{args.port} ({exc}). "
            "Start it with: bash tools/local_imagegen/comfyui_vdrive.sh serve"
        ) from exc

    uploaded = upload_image(args.host, args.port, image_path, image_path.name)
    uploaded_init = None
    if args.init == "hr":
        uploaded_init = upload_image(args.host, args.port, init_hr_path, f"init_{init_hr_path.name}")
    workflow = build_sd35_img2img_workflow(
        image_name=uploaded,
        positive=args.positive,
        negative=args.negative,
        width=args.width,
        height=args.height,
        steps=args.steps,
        cfg=args.cfg,
        denoise=effective_denoise,
        seed=args.seed,
        ckpt=args.ckpt,
        upscale_method=args.upscale_method,
        model_shift=args.model_shift,
        sampler_name=args.sampler,
        scheduler=args.scheduler,
        controlnet_name=args.controlnet_tile,
        controlnet_strength=args.controlnet_strength,
        controlnet_start=args.controlnet_start,
        controlnet_end=args.controlnet_end,
        control_blur_radius=args.control_blur_radius,
        control_blur_sigma=args.control_blur_sigma,
        filename_prefix=args.filename_prefix,
        init_mode=args.init,
        init_image_name=uploaded_init,
        interstep_nearest_collapse=args.interstep_nearest_collapse,
        project_mode=args.project_mode,
        block_pull=args.block_pull,
        exact_sample=args.exact_sample,
        spare_nn_samples=args.spare_nn_samples,
        spare_latent_mask=args.spare_latent_mask,
        project_every_n=args.project_every_n,
        project_start_percent=args.project_start_percent,
        project_end_percent=args.project_end_percent,
        influence_radius=args.influence_radius,
        influence_falloff=args.influence_falloff,
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
        raise SystemExit(f"ComfyUI job failed: {json.dumps(hist)[:1500]}")
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
        "schema": "local_imagegen.exact_img2img_sd35.v5",
        "arch": "sd3.5-medium",
        "image": str(image_path),
        "out": str(args.out.resolve()),
        "width": args.width,
        "height": args.height,
        "seed": args.seed,
        "init": args.init,
        "init_hr": str(init_hr_path) if init_hr_path is not None else None,
        "denoise": effective_denoise,
        "cfg": args.cfg,
        "steps": args.steps,
        "ckpt": args.ckpt,
        "model_shift": args.model_shift,
        "sampler": args.sampler,
        "scheduler": args.scheduler,
        "positive": args.positive,
        "upscale_method": args.upscale_method if args.init == "lanczos" else None,
        "controlnet_tile": args.controlnet_tile,
        "controlnet_strength": args.controlnet_strength if args.controlnet_tile else None,
        "controlnet_start": args.controlnet_start if args.controlnet_tile else None,
        "controlnet_end": args.controlnet_end if args.controlnet_tile else None,
        "control_blur_radius": args.control_blur_radius if args.controlnet_tile else None,
        "interstep_nearest_collapse": {
            "enabled": args.interstep_nearest_collapse,
            "project_mode": args.project_mode,
            "block_pull": args.block_pull,
            "exact_sample": args.exact_sample,
            "spare_nn_samples": args.spare_nn_samples,
            "spare_latent_mask": args.spare_latent_mask,
            "every_n": args.project_every_n,
            "start_percent": args.project_start_percent,
            "end_percent": args.project_end_percent,
            "influence_radius": args.influence_radius,
            "influence_falloff": args.influence_falloff,
            "node": "KSamplerNearestCollapse",
        },
        "project_nearest_collapse_post": nearest_meta,
        "prompt_id": real_id,
        "proof": (
            f"local ComfyUI exact-size SD3.5 "
            + (
                "text2img"
                if args.init == "none"
                else (
                    "img2img (init-hr)"
                    if args.init == "hr"
                    else f"img2img ({args.upscale_method})"
                )
            )
            + ("; ControlNetApplySD3 Tile" if args.controlnet_tile else "; no Tile")
            + (
                f"; interstep nearest-collapse/{args.project_mode}"
                if args.interstep_nearest_collapse
                else ""
            )
            + ("; post sample-stamp" if args.project_nearest_collapse else "")
            + ") (size check passed)"
        ),
    }
    args.out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
