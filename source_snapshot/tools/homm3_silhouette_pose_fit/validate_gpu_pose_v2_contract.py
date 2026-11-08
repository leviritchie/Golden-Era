#!/usr/bin/env python3
"""Entry point for the fast V2 pose-pipeline artifact validator.

Keeping this wrapper beside the existing pose-pipeline tools makes the V2
contract available to the normal validation path without making the package's
notebook-facing imports depend on command-line argument parsing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gpu_pose_v2.validate_contract import validate_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_result(args.result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
