"""Talk to a running Blender's MCP socket server without an MCP client.

Two uses: proving the whole path works (addon loaded -> socket accepted -> command executed on Blender's
main thread), and driving Blender from a terminal when no MCP client is attached.  A successful ``ping``
only proves transport; ``scene`` and ``code`` prove the main-thread timer path, which is the part that a
background Blender silently fails.

    py -3 tools/blender_mcp/probe.py ping
    py -3 tools/blender_mcp/probe.py scene
    py -3 tools/blender_mcp/probe.py object --name Cube
    py -3 tools/blender_mcp/probe.py code --code "import bpy; print(len(bpy.data.objects))"
"""
from __future__ import annotations

import argparse
import json
import socket
import sys


def send(payload: dict, *, host: str, port: int, timeout: float) -> dict:
    """One JSON command, one JSON reply, on a connection kept open by the addon."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(json.dumps(payload).encode("utf-8"))
        sock.settimeout(timeout)
        chunks: list[bytes] = []
        while True:
            try:
                data = sock.recv(65536)
            except socket.timeout:
                break
            if not data:
                break
            chunks.append(data)
            try:
                # The addon writes one JSON object with no framing, so a reply is "parseable yet".
                return json.loads(b"".join(chunks).decode("utf-8"))
            except json.JSONDecodeError:
                continue
    raw = b"".join(chunks)
    if not raw:
        raise SystemExit(
            f"fail-closed: no bytes from {host}:{port}; is Blender running with the MCP addon "
            "connected (N panel -> MCP for Blender -> Start MCP Server)?"
        )
    raise SystemExit(f"fail-closed: reply from {host}:{port} is not one JSON object: {raw[:400]!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["ping", "scene", "object", "code", "screenshot", "export"])
    parser.add_argument("--code", default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--path", default=None)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    if args.command == "ping":
        payload = {"type": "ping"}
    elif args.command == "scene":
        payload = {"type": "get_scene_info"}
    elif args.command == "object":
        if not args.name:
            parser.error("object needs --name")
        payload = {"type": "get_object_info", "params": {"object_name": args.name}}
    elif args.command == "code":
        if not args.code:
            parser.error("code needs --code")
        payload = {"type": "execute_code", "params": {"code": args.code}}
    elif args.command == "screenshot":
        payload = {"type": "get_viewport_screenshot", "params": {}}
    else:
        if not args.path:
            parser.error("export needs --path")
        payload = {"type": "export_scene", "params": {"filepath": args.path}}

    reply = send(payload, host=args.host, port=args.port, timeout=args.timeout)
    print(json.dumps(reply, indent=2)[:4000])
    return 0 if reply.get("status") == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
