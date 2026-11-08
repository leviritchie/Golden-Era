from __future__ import annotations

import unittest
from typing import Any, Mapping

from experiments.campaign_port_poc.procedural_scenarios.events import (
    CaptureTrigger,
    CounterAction,
    MechanicalEventSpec,
    ObjectiveProgressAction,
    ResourceAction,
    VictoryAction,
    compile_mechanical_events,
)
from experiments.campaign_port_poc.procedural_scenarios.text import (
    FlavorTextValidationError,
    TextMode,
    TextProviderError,
    generate_flavor_text,
)


def mechanical_events() -> tuple[MechanicalEventSpec, ...]:
    return (
        MechanicalEventSpec(
            event_id="proc.capture_keep",
            title="Capture the keep",
            objective_label="Capture the keep",
            triggers=(CaptureTrigger("proc.keep"),),
            actions=(
                ResourceAction("gold", 1000),
                ResourceAction("wood", -2),
                CounterAction("proc.keep_captured", 1),
                ObjectiveProgressAction("proc.obj.capture_keep"),
                VictoryAction("proc.victory"),
            ),
        ),
    )


class FakeProvider:
    provider_id = "fake"
    model = "fake-model"
    prompt_version = "test-prompt-v1"

    def __init__(self, payload: Mapping[str, Any] | None = None, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.calls = 0

    def generate(self, request: object) -> Mapping[str, Any]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.payload is not None
        return self.payload


class MemoryCache:
    def __init__(self) -> None:
        self.items: dict[str, Mapping[str, Any]] = {}

    def get(self, key: str) -> Mapping[str, Any] | None:
        return self.items.get(key)

    def put(self, key: str, payload: Mapping[str, Any]) -> None:
        self.items[key] = dict(payload)


class EventsAndTextTests(unittest.TestCase):
    def test_textless_mechanics_emit_no_dialog_or_fallback_victory(self) -> None:
        compiled = compile_mechanical_events(
            mechanical_events(),
            declared_counter_sids=("proc.keep_captured",),
        )
        action_names = [
            action["a"]
            for trigger in compiled
            for action in trigger["actions"]
        ]
        self.assertEqual(action_names.count("GameVictory"), 1)
        self.assertIn("RemoveRes", action_names)
        self.assertNotIn("Dialog", action_names)
        self.assertNotIn("Print", action_names)
        self.assertNotIn("DefeatAll", repr(compiled))

        provider = FakeProvider(error=AssertionError("none mode called provider"))
        result = generate_flavor_text(
            mechanical_events(),
            locale="en-US",
            mode=TextMode.NONE,
            provider=provider,
        )
        self.assertTrue(result.textless)
        self.assertIsNone(result.error)
        self.assertEqual(provider.calls, 0)

    def test_schema_rejection_is_textless_optional_and_fails_required(self) -> None:
        invalid = FakeProvider(
            payload={
                "items": [
                    {
                        "eventId": "changed.mechanics.id",
                        "title": "A title",
                        "body": "A body",
                    }
                ]
            }
        )
        optional = generate_flavor_text(
            mechanical_events(),
            locale="en-US",
            mode=TextMode.OPTIONAL,
            provider=invalid,
        )
        self.assertTrue(optional.textless)
        self.assertIn("exactly match mechanics", optional.error or "")

        with self.assertRaises(FlavorTextValidationError):
            generate_flavor_text(
                mechanical_events(),
                locale="en-US",
                mode=TextMode.REQUIRED,
                provider=invalid,
            )

    def test_valid_response_is_cached_by_mechanics_and_provider_identity(self) -> None:
        provider = FakeProvider(
            payload={
                "items": [
                    {
                        "eventId": "proc.capture_keep",
                        "title": "The Last Rampart",
                        "body": "The keep commands the road ahead.",
                    }
                ]
            }
        )
        cache = MemoryCache()
        first = generate_flavor_text(
            mechanical_events(),
            locale="en-US",
            mode=TextMode.REQUIRED,
            provider=provider,
            cache=cache,
        )
        second = generate_flavor_text(
            mechanical_events(),
            locale="en-US",
            mode=TextMode.REQUIRED,
            provider=provider,
            cache=cache,
        )

        self.assertEqual(provider.calls, 1)
        self.assertFalse(first.provenance.from_cache if first.provenance else True)
        self.assertTrue(second.provenance.from_cache if second.provenance else False)
        self.assertEqual(
            first.provenance.content_sha256 if first.provenance else None,
            second.provenance.content_sha256 if second.provenance else None,
        )

    def test_optional_provider_failure_reports_error_required_fails_closed(self) -> None:
        provider = FakeProvider(error=RuntimeError("endpoint unavailable"))
        optional = generate_flavor_text(
            mechanical_events(),
            locale="en-US",
            mode="optional",
            provider=provider,
        )
        self.assertTrue(optional.textless)
        self.assertIn("endpoint unavailable", optional.error or "")

        with self.assertRaises(TextProviderError):
            generate_flavor_text(
                mechanical_events(),
                locale="en-US",
                mode="required",
                provider=provider,
            )


if __name__ == "__main__":
    unittest.main()
