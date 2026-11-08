"""Blender startup script: enable the MCP addon and start its socket server.

Blender's addon hands commands to the main thread through ``bpy.app.timers``, and timers only fire while
Blender's own event loop is running.  A ``-b`` (background) instance therefore accepts the connection,
queues the command, and never answers it - so this script refuses to pretend otherwise and says why.

A detached GUI launch has nowhere to print, so the outcome is written to a status file as well:

    blender.exe --python tools/blender_mcp/start_server.py
    py -3 tools/blender_mcp/probe.py ping
"""
from __future__ import annotations

import json
import traceback
from pathlib import Path

import addon_utils
import bpy

MODULE = "blender_mcp"
ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "artifacts/blender_mcp/server_status.json"


def _record(payload: dict) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"blender_mcp: {json.dumps(payload, sort_keys=True)}")


def main() -> None:
    if bpy.app.background:
        _record(
            {
                "ok": False,
                "reason": "background_mode",
                "detail": (
                    "the addon executes commands through bpy.app.timers, which need Blender's GUI "
                    "event loop; launch Blender with a window instead"
                ),
            }
        )
        return
    addon_utils.modules_refresh()
    if MODULE not in bpy.context.preferences.addons:
        addon_utils.enable(MODULE, default_set=True, persistent=True)
    server = getattr(bpy.types, "blendermcp_server", None)
    if server is None or not server.running:
        bpy.ops.blendermcp.start_server()
    server = getattr(bpy.types, "blendermcp_server", None)
    _record(
        {
            "ok": bool(server is not None and server.running),
            "addonEnabled": MODULE in bpy.context.preferences.addons,
            "host": getattr(server, "host", None),
            "port": getattr(server, "port", None) or int(bpy.context.scene.blendermcp_port),
            "blender": bpy.app.version_string,
            "statusFile": str(STATUS).replace("\\", "/"),
        }
    )


try:
    main()
except Exception:
    _record({"ok": False, "reason": "exception", "traceback": traceback.format_exc()})
