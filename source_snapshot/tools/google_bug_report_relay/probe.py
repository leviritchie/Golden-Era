#!/usr/bin/env python3
"""Explicit anonymous HTTP probe; creates synthetic ZIPs only, never reads game files."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

MAX_REPLY_BYTES = 64 * 1024
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
# Same shared filter token as ModBugReportTransport.ClientToken. It is public and is not authentication.
CLIENT_TOKEN = "golden-era-mod-report-1"
SYNTHETIC_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aJ1sAAAAASUVORK5CYII="
)


class GoogleContentRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != "https" or target.hostname != "script.googleusercontent.com":
            raise ValueError("Unexpected redirect; no payload or credentials will be forwarded")
        if code not in (301, 302, 303) or req.get_method() != "POST":
            raise ValueError("Unexpected redirect flow; inspect the deployment instead of retrying")
        return urllib.request.Request(newurl, method="GET")


def synthetic_bundle(at_limit: bool) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(zipfile.ZipInfo("metadata.json"), json.dumps({"synthetic": True, "purpose": "Google pilot"}))
        archive.writestr(zipfile.ZipInfo("bepinex-log-tail.txt"), "SYNTHETIC ONLY: not a game log.\n")
        archive.writestr(zipfile.ZipInfo("native-log-tail.txt"), "SYNTHETIC ONLY: not a native log.\n")
        # A one-pixel PNG is a synthetic screenshot fixture, not a capture of the user's screen.
        archive.writestr(zipfile.ZipInfo("screenshot.png"), SYNTHETIC_PNG)
        archive.writestr(zipfile.ZipInfo("synthetic-padding.bin"), b"")
    if not at_limit:
        return buffer.getvalue()
    padding = MAX_BUNDLE_BYTES - len(buffer.getvalue())
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        # Read only our in-memory synthetic fixture, not anything from disk.
        with zipfile.ZipFile(io.BytesIO(synthetic_bundle(False))) as original:
            for info in original.infolist():
                archive.writestr(info, b"x" * padding if info.filename == "synthetic-padding.bin"
                                 else original.read(info))
    bundle = buffer.getvalue()
    if len(bundle) != MAX_BUNDLE_BYTES:
        raise ValueError("Synthetic limit fixture did not match the bundle contract")
    return bundle


def synthetic_player_bundle(report_id: str) -> bytes:
    """A synthetic ZIP shaped like bundle_contract.json so the player route's entry/schema checks accept it."""
    report = {
        "schema": "oe_mod_bug_report.v3", "createdUtc": "2026-01-01T00:00:00.0000000Z", "reportId": report_id,
        "source": "native_form", "reportHash": "0" * 64, "pluginVersion": "synthetic",
        "title": "SYNTHETIC PROBE", "description": "SYNTHETIC ONLY: not a player report.", "category": "synthetic",
        "tag": "synthetic", "gameId": "synthetic", "contactProvided": "false", "os": "synthetic",
        "nativeAttachmentsOmitted": "none", "screenshot": "included", "limits": "synthetic", "scrubbing": "synthetic",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(zipfile.ZipInfo("report.json"), json.dumps(report, indent=1))
        archive.writestr(zipfile.ZipInfo("bepinex_log_tail.txt"), "SYNTHETIC ONLY: not a game log.\n")
        archive.writestr(zipfile.ZipInfo("native_log.txt"), "SYNTHETIC ONLY: not a native log.\n")
        archive.writestr(zipfile.ZipInfo("payload_manifest.json"), json.dumps({"pluginVersion": "synthetic"}))
        archive.writestr(zipfile.ZipInfo("screenshot.png"), SYNTHETIC_PNG)
    return buffer.getvalue()


def submit(endpoint: str, body: dict) -> dict:
    request = urllib.request.Request(
        endpoint, data=json.dumps(body, separators=(",", ":")).encode("ascii"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    # No cookie jar, OAuth token, browser session, or retry: this must work anonymously.
    opener = urllib.request.build_opener(GoogleContentRedirect())
    with opener.open(request, timeout=25) as response:
        data = response.read(MAX_REPLY_BYTES + 1)
        if len(data) > MAX_REPLY_BYTES:
            raise ValueError("Receiver response exceeded the bounded reply limit")
        if response.status != 200 or response.headers.get_content_type() != "application/json":
            raise ValueError("Expected a JSON acknowledgement, not a login page or HTTP success alone")
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError("Receiver reply was not a JSON object")
    if result.get("ok") is not True:
        raise ValueError(f"Receiver refused synthetic probe: {result.get('error', 'invalid_reply')}")
    if result.get("reportId") != body["reportId"] or result.get("sha256") != body["sha256"]:
        raise ValueError("Receiver acknowledgement did not match this synthetic report")
    if type(result.get("duplicate")) is not bool:
        raise ValueError("Receiver acknowledgement omitted duplicate status")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--submit-synthetic", action="store_true", required=True,
                        help="Explicitly authorize one synthetic upload; never invoked by build/deploy")
    parser.add_argument("--at-limit", action="store_true", help="Probe an exactly 8 MiB pilot ZIP")
    parser.add_argument("--player-format", action="store_true",
                        help="Send only synthetic bytes using the player-report envelope; never reads game data")
    parser.add_argument("--oversize", action="store_true",
                        help="Probe an 8 MiB plus one-byte synthetic ZIP refusal")
    parser.add_argument("--report-id", type=uuid.UUID, help="Reuse an ID only for an explicit duplicate probe")
    args = parser.parse_args()
    if not re.fullmatch(r"https://script\.google\.com/macros/s/[A-Za-z0-9_-]+/exec", args.endpoint):
        parser.error("Use the observed Apps Script /exec deployment URL, not a login or /dev URL")
    if args.oversize and args.at_limit:
        parser.error("Choose either --at-limit or --oversize")
    if args.player_format and args.at_limit:
        parser.error("--at-limit applies to the pinned pilot fixture; the player route inspects entries")
    report_id = str(args.report_id or uuid.uuid4())
    if args.player_format and not args.oversize:
        bundle = synthetic_player_bundle(report_id)
    else:
        bundle = synthetic_bundle(args.at_limit or args.oversize)
    if args.oversize:
        bundle += b"x"
    body = {"version": 1, "purpose": "player-report" if args.player_format else "synthetic-pilot",
            "reportId": report_id,
            "sha256": hashlib.sha256(bundle).hexdigest(), "bundleBase64": base64.b64encode(bundle).decode("ascii")}
    if args.player_format:
        body["version"] = 2
        body["clientToken"] = CLIENT_TOKEN
    started = time.monotonic()
    try:
        result = submit(args.endpoint, body)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(json.dumps({"anonymousHttpProven": False, "error": str(exc), "retried": False}))
        return 1
    print(json.dumps({"anonymousHttpProven": True, "storedBytesClaimed": len(bundle),
                      "reportId": result["reportId"], "sha256": result["sha256"],
                      "duplicate": result["duplicate"], "elapsedSeconds": round(time.monotonic() - started, 3),
                      "ownerDriveReadbackRequired": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
