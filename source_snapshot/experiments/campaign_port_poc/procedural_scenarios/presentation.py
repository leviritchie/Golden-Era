"""Fail-closed bridge from optional flavor text to native presentation rows.

Mechanical compilation remains authoritative.  This module only appends one
Dialog action per flavored event and emits composable Core delta operations for
the dialog and its locale tokens.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from .events import (
    CounterAction,
    CounterTrigger,
    MechanicalEventSpec,
    compile_mechanical_events,
    mechanical_fingerprint,
)
from .text import (
    FlavorText,
    FlavorTextResult,
    FlavorTextValidationError,
    TextMode,
    validate_flavor_payload,
)


PRESENTATION_SCHEMA = "olden.procedural-scenario-presentation.v1"
_SAFE_MAP_SID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")

# These are explicit Core.zip folder contracts, not inferred locale paths.
_LOCALE_FOLDERS = {
    "en": "english",
    "en-us": "english",
    "en-gb": "english",
    "english": "english",
    "pt-br": "BRportugese",
    "cs": "czech",
    "cs-cz": "czech",
    "fr": "french",
    "fr-fr": "french",
    "de": "german",
    "de-de": "german",
    "hu": "hungarian",
    "hu-hu": "hungarian",
    "it": "italian",
    "it-it": "italian",
    "ja": "japanese",
    "ja-jp": "japanese",
    "ko": "korean",
    "ko-kr": "korean",
    "pl": "polish",
    "pl-pl": "polish",
    "ru": "russian",
    "ru-ru": "russian",
    "es": "spanish",
    "es-es": "spanish",
    "tr": "turkish",
    "tr-tr": "turkish",
    "uk": "ukrainian",
    "uk-ua": "ukrainian",
    "zh-cn": "zhCN",
    "zh-hans": "zhCN",
    "zh-tw": "zhTW",
    "zh-hant": "zhTW",
}


class PresentationError(ValueError):
    """Flavor presentation cannot be applied without violating its contract."""


@dataclass(frozen=True)
class PresentationResult:
    triggers: tuple[dict[str, Any], ...]
    core_deltas: tuple[dict[str, Any], ...]
    manifest_fragment: dict[str, Any]


def _locale_key(locale: str) -> str:
    if not isinstance(locale, str) or not locale or locale != locale.strip():
        raise PresentationError(f"unsupported presentation locale: {locale!r}")
    key = locale.replace("_", "-").lower()
    if key not in _LOCALE_FOLDERS:
        raise PresentationError(f"unsupported presentation locale: {locale!r}")
    return key


def _safe_map_sid(map_sid: str) -> str:
    if not isinstance(map_sid, str) or not _SAFE_MAP_SID_RE.fullmatch(map_sid):
        raise PresentationError(
            "map_sid must contain only ASCII letters, digits, underscores, and "
            f"hyphens and be at most 96 characters; got {map_sid!r}"
        )
    return map_sid


def _safe_member(member: str) -> str:
    path = PurePosixPath(member)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or path.suffix.lower() != ".json"
    ):
        raise PresentationError(f"unsafe presentation Core member: {member!r}")
    return path.as_posix()


def _validated_event_ids(
    events: Sequence[MechanicalEventSpec],
) -> tuple[str, ...]:
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        raise PresentationError("events must be a sequence of MechanicalEventSpec rows")
    if not events:
        raise PresentationError("presentation requires at least one mechanical event")
    if not all(isinstance(event, MechanicalEventSpec) for event in events):
        raise PresentationError("events must contain only MechanicalEventSpec rows")
    event_ids = tuple(event.event_id for event in events)
    duplicates = sorted(
        event_id for event_id in set(event_ids) if event_ids.count(event_id) > 1
    )
    if duplicates:
        raise PresentationError(f"duplicate mechanical event IDs: {duplicates}")
    return event_ids


def _validate_compiled_rows(
    compiled_triggers: Sequence[Mapping[str, Any]],
    *,
    events: Sequence[MechanicalEventSpec],
    event_ids: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    if not isinstance(compiled_triggers, Sequence) or isinstance(
        compiled_triggers, (str, bytes)
    ):
        raise PresentationError("compiled_triggers must be a sequence of mappings")

    rows: list[dict[str, Any]] = []
    actual_ids: list[str] = []
    for index, source_row in enumerate(compiled_triggers):
        if not isinstance(source_row, Mapping):
            raise PresentationError(f"compiled trigger {index} is not a mapping")
        row = dict(source_row)
        event_id = row.get("comment")
        if not isinstance(event_id, str) or not event_id:
            raise PresentationError(
                f"compiled trigger {index} has no mechanical event ID in comment"
            )
        conditions = row.get("conditions")
        actions = row.get("actions")
        if not isinstance(conditions, list) or not isinstance(actions, list):
            raise PresentationError(
                f"compiled trigger {event_id!r} requires conditions and actions lists"
            )
        for action_index, action in enumerate(actions):
            if not isinstance(action, Mapping):
                raise PresentationError(
                    f"compiled trigger {event_id!r} action {action_index} is not a mapping"
                )
            if action.get("a") in {"Dialog", "Print"}:
                raise PresentationError(
                    f"compiled trigger {event_id!r} already contains presentation action "
                    f"{action.get('a')!r}"
                )
        actual_ids.append(event_id)
        rows.append(row)

    duplicates = sorted(
        event_id for event_id in set(actual_ids) if actual_ids.count(event_id) > 1
    )
    if duplicates:
        raise PresentationError(f"duplicate compiled event IDs: {duplicates}")
    missing = sorted(set(event_ids) - set(actual_ids))
    extra = sorted(set(actual_ids) - set(event_ids))
    if missing or extra or len(actual_ids) != len(event_ids):
        raise PresentationError(
            f"compiled event IDs do not match mechanics; missing={missing}, extra={extra}"
        )

    declared_counters = {
        trigger.counter_sid
        for event in events
        for trigger in event.triggers
        if isinstance(trigger, CounterTrigger)
    }
    declared_counters.update(
        action.counter_sid
        for event in events
        for action in event.actions
        if isinstance(action, CounterAction)
    )
    expected_rows = compile_mechanical_events(
        events,
        declared_counter_sids=declared_counters,
        require_explicit_victory=False,
    )
    if tuple(rows) != expected_rows:
        raise PresentationError(
            "compiled trigger sequence does not match typed mechanics"
        )
    return tuple(rows)


def _content_sha256(items: Sequence[FlavorText]) -> str:
    payload = {"items": [item.to_dict() for item in items]}
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _provenance_cache_key(provenance: Any) -> str:
    identity = {
        "mechanicalFingerprint": provenance.mechanical_fingerprint,
        "providerId": provenance.provider_id,
        "model": provenance.model,
        "promptVersion": provenance.prompt_version,
        "locale": provenance.locale,
    }
    encoded = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_provenance_identity(provenance: Any) -> None:
    for field in ("provider_id", "model", "prompt_version"):
        value = getattr(provenance, field, None)
        if (
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
            or len(value) > 160
            or any(ord(char) < 32 for char in value)
        ):
            raise PresentationError(f"flavor provenance {field} is invalid")
    for field in ("mechanical_fingerprint", "cache_key", "content_sha256"):
        value = getattr(provenance, field, None)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise PresentationError(f"flavor provenance {field} is invalid")
    if not isinstance(getattr(provenance, "from_cache", None), bool):
        raise PresentationError("flavor provenance from_cache is invalid")


def _validated_flavor_items(
    flavor_result: FlavorTextResult,
    *,
    locale_key: str,
    events: Sequence[MechanicalEventSpec],
    event_ids: Sequence[str],
) -> tuple[FlavorText, ...]:
    if not isinstance(flavor_result, FlavorTextResult):
        raise PresentationError("flavor_result must be a FlavorTextResult")
    try:
        items = validate_flavor_payload(
            {"items": [item.to_dict() for item in flavor_result.items]},
            event_ids=event_ids,
        )
    except (AttributeError, FlavorTextValidationError) as exc:
        raise PresentationError(f"invalid flavor text: {exc}") from exc

    if not isinstance(flavor_result.mode, TextMode) or flavor_result.mode not in {
        TextMode.OPTIONAL,
        TextMode.REQUIRED,
    }:
        raise PresentationError(
            "nonempty flavor text requires optional or required text mode"
        )
    if flavor_result.error is not None:
        raise PresentationError("a failed flavor result cannot contain flavor items")
    provenance = flavor_result.provenance
    if provenance is None:
        raise PresentationError("nonempty flavor text requires provenance")
    _validate_provenance_identity(provenance)
    if _locale_key(provenance.locale) != locale_key:
        raise PresentationError(
            "flavor provenance locale does not match presentation locale"
        )
    expected_fingerprint = mechanical_fingerprint(events)
    if provenance.mechanical_fingerprint != expected_fingerprint:
        raise PresentationError(
            "flavor provenance mechanical fingerprint does not match events"
        )
    if provenance.content_sha256 != _content_sha256(items):
        raise PresentationError("flavor provenance content hash does not match items")
    if provenance.cache_key != _provenance_cache_key(provenance):
        raise PresentationError("flavor provenance cache key does not match identity")
    return items


def _textless_manifest(
    *,
    map_sid: str,
    locale: str,
    flavor_result: FlavorTextResult,
) -> dict[str, Any]:
    return {
        "presentation": {
            "schema": PRESENTATION_SCHEMA,
            "mapSid": map_sid,
            "locale": locale,
            "status": "textless",
            "dialogCount": 0,
            "eventBindings": [],
            "text": flavor_result.to_manifest_dict(),
        }
    }


def _binding(map_sid: str, event_id: str) -> dict[str, str]:
    digest = hashlib.sha256(
        f"{map_sid}\0{event_id}".encode("utf-8")
    ).hexdigest()[:24]
    dialog_sid = f"proc_dialog_{digest}"
    member = _safe_member(
        f"DB/dialogs/dialogs/custom_maps/{map_sid}/{dialog_sid}.json"
    )
    return {
        "eventId": event_id,
        "dialogSid": dialog_sid,
        "member": member,
        "titleSid": f"dialogue_title_{dialog_sid}",
        "bodySid": f"dialogue_text_{dialog_sid}_0",
    }


def _dialog_document(binding: Mapping[str, str]) -> dict[str, Any]:
    return {
        "array": [
            {
                "id": binding["dialogSid"],
                "localization": True,
                "slides": [
                    {
                        "id": "start",
                        "fon": "",
                        "avatars": [],
                        "title": {"sid": binding["titleSid"], "position": 3},
                        "text": binding["bodySid"],
                        "next": "ending",
                    },
                    {
                        "id": "ending",
                        "fon": "",
                        "text": "",
                        "invokeOnlyActions": True,
                        "end": True,
                    },
                ],
            }
        ]
    }


def apply_flavor_presentation(
    map_sid: str,
    locale: str,
    events: Sequence[MechanicalEventSpec],
    compiled_triggers: Sequence[Mapping[str, Any]],
    flavor_result: FlavorTextResult,
) -> PresentationResult:
    """Add presentation without rewriting any compiled mechanical field.

    Empty ``none`` results and explicit optional-provider failures remain
    textless and emit no Core operations.  All nonempty results must carry
    provenance for the same locale, mechanics fingerprint, and content.
    """

    safe_map_sid = _safe_map_sid(map_sid)
    locale_key = _locale_key(locale)
    event_ids = _validated_event_ids(events)
    rows = _validate_compiled_rows(
        compiled_triggers,
        events=events,
        event_ids=event_ids,
    )

    if not isinstance(flavor_result, FlavorTextResult):
        raise PresentationError("flavor_result must be a FlavorTextResult")
    if not flavor_result.items:
        valid_none = (
            flavor_result.mode is TextMode.NONE
            and flavor_result.error is None
            and flavor_result.provenance is None
        )
        valid_optional_failure = (
            flavor_result.mode is TextMode.OPTIONAL
            and isinstance(flavor_result.error, str)
            and bool(flavor_result.error)
            and flavor_result.provenance is None
        )
        if not (valid_none or valid_optional_failure):
            raise PresentationError("invalid textless FlavorTextResult state")
        return PresentationResult(
            triggers=copy.deepcopy(rows),
            core_deltas=(),
            manifest_fragment=_textless_manifest(
                map_sid=safe_map_sid,
                locale=locale,
                flavor_result=flavor_result,
            ),
        )

    items = _validated_flavor_items(
        flavor_result,
        locale_key=locale_key,
        events=events,
        event_ids=event_ids,
    )
    items_by_id = {item.event_id: item for item in items}
    bindings = tuple(_binding(safe_map_sid, event_id) for event_id in event_ids)
    bindings_by_id = {binding["eventId"]: binding for binding in bindings}
    if len({binding["dialogSid"] for binding in bindings}) != len(bindings):
        raise PresentationError("deterministic dialog SID collision")

    presented_rows: list[dict[str, Any]] = []
    for source_row in rows:
        row = copy.deepcopy(source_row)
        binding = bindings_by_id[row["comment"]]
        dialog_action = {
            "comment": "",
            "a": "Dialog",
            "p": [binding["dialogSid"]],
        }
        victory_index = next(
            (
                index
                for index, action in enumerate(row["actions"])
                if action.get("a") == "GameVictory"
            ),
            len(row["actions"]),
        )
        row["actions"].insert(victory_index, dialog_action)
        presented_rows.append(row)

    operations: list[dict[str, Any]] = []
    token_rows: list[dict[str, str]] = []
    for index, binding in enumerate(bindings):
        item = items_by_id[binding["eventId"]]
        operations.append(
            {
                "id": f"{safe_map_sid}:presentation:dialog:{index:04d}",
                "member": binding["member"],
                "operation": "create_json_member",
                "path": [],
                "value": _dialog_document(binding),
            }
        )
        token_rows.extend(
            (
                {"sid": binding["titleSid"], "text": item.title},
                {"sid": binding["bodySid"], "text": item.body},
            )
        )

    locale_member = _safe_member(
        f"Lang/{_LOCALE_FOLDERS[locale_key]}/texts/dialogues.json"
    )
    for section in ("tokens", "array"):
        operations.append(
            {
                "id": f"{safe_map_sid}:presentation:locale:{section}",
                "member": locale_member,
                "operation": "upsert_array",
                "path": [section],
                "key": "sid",
                "rows": copy.deepcopy(token_rows),
            }
        )

    manifest_fragment = {
        "presentation": {
            "schema": PRESENTATION_SCHEMA,
            "mapSid": safe_map_sid,
            "locale": locale,
            "localeMember": locale_member,
            "status": "generated",
            "dialogCount": len(bindings),
            "eventBindings": [dict(binding) for binding in bindings],
            "coreDeltaIds": [operation["id"] for operation in operations],
            "text": flavor_result.to_manifest_dict(),
        }
    }
    return PresentationResult(
        triggers=tuple(presented_rows),
        core_deltas=tuple(operations),
        manifest_fragment=manifest_fragment,
    )
