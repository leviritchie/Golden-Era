from __future__ import annotations

import copy
import unittest
from dataclasses import replace
from typing import Any, Mapping

from experiments.campaign_port_poc.procedural_scenarios.bundle import (
    normalize_core_deltas,
)
from experiments.campaign_port_poc.procedural_scenarios.events import (
    CaptureTrigger,
    CounterAction,
    MechanicalEventSpec,
    ResourceAction,
    TurnTrigger,
    VictoryAction,
    compile_mechanical_events,
)
from experiments.campaign_port_poc.procedural_scenarios.presentation import (
    PresentationError,
    apply_flavor_presentation,
)
from experiments.campaign_port_poc.procedural_scenarios.text import (
    FlavorText,
    FlavorTextResult,
    TextMode,
    generate_flavor_text,
)


def mechanical_events() -> tuple[MechanicalEventSpec, ...]:
    return (
        MechanicalEventSpec(
            event_id="proc_42_start",
            title="Prepare",
            triggers=(TurnTrigger(1),),
            actions=(
                ResourceAction("gold", 750),
                CounterAction("proc_42_ready", 1),
            ),
        ),
        MechanicalEventSpec(
            event_id="proc_42_victory",
            title="Take the keep",
            triggers=(CaptureTrigger("proc_42_keep"),),
            actions=(VictoryAction("proc_42_explicit_victory"),),
        ),
    )


def compiled_events() -> tuple[dict[str, Any], ...]:
    return compile_mechanical_events(
        mechanical_events(),
        declared_counter_sids=("proc_42_ready",),
    )


class FakeProvider:
    provider_id = "presentation-test"
    model = "fixed"
    prompt_version = "presentation-test-v1"

    def generate(self, request: object) -> Mapping[str, Any]:
        return {
            "items": [
                {
                    "eventId": "proc_42_start",
                    "title": "A Measured Beginning",
                    "body": "Supplies arrive as the first banners are raised.",
                },
                {
                    "eventId": "proc_42_victory",
                    "title": "The Keep Is Yours",
                    "body": "The final gate opens and the road falls silent.",
                },
            ]
        }


class PresentationTests(unittest.TestCase):
    def test_adds_one_dialog_without_changing_mechanical_rows(self) -> None:
        events = mechanical_events()
        compiled = compiled_events()
        original = copy.deepcopy(compiled)
        flavor = generate_flavor_text(
            events,
            locale="en-US",
            mode=TextMode.REQUIRED,
            provider=FakeProvider(),
        )

        result = apply_flavor_presentation(
            "proc_42",
            "en-US",
            events,
            compiled,
            flavor,
        )

        self.assertEqual(compiled, original, "the bridge mutated its input rows")
        self.assertEqual(len(result.triggers), len(original))
        for before, after in zip(original, result.triggers):
            self.assertEqual(after["comment"], before["comment"])
            self.assertEqual(after["repeat"], before["repeat"])
            self.assertEqual(after["conditions"], before["conditions"])
            self.assertEqual(after["conditionsLogic"], before["conditionsLogic"])
            mechanical_actions = [
                action for action in after["actions"] if action["a"] != "Dialog"
            ]
            dialog_actions = [
                action for action in after["actions"] if action["a"] == "Dialog"
            ]
            self.assertEqual(mechanical_actions, before["actions"])
            self.assertEqual(len(dialog_actions), 1)
            self.assertEqual(dialog_actions[0]["p"], [
                next(
                    binding["dialogSid"]
                    for binding in result.manifest_fragment["presentation"][
                        "eventBindings"
                    ]
                    if binding["eventId"] == before["comment"]
                )
            ])
            if any(action["a"] == "GameVictory" for action in after["actions"]):
                action_names = [action["a"] for action in after["actions"]]
                self.assertLess(
                    action_names.index("Dialog"),
                    action_names.index("GameVictory"),
                )

        create_rows = [
            row
            for row in result.core_deltas
            if row["operation"] == "create_json_member"
        ]
        locale_rows = [
            row for row in result.core_deltas if row["operation"] == "upsert_array"
        ]
        self.assertEqual(len(create_rows), len(events))
        self.assertEqual(
            {tuple(row["path"]) for row in locale_rows},
            {("tokens",), ("array",)},
        )
        self.assertTrue(
            all(
                row["member"] == "Lang/english/texts/dialogues.json"
                for row in locale_rows
            )
        )
        for row in create_rows:
            self.assertEqual(row["path"], [])
            self.assertEqual(row["value"]["array"][0]["localization"], True)
        normalized = normalize_core_deltas(result.core_deltas, map_sid="proc_42")
        self.assertEqual(normalized["operations"][1:], list(result.core_deltas))
        self.assertEqual(normalized["operations"][0]["member"], "DB/quickStart.json")
        self.assertEqual(
            result.manifest_fragment["presentation"]["text"]["provenance"],
            flavor.provenance.to_dict() if flavor.provenance else None,
        )

    def test_textless_result_leaves_triggers_unchanged_and_emits_no_deltas(self) -> None:
        events = mechanical_events()
        compiled = compiled_events()
        flavor = FlavorTextResult(mode=TextMode.NONE)

        result = apply_flavor_presentation(
            "proc_42",
            "en",
            events,
            compiled,
            flavor,
        )

        self.assertEqual(result.triggers, compiled)
        self.assertEqual(result.core_deltas, ())
        self.assertEqual(
            result.manifest_fragment["presentation"]["status"],
            "textless",
        )
        result.triggers[0]["comment"] = "mutated-result"
        self.assertEqual(compiled[0]["comment"], "proc_42_start")

    def test_mismatched_event_ids_fail_closed(self) -> None:
        events = mechanical_events()
        compiled = compiled_events()
        flavor = generate_flavor_text(
            events,
            locale="en-US",
            mode=TextMode.REQUIRED,
            provider=FakeProvider(),
        )

        with self.subTest("missing compiled event"):
            with self.assertRaisesRegex(PresentationError, "do not match mechanics"):
                apply_flavor_presentation(
                    "proc_42",
                    "en-US",
                    events,
                    compiled[:-1],
                    flavor,
                )

        with self.subTest("extra compiled event"):
            extra = tuple(compiled) + (
                {
                    "comment": "proc_42_extra",
                    "repeat": False,
                    "conditions": [],
                    "actions": [],
                    "conditionsLogic": "And",
                },
            )
            with self.assertRaisesRegex(PresentationError, "do not match mechanics"):
                apply_flavor_presentation(
                    "proc_42",
                    "en-US",
                    events,
                    extra,
                    flavor,
                )

        with self.subTest("duplicate compiled event"):
            duplicate = tuple(compiled) + (copy.deepcopy(compiled[0]),)
            with self.assertRaisesRegex(PresentationError, "duplicate compiled"):
                apply_flavor_presentation(
                    "proc_42",
                    "en-US",
                    events,
                    duplicate,
                    flavor,
                )

        with self.subTest("same ID but altered mechanics"):
            tampered = copy.deepcopy(compiled)
            tampered[0]["actions"][0]["p"][1] = "999999"
            with self.assertRaisesRegex(PresentationError, "does not match typed mechanics"):
                apply_flavor_presentation(
                    "proc_42",
                    "en-US",
                    events,
                    tampered,
                    flavor,
                )

        with self.subTest("reordered compiled events"):
            with self.assertRaisesRegex(PresentationError, "sequence does not match"):
                apply_flavor_presentation(
                    "proc_42",
                    "en-US",
                    events,
                    tuple(reversed(compiled)),
                    flavor,
                )

        with self.subTest("mismatched flavor event"):
            invalid = FlavorTextResult(
                mode=TextMode.REQUIRED,
                items=(
                    FlavorText(
                        event_id="proc_42_wrong",
                        title="Wrong",
                        body="This row cannot bind to mechanics.",
                    ),
                ),
                provenance=flavor.provenance,
            )
            with self.assertRaisesRegex(PresentationError, "exactly match mechanics"):
                apply_flavor_presentation(
                    "proc_42",
                    "en-US",
                    events,
                    compiled,
                    invalid,
                )

    def test_rejects_unsupported_locale_path_and_markup(self) -> None:
        events = mechanical_events()
        compiled = compiled_events()
        flavor = generate_flavor_text(
            events,
            locale="en-US",
            mode=TextMode.REQUIRED,
            provider=FakeProvider(),
        )

        with self.assertRaisesRegex(PresentationError, "unsupported presentation locale"):
            apply_flavor_presentation(
                "proc_42",
                "xx-Test",
                events,
                compiled,
                flavor,
            )
        with self.assertRaisesRegex(PresentationError, "map_sid"):
            apply_flavor_presentation(
                "../proc_42",
                "en-US",
                events,
                compiled,
                flavor,
            )

        invalid_items = list(flavor.items)
        invalid_items[0] = FlavorText(
            event_id=invalid_items[0].event_id,
            title="<b>Unsafe</b>",
            body=invalid_items[0].body,
        )
        invalid_markup = FlavorTextResult(
            mode=TextMode.REQUIRED,
            items=tuple(invalid_items),
            provenance=flavor.provenance,
        )
        with self.assertRaisesRegex(PresentationError, "disallowed markup"):
            apply_flavor_presentation(
                "proc_42",
                "en-US",
                events,
                compiled,
                invalid_markup,
            )

        assert flavor.provenance is not None
        invalid_provenance = replace(
            flavor,
            provenance=replace(flavor.provenance, cache_key="0" * 64),
        )
        with self.assertRaisesRegex(PresentationError, "cache key"):
            apply_flavor_presentation(
                "proc_42",
                "en-US",
                events,
                compiled,
                invalid_provenance,
            )

        invalid_mode = replace(flavor, mode="required")
        with self.assertRaisesRegex(PresentationError, "requires optional or required"):
            apply_flavor_presentation(
                "proc_42",
                "en-US",
                events,
                compiled,
                invalid_mode,
            )


if __name__ == "__main__":
    unittest.main()
