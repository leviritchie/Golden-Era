"""Queue item IO with claim leases (fail-closed, idempotent stage fields)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from olden_cs_recovery.paths import QUEUE_PARTITIONS_DIR
from olden_cs_recovery.schema_validate import validate_instance

_UNSAFE = re.compile(r"[^\w.\-]+")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def method_id_to_filename(method_id: str) -> str:
    safe = _UNSAFE.sub("_", method_id).strip("_")
    if len(safe) > 180:
        # Keep prefix + stable hash suffix for Windows path limits.
        import hashlib

        digest = hashlib.sha1(method_id.encode("utf-8")).hexdigest()[:12]
        safe = f"{safe[:160]}_{digest}"
    return f"{safe}.json"


def partition_dir(partition: str) -> Path:
    # Partition prefixes like Hex.Session.Battle or edb — single directory segment.
    # Nested type partitions use Hex.Session.Battle__CastMagicEventArgs.
    safe = partition.replace("/", "__").replace("\\", "__")
    return QUEUE_PARTITIONS_DIR / safe


def item_path(partition: str, method_id: str) -> Path:
    return partition_dir(partition) / method_id_to_filename(method_id)


def empty_claim() -> dict[str, Any]:
    return {
        "holder": None,
        "role": None,
        "claimed_at": None,
        "lease_expires_at": None,
    }


def write_queue_item(item: dict[str, Any], *, path: Path | None = None) -> Path:
    validate_instance("queue_item.schema.json", item, item.get("method_id", "<queue_item>"))
    target = path or item_path(item["partition"], item["method_id"])
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(item, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def load_queue_item(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FAIL: cannot load queue item {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"FAIL: queue item root must be object: {path}")
    validate_instance("queue_item.schema.json", data, str(path))
    return data


def iter_queue_items(*, partition_prefix: str | None = None) -> list[tuple[Path, dict[str, Any]]]:
    if not QUEUE_PARTITIONS_DIR.is_dir():
        return []
    out: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(QUEUE_PARTITIONS_DIR.rglob("*.json")):
        if path.name.endswith(".tmp"):
            continue
        item = load_queue_item(path)
        if partition_prefix is not None and not partition_matches(str(item.get("partition", "")), partition_prefix):
            continue
        out.append((path, item))
    return out


def partition_matches(partition: str, prefix: str) -> bool:
    """Exact partition or nested prefix (Hex.Session.Battle/Type), fail-closed."""
    return partition == prefix or partition.startswith(prefix + "/")


def lease_active(item: dict[str, Any], *, now: datetime | None = None) -> bool:
    claim = item.get("claim") or {}
    holder = claim.get("holder")
    expires = parse_iso(claim.get("lease_expires_at"))
    if not holder or expires is None:
        return False
    current = now or utc_now()
    return expires > current


def claim_item(
    item: dict[str, Any],
    *,
    holder: str,
    role: str,
    lease_minutes: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or utc_now()
    claim = item.get("claim") or empty_claim()
    if lease_active(item, now=current):
        if claim.get("holder") != holder:
            raise SystemExit(
                f"FAIL: method_id {item['method_id']} is leased by {claim.get('holder')!r} "
                f"until {claim.get('lease_expires_at')}"
            )
        # Idempotent refresh for same holder.
    item = dict(item)
    item["claim"] = {
        "holder": holder,
        "role": role,
        "claimed_at": to_iso(current),
        "lease_expires_at": to_iso(current + timedelta(minutes=lease_minutes)),
    }
    item["updated_at"] = to_iso(current)
    return item


def release_item(item: dict[str, Any], *, holder: str, now: datetime | None = None) -> dict[str, Any]:
    current = now or utc_now()
    claim = item.get("claim") or empty_claim()
    if claim.get("holder") not in (None, holder):
        if lease_active(item, now=current):
            raise SystemExit(
                f"FAIL: cannot release {item['method_id']}: held by {claim.get('holder')!r}"
            )
    item = dict(item)
    item["claim"] = empty_claim()
    item["updated_at"] = to_iso(current)
    return item
