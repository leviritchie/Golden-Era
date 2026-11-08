"""Derive a mesh-specific prop orientation record from measured source evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mesh", type=Path, required=True)
    parser.add_argument("--attachments", type=Path, required=True)
    parser.add_argument("--axis-start", type=float, nargs=3, required=True)
    parser.add_argument("--axis-end", type=float, nargs=3, required=True)
    args = parser.parse_args()
    record = json.loads(args.template.read_text(encoding="utf-8"))
    record["sourceMeshSha256"] = hashlib.sha256(args.mesh.read_bytes()).hexdigest()
    record["propAttachmentsSha256"] = hashlib.sha256(args.attachments.read_bytes()).hexdigest()
    record["axisStart"] = list(args.axis_start)
    record["axisEnd"] = list(args.axis_end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output.resolve()),
        "sourceMeshSha256": record["sourceMeshSha256"],
        "propAttachmentsSha256": record["propAttachmentsSha256"],
        "axisStart": record["axisStart"],
        "axisEnd": record["axisEnd"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
