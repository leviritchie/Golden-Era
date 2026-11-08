#!/usr/bin/env python3
"""Campaign-only Olden heroes for H3 map-instance custom names (Tyranell, …).

Native Story maps reserve non-hireable identities via ``DB/heroes/campaign/*.json``
plus ``DB/data.json`` ``campaignHeroes``. HoMM3 ports need the same for bespoke
placed-hero names that are not stock roster identities — PropHero only stores
``heroSid``, so the display name must live on a real Core hero row.

Roster SIDs (``homm3_*_hero_*``) must never be listed in ``campaignHeroes``
(see ``validate_homm3_campaign_heroes_roster_separation_contract.py``).
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import h3m_hero_sid as hero_sid

SID_PREFIX = "h3_campaign_placed_"
CORE_HERO_MEMBER = "DB/heroes/campaign/{sid}.json"
DEFAULT_CORE_ZIP = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
    r"\HeroesOldenEra_Data\StreamingAssets\Core.zip"
)
DEFAULT_OVERLAY_ROOT = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "campaign_port_poc"
    / "h3_campaign_placed_heroes_overlay"
)


class CampaignPlacedHeroError(ValueError):
    """Fail-closed campaign placed-hero stub error."""


@dataclass(frozen=True)
class PlacedHeroStubSpec:
    display_name: str
    hero_type: int
    donor_sid: str
    sid: str


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug_for_display_name(name: str) -> str:
    text = " ".join(str(name or "").strip().lower().split())
    if not text:
        raise CampaignPlacedHeroError("empty display name for campaign placed hero slug")
    slug = _SLUG_RE.sub("_", text).strip("_")
    if not slug:
        raise CampaignPlacedHeroError(f"display name {name!r} produced empty slug")
    return slug


def sid_for_display_name(name: str) -> str:
    return f"{SID_PREFIX}{slug_for_display_name(name)}"


def is_campaign_placed_hero_sid(sid: str | None) -> bool:
    return isinstance(sid, str) and sid.startswith(SID_PREFIX)


def needs_campaign_placed_stub(name: str | None) -> bool:
    """True when a placed-object custom name is not a known roster/campaign SID."""
    text = str(name or "").strip()
    if not text:
        return False
    return hero_sid.h3_hero_name_to_hero_sid(text) is None


def resolve_placed_hero_sid(
    hero_type: int,
    *,
    name: str | None = None,
) -> tuple[str, str]:
    """Resolve OE SID for a placed hero, creating a campaign-stub SID when needed.

    Evidence tags:
    - ``h3m_hero_name_over_type`` / ``h3m_hero_name`` / ``h3_hero_type`` — stock path
    - ``h3_campaign_placed_custom_name`` — bespoke map name → campaign-only stub SID
    """
    text = str(name or "").strip()
    if text and needs_campaign_placed_stub(text):
        if hero_type == hero_sid.H3_RANDOM_OR_PLACEHOLDER_HERO_TYPE:
            raise CampaignPlacedHeroError(
                f"custom-named placeholder heroType 255 cannot become campaign stub ({text!r})"
            )
        # Validate donor type exists before emitting a stub SID.
        hero_sid.h3_hero_type_to_hero_sid(hero_type)
        return sid_for_display_name(text), "h3_campaign_placed_custom_name"
    return hero_sid.resolve_h3_hero_sid(hero_type, name=name)


def _unwrap_hero_row(raw: dict[str, Any] | list[Any]) -> dict[str, Any]:
    if isinstance(raw, dict) and isinstance(raw.get("array"), list) and raw["array"]:
        row = raw["array"][0]
        if isinstance(row, dict):
            return dict(row)
    if isinstance(raw, dict) and isinstance(raw.get("id"), str):
        return dict(raw)
    raise CampaignPlacedHeroError(f"unexpected hero JSON shape: {type(raw)!r}")


def _wrap_hero_row(row: dict[str, Any]) -> dict[str, Any]:
    return {"array": [row]}


def load_donor_hero_row(core_zip: Path, donor_sid: str) -> dict[str, Any]:
    # Faction folder is prefix before _hero_N: homm3_castle_hero_8 → homm3_castle
    parts = donor_sid.split("_hero_")
    if len(parts) != 2:
        raise CampaignPlacedHeroError(f"cannot derive faction folder from donor {donor_sid!r}")
    faction_folder = parts[0]
    member = f"DB/heroes/{faction_folder}/{donor_sid}.json"
    with zipfile.ZipFile(core_zip, "r") as zf:
        if member not in zf.namelist():
            raise CampaignPlacedHeroError(f"donor hero missing from Core: {member}")
        raw = json.loads(zf.read(member).decode("utf-8-sig"))
    return _unwrap_hero_row(raw)


def build_stub_spec(*, display_name: str, hero_type: int) -> PlacedHeroStubSpec:
    name = str(display_name).strip()
    if not name:
        raise CampaignPlacedHeroError("display_name required")
    if not needs_campaign_placed_stub(name):
        raise CampaignPlacedHeroError(
            f"{name!r} resolves to a roster/campaign SID; refuse campaign stub"
        )
    donor = hero_sid.h3_hero_type_to_hero_sid(int(hero_type))
    return PlacedHeroStubSpec(
        display_name=name,
        hero_type=int(hero_type),
        donor_sid=donor,
        sid=sid_for_display_name(name),
    )


def collect_stub_specs_from_object_walks(
    walk_paths: Iterable[Path],
) -> list[PlacedHeroStubSpec]:
    """Scan object_walk JSON for hasName heroes that need campaign stubs."""
    types_by_name: dict[str, set[int]] = {}
    for path in walk_paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for row in data.get("records") or []:
            if not isinstance(row, dict):
                continue
            if row.get("payloadKind") != "hero_or_prison":
                continue
            if row.get("hasName") is not True:
                continue
            name = str(row.get("name") or "").strip()
            hero_type = row.get("heroType")
            if not name or not isinstance(hero_type, int):
                continue
            if not needs_campaign_placed_stub(name):
                continue
            if hero_type == hero_sid.H3_RANDOM_OR_PLACEHOLDER_HERO_TYPE:
                raise CampaignPlacedHeroError(
                    f"{path}: custom-named hero {name!r} has heroType 255"
                )
            types_by_name.setdefault(name, set()).add(int(hero_type))

    by_sid: dict[str, PlacedHeroStubSpec] = {}
    conflicts: list[str] = []
    for name, types in sorted(types_by_name.items()):
        try:
            hero_type = _select_donor_hero_type(name, types)
            spec = build_stub_spec(display_name=name, hero_type=hero_type)
        except CampaignPlacedHeroError as exc:
            conflicts.append(str(exc))
            continue
        prior = by_sid.get(spec.sid)
        if prior is None:
            by_sid[spec.sid] = spec
            continue
        if prior.hero_type != spec.hero_type or prior.display_name != spec.display_name:
            conflicts.append(
                f"{spec.sid}: conflict {prior.display_name!r}/type{prior.hero_type} "
                f"vs {spec.display_name!r}/type{spec.hero_type}"
            )
    if conflicts:
        raise CampaignPlacedHeroError(
            "campaign placed hero stub conflicts:\n- " + "\n- ".join(conflicts)
        )
    return [by_sid[k] for k in sorted(by_sid)]


def _select_donor_hero_type(name: str, types: set[int]) -> int:
    """Pick one donor heroType when walks disagree.

    Bespoke names must not clone late campaign-unique slots (Catherine/Gelu/…)
    unless that is the only evidence — Gen. Kendal appears as both type 4 and
    type 144 (Catherine slot) across maps.
    """
    ordered = sorted(types)
    if len(ordered) == 1:
        return ordered[0]
    classic: list[int] = []
    unique_slot: list[int] = []
    for hero_type in ordered:
        sid = hero_sid.h3_hero_type_to_hero_sid(hero_type)
        # Slots 17+ are SoD/AB campaign personalities in our Homm3 rosters.
        slot_txt = sid.rsplit("_hero_", 1)[-1]
        try:
            slot = int(slot_txt)
        except ValueError:
            slot = 0
        if slot >= 17:
            unique_slot.append(hero_type)
        else:
            classic.append(hero_type)
    if len(classic) == 1:
        return classic[0]
    if len(classic) > 1:
        raise CampaignPlacedHeroError(
            f"{name!r} has conflicting classic heroTypes {sorted(classic)}"
        )
    if len(unique_slot) == 1:
        return unique_slot[0]
    raise CampaignPlacedHeroError(
        f"{name!r} has conflicting heroTypes {ordered} (no classic donor)"
    )


def _english_hero_info_by_sid(core_zip: Path) -> dict[str, str]:
    with zipfile.ZipFile(core_zip, "r") as zf:
        info = json.loads(zf.read("Lang/english/texts/heroInfo.json").decode("utf-8-sig"))
    return {
        str(row["sid"]): str(row.get("text") or "")
        for row in (info.get("array") or [])
        if isinstance(row, dict) and isinstance(row.get("sid"), str)
    }


def _donor_loc_text(info_by_sid: dict[str, str], donor: dict[str, Any], *, suffix: str) -> str:
    donor_token = donor.get(suffix if suffix != "description" else "description")
    if suffix == "motto":
        donor_token = donor.get("motto")
    if isinstance(donor_token, str) and donor_token in info_by_sid:
        return info_by_sid[donor_token]
    donor_id = str(donor.get("id") or "")
    for key in (f"{donor_id}_{suffix}", f"{donor_id}"):
        if key in info_by_sid and suffix == "description" and key == donor_id:
            return info_by_sid[key]
        if key in info_by_sid and key.endswith(f"_{suffix}"):
            return info_by_sid[key]
    return info_by_sid.get(f"{donor_id}_{suffix}", "")


def build_stub_hero_row(spec: PlacedHeroStubSpec, donor: dict[str, Any]) -> dict[str, Any]:
    row = dict(donor)
    row["id"] = spec.sid
    row["name"] = f"{spec.sid}_name"
    row["description"] = f"{spec.sid}_description"
    row["motto"] = f"{spec.sid}_motto"
    return row


def generate_overlay_members(
    specs: list[PlacedHeroStubSpec],
    *,
    core_zip: Path,
) -> dict[str, bytes]:
    """Build Core.zip overlay members for campaign stubs + English Loc merges."""
    if not specs:
        return {}
    members: dict[str, bytes] = {}
    hero_info_rows: list[dict[str, str]] = []
    heroes_rows: list[dict[str, str]] = []
    info_by_sid = _english_hero_info_by_sid(core_zip)
    for spec in specs:
        donor = load_donor_hero_row(core_zip, spec.donor_sid)
        row = build_stub_hero_row(spec, donor)
        member = CORE_HERO_MEMBER.format(sid=spec.sid)
        members[member] = (
            json.dumps(_wrap_hero_row(row), indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        name_rows = [
            {"sid": spec.sid, "text": spec.display_name},
            {"sid": f"{spec.sid}_name", "text": spec.display_name},
            {
                "sid": f"{spec.sid}_description",
                "text": _donor_loc_text(info_by_sid, donor, suffix="description"),
            },
            {
                "sid": f"{spec.sid}_motto",
                "text": _donor_loc_text(info_by_sid, donor, suffix="motto"),
            },
        ]
        hero_info_rows.extend(name_rows)
        heroes_rows.extend(name_rows[:2])

    catalog = {
        "policy": "h3_campaign_placed_custom_names_as_campaignHeroes",
        "stubs": [
            {
                "sid": s.sid,
                "displayName": s.display_name,
                "heroType": s.hero_type,
                "donorSid": s.donor_sid,
            }
            for s in specs
        ],
        "campaignHeroes": [s.sid for s in specs],
    }
    members["DB/h3_campaign_placed_heroes_catalog.json"] = (
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    members["Lang/english/texts/heroInfo.h3_campaign_placed.json"] = (
        json.dumps({"array": hero_info_rows}, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    members["Lang/english/texts/heroes.h3_campaign_placed.json"] = (
        json.dumps({"array": heroes_rows}, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    return members


def write_overlay_directory(
    specs: list[PlacedHeroStubSpec],
    *,
    core_zip: Path,
    out_root: Path,
) -> dict[str, Any]:
    out_root = Path(out_root)
    if out_root.exists():
        # Replace generated tree only.
        for path in sorted(out_root.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
    members = generate_overlay_members(specs, core_zip=core_zip)
    for rel, payload in members.items():
        dest = out_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
    manifest = {
        "overlayRoot": str(out_root),
        "memberCount": len(members),
        "stubCount": len(specs),
        "campaignHeroes": [s.sid for s in specs],
        "members": sorted(members),
    }
    (out_root / "overlay_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def merge_loc_array(existing: dict[str, Any], extra_rows: list[dict[str, str]]) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in (existing.get("array") or [])
        if isinstance(row, dict) and isinstance(row.get("sid"), str)
    ]
    by_sid = {str(row["sid"]): row for row in rows}
    for row in extra_rows:
        sid = str(row["sid"])
        by_sid[sid] = {"sid": sid, "text": str(row.get("text") or "")}
    return {"array": [by_sid[k] for k in sorted(by_sid)]}


def load_overlay_loc_rows(overlay_root: Path, relative: str) -> list[dict[str, str]]:
    path = Path(overlay_root) / relative
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("array") or []
    return [dict(r) for r in rows if isinstance(r, dict) and isinstance(r.get("sid"), str)]


def load_catalog_campaign_heroes(overlay_root: Path) -> list[str]:
    path = Path(overlay_root) / "DB" / "h3_campaign_placed_heroes_catalog.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [str(s) for s in (data.get("campaignHeroes") or []) if isinstance(s, str) and s]


def discover_default_object_walks(repo_root: Path | None = None) -> list[Path]:
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    base = root / "artifacts" / "campaign_port_poc"
    return sorted(base.rglob("*.object_walk.json"))


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Generate H3 campaign-placed hero Core overlay.")
    parser.add_argument("--core-zip", type=Path, default=DEFAULT_CORE_ZIP)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OVERLAY_ROOT)
    parser.add_argument(
        "--walks-root",
        type=Path,
        default=None,
        help="Optional root to scan for *.object_walk.json (default: artifacts/campaign_port_poc)",
    )
    args = parser.parse_args()
    walks = (
        sorted(args.walks_root.rglob("*.object_walk.json"))
        if args.walks_root
        else discover_default_object_walks()
    )
    if not walks:
        raise SystemExit("no object_walk.json files found")
    specs = collect_stub_specs_from_object_walks(walks)
    manifest = write_overlay_directory(specs, core_zip=args.core_zip, out_root=args.out_root)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
