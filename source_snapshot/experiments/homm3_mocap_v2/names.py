"""Joint-name embeddings must stay unique. Vendor auto_clean strips digits."""
from __future__ import annotations

import re
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence


def semantic_joint_names(path: Path, mesh: Path, raw_names: Sequence[str]) -> list[str]:
    """Require a complete, asset-pinned alias map; never mix missing aliases with ordinals."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    with mesh.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if str(payload.get("meshSha256", "")).lower() != digest:
        raise ValueError("semantic aliases are not pinned to this exact mesh")
    aliases = payload.get("aliases")
    if not isinstance(aliases, dict) or set(aliases) != set(raw_names):
        raise ValueError("semantic aliases must cover exactly every retained joint")
    if not all(isinstance(value, str) for value in aliases.values()):
        raise ValueError("semantic aliases must be text")
    names = [aliases[name].strip() for name in raw_names]
    assert_unique_names(names, raw_names=raw_names)
    return names


def vendor_auto_clean(name: str) -> str:
    """Copy of the vendor digit-stripping cleaner, for collapse detection only."""
    prefixes = ("mixamorig:", "mixamorig")
    cleaned = name
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    parts: list[str] = []
    for part in re.split(r"(?=[A-Z]|_)", cleaned):
        stem = re.sub(r"[\d_]+", "", part)
        if not stem:
            continue
        if stem in {"L", "l"}:
            parts.append("Left")
        elif stem in {"R", "r"}:
            parts.append("Right")
        else:
            parts.append(stem)
    return " ".join(parts) if parts else cleaned


def ordinal_readable_name(raw_name: str, index: int) -> str:
    stem = vendor_auto_clean(raw_name).strip() or "joint"
    return f"{stem} {index:03d}"


def readable_joint_names(
    raw_names: Sequence[str],
    *,
    role_by_bone: Mapping[str, str] | None = None,
) -> list[str]:
    names = [ordinal_readable_name(str(name), index) for index, name in enumerate(raw_names)]
    if role_by_bone:
        overlay = list(names)
        for bone_name, role in role_by_bone.items():
            if bone_name not in raw_names:
                raise ValueError(
                    f"role bone {bone_name!r} is not in the bind skeleton"
                )
            overlay[list(raw_names).index(bone_name)] = f"{role} {bone_name}"
        names = overlay
    assert_unique_names(names, raw_names=raw_names)
    return names


def assert_unique_names(names: Sequence[str], *, raw_names: Sequence[str]) -> None:
    seen: dict[str, str] = {}
    collapsed = [vendor_auto_clean(name) for name in raw_names]
    if len(set(collapsed)) < len(raw_names):
        # Expected for Bone_000-style SmartRigs. Ordinal names must still be unique.
        pass
    for raw, readable in zip(raw_names, names):
        key = readable.strip().lower()
        if not key:
            raise ValueError(f"empty readable joint name for {raw!r}")
        if key in seen:
            raise ValueError(
                f"readable joint names collided: {seen[key]!r} and {raw!r} both became {readable!r}"
            )
        seen[key] = raw


def refuse_vendor_collapse(raw_names: Sequence[str]) -> None:
    collapsed = [vendor_auto_clean(name) for name in raw_names]
    unique = set(collapsed)
    if len(unique) < len(raw_names):
        raise ValueError(
            "vendor auto_clean would collapse joint names "
            f"({len(raw_names)} bones -> {len(unique)} names); "
            "use ordinal_readable_name instead"
        )
