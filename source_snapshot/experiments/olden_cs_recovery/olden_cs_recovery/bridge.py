"""Live Golden Era bridge helpers (fail-closed freshness + request)."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from olden_cs_recovery.paths import INPUT_MANIFEST_PATH, REPO_ROOT

# Reuse the established live_probe_request helper; do not fork request semantics.
_RELEASE_PORT = REPO_ROOT / "tools" / "release_port"
if str(_RELEASE_PORT) not in sys.path:
    sys.path.insert(0, str(_RELEASE_PORT))

from live_probe_request import DEFAULT_BRIDGE, request_bridge  # noqa: E402


DEFAULT_FRESHNESS_MAX_AGE_MS = 5000.0
DEFAULT_FRAME_SAMPLE_MS = 400.0


class BridgeUnavailableError(RuntimeError):
    """Bridge missing, stale, or non-responsive — fail closed."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }


def load_input_manifest() -> dict[str, Any]:
    return json.loads(INPUT_MANIFEST_PATH.read_text(encoding="utf-8-sig"))


def manifest_entry(entry_id: str) -> dict[str, Any]:
    manifest = load_input_manifest()
    for entry in manifest.get("inputs") or []:
        if entry.get("id") == entry_id:
            return entry
    raise BridgeUnavailableError(
        "manifest_entry_missing",
        f"input_manifest missing entry id={entry_id!r}",
    )


def resolve_manifest_path(entry: dict[str, Any]) -> Path:
    raw = entry["path"]
    if entry.get("path_is_absolute"):
        return Path(raw)
    return (REPO_ROOT / raw).resolve()


def default_bridge_dir() -> Path:
    entry = manifest_entry("live_probe_bridge")
    path = resolve_manifest_path(entry)
    return path


def gameassembly_path() -> Path:
    entry = manifest_entry("gameassembly_dll")
    return resolve_manifest_path(entry)


def sha256_file(path: Path, *, max_bytes: int | None = None) -> str:
    if not path.is_file():
        raise BridgeUnavailableError("gameassembly_missing", f"GameAssembly.dll missing: {path}")
    h = hashlib.sha256()
    total = 0
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            total += len(chunk)
            if max_bytes is not None and total >= max_bytes:
                break
    return h.hexdigest().upper()


def expected_gameassembly_sha256() -> str | None:
    entry = manifest_entry("gameassembly_dll")
    pinned = entry.get("expected_sha256")
    if pinned is None:
        return None
    return str(pinned).upper()


def read_status_file(bridge: Path) -> dict[str, Any]:
    status_path = bridge / "status.json"
    if not status_path.is_file():
        raise BridgeUnavailableError(
            "bridge_status_missing",
            f"missing bridge status.json (game not running or mod not loaded): {status_path}",
            details={"bridge": str(bridge)},
        )
    try:
        data = json.loads(status_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeUnavailableError(
            "bridge_status_unreadable",
            f"cannot read bridge status.json: {exc}",
            details={"bridge": str(bridge)},
        ) from exc
    if not isinstance(data, dict):
        raise BridgeUnavailableError(
            "bridge_status_invalid",
            "bridge status.json root must be an object",
            details={"bridge": str(bridge)},
        )
    return data


def status_file_age_ms(bridge: Path) -> float:
    status_path = bridge / "status.json"
    mtime = status_path.stat().st_mtime
    return max(0.0, (time.time() - mtime) * 1000.0)


def require_fresh_bridge(
    bridge: Path | None = None,
    *,
    max_age_ms: float = DEFAULT_FRESHNESS_MAX_AGE_MS,
    sample_ms: float = DEFAULT_FRAME_SAMPLE_MS,
) -> dict[str, Any]:
    """Fail closed unless status.json is fresh and frame advances while sampled."""
    bridge = bridge or default_bridge_dir()
    token = bridge / "token.txt"
    inbox = bridge / "inbox"
    outbox = bridge / "outbox"
    if not token.is_file():
        raise BridgeUnavailableError("bridge_token_missing", f"missing bridge token: {token}")
    if not inbox.is_dir() or not outbox.is_dir():
        raise BridgeUnavailableError(
            "bridge_dirs_missing",
            f"missing bridge inbox/outbox under {bridge}",
        )

    first = read_status_file(bridge)
    age1 = status_file_age_ms(bridge)
    if age1 > max_age_ms:
        raise BridgeUnavailableError(
            "bridge_stale",
            (
                f"bridge status.json age {age1:.0f}ms exceeds max_age_ms={max_age_ms:.0f}. "
                "Start Golden Era with OfflineUnlockMod live_probe_bridge before identity/oracle work."
            ),
            details={"statusAgeMs": age1, "status": first},
        )
    if first.get("ok") is not True or first.get("state") != "ready":
        raise BridgeUnavailableError(
            "bridge_not_ready",
            f"bridge status not ready: ok={first.get('ok')!r} state={first.get('state')!r}",
            details={"status": first},
        )
    frame1 = first.get("frame")
    if not isinstance(frame1, int):
        raise BridgeUnavailableError(
            "bridge_frame_missing",
            "bridge status.json missing integer frame (cannot prove freshness)",
            details={"status": first},
        )

    time.sleep(max(0.05, sample_ms / 1000.0))
    second = read_status_file(bridge)
    age2 = status_file_age_ms(bridge)
    frame2 = second.get("frame")
    if not isinstance(frame2, int):
        raise BridgeUnavailableError(
            "bridge_frame_missing",
            "bridge status.json missing integer frame on second sample",
            details={"status": second},
        )
    if frame2 <= frame1:
        raise BridgeUnavailableError(
            "bridge_frame_not_advancing",
            (
                f"bridge frame did not advance ({frame1} → {frame2}) over {sample_ms:.0f}ms. "
                "Do not mark identity-bridged or oracle-captured without a live session."
            ),
            details={"frame1": frame1, "frame2": frame2, "statusAgeMs": age2},
        )
    if age2 > max_age_ms:
        raise BridgeUnavailableError(
            "bridge_stale",
            f"bridge status.json became stale after sample (age {age2:.0f}ms)",
            details={"statusAgeMs": age2, "status": second},
        )

    return {
        "ok": True,
        "bridge": str(bridge),
        "build": second.get("build"),
        "profile": second.get("profile"),
        "frame": frame2,
        "scene": second.get("scene"),
        "statusAgeMs": age2,
        "frameAdvanced": True,
        "frame1": frame1,
        "frame2": frame2,
    }


def request_live(
    payload: dict[str, Any],
    *,
    bridge: Path | None = None,
    timeout_seconds: float = 8.0,
    require_fresh: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Send one bridge request after optional freshness gate. Returns (response, freshness)."""
    bridge = bridge or default_bridge_dir()
    freshness: dict[str, Any]
    if require_fresh:
        freshness = require_fresh_bridge(bridge)
    else:
        freshness = {"ok": True, "bridge": str(bridge), "require_fresh": False}
    try:
        response = request_bridge(bridge, payload, timeout_seconds)
    except SystemExit as exc:
        raise BridgeUnavailableError(
            "bridge_request_failed",
            str(exc),
            details={"payload_command": payload.get("command"), "bridge": str(bridge)},
        ) from exc
    return response, freshness


def build_pin_metadata(*, bridge_freshness: dict[str, Any] | None = None) -> dict[str, Any]:
    """Game build id + GameAssembly hash for oracle fixture versioning."""
    ga_path = gameassembly_path()
    actual = sha256_file(ga_path)
    expected = expected_gameassembly_sha256()
    if expected is not None and actual != expected:
        raise BridgeUnavailableError(
            "gameassembly_hash_mismatch",
            (
                f"GameAssembly SHA256 mismatch: actual={actual} expected={expected}. "
                "Refresh input_manifest pin before capturing oracles."
            ),
            details={"path": str(ga_path), "actual": actual, "expected": expected},
        )
    build_id = None
    if bridge_freshness:
        build_id = bridge_freshness.get("build")
    return {
        "game_build_id": build_id,
        "gameassembly_path": str(ga_path),
        "gameassembly_sha256": actual,
        "bridge_profile": (bridge_freshness or {}).get("profile"),
        "bridge_scene": (bridge_freshness or {}).get("scene"),
        "bridge_frame": (bridge_freshness or {}).get("frame"),
    }
