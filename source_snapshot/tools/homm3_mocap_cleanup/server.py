#!/usr/bin/env python3
"""Browser cleanup editor for idle-0 mocap binds.

Writes only under artifacts/homm3_mocap_v2/cleanup_edits/.
Never overwrites full_set_mocap_idle0_v1/runs/.
Proof: generated-artifact JSON + the browser preview. Not OE battle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import sys
import threading
import webbrowser

import numpy as np
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "experiments" / "homm3_mocap_v2"))
sys.path.insert(0, str(HERE))

from cleanup_paths import EDITS, LEDGER, RUNS, STATIC, assert_read_path, assert_write_path  # noqa: E402
from glb_skeleton import load_bind_skeleton  # noqa: E402
from schema import (  # noqa: E402
    apply_skin_rules,
    new_candidate,
    pack_dense_weights,
    skin_rules_from_payload,
    validate_candidate,
)

DEFAULT_UNIT = "h3_amalek"
DEFAULT_PORT = 8766
HIDDEN_BIND_FOLDERS = frozenset({"linked_master_bindfirst", "linked_master_scalefix", "linked_master_bodysat"})
BIND_FOLDER_TITLES = {
    "linked_master_lengthbind": "previous length-only",
    "linked_master_yawfix": "previous yaw-fix (uniform shrink)",
    "linked_master_seedscale": "previous seed-scale (no body saturate)",
    "linked_master_anatomy": "anatomical slots (foot cannot sit in knee)",
    "linked_master_floor": "floor column (feet on mesh bottom)",
    "linked_master_ground": "ground + height only (no bone moves)",
    "linked_master_scale": "yaw-fix + scale slider (hips stay)",
    "linked_master_hybrid_yawfix": "Mixamo body + Eagle wings (yaw-fix)",
    "linked_master_hybrid_scale": "Mixamo body + Eagle wings (scale)",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ok_token(value: str) -> bool:
    return bool(value) and all(ch.isalnum() or ch in "_-" for ch in value)


def parse_selection(raw: str) -> tuple[str, str]:
    text = str(raw or "").strip()
    if "@" in text:
        unit, variant = text.split("@", 1)
    else:
        unit, variant = text, "linked_master"
    if not _ok_token(unit) or not _ok_token(variant) or not variant.startswith("linked_master"):
        raise ValueError(f"invalid unit selection: {raw!r}")
    return unit, variant


def selection_id(unit: str, variant: str) -> str:
    if variant == "linked_master":
        return unit
    return f"{unit}@{variant}"


def _master_dir(unit: str, variant: str = "linked_master") -> Path:
    return RUNS / unit / variant


def _bind_glb(unit: str, variant: str = "linked_master") -> Path:
    return _master_dir(unit, variant) / "capture_bind" / f"{unit}_linked_master_bind.glb"


def _registration(unit: str, variant: str = "linked_master") -> Path:
    return _master_dir(unit, variant) / "idle0_registration.json"


def _clips_dir(unit: str, variant: str = "linked_master") -> Path:
    return _master_dir(unit, variant) / "clips"


def _fit_title(registration: Path) -> str:
    if not registration.is_file():
        return "current"
    try:
        payload = json.loads(registration.read_text(encoding="utf-8"))
        similarity = (payload.get("views") or {}).get("candidates") or [{}]
        fit = str((similarity[0].get("skeletonSimilarity") or {}).get("fit") or "")
    except (OSError, json.JSONDecodeError, IndexError, TypeError, AttributeError):
        return "current"
    if "scale_to_ground" in fit:
        return "yaw-fix + scale slider (hips stay)"
    if "ground_height" in fit:
        return "ground + height only (no bone moves)"
    if "floor_column" in fit:
        return "floor column (feet on mesh bottom)"
    if "bind_first" in fit:
        return "bind-first (current)"
    if "length" in fit:
        return "length-only"
    return "current"


def _variant_title(unit: str, variant: str, registration: Path, *, has_siblings: bool) -> str:
    if variant in BIND_FOLDER_TITLES:
        return f"{unit} — {BIND_FOLDER_TITLES[variant]}"
    if not has_siblings and variant == "linked_master":
        return unit
    return f"{unit} — {_fit_title(registration)}"


def _list_units(runs: Path | None = None) -> list[dict]:
    root = RUNS if runs is None else Path(runs)
    if not root.is_dir():
        return []
    rows = []
    for unit_dir in sorted(root.iterdir()):
        if not unit_dir.is_dir():
            continue
        unit = unit_dir.name
        variants = []
        for master in sorted(unit_dir.iterdir()):
            if not master.is_dir():
                continue
            if master.name in HIDDEN_BIND_FOLDERS:
                continue
            if master.name != "linked_master" and not master.name.startswith("linked_master_"):
                continue
            bind = master / "capture_bind" / f"{unit}_linked_master_bind.glb"
            clips = master / "clips"
            if not bind.is_file() or not clips.is_dir():
                continue
            clip_names = sorted(path.stem for path in clips.glob("Unit_*.glb"))
            if not clip_names:
                continue
            variants.append(master)
        has_siblings = len(variants) > 1
        for master in variants:
            gif = master / f"{unit}_linked_master.gif"
            overlay = master / "capture_bind" / f"{unit}_linked_master_bind_skeleton_overlay.png"
            registration = master / "idle0_registration.json"
            rows.append(
                {
                    "id": selection_id(unit, master.name),
                    "unit": unit,
                    "variant": master.name,
                    "label": _variant_title(unit, master.name, registration, has_siblings=has_siblings),
                    "clips": sorted(path.stem for path in (master / "clips").glob("Unit_*.glb")),
                    "hasGif": gif.is_file(),
                    "hasOverlay": overlay.is_file(),
                }
            )
    return rows


def _unit_payload(selection: str) -> dict:
    unit, variant = parse_selection(selection)
    bind = _bind_glb(unit, variant)
    registration = _registration(unit, variant)
    clips = _clips_dir(unit, variant)
    if not bind.is_file():
        raise FileNotFoundError(f"missing bind GLB for {selection}: {bind}")
    if not registration.is_file():
        raise FileNotFoundError(f"missing idle0 registration for {selection}: {registration}")
    clip_names = sorted(path.stem for path in clips.glob("Unit_*.glb"))
    if not clip_names:
        raise FileNotFoundError(f"missing clip GLBs for {selection}: {clips}")
    regions = bind.with_name(bind.name.replace(".glb", "_regions.json"))
    bones = []
    if regions.is_file():
        payload = json.loads(regions.read_text(encoding="utf-8"))
        seen = []
        for names in (payload.get("regionJoints") or {}).values():
            for name in names:
                if name not in seen:
                    seen.append(name)
        bones = seen
    gif = _master_dir(unit, variant) / f"{unit}_linked_master.gif"
    overlay = bind.with_name(bind.name.replace(".glb", "_skeleton_overlay.png"))
    siblings = [row for row in _list_units() if row["unit"] == unit]
    label = _variant_title(unit, variant, registration, has_siblings=len(siblings) > 1)
    return {
        "id": selection_id(unit, variant),
        "unit": unit,
        "variant": variant,
        "label": label,
        "ledger": str(LEDGER).replace("\\", "/"),
        "bindPath": str(bind.resolve()).replace("\\", "/"),
        "bindUrl": f"/api/file?path={_rel_run(bind)}",
        "bindSha256": _sha256(bind),
        "registrationPath": str(registration.resolve()).replace("\\", "/"),
        "registrationUrl": f"/api/file?path={_rel_run(registration)}",
        "registrationSha256": _sha256(registration),
        "clips": {
            name: f"/api/file?path={_rel_run(clips / f'{name}.glb')}" for name in clip_names
        },
        "gifUrl": f"/api/file?path={_rel_run(gif)}" if gif.is_file() else "",
        "overlayUrl": f"/api/file?path={_rel_run(overlay)}" if overlay.is_file() else "",
        "bones": bones,
        "defaultClip": "Unit_Idle" if "Unit_Idle" in clip_names else clip_names[0],
        "fps": 12,
        "proof": "generated-artifact",
        "note": (
            "Compare the left HoMM3 sprite reel to the 3D mesh. "
            "The Unit list is creatures, plus named bind versions when a unit has more than one. "
            "Cleanup preview only. Not ship and not consumed by the scheduler."
        ),
    }


def _rel_run(path: Path) -> str:
    return str(path.resolve().relative_to(RUNS.resolve())).replace("\\", "/")


def _resolve_run_file(rel: str) -> Path:
    if not rel or ".." in Path(rel).parts:
        raise ValueError("invalid file path")
    return assert_read_path(RUNS / rel)


_SKIN_JOBS: dict[str, dict] = {}
_SKIN_JOB_LOCK = threading.Lock()


def _apply_skin_rules(body: dict, progress=None) -> dict:
    selection = str(body.get("unit") or "")
    unit, variant = parse_selection(selection)
    bind = _bind_glb(unit, variant)
    if not bind.is_file():
        raise FileNotFoundError(f"missing bind GLB for {selection}: {bind}")
    if progress is not None:
        progress(0.02, "loading bind mesh")
    skeleton = load_bind_skeleton(bind)
    if skeleton.vertices is None:
        raise ValueError(f"{bind} has no mesh vertices")
    vertex_count = int(body.get("vertexCount") or 0)
    if vertex_count != len(skeleton.vertices):
        raise ValueError(
            f"clip vertex count {vertex_count} does not match bind GLB {len(skeleton.vertices)}"
        )
    joints = np.asarray(body.get("joints"), dtype=np.float64)
    parents = np.asarray(body.get("parents"), dtype=np.int64)
    names = [str(name) for name in (body.get("names") or [])]
    if joints.ndim != 2 or joints.shape[1] != 3:
        raise ValueError("joints must be [J,3] in the current bind")
    if parents.shape != (len(joints),) or len(names) != len(joints):
        raise ValueError("parents and names must match the joint list")
    rules = skin_rules_from_payload({"skinRules": body.get("skinRules")})
    triangles = None
    if rules["distance"] == "geodesic":
        if skeleton.triangles is None:
            raise ValueError(f"{bind} has no triangles; geodesic rules cannot run")
        triangles = np.asarray(skeleton.triangles, dtype=np.int64)
    dense = apply_skin_rules(
        np.asarray(skeleton.vertices, dtype=np.float64),
        joints,
        parents,
        names,
        rules,
        triangles=triangles,
        progress=progress,
    )
    slots = int(body.get("slots") or min(int(rules["k"]), 8))
    packed = pack_dense_weights(dense, slots=min(max(slots, 1), 8, dense.shape[1]))
    return {
        "ok": True,
        "rules": rules,
        "weightOverride": packed,
        "vertexCount": int(len(dense)),
        "proof": "generated-artifact",
    }


def _run_skin_job(job_id: str, body: dict) -> None:
    with _SKIN_JOB_LOCK:
        job = _SKIN_JOBS[job_id]
        job["message"] = "computing weights from the current bind"
        job["percent"] = 0
    def report(fraction: float, message: str) -> None:
        with _SKIN_JOB_LOCK:
            current = _SKIN_JOBS[job_id]
            current["percent"] = int(round(100.0 * fraction))
            current["message"] = message
    try:
        result = _apply_skin_rules(body, progress=report)
        with _SKIN_JOB_LOCK:
            job = _SKIN_JOBS[job_id]
            job.update(result)
            job["status"] = "done"
            job["percent"] = 100
            job["message"] = f"applied {result['vertexCount']} vertices"
    except Exception as exc:
        with _SKIN_JOB_LOCK:
            job = _SKIN_JOBS[job_id]
            job["status"] = "error"
            job["ok"] = False
            job["error"] = str(exc)
            job["message"] = str(exc)


def _start_skin_job(body: dict) -> dict:
    skin_rules_from_payload({"skinRules": body.get("skinRules")})
    parse_selection(str(body.get("unit") or ""))
    with _SKIN_JOB_LOCK:
        running = next((job for job in _SKIN_JOBS.values() if job.get("status") == "running"), None)
        if running:
            raise ValueError(f"a skin job is already running: {running['id']}")
        job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        _SKIN_JOBS[job_id] = {
            "id": job_id,
            "ok": True,
            "status": "running",
            "message": "queued",
            "percent": 0,
        }
    thread = threading.Thread(target=_run_skin_job, args=(job_id, body), daemon=True)
    thread.start()
    return {"ok": True, "jobId": job_id, "status": "running", "message": "queued", "percent": 0}


def _skin_job(job_id: str) -> dict:
    with _SKIN_JOB_LOCK:
        job = _SKIN_JOBS.get(job_id)
        if job is None:
            raise FileNotFoundError(f"unknown skin job {job_id}")
        return dict(job)


def _save_candidate(body: dict) -> dict:
    payload = validate_candidate(body)
    unit = str(payload["unit"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = assert_write_path(EDITS / unit / stamp / "candidate.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "path": str(dest).replace("\\", "/"), "proof": "generated-artifact"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, payload: dict | list) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _send_error_json(self, code: int, message: str) -> None:
        self._send_json(code, {"ok": False, "error": message})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        try:
            if route in {"/", "/index.html"}:
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                return
            if route.startswith("/static/"):
                rel = route[len("/static/") :]
                path = assert_read_path(STATIC / rel)
                mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                self._send(200, path.read_bytes(), mime)
                return
            if route == "/api/units":
                self._send_json(200, {"units": _list_units(), "ledger": str(LEDGER).replace("\\", "/")})
                return
            if route == "/api/unit":
                query = parse_qs(parsed.query)
                unit = (query.get("id") or [DEFAULT_UNIT])[0]
                self._send_json(200, _unit_payload(unit))
                return
            if route == "/api/skin-job":
                query = parse_qs(parsed.query)
                job_id = (query.get("id") or [""])[0]
                self._send_json(200, _skin_job(job_id))
                return
            if route == "/api/file":
                query = parse_qs(parsed.query)
                rel = unquote((query.get("path") or [""])[0])
                path = _resolve_run_file(rel)
                mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                self._send(200, path.read_bytes(), mime)
                return
            self._send_error_json(404, f"unknown route {route}")
        except (OSError, ValueError, FileNotFoundError) as exc:
            self._send_error_json(400, str(exc))

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            self._send_error_json(400, f"invalid JSON: {exc}")
            return
        try:
            if parsed.path == "/api/skin":
                self._send_json(200, _start_skin_job(body))
                return
            if parsed.path == "/api/save":
                source = body.get("source") or {}
                candidate = new_candidate(
                    unit=str(body.get("unit") or ""),
                    source=source,
                    skeleton_delta=body.get("skeletonDelta"),
                    bone_lengths=body.get("boneLengths") or {},
                    weight_follow_joints=bool(body.get("weightFollowJoints")),
                    weight_rewrite_from_bind=bool(body.get("weightRewriteFromBind")),
                    weight_override=body.get("weightOverride"),
                    skin_rules=body.get("skinRules"),
                    edits=body.get("edits") or [],
                    notes=str(body.get("notes") or ""),
                )
                self._send_json(200, _save_candidate(candidate))
                return
            self._send_error_json(404, f"unknown route {parsed.path}")
        except (OSError, ValueError) as exc:
            self._send_error_json(400, str(exc))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", default=DEFAULT_UNIT)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not RUNS.is_dir():
        raise SystemExit(f"mocap ledger runs folder is missing: {RUNS}")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/?unit={args.unit}"
    print(f"mocap bind lab {url}")
    print(f"writes {EDITS}")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
