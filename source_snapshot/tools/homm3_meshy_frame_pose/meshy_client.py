#!/usr/bin/env python3
"""Minimal Meshy OpenAPI client (image-to-3D, image-to-image, retexture, remesh, rigging).

Auth: MESHY_API_KEY from process env, else repo-root .env.
Never prints the key.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://api.meshy.ai/openapi/v1"


def load_api_key(env_path: Path | None = None) -> str:
    key = (os.environ.get("MESHY_API_KEY") or "").strip()
    if key:
        return key
    path = env_path or (ROOT / ".env")
    if not path.is_file():
        raise RuntimeError(f"MESHY_API_KEY not set and .env missing: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if k.strip() == "MESHY_API_KEY":
            key = v.strip().strip('"').strip("'")
            if key:
                return key
    raise RuntimeError("MESHY_API_KEY not found in environment or .env")


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request(
    method: str,
    path: str,
    api_key: str,
    body: dict | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    url = f"{BASE}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(api_key), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Meshy HTTP {e.code} {path}: {err_body[:2000]}") from e


def file_to_data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    if path.suffix.lower() == ".png":
        mime = "image/png"
    elif path.suffix.lower() in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif path.suffix.lower() == ".glb":
        mime = "model/gltf-binary"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def create_image_to_3d(
    api_key: str,
    *,
    image_path: Path,
    should_texture: bool,
    target_polycount: int | None = 4000,
    model_type: str = "smart-topology",
    ai_model: str = "meshy-t2",
    pose_mode: str | None = None,
    should_remesh: bool | None = None,
    enable_pbr: bool = False,
    remove_lighting: bool | None = None,
    texture_resolution: str | None = None,
    geometry_resolution: str | None = None,
    decimation_mode: int | None = None,
    image_enhancement: bool | None = None,
    texture_prompt: str | None = None,
    texture_image_path: Path | None = None,
) -> str:
    """Create image-to-3D task. Returns task id.

    pose_mode: None/omit = no forced pose; \"a-pose\" / \"t-pose\" when requested.
    remove_lighting: desktop \"Remove Lighting\". Docs default true; only supported for
    meshy-6/meshy-7/latest. Pass False to keep baked lighting. Always send explicitly when set
    so omit is never confused with strip-on default.
    decimation_mode: Meshy adaptive remesh (1 ultra .. 4 low). When set, target_polycount
    is omitted because the API ignores it.
    geometry_resolution: Meshy 7.1 geometry generation pass (standard, 2k, or 4k).
    texture_prompt / texture_image_path: texture guidance (text <= 800 chars, or a 2D image);
    Meshy accepts only one and bills 10 extra credits for it.
    """
    body: dict[str, Any] = {
        "image_url": file_to_data_uri(image_path),
        "model_type": model_type,
        "ai_model": ai_model,
        "should_texture": bool(should_texture),
        "target_formats": ["glb"],
        "enable_pbr": bool(enable_pbr),
    }
    if decimation_mode is not None:
        mode = int(decimation_mode)
        if mode not in {1, 2, 3, 4}:
            raise ValueError(f"decimation_mode must be 1..4, got {mode}")
        body["decimation_mode"] = mode
    elif target_polycount is not None:
        body["target_polycount"] = int(target_polycount)
    elif model_type != "standard":
        raise ValueError("need target_polycount or decimation_mode")
    if pose_mode is not None and str(pose_mode) != "":
        body["pose_mode"] = str(pose_mode)
    if should_remesh is not None:
        body["should_remesh"] = bool(should_remesh)
    if remove_lighting is not None:
        body["remove_lighting"] = bool(remove_lighting)
    if texture_resolution is not None:
        body["texture_resolution"] = str(texture_resolution)
    if geometry_resolution is not None:
        resolution = str(geometry_resolution)
        if resolution not in {"standard", "2k", "4k"}:
            raise ValueError(f"invalid geometry_resolution: {resolution!r}")
        if ai_model not in {"meshy-7.1", "latest"}:
            raise ValueError("geometry_resolution requires ai_model meshy-7.1 or latest")
        body["geometry_resolution"] = resolution
    if image_enhancement is not None:
        body["image_enhancement"] = bool(image_enhancement)
    if texture_prompt and texture_image_path is not None:
        raise ValueError("give texture_prompt or texture_image_path, not both")
    if texture_prompt:
        if not should_texture or len(texture_prompt) > 800:
            raise ValueError("texture_prompt needs should_texture and <= 800 chars")
        body["texture_prompt"] = str(texture_prompt)
    elif texture_image_path is not None:
        body["texture_image_url"] = file_to_data_uri(Path(texture_image_path))
    resp = _request("POST", "/image-to-3d", api_key, body)
    task_id = resp.get("result")
    if not task_id:
        raise RuntimeError(f"image-to-3d missing result id: {resp}")
    return str(task_id)


def create_image_to_image(
    api_key: str,
    *,
    prompt: str,
    reference_paths: list[Path],
    ai_model: str = "nano-banana-2",
    aspect_ratio: str | None = None,
    remove_background: bool | None = None,
) -> str:
    """Create an Image-to-Image task (edit a concept before image-to-3D). Returns task id.

    reference_paths: 1..5 local images sent as data URIs; the first is the image being edited.
    """
    refs = [Path(p) for p in reference_paths]
    if not 1 <= len(refs) <= 5:
        raise ValueError("reference_paths needs 1..5 images")
    body: dict[str, Any] = {
        "ai_model": str(ai_model),
        "prompt": str(prompt),
        "reference_image_urls": [file_to_data_uri(p) for p in refs],
    }
    if aspect_ratio is not None:
        body["aspect_ratio"] = str(aspect_ratio)
    if remove_background is not None:
        body["remove_background"] = bool(remove_background)
    resp = _request("POST", "/image-to-image", api_key, body)
    task_id = resp.get("result")
    if not task_id:
        raise RuntimeError(f"image-to-image missing result id: {resp}")
    return str(task_id)


def create_retexture(
    api_key: str,
    *,
    input_task_id: str | None = None,
    model_url: str | None = None,
    image_style_path: Path | None = None,
    image_style_url: str | None = None,
    text_style_prompt: str | None = None,
    ai_model: str = "meshy-6",
    enable_original_uv: bool = True,
    enable_pbr: bool = True,
    remove_lighting: bool = False,
    texture_resolution: str = "8k",
    target_formats: list[str] | None = None,
) -> str:
    """Create a Retexture task (meshy-6 materials on an existing mesh). Returns task id.

    Prefer input_task_id (Meshy Image-to-3D / Remesh) when available so UV reuse is reliable.
    remove_lighting=False keeps pre-baked lighting in the albedo while PBR maps still apply.
    """
    if not input_task_id and not model_url:
        raise ValueError("need input_task_id or model_url")
    if image_style_path is None and not image_style_url and not text_style_prompt:
        raise ValueError("need image_style_path, image_style_url, or text_style_prompt")

    body: dict[str, Any] = {
        "ai_model": str(ai_model),
        "enable_original_uv": bool(enable_original_uv),
        "enable_pbr": bool(enable_pbr),
        "remove_lighting": bool(remove_lighting),
        "texture_resolution": str(texture_resolution),
        "target_formats": list(target_formats or ["glb"]),
    }
    if input_task_id:
        body["input_task_id"] = str(input_task_id)
    if model_url:
        body["model_url"] = str(model_url)
    if image_style_path is not None:
        body["image_style_url"] = file_to_data_uri(Path(image_style_path))
    elif image_style_url:
        body["image_style_url"] = str(image_style_url)
    elif text_style_prompt:
        body["text_style_prompt"] = str(text_style_prompt)

    resp = _request("POST", "/retexture", api_key, body)
    task_id = resp.get("result")
    if not task_id:
        raise RuntimeError(f"retexture missing result id: {resp}")
    return str(task_id)


def create_remesh(
    api_key: str,
    *,
    input_task_id: str | None = None,
    model_url: str | None = None,
    target_polycount: int | None = 10000,
    topology: str = "triangle",
    decimation_mode: int | None = None,
    target_formats: list[str] | None = None,
) -> str:
    """Create a Meshy Remesh task for an existing model or Meshy task.

    Meshy accepts a completed Image-to-3D task ID directly, which avoids
    uploading the local GLB again and preserves the generated asset lineage.
    """
    if not input_task_id and not model_url:
        raise ValueError("need input_task_id or model_url")
    body: dict[str, Any] = {
        "topology": str(topology),
        "target_formats": list(target_formats or ["glb"]),
    }
    if input_task_id:
        body["input_task_id"] = str(input_task_id)
    else:
        body["model_url"] = str(model_url)
    if decimation_mode is not None:
        mode = int(decimation_mode)
        if mode not in {1, 2, 3, 4}:
            raise ValueError(f"decimation_mode must be 1..4, got {mode}")
        body["decimation_mode"] = mode
    elif target_polycount is not None:
        count = int(target_polycount)
        if count < 100 or count > 300000:
            raise ValueError("target_polycount must be between 100 and 300000")
        body["target_polycount"] = count
    resp = _request("POST", "/remesh", api_key, body)
    task_id = resp.get("result")
    if not task_id:
        raise RuntimeError(f"remesh missing result id: {resp}")
    return str(task_id)


def create_rigging(
    api_key: str,
    *,
    input_task_id: str | None = None,
    model_url: str | None = None,
    texture_image_url: str | None = None,
    height_meters: float = 1.7,
) -> str:
    if not input_task_id and not model_url:
        raise ValueError("need input_task_id or model_url")
    body: dict[str, Any] = {"height_meters": float(height_meters)}
    if input_task_id:
        body["input_task_id"] = input_task_id
    if model_url:
        body["model_url"] = model_url
    if texture_image_url:
        body["texture_image_url"] = texture_image_url
    resp = _request("POST", "/rigging", api_key, body)
    task_id = resp.get("result")
    if not task_id:
        raise RuntimeError(f"rigging missing result id: {resp}")
    return str(task_id)


def get_task(api_key: str, kind: str, task_id: str) -> dict[str, Any]:
    if kind not in {"image-to-3d", "rigging", "retexture", "remesh", "image-to-image"}:
        raise ValueError(kind)
    path = f"/{kind}/{task_id}"
    return _request("GET", path, api_key, None)


def poll_task(
    api_key: str,
    kind: str,
    task_id: str,
    *,
    timeout_s: float = 900.0,
    interval_s: float = 5.0,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = get_task(api_key, kind, task_id)
        status = str(last.get("status") or "")
        progress = last.get("progress")
        print(f"[meshy] {kind} {task_id[:8]}… status={status} progress={progress}", flush=True)
        if status in {"SUCCEEDED", "FAILED", "CANCELED"}:
            return last
        time.sleep(interval_s)
    raise TimeoutError(f"Meshy {kind} {task_id} timed out; last={last.get('status')}")


def download_url(url: str, dest: Path, timeout: float = 300.0) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        dest.write_bytes(resp.read())
    return dest


def task_error_message(task: dict[str, Any]) -> str:
    err = task.get("task_error") or {}
    if isinstance(err, dict):
        return str(err.get("message") or err) or "unknown"
    return str(err)
