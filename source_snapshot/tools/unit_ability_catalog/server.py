#!/usr/bin/env python3
"""Local browse UI for the HoMM3 custom unit ability catalog."""

from __future__ import annotations

import argparse
import subprocess
import sys
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_PORTRAIT_DIR = (
    REPO_ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_portraits"
)
GENERATOR = REPO_ROOT / "tools" / "generate_homm3_custom_unit_ability_catalog.py"


class CatalogHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, portrait_dir: Path, **kwargs):
        self.portrait_dir = portrait_dir
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/portraits/"):
            name = Path(self.path.split("?", 1)[0]).name
            if name.endswith(".png") and ".." not in name:
                target = self.portrait_dir / name
                if target.is_file():
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(target.stat().st_size))
                    self.send_header("Cache-Control", "public, max-age=3600")
                    self.end_headers()
                    self.wfile.write(target.read_bytes())
                    return
            self.send_error(404, "Portrait not found")
            return
        return super().do_GET()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def regenerate_catalog() -> None:
    cmd = [sys.executable, str(GENERATOR), "--repo-root", str(REPO_ROOT)]
    print("Regenerating catalog JSON/markdown…")
    subprocess.run(cmd, check=True, cwd=str(REPO_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--portrait-dir",
        type=Path,
        default=DEFAULT_PORTRAIT_DIR,
        help="Directory of h3_*.png unit portraits",
    )
    parser.add_argument(
        "--skip-regenerate",
        action="store_true",
        help="Do not regenerate catalog.json before serving",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open a browser tab automatically",
    )
    args = parser.parse_args()

    if not STATIC_DIR.is_dir():
        raise SystemExit(f"Missing static UI directory: {STATIC_DIR}")
    if not args.portrait_dir.is_dir():
        raise SystemExit(f"Portrait directory not found: {args.portrait_dir}")

    if not args.skip_regenerate:
        regenerate_catalog()
    elif not (STATIC_DIR / "catalog.json").is_file():
        raise SystemExit(
            "catalog.json is missing. Run without --skip-regenerate, or run "
            "tools/generate_homm3_custom_unit_ability_catalog.py first."
        )

    handler = partial(CatalogHandler, portrait_dir=args.portrait_dir.resolve())
    ThreadingHTTPServer.allow_reuse_address = True
    server = None
    bound_port = None
    last_error: OSError | None = None
    for port in range(args.port, args.port + 20):
        try:
            candidate = ThreadingHTTPServer((args.host, port), handler)
        except OSError as exc:
            last_error = exc
            continue
        server = candidate
        bound_port = port
        break
    if server is None or bound_port is None:
        raise SystemExit(
            f"Could not bind {args.host}:{args.port}-{args.port + 19}. "
            f"Last error: {last_error}"
        )
    if bound_port != args.port:
        print(
            f"Port {args.port} was unavailable; using {bound_port} instead. "
            "If the old tab still points at the busy port, close those dead "
            "Python listeners or refresh the new URL."
        )
    url = f"http://{args.host}:{bound_port}/"
    print(f"Serving unit ability catalog at {url}")
    print(f"Portraits: {args.portrait_dir}")
    print("Press Ctrl+C to stop.")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
