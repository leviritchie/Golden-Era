#!/usr/bin/env python3
"""Generate explicit Meshy 7.1 geometry candidates for repair-class units.

This is a candidate lane, not a delivery shortcut. Meshy supplies only a textured
surface; the owned skeleton, skin, and deformation audit remain in-repo. The
caller must choose a pose variant explicitly so a failed neutral-pose generation
cannot silently replace the source mesh.

The intended use is a small portfolio for units whose preflight identifies a
repeatable geometry defect, especially a prop/body bridge:

    py -3 tools/homm3_meshy_frame_pose/generate_meshy71_repair_candidates.py \
      generate --unit h3_archer --variant a-pose

Use ``start`` and ``poll`` separately when several candidates should be queued
without holding a terminal open. Existing task records are reused fail-closed.
Prepared images require both ``--source-image PATH --attempt VERSION``; they use
an isolated unit/variant/version directory, never the historical default output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from meshy_client import (  # noqa: E402
    create_image_to_3d,
    download_url,
    load_api_key,
    poll_task,
    task_error_message,
)

COVERAGE = ROOT / "artifacts/meshy_downloads/homm3_mesh_coverage.json"
OUT_ROOT = ROOT / "artifacts/meshy_downloads/meshy71_repair_candidates"
VARIANTS = ("source", "a-pose", "t-pose")
SCHEMA = "meshy71.repair_candidate.v1"


def _record(unit: str) -> dict:
    inventory = json.loads(COVERAGE.read_text(encoding="utf-8"))
    for row in inventory.get("records", []):
        if str(row.get("unitSid")) == unit:
            image = Path(str(row.get("imageInput") or ""))
            if not image.is_file():
                raise SystemExit(f"fail-closed: source still missing: {image}")
            return row
    raise SystemExit(f"fail-closed: {unit} is not in the Meshy coverage inventory")


def _safe_name(value: str) -> None:
    reserved = {"con", "prn", "aux", "nul", "tasks"}
    reserved.update(f"{prefix}{n}" for prefix in ("com", "lpt") for n in range(1, 10))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value) or value.lower() in reserved:
        raise SystemExit(f"fail-closed: unsafe or reserved output name: {value!r}")


def _unit_dir(unit: str, variant: str, attempt: str | None = None) -> Path:
    _safe_name(unit)
    if variant not in VARIANTS:
        raise SystemExit(f"fail-closed: invalid variant: {variant!r}")
    path = OUT_ROOT / unit / variant
    if attempt is not None:
        _safe_name(attempt)
        path /= attempt
    expected = OUT_ROOT.resolve() / unit / variant
    if attempt is not None:
        expected /= attempt
    if path.resolve() != expected:
        raise SystemExit("fail-closed: output escapes or aliases another candidate directory")
    for name in ("tasks", "tasks/image_to_3d.json", "candidate_meta.json", "mesh.glb", "mesh.new.glb"):
        if not (path / name).resolve().is_relative_to(path.resolve()):
            raise SystemExit(f"fail-closed: output path escapes candidate directory: {name}")
    return path


def _read_record(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"fail-closed: invalid record {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"fail-closed: expected an object in {path}")
    return payload


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write_record(path: Path, payload: dict, *, exclusive: bool = False) -> None:
    text = json.dumps(payload, indent=2) + "\n"
    if exclusive:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        return
    # Polling must not truncate the only known task ID if a process is interrupted.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _glb_url(task: dict) -> str | None:
    model_urls = task.get("model_urls") or {}
    if isinstance(model_urls, dict) and model_urls.get("glb"):
        return str(model_urls["glb"])
    result = task.get("result") or {}
    if isinstance(result, dict):
        nested = result.get("model_urls") or {}
        if isinstance(nested, dict) and nested.get("glb"):
            return str(nested["glb"])
        for key in ("glb_url", "model_url"):
            if result.get(key):
                return str(result[key])
    for key in ("glb_url", "model_url"):
        if task.get(key):
            return str(task[key])
    return None


def _texture_urls(task: dict, dest: Path) -> dict[str, str]:
    textures: dict[str, str] = {}
    for index, entry in enumerate(task.get("texture_urls") or []):
        if not isinstance(entry, dict):
            continue
        for kind in ("base_color", "metallic", "normal", "roughness", "emission"):
            url = entry.get(kind)
            if not url:
                continue
            path = dest / f"texture_{index}_{kind}.png"
            download_url(str(url), path)
            key = kind if index == 0 else f"{kind}_{index}"
            textures[key] = str(path.resolve()).replace("\\", "/")
    return textures


def _policy(unit: str, variant: str, image: Path, polycount: int) -> dict:
    return {
        "schema": SCHEMA,
        "unitSid": unit,
        "variant": variant,
        "sourceImage": str(image.resolve()).replace("\\", "/"),
        "aiModel": "latest",
        "modelType": "standard",
        "targetPolycount": int(polycount),
        "shouldTexture": True,
        "enablePbr": True,
        "shouldRemesh": True,
        "imageEnhancement": False,
        "poseMode": "" if variant == "source" else variant,
        "autoRig": False,
        "armatureAuthority": "owned_in_repo_after_candidate_audit",
        "proof": "generated candidate only",
    }


def _context(args: argparse.Namespace) -> tuple[Path, Path, dict]:
    prepared, attempt = getattr(args, "source_image", None), getattr(args, "attempt", None)
    if (prepared is None) != (attempt is None):
        raise SystemExit("fail-closed: --source-image and --attempt must be supplied together")
    dest = _unit_dir(args.unit, args.variant, attempt)
    if getattr(args, "candidate_dir", None) is not None:
        dest = args.candidate_dir.resolve()
        if not dest.is_relative_to((OUT_ROOT / args.unit).resolve()):
            raise SystemExit("fail-closed: candidate directory must be inside the selected unit root")
        if dest == (OUT_ROOT / args.unit).resolve():
            raise SystemExit("fail-closed: candidate directory must not be the unit root")
    image = Path(prepared) if prepared is not None else Path(str(_record(args.unit)["imageInput"]))
    if not image.is_file():
        raise SystemExit(f"fail-closed: source image missing: {image}")
    if args.polycount <= 0:
        raise SystemExit("fail-closed: --polycount must be positive")
    suffix = image.suffix.lower() if prepared is not None else ".png"
    if prepared is not None and suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise SystemExit("fail-closed: prepared source must be PNG, JPEG or WebP")
    source_copy = dest / ("source" + suffix)
    if not source_copy.resolve().is_relative_to(dest.resolve()):
        raise SystemExit("fail-closed: source copy escapes candidate directory")
    policy = _policy(args.unit, args.variant, image, args.polycount)
    policy.update(sourceImageSha256=_sha256(image), textureResolution="2k")
    if attempt is not None:
        policy["attempt"] = attempt
    return dest, source_copy, policy


def _existing(dest: Path, source_copy: Path, requested: dict) -> tuple[str, dict] | None:
    task = _read_record(dest / "tasks/image_to_3d.json")
    meta = _read_record(dest / "candidate_meta.json")
    if task is None and meta is None and not (dest / "mesh.glb").exists() and not source_copy.exists():
        return None
    if task is None:
        raise SystemExit("fail-closed: existing output has no task record; do not resubmit")
    task_id = str(task.get("taskId") or task.get("id") or "")
    if not task_id:
        raise SystemExit("fail-closed: task ID missing or submission uncertain; recover the existing ID, do not resubmit")
    if task.get("id") and str(task["id"]) != task_id:
        raise SystemExit("fail-closed: conflicting task IDs")
    if meta and meta.get("taskId") and str(meta["taskId"]) != task_id:
        raise SystemExit("fail-closed: metadata task ID mismatch")
    # Historical poll responses omit policy; their original settings live in candidate_meta.
    policies = [record["policy"] for record in (task, meta) if record is not None and "policy" in record]
    if not policies or any(not isinstance(p, dict) or p != policies[0] for p in policies):
        raise SystemExit("fail-closed: missing or conflicting original policy")
    policy = policies[0]
    for key, value in requested.items():
        # Historical records predate these fields. Verify their retained source bytes below,
        # and preserve the old policy verbatim rather than inventing new provenance.
        if "attempt" not in requested and key in ("sourceImageSha256", "textureResolution") and key not in policy:
            continue
        # Existing tasks keep the settings actually submitted under the prior default.
        # This transition must remain pollable and must never trigger a duplicate POST.
        if key in ("aiModel", "shouldRemesh"):
            continue
        if policy.get(key) != value:
            raise SystemExit(f"fail-closed: existing input/settings mismatch: {key}; use a new attempt")
    if policy.get("attempt") != requested.get("attempt"):
        raise SystemExit("fail-closed: attempt mismatch")
    if not source_copy.is_file() or _sha256(source_copy) != requested["sourceImageSha256"]:
        raise SystemExit("fail-closed: retained source copy missing or changed")
    return task_id, policy


def start(args: argparse.Namespace) -> int:
    dest, source_copy, requested = _context(args)
    meta_path = dest / "candidate_meta.json"
    task_path = dest / "tasks/image_to_3d.json"
    existing = _existing(dest, source_copy, requested)
    if existing:
        task_id, policy = existing
        print(json.dumps({"status": "already_queued", "taskId": task_id, "policy": policy}, indent=2))
        return 0

    policy = requested
    api_key = load_api_key()
    task_path.parent.mkdir(parents=True, exist_ok=True)
    # An interrupted/ambiguous POST must never be automatically retried as a new paid task.
    _write_record(task_path, {"status": "SUBMITTING", "policy": policy}, exclusive=True)
    with Path(policy["sourceImage"]).open("rb") as source, source_copy.open("xb") as target:
        shutil.copyfileobj(source, target)
    if _sha256(source_copy) != policy["sourceImageSha256"]:
        raise SystemExit("fail-closed: source image changed while retaining input")
    task_id = create_image_to_3d(
        api_key,
        image_path=source_copy,
        should_texture=True,
        target_polycount=policy["targetPolycount"],
        model_type="standard",
        ai_model="latest",
        should_remesh=policy["shouldRemesh"],
        enable_pbr=True,
        texture_resolution=policy["textureResolution"],
        image_enhancement=False,
        pose_mode=policy["poseMode"] or None,
    )
    if not isinstance(task_id, str) or not task_id.strip():
        raise SystemExit("fail-closed: submission returned no task ID; do not resubmit")
    _write_record(task_path, {"taskId": task_id, "policy": policy})
    _write_record(meta_path, {"status": "QUEUED", "taskId": task_id, "policy": policy})
    print(json.dumps({"status": "queued", "taskId": task_id, "policy": policy}, indent=2), flush=True)
    return 0


def poll(args: argparse.Namespace) -> int:
    dest, source_copy, requested = _context(args)
    task_path = dest / "tasks/image_to_3d.json"
    existing = _existing(dest, source_copy, requested)
    if existing is None:
        raise SystemExit(f"fail-closed: no queued task for {args.unit}/{args.variant}")
    task_id, policy = existing
    task = poll_task(load_api_key(), "image-to-3d", task_id, timeout_s=args.timeout_s, interval_s=10.0)
    if any(task.get(key) and str(task[key]) != task_id for key in ("id", "taskId")):
        raise SystemExit("fail-closed: polled response task ID mismatch")
    _write_record(task_path, {**task, "taskId": task_id, "policy": policy})
    status = str(task.get("status") or "")
    if status != "SUCCEEDED":
        meta = {"schema": SCHEMA, "status": status, "taskId": task_id, "policy": policy, "error": task_error_message(task)}
        _write_record(dest / "candidate_meta.json", meta)
        print(json.dumps(meta, indent=2))
        return 2
    url = _glb_url(task)
    if not url:
        raise SystemExit("fail-closed: succeeded Meshy task has no GLB URL")
    staging = dest / "mesh.new.glb"
    download_url(url, staging)
    if staging.stat().st_size <= 1000:
        raise SystemExit(f"fail-closed: candidate GLB is too small: {staging.stat().st_size}")
    textures = _texture_urls(task, dest)
    staging.replace(dest / "mesh.glb")
    meta = {
        "schema": SCHEMA,
        "status": "SUCCEEDED",
        "taskId": task_id,
        "policy": policy,
        "mesh": str((dest / "mesh.glb").resolve()).replace("\\", "/"),
        "meshBytes": (dest / "mesh.glb").stat().st_size,
        "meshSha256": _sha256(dest / "mesh.glb"),
        "textures": textures,
        "proof": "generated candidate only; owned bind and deformation audit outstanding",
    }
    _write_record(dest / "candidate_meta.json", meta)
    print(json.dumps(meta, indent=2), flush=True)
    return 0


def generate(args: argparse.Namespace) -> int:
    dest, source_copy, requested = _context(args)
    existing = _existing(dest, source_copy, requested)
    if existing and (dest / "mesh.glb").is_file():
        print(json.dumps({"status": "already_downloaded", "mesh": str(dest / "mesh.glb")}, indent=2))
        return 0
    code = start(args)
    if code != 0:
        return code
    return poll(args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("start", start), ("poll", poll), ("generate", generate)):
        child = sub.add_parser(name)
        child.add_argument("--unit", required=True)
        child.add_argument("--variant", choices=VARIANTS, required=True)
        child.add_argument("--source-image", type=Path, help="Prepared input; requires a new named --attempt")
        child.add_argument("--attempt", help="Safe output version name; requires --source-image")
        child.add_argument("--candidate-dir", type=Path, help="Explicit isolated candidate directory under the unit root")
        child.add_argument("--polycount", type=int, default=8000)
        child.add_argument("--timeout-s", type=float, default=1800.0)
        child.set_defaults(handler=handler)
    args = parser.parse_args()
    if args.polycount <= 0:
        parser.error("--polycount must be positive")
    if (args.source_image is None) != (args.attempt is None):
        parser.error("--source-image and --attempt must be supplied together")
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
