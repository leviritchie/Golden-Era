"""Load and index mono_deobf_semantic_map.json (fail-closed; never invent matches)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from olden_cs_recovery.paths import REPO_ROOT


@dataclass(frozen=True)
class RejectedCollision:
    mono_full: str
    deobf_full: str
    mono_simple: str
    deobf_simple: str
    reason: str


@dataclass
class TypeMatch:
    """Best map hit for a current (deobf) type name."""

    current_type_name: str
    mono_full: str | None
    mono_namespace: str | None
    mono_simple: str | None
    confidence: str | None
    score: float | None
    reasons: list[str] = field(default_factory=list)
    candidate: dict[str, Any] | None = None
    source: str = "rows"  # rows | focusRows | manualTypeAliases
    skip_reason: str | None = None


class MonoSemanticMap:
    def __init__(self, path: Path, data: dict[str, Any]):
        self.path = path
        self.data = data
        self.by_deobf: dict[str, list[dict[str, Any]]] = {}
        self.by_mono: dict[str, list[dict[str, Any]]] = {}
        self.manual_by_current: dict[str, dict[str, Any]] = {}
        self.rejected: list[RejectedCollision] = []
        self._index()

    def _index(self) -> None:
        for section in ("rows", "focusRows"):
            for row in self.data.get(section) or []:
                mono = row.get("mono") or {}
                mono_full = mono.get("full")
                for cand in row.get("candidates") or []:
                    packed = {
                        "section": section,
                        "mono": mono,
                        "candidate": cand,
                    }
                    deobf = cand.get("deobf") or {}
                    deobf_full = deobf.get("full")
                    if deobf_full:
                        self.by_deobf.setdefault(deobf_full, []).append(packed)
                    if mono_full:
                        self.by_mono.setdefault(mono_full, []).append(packed)

        for alias in self.data.get("manualTypeAliases") or []:
            current = alias.get("current")
            if current:
                self.manual_by_current[str(current)] = alias

        for row in self.data.get("rejectedSimpleNameCollisions") or []:
            mono = row.get("mono") or {}
            deobf = row.get("deobf") or {}
            mono_full = str(mono.get("full") or "")
            deobf_full = str(deobf.get("full") or "")
            if not mono_full or not deobf_full:
                continue
            self.rejected.append(
                RejectedCollision(
                    mono_full=mono_full,
                    deobf_full=deobf_full,
                    mono_simple=str(mono.get("name") or mono_full.rsplit(".", 1)[-1]),
                    deobf_simple=str(deobf.get("name") or deobf_full.rsplit(".", 1)[-1]),
                    reason=str(row.get("reason") or "rejected simple-name collision"),
                )
            )

    def lookup_type(self, current_type_name: str) -> TypeMatch:
        """
        Look up current DiffableCs / recovered type name.

        Never invents a Mono match. Missing map → skip_reason set, empty proposal.
        """
        name = (current_type_name or "").strip()
        if not name:
            return TypeMatch(
                current_type_name=name,
                mono_full=None,
                mono_namespace=None,
                mono_simple=None,
                confidence=None,
                score=None,
                skip_reason="empty type_name; cannot look up Mono semantic map",
            )

        packed_list = self.by_deobf.get(name) or self.by_mono.get(name) or []
        if packed_list:
            best = _best_packed(packed_list)
            mono = best["mono"]
            cand = best["candidate"]
            return TypeMatch(
                current_type_name=name,
                mono_full=mono.get("full"),
                mono_namespace=mono.get("namespace"),
                mono_simple=mono.get("name"),
                confidence=cand.get("confidence"),
                score=cand.get("score"),
                reasons=[str(r) for r in (cand.get("reasons") or [])],
                candidate=cand,
                source=str(best.get("section") or "rows"),
            )

        alias = self.manual_by_current.get(name)
        if alias is not None:
            mono_full = str(alias.get("mono") or "")
            simple = mono_full.rsplit(".", 1)[-1] if mono_full else None
            ns = mono_full.rsplit(".", 1)[0] if mono_full and "." in mono_full else ""
            return TypeMatch(
                current_type_name=name,
                mono_full=mono_full or None,
                mono_namespace=ns,
                mono_simple=simple,
                confidence=alias.get("confidence"),
                score=None,
                reasons=[str(e) for e in (alias.get("evidence") or [])],
                candidate={
                    "confidence": alias.get("confidence"),
                    "reasons": list(alias.get("evidence") or []),
                    "deobf": {"full": name, "name": name.rsplit(".", 1)[-1]},
                    "manual": True,
                    "doc": alias.get("doc"),
                },
                source="manualTypeAliases",
            )

        return TypeMatch(
            current_type_name=name,
            mono_full=None,
            mono_namespace=None,
            mono_simple=None,
            confidence=None,
            score=None,
            skip_reason=(
                f"No Mono semantic-map row for type {name!r} "
                f"(checked rows/focusRows/manualTypeAliases in {self.path.as_posix()}). "
                "Fail closed: empty proposal."
            ),
        )

    def is_rejected_pair(self, *, mono_full: str, deobf_full: str) -> RejectedCollision | None:
        for row in self.rejected:
            if row.mono_full == mono_full and row.deobf_full == deobf_full:
                return row
        return None

    def rejected_for_simple_name(self, simple_name: str) -> list[RejectedCollision]:
        return [r for r in self.rejected if r.mono_simple == simple_name or r.deobf_simple == simple_name]


def _best_packed(packed_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Prefer strong-static, then highest score. Fail closed on empty list."""
    if not packed_list:
        raise RuntimeError("internal: _best_packed on empty list")
    rank = {
        "strong-static": 0,
        "probable-static": 1,
        "candidate": 2,
        "weak-candidate": 3,
        "missing-side": 4,
    }

    def key(p: dict[str, Any]) -> tuple[int, float]:
        cand = p.get("candidate") or {}
        conf = str(cand.get("confidence") or "missing-side")
        score = float(cand.get("score") or 0.0)
        return (rank.get(conf, 99), -score)

    return sorted(packed_list, key=key)[0]


def resolve_mono_map_path() -> Path:
    """Resolve pinned path from input_manifest; fail closed if missing."""
    manifest_path = REPO_ROOT / "experiments" / "olden_cs_recovery" / "input_manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"FAIL: missing input_manifest.json at {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    for entry in manifest.get("inputs") or []:
        if entry.get("id") == "mono_deobf_semantic_map":
            rel = entry.get("path")
            if not rel:
                raise SystemExit("FAIL: mono_deobf_semantic_map entry missing path")
            path = Path(rel)
            if not path.is_absolute():
                path = REPO_ROOT / path
            if not path.is_file():
                raise SystemExit(
                    f"FAIL: mono_deobf_semantic_map missing at {path}. "
                    "Do not invent Mono matches."
                )
            return path
    raise SystemExit("FAIL: input_manifest.json has no mono_deobf_semantic_map input")


def load_mono_map(path: Path | None = None) -> MonoSemanticMap:
    target = path or resolve_mono_map_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FAIL: cannot load mono semantic map {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"FAIL: mono semantic map root must be object: {target}")
    if "rows" not in data and "manualTypeAliases" not in data:
        raise SystemExit(f"FAIL: mono semantic map missing rows/manualTypeAliases: {target}")
    return MonoSemanticMap(target, data)
