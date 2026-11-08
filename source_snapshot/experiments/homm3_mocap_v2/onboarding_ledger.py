"""Small, append-only timing ledger for animation onboarding experiments."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path

CATEGORIES = {"auth", "preparation", "capture", "fit", "validation"}
_UNIT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("started-at must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("started-at must include a timezone")
    return parsed.timestamp()


def _valid_unit(unit: str) -> None:
    if not _UNIT.fullmatch(unit):
        raise ValueError("unit must be a safe name (letters, digits, _, ., - only)")


def _load(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(f"ledger does not exist: {path}") from exc


def start(output: str, unit: str, started_at: str | None = None, *, now: float | None = None) -> dict:
    _valid_unit(unit)
    path = Path(output)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite ledger: {path}")
    timestamp = _parse_iso(started_at) if started_at else (time.time() if now is None else now)
    ledger = {"schema": 1, "unit": unit, "startUTC": _iso(timestamp),
              "startTimestampSeconds": timestamp, "stages": [], "notes": [],
              "modelCost": "unavailable"}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(ledger, handle, indent=2)
        handle.write("\n")
    return ledger


def stage(ledger_path: str, name: str, category: str, seconds: float, *, now: float | None = None) -> dict:
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of: {', '.join(sorted(CATEGORIES))}")
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("stage seconds must be finite and non-negative")
    path = Path(ledger_path)
    ledger = _load(path)
    start_seconds = time.time() if now is None else now
    entry = {"name": name, "category": category, "recordedUTC": _iso(start_seconds),
             "recordedTimestampSeconds": start_seconds, "durationSeconds": seconds}
    if "finishUTC" in ledger:
        raise ValueError("cannot add a stage after ledger finish")
    ledger["stages"].append(entry)
    _write(path, ledger)
    return entry


def note(ledger_path: str, text: str, artifact: str | None = None) -> dict:
    if not text.strip():
        raise ValueError("note text cannot be empty")
    record = {"text": text}
    if artifact is not None:
        artifact_path = Path(artifact)
        if not artifact_path.is_file():
            raise ValueError("artifact must be an existing file")
        digest = hashlib.sha256()
        with artifact_path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        record["artifact"] = str(artifact_path)
        record["artifactSHA256"] = digest.hexdigest()
    path = Path(ledger_path)
    ledger = _load(path)
    if "finishUTC" in ledger:
        raise ValueError("cannot add a note after ledger finish")
    ledger["notes"].append(record)
    _write(path, ledger)
    return record


def finish(ledger_path: str, *, now: float | None = None) -> dict:
    path = Path(ledger_path)
    ledger = _load(path)
    if "finishUTC" in ledger:
        raise ValueError("ledger is already finished")
    end = time.time() if now is None else now
    elapsed = end - float(ledger["startTimestampSeconds"])
    if elapsed < 0:
        raise ValueError("finish time cannot precede ledger start")
    ledger["finishUTC"] = _iso(end)
    ledger["finishTimestampSeconds"] = end
    ledger["endToEndSeconds"] = elapsed
    ledger["stageSeconds"] = sum(item["durationSeconds"] for item in ledger["stages"])
    _write(path, ledger)
    return ledger


def _write(path: Path, ledger: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(ledger, handle, indent=2)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("start"); p.add_argument("--output", required=True); p.add_argument("--unit", required=True); p.add_argument("--started-at")
    p = commands.add_parser("stage"); p.add_argument("--ledger", required=True); p.add_argument("--name", required=True); p.add_argument("--category", required=True); p.add_argument("--seconds", required=True, type=float)
    p = commands.add_parser("note"); p.add_argument("--ledger", required=True); p.add_argument("--text", required=True); p.add_argument("--artifact")
    p = commands.add_parser("finish"); p.add_argument("--ledger", required=True)
    args = parser.parse_args(argv)
    if args.command == "start": result = start(args.output, args.unit, args.started_at)
    elif args.command == "stage": result = stage(args.ledger, args.name, args.category, args.seconds)
    elif args.command == "note": result = note(args.ledger, args.text, args.artifact)
    else: result = finish(args.ledger)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
