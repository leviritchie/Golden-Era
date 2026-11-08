"""Optional, presentation-only flavor text for procedural scenarios."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .events import MechanicalEventSpec, mechanical_fingerprint


TEXT_PROMPT_VERSION = "procedural-flavor.v1"
MAX_TITLE_LENGTH = 80
MAX_BODY_LENGTH = 800
MAX_HTTP_RESPONSE_BYTES = 1_000_000
_MARKUP_RE = re.compile(
    r"(?:<[^>\r\n]+>|```|!\[[^\]]*\]\([^)]*\)|\[[^\]]+\]\([^)]*\)|"
    r"^\s{0,3}(?:#{1,6}\s|[-*+]\s))",
    re.MULTILINE,
)


class TextMode(str, Enum):
    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


class FlavorTextError(ValueError):
    """Base error for text policy, transport, cache, or schema failures."""


class FlavorTextValidationError(FlavorTextError):
    pass


class TextProviderError(FlavorTextError):
    pass


class TextPolicyError(FlavorTextError):
    pass


@dataclass(frozen=True)
class FlavorText:
    """Presentation fields for one immutable mechanical event ID."""

    event_id: str
    title: str
    body: str

    def to_dict(self) -> dict[str, str]:
        return {"eventId": self.event_id, "title": self.title, "body": self.body}


@dataclass(frozen=True)
class TextRequest:
    locale: str
    mechanical_fingerprint: str
    events: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "locale": self.locale,
            "mechanicalFingerprint": self.mechanical_fingerprint,
            "events": list(self.events),
        }


@runtime_checkable
class TextProvider(Protocol):
    provider_id: str
    model: str
    prompt_version: str

    def generate(self, request: TextRequest) -> Mapping[str, Any]:
        """Return ``{"items": [{eventId, title, body}, ...]}``."""


@dataclass(frozen=True)
class NoneTextProvider:
    provider_id: str = "none"
    model: str = "none"
    prompt_version: str = TEXT_PROMPT_VERSION

    def generate(self, request: TextRequest) -> Mapping[str, Any]:
        return {"items": []}


@dataclass(frozen=True)
class TextProvenance:
    provider_id: str
    model: str
    prompt_version: str
    locale: str
    mechanical_fingerprint: str
    cache_key: str
    content_sha256: str
    from_cache: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "providerId": self.provider_id,
            "model": self.model,
            "promptVersion": self.prompt_version,
            "locale": self.locale,
            "mechanicalFingerprint": self.mechanical_fingerprint,
            "cacheKey": self.cache_key,
            "contentSha256": self.content_sha256,
            "fromCache": self.from_cache,
        }


@dataclass(frozen=True)
class FlavorTextResult:
    mode: TextMode
    items: tuple[FlavorText, ...] = ()
    provenance: TextProvenance | None = None
    error: str | None = None

    @property
    def textless(self) -> bool:
        return not self.items

    def to_manifest_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "status": (
                "disabled"
                if self.mode is TextMode.NONE
                else "failed_textless"
                if self.error
                else "generated"
            ),
            "items": [item.to_dict() for item in self.items],
            "provenance": (
                None if self.provenance is None else self.provenance.to_dict()
            ),
            "error": self.error,
        }


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _content_hash(items: Sequence[FlavorText]) -> str:
    return hashlib.sha256(
        _canonical_bytes({"items": [item.to_dict() for item in items]})
    ).hexdigest()


def text_cache_key(
    *,
    mechanical_fingerprint_value: str,
    provider: TextProvider,
    locale: str,
) -> str:
    identity = {
        "mechanicalFingerprint": mechanical_fingerprint_value,
        "providerId": provider.provider_id,
        "model": provider.model,
        "promptVersion": provider.prompt_version,
        "locale": locale,
    }
    return hashlib.sha256(_canonical_bytes(identity)).hexdigest()


class FlavorTextCache:
    """Small content-addressed JSON cache with validated readback."""

    def __init__(self, directory: Path | str):
        self.directory = Path(directory)

    def _path(self, key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise FlavorTextError(f"invalid text cache key: {key!r}")
        return self.directory / f"{key}.json"

    def get(self, key: str) -> Mapping[str, Any] | None:
        path = self._path(key)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FlavorTextError(f"invalid flavor-text cache entry {path}: {exc}") from exc
        if not isinstance(value, dict) or set(value) != {"cacheKey", "payload"}:
            raise FlavorTextError(f"invalid flavor-text cache envelope: {path}")
        if value["cacheKey"] != key or not isinstance(value["payload"], dict):
            raise FlavorTextError(f"flavor-text cache identity mismatch: {path}")
        return value["payload"]

    def put(self, key: str, payload: Mapping[str, Any]) -> None:
        path = self._path(key)
        self.directory.mkdir(parents=True, exist_ok=True)
        envelope = {"cacheKey": key, "payload": dict(payload)}
        temp = path.with_suffix(".tmp")
        try:
            temp.write_text(
                json.dumps(envelope, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temp.replace(path)
        except OSError as exc:
            raise FlavorTextError(f"could not write flavor-text cache {path}: {exc}") from exc


def _request_for(
    events: Sequence[MechanicalEventSpec],
    *,
    locale: str,
) -> TextRequest:
    if not isinstance(locale, str) or not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", locale):
        raise TextPolicyError(f"invalid locale: {locale!r}")
    fingerprint = mechanical_fingerprint(events)
    return TextRequest(
        locale=locale,
        mechanical_fingerprint=fingerprint,
        events=tuple(event.to_dict() for event in events),
    )


def _validate_text_field(value: Any, *, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise FlavorTextValidationError(f"{field} must be a string")
    if not value.strip():
        raise FlavorTextValidationError(f"{field} must be non-empty")
    if len(value) > max_length:
        raise FlavorTextValidationError(
            f"{field} exceeds {max_length} characters"
        )
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise FlavorTextValidationError(f"{field} contains control characters")
    if _MARKUP_RE.search(value):
        raise FlavorTextValidationError(f"{field} contains disallowed markup")
    return value


def validate_flavor_payload(
    payload: Mapping[str, Any],
    *,
    event_ids: Sequence[str],
) -> tuple[FlavorText, ...]:
    """Validate presentation-only output and pin every mechanical event ID."""

    if not isinstance(payload, Mapping) or set(payload) != {"items"}:
        raise FlavorTextValidationError("flavor payload must contain only 'items'")
    rows = payload["items"]
    if not isinstance(rows, list):
        raise FlavorTextValidationError("flavor payload 'items' must be a list")

    expected = tuple(event_ids)
    if len(set(expected)) != len(expected):
        raise FlavorTextValidationError("mechanical event IDs are not unique")
    items: list[FlavorText] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != {"eventId", "title", "body"}:
            raise FlavorTextValidationError(
                f"flavor item {index} must contain only eventId, title, and body"
            )
        event_id = row["eventId"]
        if not isinstance(event_id, str):
            raise FlavorTextValidationError(f"flavor item {index} eventId must be a string")
        items.append(
            FlavorText(
                event_id=event_id,
                title=_validate_text_field(
                    row["title"],
                    field=f"{event_id} title",
                    max_length=MAX_TITLE_LENGTH,
                ),
                body=_validate_text_field(
                    row["body"],
                    field=f"{event_id} body",
                    max_length=MAX_BODY_LENGTH,
                ),
            )
        )

    actual = tuple(item.event_id for item in items)
    if len(set(actual)) != len(actual):
        raise FlavorTextValidationError("flavor response contains duplicate event IDs")
    if set(actual) != set(expected) or len(actual) != len(expected):
        raise FlavorTextValidationError(
            f"flavor response event IDs must exactly match mechanics; "
            f"expected {list(expected)}, got {list(actual)}"
        )
    by_id = {item.event_id: item for item in items}
    return tuple(by_id[event_id] for event_id in expected)


class OpenAICompatibleTextProvider:
    """Chat-completions structured-output provider using only the stdlib."""

    provider_id = "openai-compatible"

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        prompt_version: str = TEXT_PROMPT_VERSION,
    ):
        if not endpoint.startswith(("https://", "http://")):
            raise ValueError("text-provider endpoint must be an HTTP(S) URL")
        if not model.strip():
            raise ValueError("text-provider model must be non-empty")
        if timeout_seconds <= 0:
            raise ValueError("text-provider timeout_seconds must be positive")
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.prompt_version = prompt_version

    @staticmethod
    def _response_schema(event_ids: Sequence[str]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["items"],
            "properties": {
                "items": {
                    "type": "array",
                    "minItems": len(event_ids),
                    "maxItems": len(event_ids),
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["eventId", "title", "body"],
                        "properties": {
                            "eventId": {"type": "string", "enum": list(event_ids)},
                            "title": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": MAX_TITLE_LENGTH,
                            },
                            "body": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": MAX_BODY_LENGTH,
                            },
                        },
                    },
                }
            },
        }

    def generate(self, request: TextRequest) -> Mapping[str, Any]:
        event_ids = [str(event["eventId"]) for event in request.events]
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Write concise plain-text fantasy flavor for immutable game "
                        "mechanics. Return every supplied eventId exactly once. Never "
                        "add, remove, rename, or reinterpret mechanics, IDs, objectives, "
                        "rewards, factions, or victory conditions. Do not use markup."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(request.to_dict(), ensure_ascii=False),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "procedural_scenario_flavor",
                    "strict": True,
                    "schema": self._response_schema(event_ids),
                },
            },
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        http_request = urllib.request.Request(
            self.endpoint,
            data=_canonical_bytes(body),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                http_request,
                timeout=self.timeout_seconds,
            ) as response:
                raw = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise TextProviderError(f"text-provider request failed: {exc}") from exc
        if len(raw) > MAX_HTTP_RESPONSE_BYTES:
            raise TextProviderError("text-provider response exceeds size limit")
        try:
            response_doc = json.loads(raw.decode("utf-8"))
            content = response_doc["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message content is not a string")
            payload = json.loads(content)
        except (UnicodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise TextProviderError(
                "text-provider response is not a valid structured chat completion"
            ) from exc
        if not isinstance(payload, dict):
            raise TextProviderError("text-provider structured content must be an object")
        return payload


def generate_flavor_text(
    events: Sequence[MechanicalEventSpec],
    *,
    locale: str,
    mode: TextMode | str = TextMode.NONE,
    provider: TextProvider | None = None,
    cache: FlavorTextCache | None = None,
) -> FlavorTextResult:
    """Apply none/optional/required policy after mechanics are finalized."""

    try:
        selected_mode = mode if isinstance(mode, TextMode) else TextMode(mode)
    except ValueError as exc:
        raise TextPolicyError(f"unsupported text mode: {mode!r}") from exc
    if selected_mode is TextMode.NONE:
        return FlavorTextResult(mode=selected_mode)

    if provider is None or isinstance(provider, NoneTextProvider):
        error = "text mode requires a configured non-none TextProvider"
        if selected_mode is TextMode.OPTIONAL:
            return FlavorTextResult(mode=selected_mode, error=error)
        raise TextPolicyError(error)

    request = _request_for(events, locale=locale)
    key = text_cache_key(
        mechanical_fingerprint_value=request.mechanical_fingerprint,
        provider=provider,
        locale=locale,
    )
    try:
        cached_payload = None if cache is None else cache.get(key)
        from_cache = cached_payload is not None
        payload = cached_payload if from_cache else provider.generate(request)
        items = validate_flavor_payload(
            payload,
            event_ids=[event.event_id for event in events],
        )
        if cache is not None and not from_cache:
            cache.put(key, {"items": [item.to_dict() for item in items]})
        provenance = TextProvenance(
            provider_id=provider.provider_id,
            model=provider.model,
            prompt_version=provider.prompt_version,
            locale=locale,
            mechanical_fingerprint=request.mechanical_fingerprint,
            cache_key=key,
            content_sha256=_content_hash(items),
            from_cache=from_cache,
        )
        return FlavorTextResult(
            mode=selected_mode,
            items=items,
            provenance=provenance,
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        if selected_mode is TextMode.OPTIONAL:
            return FlavorTextResult(mode=selected_mode, error=error)
        if isinstance(exc, FlavorTextError):
            raise
        raise TextProviderError(error) from exc

