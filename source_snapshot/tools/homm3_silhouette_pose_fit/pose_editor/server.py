#!/usr/bin/env python3
"""Local browser pose editor for sprite-feasibility fits.

Prototype: h3_roc idle_start_move_end. Writes only under
artifacts/sprite_feasibility/**/manual_edit/. Never Meshy or live fused-push.
Proof: generated-artifact JSON + the browser preview. Not OE battle.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[3]
FIT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
sys.path.insert(0, str(FIT))

from pose_editor.pose_editor_paths import (  # noqa: E402
    SPRITE_TREE,
    WORK_TREE,
    assert_read_path,
    assert_write_path,
    manual_edit_dir,
    work_clip_dir,
)
from sprite_anatomy import load_unit_anatomy_catalog  # noqa: E402
from sprite_pose_feasibility import (  # noqa: E402
    flight_phase_representative_frames,
    frame_rest_source,
    idle_band_from_payload,
)

DEFAULT_UNIT = "h3_roc"
DEFAULT_CLIP = "idle_start_move_end"
DEFAULT_PORT = 8765


def _json_load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_dump(path: Path, payload: dict) -> None:
    dest = assert_write_path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _require_degrees(payload: dict, source: str) -> None:
    if payload.get("poseUnits") != "degrees":
        raise ValueError(f"{source} must declare poseUnits=degrees")


def _camera_basis(fit: dict) -> dict:
    rows = fit["basisScreenRows"]
    right = _norm3(rows[0])
    down = _norm3(rows[1])
    up = [-down[0], -down[1], -down[2]]
    forward = _cross(up, right)
    forward = _norm3(forward)
    offset = [float(fit["screenOffsetPx"][0]), float(fit["screenOffsetPx"][1])]
    width, height = (int(fit["sourceResolution"][0]), int(fit["sourceResolution"][1]))
    px = float(fit["pxPerWorld"])
    return {
        "right": right,
        "down": down,
        "up": up,
        "forward": forward,
        "offsetPx": offset,
        "pxPerWorld": [px, px],
        "sourceResolution": [width, height],
        "yawDeg": float((fit.get("profileMetrics") or {}).get("bestYawDeg") or 0.0),
        "worldUp": [0.0, 1.0, 0.0],
        "characterForward": list((fit.get("profileMetrics") or {}).get("characterForward") or [0, 0, 1]),
    }


def _norm3(vec: list[float]) -> list[float]:
    x, y, z = float(vec[0]), float(vec[1]), float(vec[2])
    length = (x * x + y * y + z * z) ** 0.5
    if length <= 1e-12:
        raise ValueError("camera basis vector is zero")
    return [x / length, y / length, z / length]


def _cross(a: list[float], b: list[float]) -> list[float]:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _architecture_round(work: Path) -> Path:
    index = _json_load(work / "index.json")
    rid = index.get("architectureRound") or index.get("argmaxRound")
    if not rid:
        raise ValueError(f"{work} has no architectureRound")
    path = work / str(rid)
    if not path.is_dir():
        raise ValueError(f"architecture round {rid} is missing")
    return path


def _pose_payload(path: Path) -> dict:
    payload = _json_load(path)
    _require_degrees(payload, str(path))
    return payload


def _sprite_dir(clip_payload: dict) -> Path:
    paths = clip_payload.get("targetPaths") or []
    if not paths:
        raise ValueError("clip has no targetPaths")
    directory = Path(str(paths[0])).resolve().parent
    return assert_read_path(directory)


def build_session(unit: str, clip: str) -> dict:
    work = work_clip_dir(unit, clip)
    if not (work / "index.json").is_file():
        raise ValueError(f"no sprite-feasibility index at {work}")
    round_dir = _architecture_round(work)
    clip_payload = _json_load(round_dir / "gpu_clip_result.json")
    if "poseUnits" in clip_payload:
        _require_degrees(clip_payload, str(round_dir / "gpu_clip_result.json"))
    prefix, suffix = idle_band_from_payload(clip_payload)
    frames = [int(frame) for frame in (clip_payload.get("frameIndices") or [])]
    if not frames:
        raise ValueError("clip has no frameIndices")
    camera_fit = assert_read_path(work / "round_00" / "profile_camera_fit.json")
    camera = _camera_basis(_json_load(camera_fit))
    catalog = load_unit_anatomy_catalog(unit)
    sprite_dir = _sprite_dir(clip_payload)
    try:
        sprite_dir.resolve().relative_to(SPRITE_TREE.resolve())
    except ValueError as exc:
        raise ValueError(f"sprite directory is not under pose_picker_runs: {sprite_dir}") from exc
    sources = [
        frame_rest_source(int(frame), prefix=prefix, suffix=suffix, frame_count=len(frames))
        for frame in frames
    ]
    reps = flight_phase_representative_frames(frames, prefix=prefix, suffix=suffix)
    meshes = {
        "perch": round_dir / "perch_rest.glb",
        "takeoff": round_dir / "fly_rest_takeoff.glb",
        "cruise": round_dir / "fly_rest_cruise.glb",
        "landing": round_dir / "fly_rest_landing.glb",
    }
    if not meshes["perch"].is_file():
        meshes["perch"] = round_dir / "after.glb"
    present = {name: path.is_file() for name, path in meshes.items()}
    edit_dir = work / "manual_edit" / "current"
    idle_poses_path = edit_dir / "after_poses.json"
    if not idle_poses_path.is_file():
        idle_poses_path = round_dir / "after_poses.json"
    fly_poses_path = edit_dir / "fly_poses.json"
    if not fly_poses_path.is_file():
        fly_candidate = round_dir / "fly_temporal_poses.json"
        fly_poses_path = fly_candidate if fly_candidate.is_file() else idle_poses_path
    idle_poses = _pose_payload(idle_poses_path)
    fly_poses = _pose_payload(fly_poses_path)
    return {
        "unit": unit,
        "clip": clip,
        "proof": "generated-artifact",
        "neverMasterGlb": True,
        "poseUnits": "degrees",
        "architectureRound": round_dir.name,
        "idlePrefixFrames": int(prefix),
        "idleSuffixFrames": int(suffix),
        "frameIndices": frames,
        "frameRestSources": sources,
        "representatives": {str(name): int(frame) for name, frame in reps.items()},
        "camera": camera,
        "cameraFitPath": str(camera_fit).replace("\\", "/"),
        "anatomy": catalog,
        "meshesPresent": present,
        "meshUrls": {
            name: f"/api/mesh/{unit}/{clip}/{name}"
            for name, exists in present.items()
            if exists
        },
        "spriteUrlPrefix": f"/api/sprite/{unit}/{clip}/",
        "rasterResolution": [288, 258],
        "sourceRound": round_dir.name,
        "idlePoses": idle_poses.get("poses") or {},
        "flyPoses": fly_poses.get("poses") or {},
        "loadedIdlePoses": str(idle_poses_path).replace("\\", "/"),
        "loadedFlyPoses": str(fly_poses_path).replace("\\", "/"),
        "concatenatedClipDoesNotWrap": bool(prefix or suffix),
        "playbackMs": 180,
        "idleReferenceFrame": next(
            (int(frame) for frame, source in zip(frames, sources) if source == "perch"),
            int(frames[0]),
        ),
    }


def mesh_file(unit: str, clip: str, name: str) -> Path:
    allowed = {
        "perch": "perch_rest.glb",
        "takeoff": "fly_rest_takeoff.glb",
        "cruise": "fly_rest_cruise.glb",
        "landing": "fly_rest_landing.glb",
    }
    if name not in allowed:
        raise ValueError(f"unknown mesh {name}")
    round_dir = _architecture_round(work_clip_dir(unit, clip))
    path = round_dir / allowed[name]
    if name == "perch" and not path.is_file():
        path = round_dir / "after.glb"
    return assert_read_path(path)


def sprite_file(unit: str, clip: str, frame: int) -> Path:
    work = work_clip_dir(unit, clip)
    round_dir = _architecture_round(work)
    clip_payload = _json_load(round_dir / "gpu_clip_result.json")
    directory = _sprite_dir(clip_payload)
    path = directory / f"{int(frame):02d}.png"
    return assert_read_path(path)


def save_session(body: dict) -> dict:
    unit = str(body.get("unit") or "")
    clip = str(body.get("clip") or "")
    dest = manual_edit_dir(unit, clip)
    dest.mkdir(parents=True, exist_ok=True)
    work = work_clip_dir(unit, clip)
    camera_fit = work / "round_00" / "profile_camera_fit.json"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    idle = {
        "poseUnits": "degrees",
        "neverMasterGlb": True,
        "proof": "generated-artifact",
        "manualEdit": True,
        "unit": unit,
        "clip": clip,
        "poses": body.get("idlePoses") or {},
        "frameIndices": [int(frame) for frame in (body.get("frameIndices") or [])],
        "cameraFitPath": str(camera_fit.resolve()).replace("\\", "/"),
        "editedAt": stamp,
    }
    fly = dict(idle)
    fly["poses"] = body.get("flyPoses") or {}
    _require_degrees(idle, "idlePoses")
    _require_degrees(fly, "flyPoses")
    _json_dump(dest / "after_poses.json", idle)
    _json_dump(dest / "fly_poses.json", fly)
    meta = {
        "poseUnits": "degrees",
        "neverMasterGlb": True,
        "unit": unit,
        "clip": clip,
        "editedAt": stamp,
        "note": str(body.get("note") or ""),
        "sourceRound": str(body.get("sourceRound") or ""),
    }
    _json_dump(dest / "session.json", meta)
    snapshot = dest.parent / stamp
    snapshot.mkdir(parents=True, exist_ok=True)
    for name in ("after_poses.json", "fly_poses.json", "session.json"):
        (snapshot / name).write_text((dest / name).read_text(encoding="utf-8"), encoding="utf-8")
        assert_write_path(snapshot / name)
    return {
        "ok": True,
        "dir": str(dest).replace("\\", "/"),
        "snapshot": str(snapshot).replace("\\", "/"),
        "editedAt": stamp,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self._send(code, raw, "application/json; charset=utf-8")

    def _send_file(self, path: Path, content_type: str | None = None) -> None:
        data = path.read_bytes()
        guessed = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(200, data, guessed)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path in {"/", "/index.html"}:
                self._send_file(STATIC / "index.html", "text/html; charset=utf-8")
                return
            if path.startswith("/static/"):
                name = Path(path[len("/static/") :]).name
                dest = STATIC / name
                if not dest.is_file():
                    raise FileNotFoundError(name)
                self._send_file(dest)
                return
            if path == "/api/session":
                query = parse_qs(parsed.query)
                unit = (query.get("unit") or [DEFAULT_UNIT])[0]
                clip = (query.get("clip") or [DEFAULT_CLIP])[0]
                self._send_json(200, build_session(unit, clip))
                return
            if path.startswith("/api/mesh/"):
                parts = path.strip("/").split("/")
                _, _, unit, clip, name = parts
                self._send_file(mesh_file(unit, clip, name), "model/gltf-binary")
                return
            if path.startswith("/api/sprite/"):
                parts = path.strip("/").split("/")
                _, _, unit, clip, filename = parts
                frame = int(Path(filename).stem)
                self._send_file(sprite_file(unit, clip, frame), "image/png")
                return
            self._send_json(404, {"ok": False, "error": "not found"})
        except Exception as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/save":
            self._send_json(404, {"ok": False, "error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
            self._send_json(200, save_session(body))
        except Exception as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})


def main() -> None:
    parser = argparse.ArgumentParser(description="Sprite feasibility pose editor (Roc prototype)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--unit", default=DEFAULT_UNIT)
    parser.add_argument("--clip", default=DEFAULT_CLIP)
    args = parser.parse_args()
    build_session(args.unit, args.clip)
    server = ThreadingHTTPServer(("127.0.0.1", int(args.port)), Handler)
    print(
        f"pose editor http://127.0.0.1:{int(args.port)}/?unit={args.unit}&clip={args.clip}",
        flush=True,
    )
    print(f"writes {WORK_TREE / args.unit / args.clip / 'manual_edit'}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
