"""Retain-base merge for single-scenario / raw-translation Core overlay members.

The homecoming raw-translation installer and the brine_bell / emberwatch_signal /
floodgate_gambit / event_runtime_probe installers used to write each overlay member over
the Core's copy whole. Their overlays are snapshots taken from an earlier Core, so a whole
replace silently deleted every row the Core had gained since the snapshot: rows added by
earlier layers (the release overlay's ``homm3_custom_town_buildings_construction`` siege-wall
preset), rows added by a newer vanilla build (new ``customMaps`` template names, new
``quickStart`` templates), and sibling scenarios' ``quickStart`` entries.

``merge_overlay_member`` keeps the overlay's document exactly as authored and only appends
the base rows it does not name. When the base has no such rows the overlay bytes are
returned verbatim, so an install onto a Core that the snapshot already covers is byte-for-byte
what the old whole replace produced. Overlay rows still win per key; a snapshot that carries
a vanilla row therefore still pins it (that is a snapshot-content problem, not a merge one).

Supported shapes (anything else fails closed):
  * ``DB/quickStart.json``: every list-valued key is unioned (overlay order, then base extras).
  * Lang sid catalogs ``{"tokens":[{"sid",...}], "array":[...]}``: per section, by ``sid``.
  * id-array catalogs ``{"array":[{"id",...}]}``: by ``id``. Base ``homm3_xfp_*`` rows in
    ``DB/objects_logic/`` and ``homecoming_exact_footprint_objects.json`` are not retained,
    matching the continuity weave's ``drop_unreferenced_base_xfp`` retirement rule.

``rebase_overlay_member`` is the snapshot-content fix for a vanilla patch: given the old and
the new vanilla bytes of a member, it looks only at the rows the patch changed: it drops
overlay rows that only restate the old vanilla row and 3-way merges the rest (base = old vanilla, ours = overlay, theirs = new vanilla), so
the retain-base merge above lets the new vanilla rows through. Field conflicts fail closed.
tools/port_current/rebase_core_overlays.py drives it over the campaign/scenario overlays.

Proof tier: source/static; exercised on generated Cores by tools/port_current (generated
artifact at most).
"""
from __future__ import annotations

import json
from typing import Any

QUICKSTART_MEMBER = "DB/quickStart.json"
LANG_SECTIONS = ("tokens", "array")


class OverlayMergeError(ValueError):
    pass


def _load(raw: bytes, member: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OverlayMergeError(f"{member}: not JSON ({exc})") from exc


def _dump(doc: Any) -> bytes:
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _keyed_rows(doc: Any, section: str, key: str) -> list[dict[str, Any]] | None:
    rows = doc.get(section) if isinstance(doc, dict) else None
    if rows is None:
        return None
    if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get(key), str) for r in rows):
        return None
    return rows


def _retire_base_row(member: str, row_id: str) -> bool:
    if not row_id.startswith("homm3_xfp_"):
        return False
    return member.startswith("DB/objects_logic/") or member.endswith(
        "DB/map/objects/homecoming_exact_footprint_objects.json"
    )


def merge_quickstart(base: bytes, overlay: bytes, *, member: str = QUICKSTART_MEMBER) -> bytes:
    b, o = _load(base, member), _load(overlay, member)
    if not isinstance(b, dict) or not isinstance(o, dict):
        raise OverlayMergeError(f"{member}: quickStart must be a JSON object")
    added = False
    for key, base_value in b.items():
        if key not in o:
            o[key] = base_value
            added = True
            continue
        if isinstance(base_value, list) and isinstance(o[key], list):
            extra = [v for v in base_value if v not in o[key]]
            if extra:
                o[key] = list(o[key]) + extra
                added = True
    return _dump(o) if added else overlay


def merge_lang(base: bytes, overlay: bytes, *, member: str) -> bytes:
    b, o = _load(base, member), _load(overlay, member)
    if not isinstance(b, dict) or not isinstance(o, dict):
        raise OverlayMergeError(f"{member}: Lang catalog must be a JSON object")
    added = False
    for section in LANG_SECTIONS:
        brows = _keyed_rows(b, section, "sid")
        orows = _keyed_rows(o, section, "sid")
        if section in b and brows is None:
            raise OverlayMergeError(f"{member}: base {section} is not a sid-row list")
        if section in o and orows is None:
            raise OverlayMergeError(f"{member}: overlay {section} is not a sid-row list")
        if not brows:
            continue
        have = {r["sid"] for r in (orows or [])}
        extra = [r for r in brows if r["sid"] not in have]
        if extra:
            o[section] = list(orows or []) + extra
            added = True
    return _dump(o) if added else overlay


def merge_id_array(base: bytes, overlay: bytes, *, member: str) -> bytes:
    b, o = _load(base, member), _load(overlay, member)
    brows = _keyed_rows(b, "array", "id")
    orows = _keyed_rows(o, "array", "id")
    if brows is None or orows is None:
        raise OverlayMergeError(f"{member}: not an id-array catalog on both sides")
    have = {r["id"] for r in orows}
    extra = [r for r in brows if r["id"] not in have and not _retire_base_row(member, r["id"])]
    if not extra:
        return overlay
    o["array"] = list(orows) + extra
    return _dump(o)


def _is_lang_catalog(doc: Any) -> bool:
    return isinstance(doc, dict) and any(k in doc for k in LANG_SECTIONS) and all(
        _keyed_rows(doc, k, "sid") is not None for k in LANG_SECTIONS if k in doc
    )


def merge_overlay_member(member: str, base: bytes | None, overlay: bytes) -> bytes:
    """Return the bytes to write for ``member``; see module docstring. Fails closed."""
    if base is None or base == overlay:
        return overlay
    if member == QUICKSTART_MEMBER:
        return merge_quickstart(base, overlay, member=member)
    if not member.endswith(".json"):
        raise OverlayMergeError(f"{member}: no merge rule for a non-JSON overlay member")
    odoc = _load(overlay, member)
    if member.startswith("Lang/") and _is_lang_catalog(odoc):
        return merge_lang(base, overlay, member=member)
    if _keyed_rows(odoc, "array", "id") is not None:
        return merge_id_array(base, overlay, member=member)
    raise OverlayMergeError(f"{member}: overlay is neither quickStart, a Lang sid catalog nor an id-array catalog")


# --- vanilla-patch rebase of overlay snapshots -------------------------------------------
#
# Overlay rows are read as field patches over the vanilla row. A field the overlay row does
# not carry is a snapshot omission (the snapshot predates the field, or its serializer dropped
# it), never a deletion: the merged row takes the vanilla value. That is what keeps
# ``applyMultipleInteraction`` on the vanilla barracks rows, which every campaign snapshot
# lacks. JSON values compare strictly (``True`` != ``1``, ``1`` != ``1.0``); lists are atoms.

RESOLVE_CHOICES = ("theirs", "ours")


class OverlayRebaseConflict(OverlayMergeError):
    def __init__(self, member: str, conflicts: list[str]):
        self.member = member
        self.conflicts = conflicts
        super().__init__(f"{member}: {len(conflicts)} rebase conflict(s): " + "; ".join(conflicts[:5]))


class _FieldConflict(Exception):
    pass


_ABSENT: Any = object()


def same_json(a: Any, b: Any) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same_json(v, b[k]) for k, v in a.items())
    if isinstance(a, list):
        return len(a) == len(b) and all(same_json(x, y) for x, y in zip(a, b))
    return a == b


def _short(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= 80 else text[:77] + "..."


def three_way_value(base: Any, ours: Any, theirs: Any, path: str) -> Any:
    """Merge one JSON value (base = old vanilla, theirs = new vanilla). Raises _FieldConflict."""
    if isinstance(base, dict) and isinstance(ours, dict) and isinstance(theirs, dict):
        out: dict[str, Any] = {}
        for key in list(theirs) + [k for k in ours if k not in theirs]:
            o = ours.get(key, _ABSENT)
            t = theirs.get(key, _ABSENT)
            b = base.get(key, _ABSENT)
            sub = f"{path}.{key}"
            if o is _ABSENT:
                value = t  # snapshot omission: take vanilla
            elif b is _ABSENT:
                if t is not _ABSENT and not same_json(o, t):
                    raise _FieldConflict(f"{sub} added by vanilla and overlay with different values")
                value = o
            elif t is _ABSENT:
                if not same_json(o, b):
                    raise _FieldConflict(f"{sub} removed by vanilla but changed by overlay")
                value = _ABSENT
            else:
                value = three_way_value(b, o, t, sub)
            if value is not _ABSENT:
                out[key] = value
        return out
    if same_json(ours, base):
        return theirs
    if same_json(theirs, base) or same_json(ours, theirs):
        return ours
    raise _FieldConflict(f"{path} changed by both (old={_short(base)} overlay={_short(ours)} new={_short(theirs)})")


def _render_like(doc: Any, like: bytes) -> bytes:
    """Dump ``doc`` keeping the indent unit, BOM and newline style of the original bytes."""
    bom = like.startswith(b"\xef\xbb\xbf")
    body = like[3:] if bom else like
    newline = "\r\n" if b"\r\n" in body else "\n"
    indent: str | int = 2
    first_break = body.find(b"\n")
    if first_break >= 0:
        line = body[first_break + 1 :].split(b"\n", 1)[0]
        if line.startswith(b"\t"):
            indent = "\t"
        else:
            indent = (len(line) - len(line.lstrip(b" "))) or 2
    text = json.dumps(doc, indent=indent, ensure_ascii=False)
    if newline != "\n":
        text = text.replace("\n", newline)
    if body.rstrip(b" ").endswith(b"\n"):
        text += newline
    out = text.encode("utf-8")
    return (b"\xef\xbb\xbf" + out) if bom else out


def rebase_row_layout(member: str) -> tuple[tuple[str, ...], str]:
    """(sections, row key) of a rebasable member: Lang sid catalogs or id-array catalogs."""
    return (LANG_SECTIONS, "sid") if member.startswith("Lang/") else (("array",), "id")


def _index_rows(doc: Any, sections: tuple[str, ...], key: str, member: str, side: str) -> dict[tuple[str, str], Any]:
    if not isinstance(doc, dict):
        raise OverlayMergeError(f"{member}: {side} is not a JSON object")
    out: dict[tuple[str, str], Any] = {}
    for section in sections:
        if section not in doc:
            continue
        rows = _keyed_rows(doc, section, key)
        if rows is None:
            raise OverlayMergeError(f"{member}: {side} {section} is not a {key}-row list")
        for row in rows:
            rk = (section, row[key])
            if rk in out:
                raise OverlayMergeError(f"{member}: {side} has duplicate {key} {row[key]!r} in {section}")
            out[rk] = row
    if not out and not any(s in doc for s in sections):
        raise OverlayMergeError(f"{member}: {side} has none of the sections {sections}")
    return out


def rebase_overlay_member(
    member: str,
    old_vanilla: bytes,
    new_vanilla: bytes,
    overlay: bytes,
    *,
    resolutions: dict[str, str] | None = None,
) -> tuple[bytes | None, dict[str, Any]]:
    """Rebase one overlay member from the old vanilla build onto the new one.

    Per keyed row (``id`` for id-array catalogs, ``sid`` per section for Lang catalogs):
      * row in neither vanilla build (GE-owned) or identical in both builds: kept verbatim, so
        the rebase only touches what the patch changed and a re-run against the next patch
        picks up the rows that patch changes;
      * otherwise merged = 3-way(old, overlay, new). A merged row equal to the new vanilla row
        is dropped (the retain-base install merge supplies it); anything else replaces the
        overlay row in place;
      * vanilla removed the row: dropped when the overlay only restated it, else a conflict;
      * vanilla added a row key the overlay also carries: dropped when equal, else a conflict.
    ``resolutions`` maps a vanilla row key to ``"theirs"`` (take the new vanilla row) or
    ``"ours"`` (keep the overlay row verbatim) where a recorded decision overrides the merge,
    for a conflict or for snapshot-era content the merge cannot tell from a GE edit;
    ``stats["resolutionsUsed"]`` lists the entries that matched (the caller rejects entries no
    overlay matched). Returns (new bytes, or None when nothing changed; stats). ``dropped``
    counts every row removed, resolved ones included.
    Raises OverlayRebaseConflict listing every unresolved conflict in the member.
    """
    resolutions = dict(resolutions or {})
    for row_key, choice in resolutions.items():
        if choice not in RESOLVE_CHOICES:
            raise OverlayMergeError(f"{member}: resolution for {row_key!r} must be one of {RESOLVE_CHOICES}")
    sections, key = rebase_row_layout(member)
    old_rows = _index_rows(_load(old_vanilla, member), sections, key, member, "old vanilla")
    new_rows = _index_rows(_load(new_vanilla, member), sections, key, member, "new vanilla")
    ov_doc = _load(overlay, member)
    _index_rows(ov_doc, sections, key, member, "overlay")  # shape + duplicate check
    stats: dict[str, Any] = {"kept": 0, "dropped": 0, "merged": 0, "resolvedTheirs": 0, "resolvedOurs": 0}
    conflicts: list[str] = []
    used: set[str] = set()
    for section in sections:
        if section not in ov_doc:
            continue
        out_rows: list[Any] = []
        for row in ov_doc[section]:
            rk = (section, row[key])
            b = old_rows.get(rk, _ABSENT)
            t = new_rows.get(rk, _ABSENT)
            choice = resolutions.get(row[key])
            if (b is _ABSENT and t is _ABSENT) or (choice is None and same_json(b, t)):
                # GE-owned row, or a row this patch did not touch: not this rebase's business.
                stats["kept"] += 1
                out_rows.append(row)
                continue
            if choice == "ours":
                used.add(row[key])
                stats["resolvedOurs"] += 1
                out_rows.append(row)
                continue
            if choice == "theirs":
                used.add(row[key])
                stats["resolvedTheirs"] += 1
                merged = t
            else:
                try:
                    if b is _ABSENT:
                        if not same_json(row, t):
                            raise _FieldConflict("row added by vanilla and by the overlay with different values")
                        merged = t
                    elif t is _ABSENT:
                        if not same_json(three_way_value(b, row, b, row[key]), b):
                            raise _FieldConflict("row removed by vanilla but changed by the overlay")
                        merged = _ABSENT
                    else:
                        merged = three_way_value(b, row, t, row[key])
                except _FieldConflict as exc:
                    conflicts.append(f"{section}[{row[key]}]: {exc}")
                    out_rows.append(row)
                    continue
            if merged is _ABSENT or same_json(merged, t):
                stats["dropped"] += 1
                continue
            if same_json(merged, row):
                stats["kept"] += 1
                out_rows.append(row)
            else:
                stats["merged"] += 1
                out_rows.append(merged)
        ov_doc[section] = out_rows
    if conflicts:
        raise OverlayRebaseConflict(member, conflicts)
    stats["resolutionsUsed"] = sorted(used)
    if not (stats["dropped"] or stats["merged"]):
        return None, stats
    return _render_like(ov_doc, overlay), stats


def overlay_vanilla_pins(
    member: str,
    old_vanilla: bytes,
    new_vanilla: bytes,
    overlay: bytes,
    *,
    keep_ours: tuple[str, ...] = (),
) -> list[str]:
    """Rows of ``overlay`` that still pin vanilla rows the old -> new patch changed.

    A pin is a row the rebase would still drop (it restates vanilla) or merge (it pins a field
    vanilla changed), or one it cannot rebase (conflict); empty once the member is rebased.
    ``keep_ours`` names rows a recorded ``"ours"`` decision keeps. Used by
    tools/validate_core_overlay_no_vanilla_pin.py.
    """
    sections, key = rebase_row_layout(member)
    ov_rows = _index_rows(_load(overlay, member), sections, key, member, "overlay")
    present = {rk[1] for rk in ov_rows}
    resolutions = {k: "ours" for k in keep_ours if k in present}
    try:
        rebased, _ = rebase_overlay_member(member, old_vanilla, new_vanilla, overlay, resolutions=resolutions)
    except OverlayRebaseConflict as exc:
        return list(exc.conflicts)
    if rebased is None:
        return []
    out_rows = _index_rows(_load(rebased, member), sections, key, member, "rebased overlay")
    return [
        f"{rk[0]}[{rk[1]}]: " + ("restates vanilla" if rk not in out_rows else "pins a field vanilla changed")
        for rk, row in ov_rows.items()
        if rk not in out_rows or not same_json(row, out_rows[rk])
    ]
